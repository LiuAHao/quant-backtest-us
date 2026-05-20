import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class DataHelperTest(unittest.TestCase):
    def test_prepare_download_symbols_filters_special_share_suffixes(self):
        from scripts.data_utils.us_data_helpers import prepare_download_symbols

        prepared, unsupported = prepare_download_symbols(["BRK-B", "AHL$E", "AIIA.U", "MSFT"])

        self.assertEqual(prepared, ["BRK-B", "MSFT"])
        self.assertEqual(unsupported, ["AHL$E", "AIIA.U"])

    def test_write_partitioned_daily_bars_merges_latest_values(self):
        from scripts.data_utils.us_data_helpers import write_partitioned_daily_bars

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = pd.DataFrame(
                {
                    "symbol": ["AAPL"],
                    "date": ["2025-05-20"],
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.5],
                    "adj_close": [100.5],
                    "volume": [1000],
                    "dividends": [0.0],
                    "stock_splits": [0.0],
                    "amount": [100500.0],
                    "source": ["alpaca_iex"],
                    "updated_at": ["2026-05-20T00:00:00Z"],
                }
            )
            second = first.copy()
            second["close"] = [101.5]
            second["adj_close"] = [101.5]
            second["amount"] = [101500.0]
            second["updated_at"] = ["2026-05-20T00:10:00Z"]

            write_partitioned_daily_bars(first, root)
            write_partitioned_daily_bars(second, root)

            saved = pd.read_parquet(root / "year=2025" / "us_daily_bar.parquet")

        self.assertEqual(len(saved), 1)
        self.assertEqual(float(saved.iloc[0]["close"]), 101.5)


class AlpacaSourceTest(unittest.TestCase):
    def test_alpaca_symbol_mapping_round_trip(self):
        from scripts.data_source.data_source_alpaca import from_alpaca_symbol, to_alpaca_symbol

        self.assertEqual(to_alpaca_symbol("BRK-B"), "BRK.B")
        self.assertEqual(from_alpaca_symbol("BRK.B"), "BRK-B")

    def test_normalize_alpaca_bars_produces_canonical_frame(self):
        from scripts.data_source.data_source_alpaca import normalize_alpaca_bars

        frame = normalize_alpaca_bars(
            {
                "AAPL": [
                    {
                        "t": "2025-05-20T04:00:00Z",
                        "o": 189.0,
                        "h": 191.0,
                        "l": 188.0,
                        "c": 190.0,
                        "v": 12345,
                    }
                ]
            },
            updated_at="2026-05-20T00:00:00Z",
        )

        self.assertEqual(frame.iloc[0]["symbol"], "AAPL")
        self.assertEqual(frame.iloc[0]["date"], "2025-05-20")
        self.assertEqual(frame.iloc[0]["adj_close"], 190.0)
        self.assertEqual(frame.iloc[0]["source"], "alpaca_iex")


class StagedDownloadTest(unittest.TestCase):
    def test_download_batch_marks_missing_symbols_and_writes_outputs(self):
        from scripts.data_download.download_us_daily_staged import download_batch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "raw"
            output_dir = root / "standard"
            frame = pd.DataFrame(
                {
                    "symbol": ["AAPL"],
                    "date": ["2025-05-20"],
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.5],
                    "adj_close": [100.5],
                    "volume": [1000],
                    "dividends": [0.0],
                    "stock_splits": [0.0],
                    "amount": [100500.0],
                    "source": ["alpaca_iex"],
                    "updated_at": ["2026-05-20T00:00:00Z"],
                }
            )
            with patch(
                "scripts.data_download.download_us_daily_staged.fetch_daily_bars",
                return_value=frame,
            ):
                outcomes = download_batch(
                    symbols=["AAPL", "MSFT"],
                    start="2024-05-20",
                    end="2025-05-20",
                    raw_dir=raw_dir,
                    output_dir=output_dir,
                    retries=0,
                    retry_sleep=0.0,
                    feed="iex",
                    limit=10000,
                )

            outcome_map = {item.symbol: item for item in outcomes}
            self.assertEqual(outcome_map["AAPL"].status, "success")
            self.assertEqual(outcome_map["AAPL"].rows, 1)
            self.assertEqual(outcome_map["MSFT"].status, "missing")
            self.assertTrue((raw_dir / "bucket=A" / "AAPL.parquet").exists())
            self.assertTrue((output_dir / "year=2025" / "us_daily_bar.parquet").exists())

    def test_update_checkpoint_for_batch_records_partial_status(self):
        from scripts.data_download.download_us_daily_staged import DownloadOutcome, update_checkpoint_for_batch

        checkpoint: dict[str, object] = {"symbol_status": {}, "failed_symbols": [], "batches": []}
        outcomes = [
            DownloadOutcome(symbol="AAPL", status="success", rows=10, raw_path="/tmp/AAPL.parquet"),
            DownloadOutcome(symbol="MSFT", status="missing", rows=0),
        ]

        update_checkpoint_for_batch(
            checkpoint,
            outcomes,
            "batch-00001",
            ["AAPL", "MSFT"],
            "2025-05-20",
            "2026-05-20",
        )

        self.assertEqual(checkpoint["symbol_status"]["AAPL"]["status"], "success")
        self.assertEqual(checkpoint["symbol_status"]["MSFT"]["status"], "missing")
        self.assertEqual(checkpoint["failed_symbols"], ["MSFT"])
        self.assertEqual(checkpoint["batches"][0]["status"], "partial")
        self.assertEqual(checkpoint["batches"][0]["downloaded_symbols"], ["AAPL"])
        self.assertEqual(checkpoint["batches"][0]["missing_symbols"], ["MSFT"])

    def test_write_raw_symbol_bars_merges_incremental_windows(self):
        from scripts.data_download.download_us_daily_staged import write_raw_symbol_bars

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = pd.DataFrame(
                {
                    "symbol": ["AAPL"],
                    "date": ["2025-05-20"],
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.5],
                    "adj_close": [100.5],
                    "volume": [1000],
                    "dividends": [0.0],
                    "stock_splits": [0.0],
                    "amount": [100500.0],
                    "source": ["alpaca_iex"],
                    "updated_at": ["2026-05-20T00:00:00Z"],
                }
            )
            second = first.copy()
            second["date"] = ["2026-05-19"]
            second["updated_at"] = ["2026-05-20T00:10:00Z"]

            path = write_raw_symbol_bars(first, root, "AAPL")
            path = write_raw_symbol_bars(second, root, "AAPL")
            saved = pd.read_parquet(path)

        self.assertEqual(len(saved), 2)
        self.assertEqual(saved["date"].min(), "2025-05-20")
        self.assertEqual(saved["date"].max(), "2026-05-19")

    def test_checkpoint_window_mismatch_resets_success_statuses(self):
        from scripts.data_download.download_us_daily_staged import (
            checkpoint_matches_window,
            reset_checkpoint_for_window,
        )

        checkpoint = {
            "symbol_status": {
                "AAPL": {"status": "success", "max_date": "2025-05-20"},
                "AIIA.U": {"status": "unsupported"},
            },
            "failed_symbols": [],
            "batches": [{"key": "batch-00001"}],
            "last_run": {"stage": "1y", "start": "2024-05-20", "end": "2025-05-20"},
        }

        self.assertFalse(checkpoint_matches_window(checkpoint, stage="1y", start="2025-05-20", end="2026-05-20"))

        next_checkpoint = reset_checkpoint_for_window(
            checkpoint,
            stage="1y",
            start="2025-05-20",
            end="2026-05-20",
            preserved_statuses={"AIIA.U": {"status": "unsupported"}},
        )

        self.assertEqual(next_checkpoint["symbol_status"], {"AIIA.U": {"status": "unsupported"}})
        self.assertEqual(next_checkpoint["batches"], [])
        self.assertEqual(next_checkpoint["failed_symbols"], [])

    def test_select_symbols_requires_matching_symbol_window(self):
        from scripts.data_download.download_us_daily_staged import select_symbols

        checkpoint = {
            "symbol_status": {
                "AAPL": {
                    "status": "success",
                    "window_start": "2024-05-20",
                    "window_end": "2025-05-20",
                },
                "MSFT": {
                    "status": "success",
                    "window_start": "2025-05-20",
                    "window_end": "2026-05-20",
                },
            }
        }

        selected = select_symbols(
            checkpoint=checkpoint,
            symbols=["AAPL", "MSFT", "SPY"],
            retry_failed_only=False,
            start="2025-05-20",
            end="2026-05-20",
        )

        self.assertEqual(selected, ["AAPL", "SPY"])


if __name__ == "__main__":
    unittest.main()
