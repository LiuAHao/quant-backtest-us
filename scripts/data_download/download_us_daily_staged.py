from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from scripts.data_source.data_source_alpaca import fetch_daily_bars
from scripts.data_utils.us_data_helpers import (
    batch_symbols,
    build_coverage_report,
    merge_daily_bars,
    normalize_symbols,
    prepare_download_symbols,
    read_symbols_file,
    write_partitioned_daily_bars,
    write_status_files,
)


STAGE_YEARS = {
    "1y": 1,
    "2y": 2,
    "5y": 5,
    "10y": 10,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_symbol_filename(symbol: str) -> str:
    return symbol.replace("/", "_")


def raw_symbol_path(raw_dir: Path, symbol: str) -> Path:
    bucket = symbol[0] if symbol else "_"
    return raw_dir / f"bucket={bucket}" / f"{safe_symbol_filename(symbol)}.parquet"


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def subtract_years(anchor: date, years: int) -> date:
    try:
        return anchor.replace(year=anchor.year - years)
    except ValueError:
        return anchor.replace(month=2, day=28, year=anchor.year - years)


def stage_start_date(stage: str, *, end_date: str) -> str:
    if stage == "full":
        return "2010-01-01"
    years = STAGE_YEARS[stage]
    anchor = parse_iso_date(end_date)
    return subtract_years(anchor, years).strftime("%Y-%m-%d")


def load_symbol_checkpoint(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"symbol_status": {}, "failed_symbols": [], "batches": []}
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint.setdefault("symbol_status", {})
    checkpoint.setdefault("failed_symbols", [])
    checkpoint.setdefault("batches", [])
    return checkpoint


def checkpoint_matches_window(checkpoint: dict[str, object], *, stage: str, start: str, end: str) -> bool:
    run = checkpoint.get("last_run") or {}
    return run.get("stage") == stage and run.get("start") == start and run.get("end") == end


def reset_checkpoint_for_window(
    checkpoint: dict[str, object],
    *,
    stage: str,
    start: str,
    end: str,
    preserved_statuses: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    next_statuses = preserved_statuses or {}
    return {
        "window": {"stage": stage, "start": start, "end": end},
        "symbol_status": next_statuses,
        "failed_symbols": sorted(
            symbol for symbol, payload in next_statuses.items() if payload.get("status") in {"failed", "missing"}
        ),
        "batches": [],
        "coverage_report": checkpoint.get("coverage_report", {}),
        "last_run": {},
    }


def save_symbol_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def write_raw_symbol_bars(frame: pd.DataFrame, raw_dir: Path, symbol: str) -> Path:
    target = raw_symbol_path(raw_dir, symbol)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(target) if target.exists() else pd.DataFrame(columns=frame.columns)
    merged = merge_daily_bars(existing, frame)
    tmp = target.with_suffix(target.suffix + ".tmp")
    merged.sort_values(["date"], kind="mergesort").to_parquet(tmp, index=False)
    tmp.replace(target)
    return target


@dataclass(frozen=True)
class DownloadOutcome:
    symbol: str
    status: str
    rows: int
    error: str | None = None
    raw_path: str | None = None
    min_date: str | None = None
    max_date: str | None = None


def build_symbol_outcomes(frame: pd.DataFrame, symbols: list[str], raw_dir: Path) -> list[DownloadOutcome]:
    if frame.empty:
        return [DownloadOutcome(symbol=symbol, status="missing", rows=0) for symbol in symbols]

    outcomes: list[DownloadOutcome] = []
    seen: set[str] = set()
    for symbol, symbol_frame in frame.groupby("symbol", sort=True):
        raw_path = write_raw_symbol_bars(symbol_frame, raw_dir, symbol)
        outcomes.append(
            DownloadOutcome(
                symbol=symbol,
                status="success",
                rows=len(symbol_frame),
                raw_path=str(raw_path),
                min_date=str(symbol_frame["date"].min()),
                max_date=str(symbol_frame["date"].max()),
            )
        )
        seen.add(symbol)

    for symbol in symbols:
        if symbol not in seen:
            outcomes.append(DownloadOutcome(symbol=symbol, status="missing", rows=0))

    return sorted(outcomes, key=lambda item: item.symbol)


def download_batch(
    *,
    symbols: list[str],
    start: str,
    end: str,
    raw_dir: Path,
    output_dir: Path,
    retries: int,
    retry_sleep: float,
    feed: str,
    limit: int,
) -> list[DownloadOutcome]:
    last_error = ""
    for attempt in range(1, retries + 2):
        try:
            rows = fetch_daily_bars(symbols, start=start, end=end, feed=feed, limit=limit)
            if not rows.empty:
                write_partitioned_daily_bars(rows, output_dir)
            return build_symbol_outcomes(rows, symbols, raw_dir)
        except Exception as exc:  # noqa: BLE001 - keep symbol-level retries isolated.
            last_error = str(exc)
            if attempt <= retries:
                time.sleep(retry_sleep)
            else:
                return [
                    DownloadOutcome(symbol=symbol, status="failed", rows=0, error=last_error)
                    for symbol in symbols
                ]
    return [DownloadOutcome(symbol=symbol, status="failed", rows=0, error=last_error) for symbol in symbols]


def select_symbols(
    *,
    checkpoint: dict[str, object],
    symbols: list[str],
    retry_failed_only: bool,
    start: str,
    end: str,
) -> list[str]:
    if retry_failed_only:
        status_map = checkpoint.get("symbol_status", {})
        retry = [
            symbol
            for symbol in symbols
            if status_map.get(symbol, {}).get("status") in {"missing", "failed"}
        ]
        return normalize_symbols(retry)

    remaining = []
    status_map = checkpoint.get("symbol_status", {})
    for symbol in symbols:
        payload = status_map.get(symbol, {})
        if (
            payload.get("status") == "success"
            and payload.get("window_start") == start
            and payload.get("window_end") == end
        ):
            continue
        remaining.append(symbol)
    return normalize_symbols(remaining)


def update_checkpoint_for_batch(
    checkpoint: dict[str, object],
    outcomes: list[DownloadOutcome],
    batch_key: str,
    batch_symbols_requested: list[str],
    start: str,
    end: str,
) -> None:
    completed_at = utc_now_iso()
    status_map = checkpoint.setdefault("symbol_status", {})
    for outcome in outcomes:
        status_map[outcome.symbol] = {
            "status": outcome.status,
            "completed_at": completed_at,
            "rows": outcome.rows,
            "raw_path": outcome.raw_path,
            "min_date": outcome.min_date,
            "max_date": outcome.max_date,
            "error": outcome.error,
            "window_start": start,
            "window_end": end,
        }

    failed_symbols = {
        symbol
        for symbol, payload in status_map.items()
        if payload.get("status") in {"failed", "missing"}
    }
    checkpoint["failed_symbols"] = sorted(failed_symbols)
    downloaded_symbols = sorted(outcome.symbol for outcome in outcomes if outcome.status == "success")
    missing_symbols = sorted(outcome.symbol for outcome in outcomes if outcome.status == "missing")
    failed_batch_symbols = sorted(outcome.symbol for outcome in outcomes if outcome.status == "failed")
    batch_status = "success"
    if failed_batch_symbols:
        batch_status = "failed"
    elif missing_symbols and downloaded_symbols:
        batch_status = "partial"
    elif missing_symbols:
        batch_status = "missing"
    checkpoint.setdefault("batches", []).append(
        {
            "key": batch_key,
            "symbols": batch_symbols_requested,
            "status": batch_status,
            "rows": sum(outcome.rows for outcome in outcomes),
            "downloaded_symbols": downloaded_symbols,
            "missing_symbols": missing_symbols,
            "failed_symbols": failed_batch_symbols,
            "error": next((outcome.error for outcome in outcomes if outcome.error), None),
            "completed_at": completed_at,
        }
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage-aware Alpaca downloader for US daily bars.")
    parser.add_argument("--stage", choices=["1y", "2y", "5y", "10y", "full"], required=True)
    parser.add_argument("--symbols", nargs="*", default=[], help="Optional explicit symbols, e.g. AAPL MSFT SPY")
    parser.add_argument("--symbols-file", type=Path, help="Optional symbols file. Defaults to data/universe/us_core.txt when --symbols is empty.")
    parser.add_argument("--end", required=True, help="Inclusive anchor date, YYYY-MM-DD")
    parser.add_argument("--limit", type=int, help="Optional symbol cap for smoke tests.")
    parser.add_argument("--output-dir", type=Path, default=settings.US_DAILY_BAR_DIR)
    parser.add_argument("--raw-dir", type=Path, default=settings.US_DAILY_BAR_RAW_DIR)
    parser.add_argument("--meta-dir", type=Path, default=settings.META_DIR)
    parser.add_argument("--retry-failed-only", action="store_true")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument("--sleep", type=float, default=0.15, help="Delay between batches in seconds.")
    parser.add_argument("--batch-size", type=int, default=100, help="Symbols per Alpaca request.")
    parser.add_argument("--feed", default="iex", help="Alpaca market data feed, e.g. iex.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requested_symbols = normalize_symbols(args.symbols)
    symbols_file = args.symbols_file
    if symbols_file is None and not requested_symbols:
        symbols_file = PROJECT_ROOT / "data" / "universe" / "us_core.txt"
    if symbols_file:
        requested_symbols = normalize_symbols([*requested_symbols, *read_symbols_file(symbols_file)])
    prepared_symbols, unsupported_symbols = prepare_download_symbols(requested_symbols)
    if args.limit:
        prepared_symbols = prepared_symbols[: args.limit]

    checkpoint_path = args.meta_dir / f"download_us_daily_{args.stage}_checkpoint.json"
    checkpoint = load_symbol_checkpoint(checkpoint_path)
    start = stage_start_date(args.stage, end_date=args.end)
    if not checkpoint_matches_window(checkpoint, stage=args.stage, start=start, end=args.end):
        preserved = {
            symbol: payload
            for symbol, payload in checkpoint.get("symbol_status", {}).items()
            if payload.get("status") == "unsupported"
        }
        checkpoint = reset_checkpoint_for_window(
            checkpoint,
            stage=args.stage,
            start=start,
            end=args.end,
            preserved_statuses=preserved,
        )
        save_symbol_checkpoint(checkpoint_path, checkpoint)

    symbols = select_symbols(
        checkpoint=checkpoint,
        symbols=prepared_symbols,
        retry_failed_only=args.retry_failed_only,
        start=start,
        end=args.end,
    )

    if not symbols and not unsupported_symbols:
        raise SystemExit("No symbols to download for this stage.")

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.meta_dir.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    success = 0
    missing = 0
    failed = 0
    skipped = len(prepared_symbols) - len(symbols)

    status_map = checkpoint.setdefault("symbol_status", {})
    completed_at = utc_now_iso()
    for symbol in unsupported_symbols:
        status_map[symbol] = {"status": "unsupported", "completed_at": completed_at}

    batches = list(batch_symbols(symbols, args.batch_size))
    attempted_symbols = 0
    for batch_index, batch in enumerate(batches, start=1):
        outcomes = download_batch(
            symbols=batch,
            start=start,
            end=args.end,
            raw_dir=args.raw_dir,
            output_dir=args.output_dir,
            retries=args.retries,
            retry_sleep=args.retry_sleep,
            feed=args.feed,
            limit=10000,
        )
        attempted_symbols += len(batch)
        batch_key = f"batch-{batch_index:05d}"
        update_checkpoint_for_batch(checkpoint, outcomes, batch_key, batch, start, args.end)
        for outcome in outcomes:
            total_rows += outcome.rows
            if outcome.status == "success":
                success += 1
            elif outcome.status == "missing":
                missing += 1
            else:
                failed += 1
        checkpoint["coverage_report"] = build_coverage_report(checkpoint, [*prepared_symbols, *unsupported_symbols])
        checkpoint["last_run"] = {
            "stage": args.stage,
            "start": start,
            "end": args.end,
            "output_dir": str(args.output_dir),
            "raw_dir": str(args.raw_dir),
            "rows_downloaded_this_run": total_rows,
            "symbols_attempted_this_run": attempted_symbols,
            "batches_attempted_this_run": batch_index,
            "symbols_skipped": skipped,
            "completed_at": utc_now_iso(),
        }
        save_symbol_checkpoint(checkpoint_path, checkpoint)
        if args.sleep > 0:
            time.sleep(args.sleep)

    checkpoint["coverage_report"] = build_coverage_report(checkpoint, [*prepared_symbols, *unsupported_symbols])
    checkpoint["last_run"] = {
        "stage": args.stage,
        "start": start,
        "end": args.end,
        "output_dir": str(args.output_dir),
        "raw_dir": str(args.raw_dir),
        "rows_downloaded_this_run": total_rows,
        "success_symbols_this_run": success,
        "missing_symbols_this_run": missing,
        "failed_symbols_this_run": failed,
        "symbols_skipped": skipped,
        "completed_at": utc_now_iso(),
    }
    save_symbol_checkpoint(checkpoint_path, checkpoint)

    summary = {
        "coverage_report": checkpoint.get("coverage_report", {}),
        "last_run": checkpoint.get("last_run", {}),
        "failed_symbols": sorted(
            symbol for symbol, payload in checkpoint["symbol_status"].items() if payload.get("status") == "failed"
        ),
        "missing_symbols": sorted(
            symbol for symbol, payload in checkpoint["symbol_status"].items() if payload.get("status") == "missing"
        ),
        "success_symbols": sorted(
            symbol for symbol, payload in checkpoint["symbol_status"].items() if payload.get("status") == "success"
        ),
        "unsupported_symbols": sorted(
            symbol for symbol, payload in checkpoint["symbol_status"].items() if payload.get("status") == "unsupported"
        ),
    }
    stage_meta_dir = args.meta_dir / f"stage_{args.stage}"
    stage_meta_dir.mkdir(parents=True, exist_ok=True)
    (stage_meta_dir / "download_us_daily_report.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_status_files(stage_meta_dir, checkpoint)

    coverage = checkpoint["coverage_report"]
    print(
        f"Stage {args.stage}: downloaded {total_rows} rows from {start} to {args.end} "
        f"for {success} success, {missing} missing, {failed} failed, {skipped} skipped symbols."
    )
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
