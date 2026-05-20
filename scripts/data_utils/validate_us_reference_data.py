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


INSTRUMENT_REQUIRED_COLUMNS = {
    "symbol",
    "name",
    "exchange",
    "asset_class",
    "status",
    "tradable",
    "shortable",
    "fractionable",
    "easy_to_borrow",
    "marginable",
    "source",
    "updated_at",
}

CALENDAR_REQUIRED_COLUMNS = {
    "date",
    "open",
    "close",
    "session_open",
    "session_close",
    "is_open",
    "source",
    "updated_at",
}

CORPORATE_ACTION_REQUIRED_COLUMNS = {
    "symbol",
    "ca_type",
    "ca_sub_type",
    "declaration_date",
    "effective_date",
    "ex_date",
    "record_date",
    "payable_date",
    "cash",
    "old_rate",
    "new_rate",
    "source",
    "updated_at",
}


@dataclass(frozen=True)
class InstrumentsValidationReport:
    ok: bool
    rows: int
    symbols: int
    missing_columns: list[str]
    duplicate_symbols: int
    null_required_values: int


@dataclass(frozen=True)
class CalendarValidationReport:
    ok: bool
    rows: int
    min_date: str | None
    max_date: str | None
    missing_columns: list[str]
    duplicate_dates: int
    null_required_values: int


@dataclass(frozen=True)
class CorporateActionsValidationReport:
    ok: bool
    rows: int
    symbols: int
    min_ex_date: str | None
    max_ex_date: str | None
    missing_columns: list[str]
    duplicate_rows: int
    null_required_values: int


def load_reference_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def validate_instruments(frame: pd.DataFrame) -> InstrumentsValidationReport:
    missing = sorted(INSTRUMENT_REQUIRED_COLUMNS - set(frame.columns))
    if frame.empty or missing:
        return InstrumentsValidationReport(
            ok=not missing and frame.empty,
            rows=len(frame),
            symbols=0,
            missing_columns=missing,
            duplicate_symbols=0,
            null_required_values=0,
        )

    duplicate_symbols = int(frame.duplicated(["symbol"]).sum())
    null_required = int(frame[list(INSTRUMENT_REQUIRED_COLUMNS)].isna().sum().sum())
    ok = not missing and duplicate_symbols == 0 and null_required == 0
    return InstrumentsValidationReport(
        ok=ok,
        rows=len(frame),
        symbols=int(frame["symbol"].nunique()),
        missing_columns=missing,
        duplicate_symbols=duplicate_symbols,
        null_required_values=null_required,
    )


def validate_calendar(frame: pd.DataFrame) -> CalendarValidationReport:
    missing = sorted(CALENDAR_REQUIRED_COLUMNS - set(frame.columns))
    if frame.empty or missing:
        return CalendarValidationReport(
            ok=not missing and frame.empty,
            rows=len(frame),
            min_date=None,
            max_date=None,
            missing_columns=missing,
            duplicate_dates=0,
            null_required_values=0,
        )

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    duplicate_dates = int(data.duplicated(["date"]).sum())
    null_required = int(data[list(CALENDAR_REQUIRED_COLUMNS)].isna().sum().sum())
    ok = not missing and duplicate_dates == 0 and null_required == 0
    return CalendarValidationReport(
        ok=ok,
        rows=len(data),
        min_date=data["date"].min().strftime("%Y-%m-%d") if data["date"].notna().any() else None,
        max_date=data["date"].max().strftime("%Y-%m-%d") if data["date"].notna().any() else None,
        missing_columns=missing,
        duplicate_dates=duplicate_dates,
        null_required_values=null_required,
    )


def validate_corporate_actions(frame: pd.DataFrame) -> CorporateActionsValidationReport:
    missing = sorted(CORPORATE_ACTION_REQUIRED_COLUMNS - set(frame.columns))
    if frame.empty or missing:
        return CorporateActionsValidationReport(
            ok=not missing and frame.empty,
            rows=len(frame),
            symbols=0,
            min_ex_date=None,
            max_ex_date=None,
            missing_columns=missing,
            duplicate_rows=0,
            null_required_values=0,
        )

    data = frame.copy()
    data["ex_date"] = pd.to_datetime(data["ex_date"], errors="coerce")
    duplicate_rows = int(data.duplicated(["symbol", "ex_date", "ca_type", "ca_sub_type"]).sum())
    null_required = int(data[list(CORPORATE_ACTION_REQUIRED_COLUMNS)].isna().sum().sum())
    ok = not missing and duplicate_rows == 0 and null_required == 0
    return CorporateActionsValidationReport(
        ok=ok,
        rows=len(data),
        symbols=int(data["symbol"].nunique()),
        min_ex_date=data["ex_date"].min().strftime("%Y-%m-%d") if data["ex_date"].notna().any() else None,
        max_ex_date=data["ex_date"].max().strftime("%Y-%m-%d") if data["ex_date"].notna().any() else None,
        missing_columns=missing,
        duplicate_rows=duplicate_rows,
        null_required_values=null_required,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate US reference parquet data.")
    parser.add_argument(
        "--table",
        choices=["instruments", "calendar", "corporate_actions"],
        required=True,
        help="Reference table to validate.",
    )
    parser.add_argument("--path", type=Path, help="Override parquet path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.table == "instruments":
        path = args.path or (settings.US_INSTRUMENTS_DIR / "us_instruments.parquet")
        report = validate_instruments(load_reference_table(path))
    elif args.table == "calendar":
        path = args.path or (settings.US_CALENDAR_DIR / "us_calendar.parquet")
        report = validate_calendar(load_reference_table(path))
    else:
        path = args.path or (settings.US_ADJUSTMENTS_DIR / "us_corporate_actions.parquet")
        report = validate_corporate_actions(load_reference_table(path))
    for key, value in asdict(report).items():
        print(f"{key}: {value}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
