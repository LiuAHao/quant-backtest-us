import tempfile
import unittest
from pathlib import Path

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
