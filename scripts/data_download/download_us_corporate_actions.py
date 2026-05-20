from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from scripts.data_source.data_source_alpaca import fetch_corporate_actions


def build_date_windows(since: date, until: date, *, max_days: int = 90) -> list[tuple[str, str]]:
    if since > until:
        raise ValueError("since must be less than or equal to until")
    windows: list[tuple[str, str]] = []
    cursor = since
    while cursor <= until:
        window_end = min(cursor + timedelta(days=max_days - 1), until)
        windows.append((cursor.strftime("%Y-%m-%d"), window_end.strftime("%Y-%m-%d")))
        cursor = window_end + timedelta(days=1)
    return windows


def merge_corporate_actions(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        merged = incoming.copy()
    elif incoming is None or incoming.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, incoming], ignore_index=True, sort=False)

    if merged.empty:
        return pd.DataFrame(columns=incoming.columns if incoming is not None else existing.columns)

    merged = merged.sort_values(["symbol", "ex_date", "ca_type", "ca_sub_type", "updated_at"], kind="mergesort")
    merged = merged.drop_duplicates(["symbol", "ex_date", "ca_type", "ca_sub_type"], keep="last")
    return merged.reset_index(drop=True)


def download_corporate_actions(
    *,
    since: str,
    until: str,
    ca_types: str,
    symbol: str | None,
) -> pd.DataFrame:
    start_date = datetime.strptime(since, "%Y-%m-%d").date()
    end_date = datetime.strptime(until, "%Y-%m-%d").date()
    frames: list[pd.DataFrame] = []
    for window_since, window_until in build_date_windows(start_date, end_date):
        frames.append(
            fetch_corporate_actions(
                since=window_since,
                until=window_until,
                ca_types=ca_types,
                symbol=symbol,
            )
        )
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True, sort=False) if len(frames) > 1 else frames[0]
    return merge_corporate_actions(pd.DataFrame(columns=combined.columns), combined)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download US corporate actions reference data from Alpaca.")
    parser.add_argument("--since", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--until", required=True, help="End date, YYYY-MM-DD")
    parser.add_argument("--ca-types", default="dividend,split", help="Corporate action types, comma-separated.")
    parser.add_argument("--symbol", help="Optional comma-separated symbol filter, e.g. AAPL,MSFT,SPY")
    parser.add_argument("--output", type=Path, default=settings.US_ADJUSTMENTS_DIR / "us_corporate_actions.parquet")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    datetime.strptime(args.since, "%Y-%m-%d")
    datetime.strptime(args.until, "%Y-%m-%d")
    frame = download_corporate_actions(
        since=args.since,
        until=args.until,
        ca_types=args.ca_types,
        symbol=args.symbol,
    )
    existing = pd.read_parquet(args.output) if args.output.exists() else pd.DataFrame(columns=frame.columns)
    frame = merge_corporate_actions(existing, frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    print(f"Wrote {len(frame)} corporate action rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
