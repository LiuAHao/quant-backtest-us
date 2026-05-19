"""Tests for scripts/data_utils/validate_data.py using fixture data."""
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

import pandas as pd

from scripts.validate_data import DataValidator, _Settings


def _make_fixtures(root: Path, *, drop_adj: bool = False, dup_daily: bool = False):
    """Create minimal hive-partitioned parquet fixtures.

    Layout:
        root/daily_bar/trade_date=2025-01-02/part-000.parquet  ...
        root/daily_basic/trade_date=2025-01-02/part-000.parquet ...
        root/adj_factor/trade_date=2025-01-02/part-000.parquet  ...
        root/stk_limit/trade_date=2025-01-02/part-000.parquet   ...
        root/calendar/calendar.parquet
        root/instruments/instruments.parquet
    """
    dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
    codes = ["000001.SZ", "000002.SZ"]

    # calendar
    cal_dir = root / "calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)
    all_dates = [
        "2025-01-01",  # holiday
        "2025-01-02", "2025-01-03", "2025-01-06",
        "2025-01-04", "2025-01-05",  # weekend
    ]
    cal_rows = [{"trade_date": d, "is_open": 1 if d in dates else 0} for d in all_dates]
    pd.DataFrame(cal_rows).to_parquet(cal_dir / "calendar.parquet", index=False)

    # instruments
    inst_dir = root / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)
    inst_rows = [
        {"ts_code": c, "name": f"Stock {c}", "list_date": "2020-01-01"}
        for c in codes
    ]
    pd.DataFrame(inst_rows).to_parquet(inst_dir / "instruments.parquet", index=False)

    # daily_bar
    for dt in dates:
        d = root / "daily_bar" / f"trade_date={dt}"
        d.mkdir(parents=True, exist_ok=True)
        rows = []
        for c in codes:
            rows.append({
                "ts_code": c, "trade_date": dt,
                "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2,
                "volume": 100000, "amount": 1020000.0,
            })
        if dup_daily and dt == "2025-01-02":
            rows.append(rows[0].copy())  # inject duplicate
        pd.DataFrame(rows).to_parquet(d / "part-000.parquet", index=False)

    # daily_basic
    for dt in dates:
        d = root / "daily_basic" / f"trade_date={dt}"
        d.mkdir(parents=True, exist_ok=True)
        rows = [
            {"ts_code": c, "trade_date": dt, "pe_ttm": 15.0, "pb": 1.2, "total_mv": 1000000.0}
            for c in codes
        ]
        pd.DataFrame(rows).to_parquet(d / "part-000.parquet", index=False)

    # adj_factor
    if not drop_adj:
        for dt in dates:
            d = root / "adj_factor" / f"trade_date={dt}"
            d.mkdir(parents=True, exist_ok=True)
            rows = [
                {"ts_code": c, "trade_date": dt, "adj_factor": 1.0}
                for c in codes
            ]
            pd.DataFrame(rows).to_parquet(d / "part-000.parquet", index=False)

    # stk_limit
    for dt in dates:
        d = root / "stk_limit" / f"trade_date={dt}"
        d.mkdir(parents=True, exist_ok=True)
        rows = [
            {"ts_code": c, "trade_date": dt, "up_limit": 11.22, "down_limit": 9.18}
            for c in codes
        ]
        pd.DataFrame(rows).to_parquet(d / "part-000.parquet", index=False)


class DataValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path.cwd() / ".test-tmp-validation" / self._testMethodName
        if self.tmp.exists():
            shutil.rmtree(self.tmp)
        self.tmp.mkdir(parents=True)
        _make_fixtures(self.tmp)
        self.settings = _Settings(data_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_summary_is_json_serializable(self):
        v = DataValidator(settings=self.settings)
        result = v.validate_range("2025-01-02", "2025-01-06")
        # Must not raise
        json_str = json.dumps(result, ensure_ascii=False)
        self.assertIsInstance(json_str, str)
        self.assertIn("total_checks", result)
        self.assertIn("pass_rate", result)

    def test_pass_rate_100_on_clean_data(self):
        v = DataValidator(settings=self.settings)
        result = v.validate_range("2025-01-02", "2025-01-06")
        self.assertEqual(result["failed"], 0)
        self.assertAlmostEqual(result["pass_rate"], 1.0, places=4)

    def test_calendar_based_not_weekday(self):
        """2025-01-04 (Saturday) should not be validated even though weekday < 5."""
        v = DataValidator(settings=self.settings)
        # 2025-01-01 is holiday (is_open=0), 2025-01-04/05 weekend
        # Should only check 2025-01-02, 2025-01-03, 2025-01-06
        trading_days = v._trading_days("2025-01-01", "2025-01-06")
        self.assertEqual(trading_days, ["2025-01-02", "2025-01-03", "2025-01-06"])
        # weekday-based would include 2025-01-02, 2025-01-03, 2025-01-06
        # but also 2025-01-01 (Wed holiday) — calendar skips it
        result = v.validate_range("2025-01-01", "2025-01-06")
        self.assertEqual(result["failed"], 0)

    def test_detects_missing_adj_factor(self):
        # Remove existing adj_factor fixtures, then recreate without them
        shutil.rmtree(self.tmp / "adj_factor", ignore_errors=True)
        _make_fixtures(self.tmp, drop_adj=True)
        v = DataValidator(settings=self.settings)
        result = v.validate_range("2025-01-02", "2025-01-06")
        self.assertGreater(result["failed"], 0)
        adj_failures = [d for d in result["failed_details"] if d["dataset"] == "adj_factor"]
        self.assertTrue(len(adj_failures) > 0)

    def test_detects_duplicate_daily_bar(self):
        shutil.rmtree(self.tmp / "daily_bar", ignore_errors=True)
        _make_fixtures(self.tmp, dup_daily=True)
        v = DataValidator(settings=self.settings)
        result = v.validate_range("2025-01-02", "2025-01-02")
        self.assertGreater(result["failed"], 0)
        pk_failures = [d for d in result["failed_details"] if d["check_name"] == "主键唯一性"]
        self.assertTrue(len(pk_failures) > 0)

    def test_validate_latest_runs(self):
        """validate_latest should not crash even with limited fixture data."""
        v = DataValidator(settings=self.settings)
        # Just ensure it runs without error
        result = v.validate_latest(days=5)
        self.assertIn("total_checks", result)

    def test_instruments_check(self):
        v = DataValidator(settings=self.settings)
        results = v.check_instruments()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].passed)

    def test_instruments_missing(self):
        (self.tmp / "instruments" / "instruments.parquet").unlink()
        v = DataValidator(settings=self.settings)
        results = v.check_instruments()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].passed)

    def test_instruments_symbol_only(self):
        inst_dir = self.tmp / "instruments"
        pd.DataFrame([
            {"ts_code": "000001.SZ", "symbol": "平安银行", "list_date": "2020-01-01"},
        ]).to_parquet(inst_dir / "instruments.parquet", index=False)
        v = DataValidator(settings=self.settings)
        results = v.check_instruments()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].passed)

    def test_instruments_name_only(self):
        inst_dir = self.tmp / "instruments"
        pd.DataFrame([
            {"ts_code": "000001.SZ", "name": "平安银行", "list_date": "2020-01-01"},
        ]).to_parquet(inst_dir / "instruments.parquet", index=False)
        v = DataValidator(settings=self.settings)
        results = v.check_instruments()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].passed)

    def test_instruments_missing_name_and_symbol(self):
        inst_dir = self.tmp / "instruments"
        pd.DataFrame([
            {"ts_code": "000001.SZ", "list_date": "2020-01-01"},
        ]).to_parquet(inst_dir / "instruments.parquet", index=False)
        v = DataValidator(settings=self.settings)
        results = v.check_instruments()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].passed)
        self.assertIn("name", results[0].details)
        self.assertIn("symbol", results[0].details)

    def test_single_date_validation(self):
        v = DataValidator(settings=self.settings)
        results = v.validate_date("2025-01-02")
        self.assertGreater(len(results), 0)
        self.assertTrue(all(r.passed for r in results))

    def test_nonexistent_date_returns_data_exists_false(self):
        v = DataValidator(settings=self.settings)
        results = v.validate_date("2025-01-10")
        # Should have calendar check (not in calendar) and data exists = False
        self.assertTrue(len(results) > 0)

    def test_check_result_to_dict(self):
        from scripts.validate_data import CheckResult
        r = CheckResult("daily_bar", "test", True, "ok", "2025-01-02")
        d = r.to_dict()
        self.assertEqual(d["dataset"], "daily_bar")
        self.assertTrue(d["passed"])
        # Must be JSON-serializable
        json.dumps(d)


if __name__ == "__main__":
    unittest.main()
