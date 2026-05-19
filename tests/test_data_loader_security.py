from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from backtest.data_loader import DataLoader
from tests.helpers.market_data import (
    write_adj_factor,
    write_calendar,
    write_daily_bar,
    write_daily_basic,
    write_financial,
    write_instruments,
)
from tests.helpers.temp_env import TempProjectEnv


# SQL injection payloads commonly used in tests
INJECTION_PAYLOADS = [
    "'; DROP TABLE daily_bar; --",
    "' OR '1'='1",
    "' OR 1=1 --",
    "'; SELECT * FROM calendar; --",
    "\" OR \"\"=\"\"",
    "1; DELETE FROM calendar WHERE 1=1",
    "' UNION SELECT * FROM calendar --",
]


def _make_security_fixtures(root: Path):
    """Create parquet fixtures with instruments, calendar (with next/prev), and financial data."""
    dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]

    write_daily_bar(
        root,
        [
            {
                "ts_code": "000001.SZ", "trade_date": dt,
                "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2,
                "pre_close": 10.0, "volume": 100000, "amount": 1000000.0,
            }
            for dt in dates
        ],
        partition="2025",
    )

    write_adj_factor(
        root,
        [{"ts_code": "000001.SZ", "trade_date": dt, "adj_factor": 1.0} for dt in dates],
        partition="2025",
    )

    next_dates = dates[1:] + [None]
    prev_dates = [None] + dates[:-1]
    write_calendar(
        root,
        [
            {
                "trade_date": dt,
                "is_open": 1,
                "next_trade_date": nd,
                "prev_trade_date": pd_val,
            }
            for dt, nd, pd_val in zip(dates, next_dates, prev_dates)
        ],
    )

    write_daily_basic(
        root,
        [
            {
                "ts_code": "000001.SZ", "trade_date": dt,
                "circ_mv": 100000.0, "total_mv": 200000.0,
                "total_share": 50000.0, "float_share": 40000.0,
                "free_share": 35000.0, "turnover_rate": 1.5,
                "pe_ttm": 12.0, "pb": 1.2,
            }
            for dt in dates
        ],
        partition="2025",
    )

    write_instruments(
        root,
        [
            {"ts_code": "000001.SZ", "name": "平安银行", "exchange": "SZ", "status": "L", "list_date": "1991-04-03"},
            {"ts_code": "600000.SH", "name": "浦发银行", "exchange": "SH", "status": "L", "list_date": "1999-11-10"},
            {"ts_code": "000002.SZ", "name": "万科A", "exchange": "SZ", "status": "L", "list_date": "1991-01-29"},
        ],
    )

    write_financial(
        root,
        [
            {
                "ts_code": "000001.SZ", "ann_date": "2025-01-05", "end_date": "2024-12-31",
                "roe": 10.5, "roa": 0.8,
            },
        ],
    )


class DataLoaderSecurityTest(unittest.TestCase):
    """Tests verifying SQL injection cannot expand query scope or execute extra statements."""

    def setUp(self):
        self.env = TempProjectEnv.under_cwd(self._testMethodName).patch_data_dirs().start()
        self.tmp_path = self.env.data_dir
        _make_security_fixtures(self.tmp_path)
        self.loader = DataLoader()

    def tearDown(self):
        self.loader.close()
        self.env.stop()

    # =========================================================
    # get_adj_factor — ts_code goes directly into SQL as a param
    # =========================================================

    def test_get_adj_factor_injection_ts_code_returns_none(self):
        """Malicious ts_code passed as parameter — should return None (no match), not execute injection."""
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                result = self.loader.get_adj_factor(payload, "2025-01-02")
                self.assertIsNone(result)

    def test_get_adj_factor_injection_date_raises(self):
        """Malicious date strings rejected by _to_datetime() before reaching SQL."""
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.loader.get_adj_factor("000001.SZ", payload)

    def test_get_adj_factor_normal(self):
        """Normal call should still work after parameterization."""
        result = self.loader.get_adj_factor("000001.SZ", "2025-01-02")
        self.assertEqual(result, 1.0)

    # =========================================================
    # get_next_trade_date / get_prev_trade_date — date parsed by _to_datetime
    # =========================================================

    def test_get_next_trade_date_injection_raises(self):
        """Malicious dates rejected by _to_datetime()."""
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.loader.get_next_trade_date(payload)

    def test_get_next_trade_date_normal(self):
        result = self.loader.get_next_trade_date("2025-01-02")
        self.assertIsNotNone(result)
        self.assertEqual(result.strftime("%Y-%m-%d"), "2025-01-03")

    def test_get_prev_trade_date_injection_raises(self):
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.loader.get_prev_trade_date(payload)

    def test_get_prev_trade_date_normal(self):
        result = self.loader.get_prev_trade_date("2025-01-03")
        self.assertIsNotNone(result)
        self.assertEqual(result.strftime("%Y-%m-%d"), "2025-01-02")

    # =========================================================
    # is_trade_date — date parsed by _to_datetime
    # =========================================================

    def test_is_trade_date_injection_raises(self):
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.loader.is_trade_date(payload)

    def test_is_trade_date_normal(self):
        self.assertTrue(self.loader.is_trade_date("2025-01-02"))

    # =========================================================
    # get_trade_calendar — dates parsed by _to_datetime
    # =========================================================

    def test_get_trade_calendar_injection_dates_raises(self):
        """Injected dates rejected by _to_datetime()."""
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.loader.get_trade_calendar(start_date=payload, end_date="2025-01-08")
                with self.assertRaises(ValueError):
                    self.loader.get_trade_calendar(start_date="2025-01-02", end_date=payload)

    def test_get_trade_calendar_normal(self):
        cal = self.loader.get_trade_calendar(start_date="2025-01-02", end_date="2025-01-08")
        self.assertEqual(len(cal), 5)

    # =========================================================
    # get_instruments — exchange/status validated against whitelist
    # =========================================================

    def test_get_instruments_invalid_exchange_raises(self):
        """Invalid exchange values should raise ValueError, not be interpolated into SQL."""
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.loader.get_instruments(exchange=payload)

    def test_get_instruments_invalid_status_raises(self):
        """Invalid status values should raise ValueError."""
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.loader.get_instruments(status=payload)

    def test_get_instruments_valid_exchange(self):
        df = self.loader.get_instruments(exchange="SZ")
        self.assertFalse(df.empty)
        self.assertTrue((df["exchange"] == "SZ").all())

    def test_get_instruments_valid_status(self):
        df = self.loader.get_instruments(status="L")
        self.assertFalse(df.empty)
        self.assertTrue((df["status"] == "L").all())

    def test_get_instruments_no_filter(self):
        df = self.loader.get_instruments()
        self.assertEqual(len(df), 3)

    # =========================================================
    # get_latest_financial — table validated against whitelist
    # =========================================================

    def test_get_latest_financial_injection_ts_code_returns_none(self):
        """Malicious ts_code passed as parameter — should return None (no match)."""
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                result = self.loader.get_latest_financial(payload, "2025-01-08")
                self.assertIsNone(result)

    def test_get_latest_financial_invalid_table_returns_none(self):
        """Invalid table names should be rejected, not interpolated."""
        for payload in ["daily_bar", "calendar; DROP TABLE fina_indicator; --", "UNION SELECT", "fina_indicator; --"]:
            with self.subTest(payload=payload):
                result = self.loader.get_latest_financial("000001.SZ", "2025-01-08", table=payload)
                self.assertIsNone(result)

    def test_get_latest_financial_normal(self):
        result = self.loader.get_latest_financial("000001.SZ", "2025-01-08")
        self.assertIsNotNone(result)
        self.assertFalse(result.empty)

    # =========================================================
    # get_financial_cross_section — table validated against whitelist
    # =========================================================

    def test_get_financial_cross_section_invalid_table(self):
        result = self.loader.get_financial_cross_section("2025-01-08", table="daily_bar")
        self.assertTrue(result.empty)

    def test_get_financial_cross_section_normal(self):
        result = self.loader.get_financial_cross_section("2025-01-08")
        self.assertFalse(result.empty)

    # =========================================================
    # get_history / get_cross_section — ts_code as parameter
    # =========================================================

    def test_get_history_injection_ts_code_returns_empty(self):
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                df = self.loader.get_history(payload, "2025-01-08", window=5)
                self.assertTrue(df.empty)

    def test_get_cross_section_injection_date_raises(self):
        for payload in INJECTION_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.loader.get_cross_section(payload)

    # =========================================================
    # White-box: source inspection confirms parameterized queries
    # =========================================================

    def test_adj_factor_sql_uses_question_mark_params(self):
        """Source inspection: get_adj_factor SQL must use ? placeholders, not f-string interpolation."""
        import inspect
        src = inspect.getsource(self.loader.get_adj_factor.__func__)
        self.assertIn("? AND trade_date = ?", src)
        # Ensure no f-string with ts_code or date_str in the SQL query
        self.assertNotIn("'{ts_code}'", src)
        self.assertNotIn("'{date_str}'", src)

    def test_instruments_sql_uses_question_mark_params(self):
        """Source inspection: get_instruments SQL must use ? placeholders."""
        import inspect
        src = inspect.getsource(self.loader.get_instruments.__func__)
        self.assertIn("exchange = ?", src)
        self.assertIn("status = ?", src)

    def test_calendar_sql_uses_question_mark_params(self):
        """Source inspection: get_trade_calendar SQL must use ? placeholders."""
        import inspect
        src = inspect.getsource(self.loader.get_trade_calendar.__func__)
        self.assertIn("trade_date >= ?", src)
        self.assertIn("trade_date <= ?", src)

    def test_next_prev_trade_date_sql_uses_question_mark_params(self):
        """Source inspection: get_next/prev_trade_date SQL must use ? placeholders."""
        import inspect
        src_next = inspect.getsource(self.loader.get_next_trade_date.__func__)
        src_prev = inspect.getsource(self.loader.get_prev_trade_date.__func__)
        self.assertIn("WHERE trade_date = ?", src_next)
        self.assertIn("WHERE trade_date = ?", src_prev)

    def test_is_trade_date_sql_uses_question_mark_params(self):
        """Source inspection: is_trade_date SQL must use ? placeholders."""
        import inspect
        src = inspect.getsource(self.loader.is_trade_date.__func__)
        self.assertIn("WHERE trade_date = ?", src)

    def test_prepare_backtest_data_sql_uses_question_mark_params(self):
        """Source inspection: prepare_backtest_data SQL must use ? placeholders."""
        import inspect
        src = inspect.getsource(self.loader.prepare_backtest_data.__func__)
        self.assertIn("BETWEEN ? AND ?", src)

    # =========================================================
    # Column name injection (from existing tests — regression)
    # =========================================================

    def test_get_history_rejects_unsafe_field_name(self):
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

    def test_get_latest_financial_rejects_unsafe_field_name(self):
        with self.assertRaises(ValueError):
            self.loader.get_latest_financial(
                "000001.SZ",
                "2025-01-08",
                fields=["roe", "roa FROM fina_indicator; DROP TABLE daily_bar; --"],
            )

    # =========================================================
    # get_instruments rejects boundary values outside the whitelist
    # =========================================================

    def test_get_instruments_rejects_lowercase_exchange(self):
        with self.assertRaises(ValueError):
            self.loader.get_instruments(exchange="sz")

    def test_get_instruments_rejects_numeric_exchange(self):
        with self.assertRaises(ValueError):
            self.loader.get_instruments(exchange="1")

    def test_get_instruments_empty_exchange_treated_as_no_filter(self):
        """Empty string is falsy, so it's treated as 'no filter' — returns all instruments."""
        df = self.loader.get_instruments(exchange="")
        self.assertEqual(len(df), 3)

    def test_get_instruments_rejects_lowercase_status(self):
        with self.assertRaises(ValueError):
            self.loader.get_instruments(status="l")

    def test_get_instruments_rejects_extended_status(self):
        with self.assertRaises(ValueError):
            self.loader.get_instruments(status="LD")


if __name__ == "__main__":
    unittest.main()
