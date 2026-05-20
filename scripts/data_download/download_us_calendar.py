from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from scripts.data_source.data_source_alpaca import fetch_calendar


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download US market calendar reference data from Alpaca.")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD")
    parser.add_argument("--output", type=Path, default=settings.US_CALENDAR_DIR / "us_calendar.parquet")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    datetime.strptime(args.start, "%Y-%m-%d")
    datetime.strptime(args.end, "%Y-%m-%d")
    frame = fetch_calendar(start=args.start, end=args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    print(f"Wrote {len(frame)} calendar rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
