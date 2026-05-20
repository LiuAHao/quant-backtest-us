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
    def test_prepare_download_symbols_converts_share_classes_and_flags_unsupported(self):
        from scripts.data_download.download_us_daily import prepare_download_symbols

        prepared, unsupported = prepare_download_symbols(
            ["AKO.A", "AKO.B", "AHL$E", "AIIA.U", "BRK-B", "MSFT"]
        )

        self.assertEqual(prepared, ["AKO-A", "AKO-B", "BRK-B", "MSFT"])
        self.assertEqual(unsupported, ["AHL$E", "AIIA.U"])

    def test_read_symbols_file_raises_clear_error_for_missing_file(self):
        from scripts.data_download.download_us_daily import read_symbols_file

        missing = Path("/tmp/definitely_missing_us_all.txt")
        if missing.exists():
            missing.unlink()

        with self.assertRaisesRegex(FileNotFoundError, "Symbols file not found"):
            read_symbols_file(missing)

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

    def test_unsupported_symbols_are_marked_without_download_attempt(self):
        from scripts.data_download.download_us_daily import prepare_download_symbols, update_symbol_status

        checkpoint = {"symbol_status": {}}
        prepared, unsupported = prepare_download_symbols(["AHL$E", "AIIA.U", "MSFT"])
        update_symbol_status(
            checkpoint,
            completed_at="2026-05-20T00:00:00Z",
        )
        for symbol in unsupported:
            checkpoint["symbol_status"][symbol] = {
                "status": "unsupported",
                "completed_at": "2026-05-20T00:00:00Z",
            }

        self.assertEqual(prepared, ["MSFT"])
        self.assertEqual(unsupported, ["AHL$E", "AIIA.U"])
        self.assertEqual(checkpoint["symbol_status"]["AHL$E"]["status"], "unsupported")

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

    def test_load_checkpoint_backfills_symbol_status_and_coverage_from_legacy_file(self):
        from scripts.data_download.download_us_daily import load_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "checkpoint.json"
            checkpoint_path.write_text(
                """
                {
                  "batches": [
                    {
                      "symbols": ["AAPL", "MSFT"],
                      "status": "success",
                      "downloaded_symbols": ["AAPL", "MSFT"],
                      "missing_symbols": []
                    },
                    {
                      "symbols": ["META"],
                      "status": "partial",
                      "downloaded_symbols": [],
                      "missing_symbols": ["META"]
                    }
                  ],
                  "failed_symbols": ["TSLA"]
                }
                """,
                encoding="utf-8",
            )

            checkpoint = load_checkpoint(checkpoint_path)

        self.assertEqual(checkpoint["symbol_status"]["AAPL"]["status"], "success")
        self.assertEqual(checkpoint["symbol_status"]["META"]["status"], "missing")
        self.assertEqual(checkpoint["symbol_status"]["TSLA"]["status"], "failed")
        self.assertEqual(checkpoint["coverage_report"]["requested_symbols"], 3)

    def test_success_status_is_not_overwritten_by_later_missing(self):
        from scripts.data_download.download_us_daily import update_symbol_status

        checkpoint = {"symbol_status": {}}
        update_symbol_status(
            checkpoint,
            success_symbols=["AVGO"],
            completed_at="2026-05-20T00:00:00Z",
        )
        update_symbol_status(
            checkpoint,
            missing_symbols=["AVGO"],
            completed_at="2026-05-21T00:00:00Z",
        )

        self.assertEqual(checkpoint["symbol_status"]["AVGO"]["status"], "success")

    def test_load_checkpoint_backfills_success_from_existing_parquet(self):
        from scripts.data_download.download_us_daily import load_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "checkpoint.json"
            checkpoint_path.write_text(
                """
                {
                  "batches": [
                    {
                      "symbols": ["AVGO"],
                      "status": "partial",
                      "downloaded_symbols": [],
                      "missing_symbols": ["AVGO"]
                    }
                  ],
                  "failed_symbols": ["AVGO"]
                }
                """,
                encoding="utf-8",
            )
            bars_root = root / "bars"
            partition = bars_root / "year=2024"
            partition.mkdir(parents=True)
            pd.DataFrame(
                {
                    "symbol": ["AVGO"],
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
            ).to_parquet(partition / "us_daily_bar.parquet", index=False)

            checkpoint = load_checkpoint(checkpoint_path, output_dir=bars_root)

        self.assertEqual(checkpoint["symbol_status"]["AVGO"]["status"], "success")
        self.assertEqual(checkpoint["failed_symbols"], [])

    def test_failed_batch_falls_back_to_single_symbol_retries(self):
        from scripts.data_download.download_us_daily import download_batches, load_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "meta" / "checkpoint.json"

            def fake_fetch(symbols, **_kwargs):
                if len(symbols) > 1:
                    raise RuntimeError("batch failed")
                symbol = symbols[0]
                if symbol == "META":
                    raise RuntimeError("single failed")
                return pd.DataFrame(
                    {
                        "symbol": [symbol],
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

            with patch("scripts.data_download.download_us_daily.fetch_daily_bars", side_effect=fake_fetch):
                download_batches(
                    symbols=["AAPL", "META"],
                    start="2024-01-02",
                    end="2024-01-10",
                    output_dir=root / "bars",
                    checkpoint_path=checkpoint_path,
                    batch_size=2,
                    retries=0,
                    fallback_to_single_symbol=True,
                )

            checkpoint = load_checkpoint(checkpoint_path)

        self.assertEqual(checkpoint["symbol_status"]["AAPL"]["status"], "success")
        self.assertEqual(checkpoint["symbol_status"]["META"]["status"], "failed")
        self.assertEqual(checkpoint["failed_symbols"], ["META"])

    def test_retry_failed_only_uses_checkpoint_failed_and_missing_symbols(self):
        from scripts.data_download.download_us_daily import resolve_retry_symbols

        checkpoint = {
            "symbol_status": {
                "AAPL": {"status": "success"},
                "META": {"status": "missing"},
                "TSLA": {"status": "failed"},
                "MSFT": {"status": "unknown"},
            }
        }

        symbols = resolve_retry_symbols(checkpoint)

        self.assertEqual(symbols, ["META", "TSLA"])

    def test_write_status_files_exports_failed_missing_and_success_symbols(self):
        from scripts.data_download.download_us_daily import write_status_files

        checkpoint = {
            "symbol_status": {
                "AAPL": {"status": "success"},
                "META": {"status": "missing"},
                "TSLA": {"status": "failed"},
                "AHL$E": {"status": "unsupported"},
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            meta_dir = Path(tmp)
            write_status_files(meta_dir, checkpoint)

            failed = (meta_dir / "failed_symbols.txt").read_text(encoding="utf-8").splitlines()
            missing = (meta_dir / "missing_symbols.txt").read_text(encoding="utf-8").splitlines()
            success = (meta_dir / "success_symbols.txt").read_text(encoding="utf-8").splitlines()
            unsupported = (meta_dir / "unsupported_symbols.txt").read_text(encoding="utf-8").splitlines()

        self.assertEqual(failed, ["TSLA"])
        self.assertEqual(missing, ["META"])
        self.assertEqual(success, ["AAPL"])
        self.assertEqual(unsupported, ["AHL$E"])

    def test_download_batches_writes_status_files_via_main_flow_helpers(self):
        from scripts.data_download.download_us_daily import download_batches, load_checkpoint, write_status_files

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
                checkpoint = download_batches(
                    symbols=["AAPL", "META"],
                    start="2024-01-02",
                    end="2024-01-10",
                    output_dir=root / "bars",
                    checkpoint_path=checkpoint_path,
                    batch_size=2,
                    retries=0,
                )
            write_status_files(checkpoint_path.parent, checkpoint)
            saved = load_checkpoint(checkpoint_path)

            failed = (checkpoint_path.parent / "failed_symbols.txt").read_text(encoding="utf-8").splitlines()
            missing = (checkpoint_path.parent / "missing_symbols.txt").read_text(encoding="utf-8").splitlines()
            summary = (checkpoint_path.parent / "download_us_daily_report.json").read_text(encoding="utf-8")

        self.assertEqual(saved["coverage_report"]["requested_symbols"], 2)
        self.assertEqual(failed, [])
        self.assertEqual(missing, ["META"])
        self.assertIn('"missing_symbols"', summary)


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

    def test_parse_nasdaq_trader_rows_normalizes_share_classes_and_skips_unsupported_suffixes(self):
        from scripts.data_download.build_us_universe import parse_nasdaq_trader_rows

        rows = [
            {"ACT Symbol": "AKO.A", "Test Issue": "N", "Round Lot Size": "100"},
            {"ACT Symbol": "AKO.B", "Test Issue": "N", "Round Lot Size": "100"},
            {"ACT Symbol": "AIIA.U", "Test Issue": "N", "Round Lot Size": "100"},
            {"ACT Symbol": "AHL$E", "Test Issue": "N", "Round Lot Size": "100"},
        ]

        report = parse_nasdaq_trader_rows(rows)

        self.assertEqual(report["symbols"], ["AKO-A", "AKO-B"])
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

    def test_negative_adj_close_is_reported_separately_from_invalid_ohlc_rows(self):
        from scripts.data_utils.validate_us_data import validate_daily_bars

        frame = pd.DataFrame(
            {
                "symbol": ["SVA"],
                "date": ["2010-01-04"],
                "open": [6.39],
                "high": [6.62],
                "low": [6.39],
                "close": [6.55],
                "adj_close": [-49.13],
                "volume": [935377],
                "source": ["yfinance"],
                "updated_at": ["2026-05-20T00:00:00Z"],
            }
        )

        report = validate_daily_bars(frame)

        self.assertEqual(report.invalid_price_rows, 0)
        self.assertEqual(report.invalid_adjusted_close_rows, 1)

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
