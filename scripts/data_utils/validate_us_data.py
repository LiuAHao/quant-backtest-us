from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings


REQUIRED_COLUMNS = {
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "source",
    "updated_at",
}


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    rows: int
    symbols: int
    min_date: str | None
    max_date: str | None
    missing_columns: list[str]
    duplicate_symbol_dates: int
    invalid_price_rows: int
    invalid_adjusted_close_rows: int
    invalid_volume_rows: int
    null_required_values: int


def load_daily_bars(root: Path = settings.US_DAILY_BAR_DIR) -> pd.DataFrame:
    files = sorted(root.glob("year=*/*.parquet"))
    if not files and root.exists():
        files = sorted(root.glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat((pd.read_parquet(file) for file in files), ignore_index=True, sort=False)


def validate_daily_bars(frame: pd.DataFrame) -> ValidationReport:
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if frame.empty or missing:
        return ValidationReport(
            ok=not missing and frame.empty,
            rows=len(frame),
            symbols=0,
            min_date=None,
            max_date=None,
            missing_columns=missing,
            duplicate_symbol_dates=0,
            invalid_price_rows=0,
            invalid_adjusted_close_rows=0,
            invalid_volume_rows=0,
            null_required_values=0,
        )

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    ohlc_columns = ["open", "high", "low", "close"]
    numeric_columns = ohlc_columns + ["adj_close", "volume"]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    duplicate_count = int(data.duplicated(["symbol", "date"]).sum())
    invalid_price = (
        (data["high"] < data[["open", "low", "close"]].max(axis=1))
        | (data["low"] > data[["open", "high", "close"]].min(axis=1))
        | (data[ohlc_columns] < 0).any(axis=1)
    )
    invalid_adjusted_close = data["adj_close"].isna() | (data["adj_close"] <= 0)
    invalid_volume = data["volume"].isna() | (data["volume"] < 0)
    null_required = int(data[list(REQUIRED_COLUMNS)].isna().sum().sum())

    ok = (
        not missing
        and duplicate_count == 0
        and int(invalid_price.sum()) == 0
        and int(invalid_adjusted_close.sum()) == 0
        and int(invalid_volume.sum()) == 0
        and null_required == 0
    )
    return ValidationReport(
        ok=ok,
        rows=len(data),
        symbols=int(data["symbol"].nunique()),
        min_date=data["date"].min().strftime("%Y-%m-%d") if data["date"].notna().any() else None,
        max_date=data["date"].max().strftime("%Y-%m-%d") if data["date"].notna().any() else None,
        missing_columns=missing,
        duplicate_symbol_dates=duplicate_count,
        invalid_price_rows=int(invalid_price.sum()),
        invalid_adjusted_close_rows=int(invalid_adjusted_close.sum()),
        invalid_volume_rows=int(invalid_volume.sum()),
        null_required_values=null_required,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate local US daily-bar parquet data.")
    parser.add_argument("--data-dir", type=Path, default=settings.US_DAILY_BAR_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_daily_bars(load_daily_bars(args.data_dir))
    for key, value in asdict(report).items():
        print(f"{key}: {value}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
