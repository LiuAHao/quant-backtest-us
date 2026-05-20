from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from scripts.data_source.data_source_alpaca import fetch_assets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download US instruments reference data from Alpaca.")
    parser.add_argument("--output", type=Path, default=settings.US_INSTRUMENTS_DIR / "us_instruments.parquet")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = fetch_assets()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    print(f"Wrote {len(frame)} instrument rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
