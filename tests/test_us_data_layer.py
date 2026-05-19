import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class YFinanceNormalizationTest(unittest.TestCase):
    def test_normalizes_multi_ticker_download_to_canonical_rows(self):
        from scripts.data_source.data_source_yfinance import normalize_yfinance_download

        raw = pd.DataFrame(
            {
                ("Open", "AAPL"): [10.0, 11.0],
                ("High", "AAPL"): [12.0, 12.5],
                ("Low", "AAPL"): [9.5, 10.5],
                ("Close", "AAPL"): [11.5, 12.0],
                ("Adj Close", "AAPL"): [11.0, 11.8],
                ("Volume", "AAPL"): [1000, 1500],
                ("Dividends", "AAPL"): [0.0, 0.1],
                ("Stock Splits", "AAPL"): [0.0, 0.0],
                ("Open", "MSFT"): [20.0, 21.0],
                ("High", "MSFT"): [22.0, 23.0],
                ("Low", "MSFT"): [19.0, 20.0],
                ("Close", "MSFT"): [21.0, 22.0],
                ("Adj Close", "MSFT"): [20.5, 21.5],
                ("Volume", "MSFT"): [2000, 2500],
                ("Dividends", "MSFT"): [0.0, 0.0],
                ("Stock Splits", "MSFT"): [0.0, 0.0],
            },
            index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
        )

        result = normalize_yfinance_download(raw, updated_at="2026-05-20T00:00:00Z")

        self.assertEqual(
            list(result.columns),
            [
                "symbol",
                "date",
                "open",
                "high",
                "low",
                "close",
                "adj_close",
                "volume",
                "dividends",
                "stock_splits",
                "amount",
                "source",
                "updated_at",
            ],
        )
        self.assertEqual(len(result), 4)
        self.assertEqual(result.iloc[0]["symbol"], "AAPL")
        self.assertEqual(result.iloc[0]["date"], "2024-01-02")
        self.assertEqual(result.iloc[0]["amount"], 11500.0)
        self.assertEqual(set(result["source"]), {"yfinance"})


class DownloadUtilityTest(unittest.TestCase):
    def test_batches_symbols_without_empty_batches(self):
        from scripts.data_download.download_us_daily import batch_symbols

        self.assertEqual(
            list(batch_symbols(["aapl", "MSFT", "nvda", "SPY", "QQQ"], 2)),
            [["AAPL", "MSFT"], ["NVDA", "SPY"], ["QQQ"]],
        )

    def test_merge_daily_bars_keeps_latest_duplicate(self):
        from scripts.data_download.download_us_daily import merge_daily_bars

        existing = pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "date": ["2024-01-02"],
                "close": [10.0],
                "updated_at": ["2026-05-19T00:00:00Z"],
            }
        )
        incoming = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "date": ["2024-01-02", "2024-01-02"],
                "close": [11.0, 20.0],
                "updated_at": ["2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z"],
            }
        )

        result = merge_daily_bars(existing, incoming)

        self.assertEqual(len(result), 2)
        aapl = result[result["symbol"] == "AAPL"].iloc[0]
        self.assertEqual(aapl["close"], 11.0)

    def test_successful_retry_removes_symbols_from_failed_checkpoint(self):
        from scripts.data_download.download_us_daily import download_batches, load_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "meta" / "checkpoint.json"
            checkpoint_path.parent.mkdir()
            checkpoint_path.write_text(
                """
                {
                  "batches": [],
                  "failed_symbols": ["AAPL", "MSFT"]
                }
                """,
                encoding="utf-8",
            )
            rows = pd.DataFrame(
                {
                    "symbol": ["AAPL", "MSFT"],
                    "date": ["2024-01-02", "2024-01-02"],
                    "open": [10.0, 20.0],
                    "high": [11.0, 21.0],
                    "low": [9.0, 19.0],
                    "close": [10.5, 20.5],
                    "adj_close": [10.5, 20.5],
                    "volume": [100, 200],
                    "dividends": [0.0, 0.0],
                    "stock_splits": [0.0, 0.0],
                    "amount": [1050.0, 4100.0],
                    "source": ["yfinance", "yfinance"],
                    "updated_at": ["2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z"],
                }
            )

            with patch("scripts.data_download.download_us_daily.fetch_daily_bars", return_value=rows):
                download_batches(
                    symbols=["AAPL", "MSFT"],
                    start="2024-01-02",
                    end="2024-01-10",
                    output_dir=root / "bars",
                    checkpoint_path=checkpoint_path,
                    batch_size=2,
                    retries=0,
                )

            checkpoint = load_checkpoint(checkpoint_path)

        self.assertEqual(checkpoint["failed_symbols"], [])

    def test_skipped_completed_batch_is_reported(self):
        from scripts.data_download.download_us_daily import download_batches

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "meta" / "checkpoint.json"
            checkpoint_path.parent.mkdir()
            checkpoint_path.write_text(
                """
                {
                  "batches": [
                    {
                      "key": "AAPL|MSFT",
                      "status": "success"
                    }
                  ],
                  "failed_symbols": []
                }
                """,
                encoding="utf-8",
            )

            result = download_batches(
                symbols=["AAPL", "MSFT"],
                start="2024-01-02",
                end="2024-01-10",
                output_dir=root / "bars",
                checkpoint_path=checkpoint_path,
                batch_size=2,
                retries=0,
            )

        self.assertEqual(result["last_run"]["rows_downloaded_this_run"], 0)
        self.assertEqual(result["last_run"]["skipped_batches"], 1)

    def test_partial_batch_keeps_missing_symbol_retryable(self):
        from scripts.data_download.download_us_daily import download_batches, load_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "meta" / "checkpoint.json"
            rows = pd.DataFrame(
                {
                    "symbol": ["AAPL"],
                    "date": ["2024-01-02"],
                    "open": [10.0],
                    "high": [11.0],
                    "low": [9.0],
                    "close": [10.5],
                    "adj_close": [10.5],
                    "volume": [100],
                    "dividends": [0.0],
                    "stock_splits": [0.0],
                    "amount": [1050.0],
                    "source": ["yfinance"],
                    "updated_at": ["2026-05-20T00:00:00Z"],
                }
            )

            with patch("scripts.data_download.download_us_daily.fetch_daily_bars", return_value=rows):
                download_batches(
                    symbols=["AAPL", "META"],
                    start="2024-01-02",
                    end="2024-01-10",
                    output_dir=root / "bars",
                    checkpoint_path=checkpoint_path,
                    batch_size=2,
                    retries=0,
                )

            checkpoint = load_checkpoint(checkpoint_path)
            saved = pd.read_parquet(root / "bars" / "year=2024" / "us_daily_bar.parquet")

        self.assertEqual(checkpoint["failed_symbols"], ["META"])
        self.assertEqual(checkpoint["batches"][0]["status"], "partial")
        self.assertEqual(checkpoint["batches"][0]["downloaded_symbols"], ["AAPL"])
        self.assertEqual(checkpoint["batches"][0]["missing_symbols"], ["META"])
        self.assertEqual(saved["symbol"].tolist(), ["AAPL"])

    def test_empty_batch_result_marks_all_symbols_missing(self):
        from scripts.data_download.download_us_daily import download_batches, load_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "meta" / "checkpoint.json"
            rows = pd.DataFrame(
                columns=[
                    "symbol",
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "adj_close",
                    "volume",
                    "dividends",
                    "stock_splits",
                    "amount",
                    "source",
                    "updated_at",
                ]
            )

            with patch("scripts.data_download.download_us_daily.fetch_daily_bars", return_value=rows):
                download_batches(
                    symbols=["AAPL", "META"],
                    start="2024-01-02",
                    end="2024-01-10",
                    output_dir=root / "bars",
                    checkpoint_path=checkpoint_path,
                    batch_size=2,
                    retries=0,
                )

            checkpoint = load_checkpoint(checkpoint_path)

        self.assertEqual(checkpoint["failed_symbols"], ["AAPL", "META"])
        self.assertEqual(checkpoint["batches"][0]["status"], "partial")
        self.assertEqual(checkpoint["batches"][0]["downloaded_symbols"], [])
        self.assertEqual(checkpoint["batches"][0]["missing_symbols"], ["AAPL", "META"])

    def test_symbol_status_is_written_for_downloaded_and_missing_symbols(self):
        from scripts.data_download.download_us_daily import download_batches, load_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "meta" / "checkpoint.json"
            rows = pd.DataFrame(
                {
                    "symbol": ["AAPL"],
                    "date": ["2024-01-02"],
                    "open": [10.0],
                    "high": [11.0],
                    "low": [9.0],
                    "close": [10.5],
                    "adj_close": [10.5],
                    "volume": [100],
                    "dividends": [0.0],
                    "stock_splits": [0.0],
                    "amount": [1050.0],
                    "source": ["yfinance"],
                    "updated_at": ["2026-05-20T00:00:00Z"],
                }
            )

            with patch("scripts.data_download.download_us_daily.fetch_daily_bars", return_value=rows):
                download_batches(
                    symbols=["AAPL", "META"],
                    start="2024-01-02",
                    end="2024-01-10",
                    output_dir=root / "bars",
                    checkpoint_path=checkpoint_path,
                    batch_size=2,
                    retries=0,
                )

            checkpoint = load_checkpoint(checkpoint_path)

        self.assertEqual(checkpoint["symbol_status"]["AAPL"]["status"], "success")
        self.assertEqual(checkpoint["symbol_status"]["META"]["status"], "missing")

    def test_coverage_report_counts_symbol_status(self):
        from scripts.data_download.download_us_daily import build_coverage_report

        checkpoint = {
            "symbol_status": {
                "AAPL": {"status": "success"},
                "MSFT": {"status": "success"},
                "META": {"status": "missing"},
                "ZZZZ": {"status": "failed"},
            }
        }

        report = build_coverage_report(checkpoint, requested_symbols=["AAPL", "MSFT", "META", "ZZZZ"])

        self.assertEqual(report["requested_symbols"], 4)
        self.assertEqual(report["success_symbols"], 2)
        self.assertEqual(report["missing_symbols"], 1)
        self.assertEqual(report["failed_symbols"], 1)


class UniverseUtilityTest(unittest.TestCase):
    def test_parse_nasdaq_trader_rows_filters_test_and_non_tradable_entries(self):
        from scripts.data_download.build_us_universe import parse_nasdaq_trader_rows

        rows = [
            {
                "Symbol": "AAPL",
                "Test Issue": "N",
                "ETF": "N",
                "Round Lot Size": "100",
                "Financial Status": "N",
            },
            {
                "Symbol": "QQQ",
                "Test Issue": "N",
                "ETF": "Y",
                "Round Lot Size": "100",
                "Financial Status": "N",
            },
            {
                "Symbol": "ZVZZT",
                "Test Issue": "Y",
                "ETF": "N",
                "Round Lot Size": "100",
                "Financial Status": "N",
            },
            {
                "Symbol": "ODD",
                "Test Issue": "N",
                "ETF": "N",
                "Round Lot Size": "0",
                "Financial Status": "N",
            },
        ]

        report = parse_nasdaq_trader_rows(rows)

        self.assertEqual(report["symbols"], ["AAPL", "QQQ"])
        self.assertEqual(report["counts"]["kept"], 2)
        self.assertEqual(report["counts"]["filtered"], 2)


class ValidationTest(unittest.TestCase):
    def test_validates_required_columns_duplicates_and_price_ranges(self):
        from scripts.data_utils.validate_us_data import validate_daily_bars

        frame = pd.DataFrame(
            {
                "symbol": ["AAPL", "AAPL"],
                "date": ["2024-01-02", "2024-01-02"],
                "open": [10.0, 10.0],
                "high": [9.0, 11.0],
                "low": [8.0, 8.0],
                "close": [9.5, 10.5],
                "adj_close": [9.4, 10.4],
                "volume": [100, -1],
                "source": ["yfinance", "yfinance"],
                "updated_at": ["2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z"],
            }
        )

        report = validate_daily_bars(frame)

        self.assertFalse(report.ok)
        self.assertGreater(report.duplicate_symbol_dates, 0)
        self.assertGreater(report.invalid_price_rows, 0)
        self.assertGreater(report.invalid_volume_rows, 0)

    def test_loads_partitioned_parquet_for_validation(self):
        from scripts.data_utils.validate_us_data import load_daily_bars

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            partition = root / "year=2024"
            partition.mkdir()
            pd.DataFrame({"symbol": ["AAPL"], "date": ["2024-01-02"]}).to_parquet(
                partition / "part.parquet",
                index=False,
            )

            result = load_daily_bars(root)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["symbol"], "AAPL")


if __name__ == "__main__":
    unittest.main()
