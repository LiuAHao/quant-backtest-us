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
UNSUPPORTED_SUFFIXES = (".U", ".R", ".WS", ".W", ".RT")


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


def normalize_download_symbol(symbol: str) -> tuple[str | None, str | None]:
    clean = symbol.strip().upper()
    if not clean:
        return None, "empty"
    if "$" in clean:
        return None, "preferred_or_special_share"
    if clean.endswith(UNSUPPORTED_SUFFIXES):
        return None, "unsupported_suffix"
    if "." in clean:
        left, right = clean.rsplit(".", 1)
        if len(right) == 1 and right.isalpha():
            return f"{left}-{right}", None
    return clean, None


def prepare_download_symbols(symbols: Iterable[str]) -> tuple[list[str], list[str]]:
    prepared: list[str] = []
    unsupported: list[str] = []
    seen: set[str] = set()
    for original in normalize_symbols(symbols):
        normalized, reason = normalize_download_symbol(original)
        if normalized:
            if normalized not in seen:
                seen.add(normalized)
                prepared.append(normalized)
        else:
            unsupported.append(original)
    return prepared, unsupported


def read_symbols_file(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"Symbols file not found: {path}. Run scripts/data_download/build_us_universe.py first "
            "or provide an existing symbols file."
        )
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


def extract_downloaded_symbols(rows: pd.DataFrame) -> list[str]:
    if rows is None or rows.empty or "symbol" not in rows:
        return []
    return normalize_symbols(rows["symbol"].dropna().astype(str).tolist())


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


def load_checkpoint(path: Path, output_dir: Path | None = None) -> dict[str, object]:
    if not path.exists():
        return {"batches": [], "failed_symbols": [], "symbol_status": {}}
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint.setdefault("batches", [])
    checkpoint.setdefault("failed_symbols", [])
    checkpoint.setdefault("symbol_status", {})
    status_map = checkpoint["symbol_status"]
    if not status_map:
        for batch in checkpoint["batches"]:
            if not isinstance(batch, dict):
                continue
            completed_at = batch.get("completed_at", "")
            downloaded = batch.get("downloaded_symbols", [])
            missing = batch.get("missing_symbols", [])
            update_symbol_status(
                checkpoint,
                success_symbols=downloaded,
                missing_symbols=missing,
                completed_at=completed_at,
            )
        update_symbol_status(
            checkpoint,
            failed_symbols=checkpoint.get("failed_symbols", []),
            completed_at="",
        )
    if output_dir is not None and output_dir.exists():
        parquet_symbols = set()
        for file in sorted(output_dir.glob("year=*/*.parquet")):
            frame = pd.read_parquet(file, columns=["symbol"])
            parquet_symbols.update(frame["symbol"].dropna().astype(str).str.upper().tolist())
        update_symbol_status(
            checkpoint,
            success_symbols=sorted(parquet_symbols),
            completed_at="",
        )
        checkpoint["failed_symbols"] = [
            symbol
            for symbol in checkpoint.get("failed_symbols", [])
            if checkpoint["symbol_status"].get(symbol, {}).get("status") != "success"
        ]
    requested = []
    for batch in checkpoint["batches"]:
        if isinstance(batch, dict):
            requested.extend(batch.get("symbols", []))
    if requested:
        checkpoint["coverage_report"] = build_coverage_report(checkpoint, requested)
    elif checkpoint.get("symbol_status"):
        checkpoint["coverage_report"] = build_coverage_report(checkpoint, checkpoint["symbol_status"].keys())
    return checkpoint


def save_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def update_symbol_status(
    checkpoint: dict[str, object],
    *,
    success_symbols: Iterable[str] = (),
    missing_symbols: Iterable[str] = (),
    failed_symbols: Iterable[str] = (),
    completed_at: str,
) -> None:
    status_map = checkpoint.setdefault("symbol_status", {})
    for symbol in normalize_symbols(success_symbols):
        status_map[symbol] = {"status": "success", "completed_at": completed_at}
    for symbol in normalize_symbols(missing_symbols):
        existing = status_map.get(symbol, {})
        if existing.get("status") == "success":
            continue
        status_map[symbol] = {"status": "missing", "completed_at": completed_at}
    for symbol in normalize_symbols(failed_symbols):
        existing = status_map.get(symbol, {})
        if existing.get("status") == "success":
            continue
        status_map[symbol] = {"status": "failed", "completed_at": completed_at}


def build_coverage_report(checkpoint: dict[str, object], requested_symbols: Iterable[str]) -> dict[str, int]:
    requested = normalize_symbols(requested_symbols)
    status_map = checkpoint.get("symbol_status", {})
    counts = {"success": 0, "missing": 0, "failed": 0, "unknown": 0}
    for symbol in requested:
        status = status_map.get(symbol, {}).get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "requested_symbols": len(requested),
        "success_symbols": counts.get("success", 0),
        "missing_symbols": counts.get("missing", 0),
        "failed_symbols": counts.get("failed", 0),
        "unknown_symbols": counts.get("unknown", 0),
    }


def resolve_retry_symbols(checkpoint: dict[str, object]) -> list[str]:
    status_map = checkpoint.get("symbol_status", {})
    symbols = [
        symbol
        for symbol, payload in status_map.items()
        if payload.get("status") in {"missing", "failed"}
    ]
    return normalize_symbols(symbols)


def write_symbol_list(path: Path, symbols: Iterable[str]) -> None:
    clean = normalize_symbols(symbols)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(clean)
    if clean:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def write_status_files(meta_dir: Path, checkpoint: dict[str, object]) -> None:
    status_map = checkpoint.get("symbol_status", {})
    success = [symbol for symbol, payload in status_map.items() if payload.get("status") == "success"]
    missing = [symbol for symbol, payload in status_map.items() if payload.get("status") == "missing"]
    failed = [symbol for symbol, payload in status_map.items() if payload.get("status") == "failed"]
    unsupported = [symbol for symbol, payload in status_map.items() if payload.get("status") == "unsupported"]
    write_symbol_list(meta_dir / "success_symbols.txt", success)
    write_symbol_list(meta_dir / "missing_symbols.txt", missing)
    write_symbol_list(meta_dir / "failed_symbols.txt", failed)
    write_symbol_list(meta_dir / "unsupported_symbols.txt", unsupported)
    summary_path = meta_dir / "download_us_daily_report.json"
    summary = {
        "coverage_report": checkpoint.get("coverage_report", {}),
        "last_run": checkpoint.get("last_run", {}),
        "failed_symbols": normalize_symbols(failed),
        "missing_symbols": normalize_symbols(missing),
        "success_symbols": normalize_symbols(success),
        "unsupported_symbols": normalize_symbols(unsupported),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def _run_single_symbol_fallback(
    *,
    batch: list[str],
    start: str,
    end: str | None,
    output_dir: Path,
    checkpoint: dict[str, object],
    failed_symbols: set[str],
    threads: bool | int,
) -> int:
    fallback_rows = 0
    for symbol in batch:
        completed_at = utc_now_iso()
        try:
            rows = fetch_daily_bars([symbol], start=start, end=end, batch_threads=threads)
            downloaded_symbols = extract_downloaded_symbols(rows)
            if downloaded_symbols:
                write_partitioned_daily_bars(rows, output_dir)
                fallback_rows += len(rows)
                failed_symbols.discard(symbol)
                update_symbol_status(
                    checkpoint,
                    success_symbols=downloaded_symbols,
                    completed_at=completed_at,
                )
            else:
                failed_symbols.add(symbol)
                update_symbol_status(
                    checkpoint,
                    missing_symbols=[symbol],
                    completed_at=completed_at,
                )
        except Exception:  # noqa: BLE001 - fallback should keep scanning remaining symbols.
            failed_symbols.add(symbol)
            update_symbol_status(
                checkpoint,
                failed_symbols=[symbol],
                completed_at=completed_at,
            )
    return fallback_rows


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
    fallback_to_single_symbol: bool = False,
) -> dict[str, object]:
    checkpoint = load_checkpoint(checkpoint_path, output_dir=output_dir)
    completed_keys = {
        item["key"]
        for item in checkpoint.get("batches", [])
        if isinstance(item, dict) and item.get("status") == "success"
    }
    failed_symbols: set[str] = set(checkpoint.get("failed_symbols", []))
    total_rows = 0
    skipped_batches = 0

    for index, batch in enumerate(batch_symbols(symbols, batch_size), start=1):
        key = "|".join(batch)
        if key in completed_keys:
            skipped_batches += 1
            continue

        last_error = ""
        for attempt in range(1, retries + 2):
            try:
                rows = fetch_daily_bars(batch, start=start, end=end, batch_threads=threads)
                write_counts = write_partitioned_daily_bars(rows, output_dir)
                total_rows += len(rows)
                downloaded_symbols = extract_downloaded_symbols(rows)
                missing_symbols = [symbol for symbol in batch if symbol not in set(downloaded_symbols)]
                failed_symbols.difference_update(downloaded_symbols)
                failed_symbols.update(missing_symbols)
                completed_at = utc_now_iso()
                update_symbol_status(
                    checkpoint,
                    success_symbols=downloaded_symbols,
                    missing_symbols=missing_symbols,
                    completed_at=completed_at,
                )
                checkpoint.setdefault("batches", []).append(
                    {
                        "key": key,
                        "symbols": batch,
                        "batch_index": index,
                        "status": "success" if not missing_symbols else "partial",
                        "rows": len(rows),
                        "downloaded_symbols": downloaded_symbols,
                        "missing_symbols": missing_symbols,
                        "partitions": write_counts,
                        "completed_at": completed_at,
                    }
                )
                checkpoint["failed_symbols"] = sorted(failed_symbols)
                save_checkpoint(checkpoint_path, checkpoint)
                if not missing_symbols:
                    break
                last_error = f"Missing symbols: {', '.join(missing_symbols)}"
                if attempt <= retries:
                    time.sleep(retry_sleep)
                else:
                    break
            except Exception as exc:  # noqa: BLE001 - CLI records source failures and continues.
                last_error = str(exc)
                if attempt <= retries:
                    time.sleep(retry_sleep)
                else:
                    completed_at = utc_now_iso()
                    fallback_rows = 0
                    if fallback_to_single_symbol and len(batch) > 1:
                        fallback_rows = _run_single_symbol_fallback(
                            batch=batch,
                            start=start,
                            end=end,
                            output_dir=output_dir,
                            checkpoint=checkpoint,
                            failed_symbols=failed_symbols,
                            threads=threads,
                        )
                        total_rows += fallback_rows
                    else:
                        failed_symbols.update(batch)
                        update_symbol_status(
                            checkpoint,
                            failed_symbols=batch,
                            completed_at=completed_at,
                        )
                    checkpoint.setdefault("batches", []).append(
                        {
                            "key": key,
                            "symbols": batch,
                            "batch_index": index,
                            "status": "failed",
                            "error": last_error,
                            "fallback_rows": fallback_rows,
                            "completed_at": completed_at,
                        }
                    )
                    checkpoint["failed_symbols"] = sorted(failed_symbols)
                    save_checkpoint(checkpoint_path, checkpoint)

    checkpoint["failed_symbols"] = sorted(failed_symbols)
    checkpoint["coverage_report"] = build_coverage_report(checkpoint, symbols)
    checkpoint["last_run"] = {
        "start": start,
        "end": end,
        "output_dir": str(output_dir),
        "batch_size": batch_size,
        "rows_downloaded_this_run": total_rows,
        "skipped_batches": skipped_batches,
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
    parser.add_argument("--retry-failed-only", action="store_true", help="Only retry symbols currently marked missing or failed in the checkpoint")
    parser.add_argument("--fallback-to-single-symbol", action="store_true", help="When a batch fails, retry its symbols one by one")
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
    checkpoint = load_checkpoint(args.checkpoint)
    symbols = normalize_symbols(args.symbols)
    if args.symbols_file:
        symbols = normalize_symbols([*symbols, *read_symbols_file(args.symbols_file)])
    if args.retry_failed_only:
        symbols = resolve_retry_symbols(checkpoint)
    symbols, unsupported_symbols = prepare_download_symbols(symbols)
    if unsupported_symbols:
        update_symbol_status(
            checkpoint,
            completed_at=utc_now_iso(),
        )
        status_map = checkpoint.setdefault("symbol_status", {})
        completed_at = utc_now_iso()
        for symbol in unsupported_symbols:
            status_map[symbol] = {"status": "unsupported", "completed_at": completed_at}
    if not symbols and not unsupported_symbols:
        raise SystemExit("No symbols provided. Use --symbols, --symbols-file, or --retry-failed-only.")

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
        fallback_to_single_symbol=args.fallback_to_single_symbol,
    )
    if unsupported_symbols:
        checkpoint["coverage_report"] = build_coverage_report(
            checkpoint,
            [*symbols, *unsupported_symbols],
        )
    write_status_files(args.checkpoint.parent, checkpoint)
    last_run = checkpoint["last_run"]
    failed_symbol_count = len(checkpoint.get("failed_symbols", []))
    skipped_batches = int(last_run.get("skipped_batches", 0))
    if last_run["rows_downloaded_this_run"] == 0 and skipped_batches > 0 and failed_symbol_count == 0:
        print(
            f"No new rows downloaded. Skipped {skipped_batches} completed batch"
            f"{'' if skipped_batches == 1 else 'es'} from checkpoint at {args.checkpoint}."
        )
    else:
        coverage = checkpoint.get("coverage_report", {})
        print(
            f"Downloaded {last_run['rows_downloaded_this_run']} rows into {last_run['output_dir']} "
            f"with {failed_symbol_count} failed symbols and {skipped_batches} skipped batch"
            f"{'' if skipped_batches == 1 else 'es'}."
        )
        if coverage:
            print(
                "Coverage: "
                f"{coverage['success_symbols']} success, "
                f"{coverage['missing_symbols']} missing, "
                f"{coverage['failed_symbols']} failed, "
                f"{coverage['unknown_symbols']} unknown "
                f"out of {coverage['requested_symbols']} requested symbols."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
