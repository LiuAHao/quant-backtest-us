import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class AlpacaReferenceSourceTest(unittest.TestCase):
    def test_normalize_alpaca_assets_produces_canonical_frame(self):
        from scripts.data_source.data_source_alpaca import normalize_alpaca_assets

        frame = normalize_alpaca_assets(
            [
                {
                    "symbol": "BRK.B",
                    "name": "BERKSHIRE HATHAWAY Class B",
                    "exchange": "NYSE",
                    "class": "us_equity",
                    "status": "active",
                    "tradable": True,
                    "shortable": True,
                    "fractionable": True,
                    "easy_to_borrow": True,
                    "marginable": True,
                }
            ],
            updated_at="2026-05-20T00:00:00Z",
        )

        self.assertEqual(frame.iloc[0]["symbol"], "BRK-B")
        self.assertEqual(frame.iloc[0]["asset_class"], "us_equity")
        self.assertEqual(frame.iloc[0]["source"], "alpaca_assets")

    def test_normalize_alpaca_calendar_produces_canonical_frame(self):
        from scripts.data_source.data_source_alpaca import normalize_alpaca_calendar

        frame = normalize_alpaca_calendar(
            [
                {
                    "date": "2025-05-01",
                    "open": "09:30",
                    "close": "16:00",
                    "session_open": "0400",
                    "session_close": "2000",
                }
            ],
            updated_at="2026-05-20T00:00:00Z",
        )

        self.assertEqual(frame.iloc[0]["date"], "2025-05-01")
        self.assertEqual(frame.iloc[0]["is_open"], True)
        self.assertEqual(frame.iloc[0]["source"], "alpaca_calendar")

    def test_normalize_alpaca_corporate_actions_produces_canonical_frame(self):
        from scripts.data_source.data_source_alpaca import normalize_alpaca_corporate_actions

        frame = normalize_alpaca_corporate_actions(
            [
                {
                    "ca_type": "dividend",
                    "ca_sub_type": "cash",
                    "target_symbol": "AAPL",
                    "declaration_date": "2026-05-07",
                    "effective_date": "2026-05-11",
                    "ex_date": "2026-05-11",
                    "record_date": "2026-05-11",
                    "payable_date": "2026-05-14",
                    "cash": "0.27",
                    "old_rate": "1",
                    "new_rate": "1",
                }
            ],
            updated_at="2026-05-20T00:00:00Z",
        )

        self.assertEqual(frame.iloc[0]["symbol"], "AAPL")
        self.assertEqual(frame.iloc[0]["ca_type"], "dividend")
        self.assertEqual(float(frame.iloc[0]["cash"]), 0.27)
        self.assertEqual(frame.iloc[0]["source"], "alpaca_corporate_actions")


class ReferenceValidationTest(unittest.TestCase):
    def test_validate_instruments_accepts_canonical_frame(self):
        from scripts.data_utils.validate_us_reference_data import validate_instruments

        frame = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc. Common Stock",
                    "exchange": "NASDAQ",
                    "asset_class": "us_equity",
                    "status": "active",
                    "tradable": True,
                    "shortable": True,
                    "fractionable": True,
                    "easy_to_borrow": True,
                    "marginable": True,
                    "source": "alpaca_assets",
                    "updated_at": "2026-05-20T00:00:00Z",
                }
            ]
        )

        report = validate_instruments(frame)
        self.assertTrue(report.ok)
        self.assertEqual(report.rows, 1)
        self.assertEqual(report.duplicate_symbols, 0)

    def test_validate_calendar_accepts_canonical_frame(self):
        from scripts.data_utils.validate_us_reference_data import validate_calendar

        frame = pd.DataFrame(
            [
                {
                    "date": "2025-05-01",
                    "open": "09:30",
                    "close": "16:00",
                    "session_open": "0400",
                    "session_close": "2000",
                    "is_open": True,
                    "source": "alpaca_calendar",
                    "updated_at": "2026-05-20T00:00:00Z",
                }
            ]
        )

        report = validate_calendar(frame)
        self.assertTrue(report.ok)
        self.assertEqual(report.rows, 1)
        self.assertEqual(report.duplicate_dates, 0)

    def test_validate_corporate_actions_accepts_canonical_frame(self):
        from scripts.data_utils.validate_us_reference_data import validate_corporate_actions

        frame = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "ca_type": "dividend",
                    "ca_sub_type": "cash",
                    "declaration_date": "2026-05-07",
                    "effective_date": "2026-05-11",
                    "ex_date": "2026-05-11",
                    "record_date": "2026-05-11",
                    "payable_date": "2026-05-14",
                    "cash": 0.27,
                    "old_rate": 1.0,
                    "new_rate": 1.0,
                    "source": "alpaca_corporate_actions",
                    "updated_at": "2026-05-20T00:00:00Z",
                }
            ]
        )

        report = validate_corporate_actions(frame)
        self.assertTrue(report.ok)
        self.assertEqual(report.rows, 1)
        self.assertEqual(report.duplicate_rows, 0)

    def test_load_reference_table_reads_parquet(self):
        from scripts.data_utils.validate_us_reference_data import load_reference_table

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.parquet"
            pd.DataFrame([{"symbol": "AAPL"}]).to_parquet(path, index=False)
            frame = load_reference_table(path)

        self.assertEqual(len(frame), 1)


class CorporateActionsDownloadTest(unittest.TestCase):
    def test_build_date_windows_splits_into_ninety_day_chunks(self):
        from scripts.data_download.download_us_corporate_actions import build_date_windows

        windows = build_date_windows(date(2026, 1, 1), date(2026, 5, 21), max_days=90)

        self.assertEqual(
            windows,
            [
                ("2026-01-01", "2026-03-31"),
                ("2026-04-01", "2026-05-21"),
            ],
        )

    def test_merge_corporate_actions_deduplicates_existing_rows(self):
        from scripts.data_download.download_us_corporate_actions import merge_corporate_actions

        existing = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "ca_type": "dividend",
                    "ca_sub_type": "cash",
                    "declaration_date": "2026-05-07",
                    "effective_date": "2026-05-11",
                    "ex_date": "2026-05-11",
                    "record_date": "2026-05-11",
                    "payable_date": "2026-05-14",
                    "cash": 0.27,
                    "old_rate": 1.0,
                    "new_rate": 1.0,
                    "source": "alpaca_corporate_actions",
                    "updated_at": "2026-05-20T00:00:00Z",
                }
            ]
        )
        incoming = existing.copy()
        incoming["updated_at"] = ["2026-05-21T00:00:00Z"]

        merged = merge_corporate_actions(existing, incoming)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.iloc[0]["updated_at"], "2026-05-21T00:00:00Z")

    def test_download_corporate_actions_uses_multiple_windows(self):
        from scripts.data_download.download_us_corporate_actions import download_corporate_actions

        first = pd.DataFrame(
            [
                {
                    "symbol": "MSFT",
                    "ca_type": "dividend",
                    "ca_sub_type": "cash",
                    "declaration_date": "2026-02-17",
                    "effective_date": "2026-02-19",
                    "ex_date": "2026-02-19",
                    "record_date": "2026-02-19",
                    "payable_date": "2026-03-12",
                    "cash": 0.91,
                    "old_rate": 1.0,
                    "new_rate": 1.0,
                    "source": "alpaca_corporate_actions",
                    "updated_at": "2026-05-20T00:00:00Z",
                }
            ]
        )
        second = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "ca_type": "dividend",
                    "ca_sub_type": "cash",
                    "declaration_date": "2026-05-07",
                    "effective_date": "2026-05-11",
                    "ex_date": "2026-05-11",
                    "record_date": "2026-05-11",
                    "payable_date": "2026-05-14",
                    "cash": 0.27,
                    "old_rate": 1.0,
                    "new_rate": 1.0,
                    "source": "alpaca_corporate_actions",
                    "updated_at": "2026-05-20T00:00:00Z",
                }
            ]
        )

        with patch(
            "scripts.data_download.download_us_corporate_actions.fetch_corporate_actions",
            side_effect=[first, second],
        ) as mocked:
            frame = download_corporate_actions(
                since="2026-01-01",
                until="2026-05-21",
                ca_types="dividend,split",
                symbol="AAPL,MSFT",
            )

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(len(frame), 2)
        self.assertEqual(sorted(frame["symbol"].tolist()), ["AAPL", "MSFT"])


if __name__ == "__main__":
    unittest.main()
