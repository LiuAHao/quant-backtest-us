from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from scripts.data_source.data_source_yfinance import CANONICAL_COLUMNS, fetch_daily_bars


DEFAULT_BATCH_SIZE = 80


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for item in symbols:
        symbol = item.strip().upper() if item else ""
        if symbol and symbol not in seen:
            seen.add(symbol)
            clean.append(symbol)
    return clean


def read_symbols_file(path: Path) -> list[str]:
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].replace(",", " ").strip()
        if clean:
            symbols.extend(clean.split())
    return normalize_symbols(symbols)


def batch_symbols(symbols: Iterable[str], batch_size: int) -> Iterator[list[str]]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    clean = normalize_symbols(symbols)
    for start in range(0, len(clean), batch_size):
        batch = clean[start : start + batch_size]
        if batch:
            yield batch


def merge_daily_bars(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        merged = incoming.copy()
    elif incoming is None or incoming.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, incoming], ignore_index=True, sort=False)

    if merged.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    merged["symbol"] = merged["symbol"].astype(str).str.upper()
    merged["date"] = pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%d")
    if "updated_at" not in merged:
        merged["updated_at"] = ""
    merged = merged.sort_values(["symbol", "date", "updated_at"], kind="mergesort")
    merged = merged.drop_duplicates(["symbol", "date"], keep="last")
    return merged.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)


def _read_existing_partition(partition_dir: Path) -> pd.DataFrame:
    files = sorted(partition_dir.glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return pd.concat((pd.read_parquet(file) for file in files), ignore_index=True, sort=False)


def write_partitioned_daily_bars(frame: pd.DataFrame, output_dir: Path) -> dict[int, int]:
    if frame.empty:
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d")
    data["year"] = data["date"].str.slice(0, 4).astype(int)
    counts: dict[int, int] = {}

    for year, year_frame in data.groupby("year", sort=True):
        partition_dir = output_dir / f"year={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        existing = _read_existing_partition(partition_dir)
        merged = merge_daily_bars(existing.drop(columns=["year"], errors="ignore"), year_frame.drop(columns=["year"]))
        final_path = partition_dir / "us_daily_bar.parquet"
        tmp_path = partition_dir / f".{final_path.name}.tmp"
        merged.to_parquet(tmp_path, index=False)
        tmp_path.replace(final_path)
        for old_file in partition_dir.glob("*.parquet"):
            if old_file != final_path:
                old_file.unlink()
        counts[int(year)] = len(merged)

    return counts


def load_checkpoint(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"batches": [], "failed_symbols": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def download_batches(
    *,
    symbols: Iterable[str],
    start: str,
    end: str | None,
    output_dir: Path,
    checkpoint_path: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    retries: int = 2,
    retry_sleep: float = 2.0,
    threads: bool | int = True,
) -> dict[str, object]:
    checkpoint = load_checkpoint(checkpoint_path)
    completed_keys = {
        item["key"]
        for item in checkpoint.get("batches", [])
        if isinstance(item, dict) and item.get("status") == "success"
    }
    failed_symbols: set[str] = set(checkpoint.get("failed_symbols", []))
    total_rows = 0

    for index, batch in enumerate(batch_symbols(symbols, batch_size), start=1):
        key = "|".join(batch)
        if key in completed_keys:
            continue

        last_error = ""
        for attempt in range(1, retries + 2):
            try:
                rows = fetch_daily_bars(batch, start=start, end=end, batch_threads=threads)
                write_counts = write_partitioned_daily_bars(rows, output_dir)
                total_rows += len(rows)
                failed_symbols.difference_update(batch)
                checkpoint.setdefault("batches", []).append(
                    {
                        "key": key,
                        "symbols": batch,
                        "batch_index": index,
                        "status": "success",
                        "rows": len(rows),
                        "partitions": write_counts,
                        "completed_at": utc_now_iso(),
                    }
                )
                checkpoint["failed_symbols"] = sorted(failed_symbols)
                save_checkpoint(checkpoint_path, checkpoint)
                break
            except Exception as exc:  # noqa: BLE001 - CLI records source failures and continues.
                last_error = str(exc)
                if attempt <= retries:
                    time.sleep(retry_sleep)
                else:
                    failed_symbols.update(batch)
                    checkpoint.setdefault("batches", []).append(
                        {
                            "key": key,
                            "symbols": batch,
                            "batch_index": index,
                            "status": "failed",
                            "error": last_error,
                            "completed_at": utc_now_iso(),
                        }
                    )
                    checkpoint["failed_symbols"] = sorted(failed_symbols)
                    save_checkpoint(checkpoint_path, checkpoint)

    checkpoint["failed_symbols"] = sorted(failed_symbols)
    checkpoint["last_run"] = {
        "start": start,
        "end": end,
        "output_dir": str(output_dir),
        "batch_size": batch_size,
        "rows_downloaded_this_run": total_rows,
        "completed_at": utc_now_iso(),
    }
    save_checkpoint(checkpoint_path, checkpoint)
    return checkpoint


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download US daily bars with yfinance.")
    parser.add_argument("--symbols", nargs="*", default=[], help="Symbols to download, e.g. AAPL MSFT SPY")
    parser.add_argument("--symbols-file", type=Path, help="Text file with symbols separated by whitespace or commas")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", help="End date, YYYY-MM-DD. yfinance treats this as exclusive.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--output-dir", type=Path, default=settings.US_DAILY_BAR_DIR)
    parser.add_argument("--checkpoint", type=Path, default=settings.META_DIR / "download_us_daily_checkpoint.json")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument("--threads", default="true", help="true, false, or an integer thread count for yfinance")
    return parser.parse_args()


def parse_threads(value: str) -> bool | int:
    lowered = value.lower()
    if lowered in {"true", "yes", "1"}:
        return True
    if lowered in {"false", "no", "0"}:
        return False
    return int(value)


def main() -> int:
    args = parse_args()
    symbols = normalize_symbols(args.symbols)
    if args.symbols_file:
        symbols = normalize_symbols([*symbols, *read_symbols_file(args.symbols_file)])
    if not symbols:
        raise SystemExit("No symbols provided. Use --symbols or --symbols-file.")

    checkpoint = download_batches(
        symbols=symbols,
        start=args.start,
        end=args.end,
        output_dir=args.output_dir,
        checkpoint_path=args.checkpoint,
        batch_size=args.batch_size,
        retries=args.retries,
        retry_sleep=args.retry_sleep,
        threads=parse_threads(args.threads),
    )
    last_run = checkpoint["last_run"]
    print(
        f"Downloaded {last_run['rows_downloaded_this_run']} rows into {last_run['output_dir']} "
        f"with {len(checkpoint.get('failed_symbols', []))} failed symbols."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
