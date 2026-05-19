from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import numpy as np

from backtest.data_loader import DataLoader
from tests.helpers.market_data import (
    write_adj_factor,
    write_calendar,
    write_daily_bar,
    write_daily_basic,
    write_stk_limit,
)
from tests.helpers.temp_env import TempProjectEnv


def _make_fixture_data(root: Path):
    """Create minimal parquet fixtures for one stock over 5 trading days.

    Files are placed in year-partitioned subdirectories (2025/*.parquet)
    to match the hive_partitioning=1 glob used by DataLoader.
    """
    dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]

    bars = []
    closes = [10.0, 10.5, 10.2, 10.8, 11.0]
    for i, (dt, c) in enumerate(zip(dates, closes)):
        bars.append({
            "ts_code": "000001.SZ",
            "trade_date": dt,
            "open": c - 0.2,
            "high": c + 0.3,
            "low": c - 0.4,
            "close": c,
            "pre_close": closes[i - 1] if i > 0 else c,
            "volume": 1000000,
            "amount": 10000000.0,
        })
    write_daily_bar(root, bars, partition="2025")

    factors = [1.0, 1.0, 2.0, 2.0, 2.0]
    write_adj_factor(
        root,
        [
            {"ts_code": "000001.SZ", "trade_date": dt, "adj_factor": f}
            for dt, f in zip(dates, factors)
        ],
        partition="2025",
    )

    write_calendar(root, [{"trade_date": dt, "is_open": 1} for dt in dates])

    write_daily_basic(
        root,
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": dt,
                "circ_mv": 100000.0,
                "total_mv": 200000.0,
                "total_share": 50000.0,
                "float_share": 40000.0,
                "free_share": 35000.0,
                "turnover_rate": 1.5,
                "pe_ttm": 12.0,
                "pb": 1.2,
            }
            for dt in dates
        ],
        partition="2025",
    )

    write_stk_limit(
        root,
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": dt,
                "up_limit": round(c * 1.1, 2),
                "down_limit": round(c * 0.9, 2),
            }
            for dt, c in zip(dates, closes)
        ],
        partition="2025",
    )


class DataLoaderAdjustmentTest(unittest.TestCase):
    """Tests for qfq / hfq adjustment correctness."""

    def setUp(self):
        self.env = TempProjectEnv.under_cwd(self._testMethodName).patch_data_dirs().start()
        self.tmp_path = self.env.data_dir
        _make_fixture_data(self.tmp_path)
        self.loader = DataLoader()

    def tearDown(self):
        self.loader.close()
        self.env.stop()

    def test_qfq_uses_latest_day_factor(self):
        """qfq should use the latest day's adj_factor as the base."""
        df = self.loader.get_history("000001.SZ", "2025-01-08", window=5, adjust="qfq")
        self.assertFalse(df.empty)
        self.assertIn("close_fq", df.columns)

        # Latest day factor = 2.0, so latest close_fq = 11.0 * 2.0 / 2.0 = 11.0
        latest_close_fq = df.iloc[-1]["close_fq"]
        self.assertAlmostEqual(latest_close_fq, 11.0, places=4)

        # Day 1 factor = 1.0, so day1 close_fq = 10.0 * 1.0 / 2.0 = 5.0
        first_close_fq = df.iloc[0]["close_fq"]
        self.assertAlmostEqual(first_close_fq, 5.0, places=4)

    def test_hfq_uses_first_day_factor(self):
        """hfq should use the first day's adj_factor as the base."""
        df = self.loader.get_history("000001.SZ", "2025-01-08", window=5, adjust="hfq")
        self.assertFalse(df.empty)
        self.assertIn("close_fq", df.columns)

        # First day factor = 1.0, so first close_fq = 10.0 * 1.0 / 1.0 = 10.0
        first_close_fq = df.iloc[0]["close_fq"]
        self.assertAlmostEqual(first_close_fq, 10.0, places=4)

        # Last day factor = 2.0, so last close_fq = 11.0 * 2.0 / 1.0 = 22.0
        latest_close_fq = df.iloc[-1]["close_fq"]
        self.assertAlmostEqual(latest_close_fq, 22.0, places=4)

    def test_get_history_returns_ascending_order(self):
        """get_history should always return data in ascending date order."""
        df = self.loader.get_history("000001.SZ", "2025-01-08", window=5, adjust="qfq")
        dates = pd.to_datetime(df["trade_date"]).tolist()
        self.assertEqual(dates, sorted(dates))

    def test_no_adjust(self):
        """No adjustment should return original prices."""
        df = self.loader.get_history("000001.SZ", "2025-01-08", window=5, adjust=None)
        self.assertFalse(df.empty)
        self.assertAlmostEqual(df.iloc[-1]["close"], 11.0, places=4)

    def test_empty_result(self):
        """Querying a non-existent stock should return empty DataFrame."""
        df = self.loader.get_history("NONEXIST.SZ", "2025-01-08", window=5)
        self.assertTrue(df.empty)

    def test_cross_section_returns_data(self):
        """get_cross_section should return data for all stocks on a given date."""
        df = self.loader.get_cross_section("2025-01-08")
        self.assertFalse(df.empty)
        self.assertIn("ts_code", df.columns)
        self.assertIn("up_limit", df.columns)
        self.assertIn("down_limit", df.columns)

    def test_trade_calendar(self):
        """get_trade_calendar should return calendar entries."""
        cal = self.loader.get_trade_calendar(start_date="2025-01-02", end_date="2025-01-08")
        self.assertEqual(len(cal), 5)

    def test_is_trade_date(self):
        self.assertTrue(self.loader.is_trade_date("2025-01-02"))
        self.assertFalse(self.loader.is_trade_date("2025-01-04"))  # Saturday

    def test_window_limits_results(self):
        """window parameter should limit the number of rows returned."""
        df = self.loader.get_history("000001.SZ", "2025-01-08", window=3, adjust=None)
        self.assertEqual(len(df), 3)

    def test_get_history_cache_hit(self):
        """After warm_up_cache, get_history should use cache and return consistent results."""
        from datetime import datetime
        self.loader.warm_up_cache(
            ["000001.SZ"],
            datetime(2025, 1, 2),
            datetime(2025, 1, 8),
        )
        df_cached = self.loader.get_history("000001.SZ", "2025-01-08", window=5, adjust="qfq")
        self.assertFalse(df_cached.empty)
        self.assertIn("close_fq", df_cached.columns)
        # Verify ascending order
        dates = pd.to_datetime(df_cached["trade_date"]).tolist()
        self.assertEqual(dates, sorted(dates))

    def test_get_history_cache_returns_copy(self):
        """Cached results should be copies to avoid mutation."""
        from datetime import datetime
        self.loader.warm_up_cache(
            ["000001.SZ"],
            datetime(2025, 1, 2),
            datetime(2025, 1, 8),
        )
        df1 = self.loader.get_history("000001.SZ", "2025-01-08", window=5, adjust=None)
        df2 = self.loader.get_history("000001.SZ", "2025-01-08", window=5, adjust=None)
        self.assertFalse(df1 is df2)  # Different objects

    def test_get_history_cache_handles_datetime_trade_dates(self):
        """Cached trade_date values may be datetime-like in real parquet files."""
        cached = self.loader.get_history("000001.SZ", "2025-01-08", window=5, adjust=None)
        cached["trade_date"] = pd.to_datetime(cached["trade_date"])
        self.loader._cache["000001.SZ"] = cached

        df = self.loader.get_history("000001.SZ", "2025-01-07", window=2, adjust=None)
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[-1]["trade_date"].strftime("%Y-%m-%d"), "2025-01-07")

    def test_get_history_rejects_unsafe_field_name(self):
        """Dynamic SELECT fields must be identifiers, not SQL fragments."""
        with self.assertRaises(ValueError):
            self.loader.get_history(
                "000001.SZ",
                "2025-01-08",
                fields=["close", "amount FROM daily_bar; DROP TABLE daily_bar; --"],
            )

    def test_get_cross_section_rejects_unsafe_field_name(self):
        with self.assertRaises(ValueError):
            self.loader.get_cross_section(
                "2025-01-08",
                fields=["ts_code", "close) AS hacked FROM daily_bar --"],
            )


if __name__ == "__main__":
    unittest.main()
