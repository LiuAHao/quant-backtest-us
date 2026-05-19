from __future__ import annotations

import shutil
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd

from backtest.data_loader import DataLoader
from backtest.engine import BacktestEngine, BacktestResult, BENCHMARK_MAP
from tests.helpers.market_data import (
    write_adj_factor,
    write_calendar,
    write_daily_bar,
    write_daily_basic,
    write_index_daily,
)
from tests.helpers.temp_env import TempProjectEnv


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

DATES = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]


def _make_engine_fixtures(root: Path):
    """Create minimal parquet fixtures for engine tests."""
    closes = [10.0, 10.2, 10.1, 10.4, 10.5]
    bars = []
    for i, (dt, c) in enumerate(zip(DATES, closes)):
        bars.append({
            "ts_code": "000001.SZ",
            "trade_date": dt,
            "open": c,
            "high": c + 0.3,
            "low": c - 0.3,
            "close": c,
            "pre_close": closes[i - 1] if i > 0 else c,
            "volume": 1_000_000,
            "amount": c * 1_000_000,
        })
    write_daily_bar(root, bars, partition="2025")

    write_adj_factor(
        root,
        [{"ts_code": "000001.SZ", "trade_date": dt, "adj_factor": 1.0} for dt in DATES],
        partition="2025",
    )
    write_calendar(root, [{"trade_date": dt, "is_open": 1} for dt in DATES])
    write_daily_basic(
        root,
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": dt,
                "circ_mv": 100_000.0,
                "total_mv": 200_000.0,
                "total_share": 50_000.0,
                "float_share": 40_000.0,
                "free_share": 35_000.0,
                "turnover_rate": 1.5,
                "pe_ttm": 12.0,
                "pb": 1.2,
            }
            for dt in DATES
        ],
        partition="2025",
    )

    idx_closes = [100.0, 102.0, 104.04, 106.12, 108.24]
    write_index_daily(
        root,
        [{"ts_code": "000300.SH", "trade_date": dt, "close": c} for dt, c in zip(DATES, idx_closes)],
        partition="2025",
    )


# ---------------------------------------------------------------------------
# Sharpe / Sortino / Calmar unit tests (construct BacktestResult directly)
# ---------------------------------------------------------------------------

class SharpeRatioTest(unittest.TestCase):
    """Sharpe ratio must use excess returns: (daily_returns - rf/252)."""

    def test_sharpe_zero_rf_matches_old_formula(self):
        # Need 6 values so that after pct_change().dropna() we get 5 returns
        daily = pd.Series([0.001, 0.001, 0.002, -0.001, 0.0015, 0.0005],
                          index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06",
                                                "2025-01-07", "2025-01-08", "2025-01-09"]))
        result = _make_result(daily, rf=0.0)
        # Engine returns are pct_change().dropna() -> [0.001, 0.002, -0.001, 0.0015, 0.0005]
        engine_returns = result.daily_returns
        expected = float(engine_returns.mean() / engine_returns.std() * np.sqrt(252))
        self.assertAlmostEqual(result.sharpe_ratio, expected, places=4)

    def test_sharpe_positive_rf_decreases(self):
        daily = pd.Series([0.001, 0.001, 0.002, -0.001, 0.0015, 0.0005],
                          index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06",
                                                "2025-01-07", "2025-01-08", "2025-01-09"]))
        r0 = _make_result(daily, rf=0.0)
        r1 = _make_result(daily, rf=0.03)
        self.assertLess(r1.sharpe_ratio, r0.sharpe_ratio)

    def test_sortino_uses_excess_returns(self):
        daily = pd.Series([0.001, 0.001, 0.002, -0.001, 0.0015, 0.0005],
                          index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06",
                                                "2025-01-07", "2025-01-08", "2025-01-09"]))
        result = _make_result(daily, rf=0.03)
        self.assertIsInstance(result.sortino_ratio, float)

    def test_calmar_ratio(self):
        daily = pd.Series([0.001, 0.01, -0.02, 0.01, 0.01, 0.01],
                          index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06",
                                                "2025-01-07", "2025-01-08", "2025-01-09"]))
        result = _make_result(daily, rf=0.0)
        if result.max_drawdown != 0:
            expected = result.annual_return / abs(result.max_drawdown)
            self.assertAlmostEqual(result.calmar_ratio, expected, places=4)


def _build_values_df(daily_returns: pd.Series, initial_capital: float) -> list[dict]:
    """Build the daily_values list that engine.run() would produce.

    The first entry is the value *after* the first day's return,
    matching how engine.run() records daily_values.
    """
    equity = initial_capital
    rows = []
    for dt, ret in daily_returns.items():
        equity *= (1 + ret)
        rows.append({
            "date": dt,
            "total_value": equity,
            "cash": equity * 0.5,
            "position_value": equity * 0.5,
            "holding_count": 1,
        })
    return rows


def _make_result(daily_returns: pd.Series, rf: float = 0.0) -> BacktestResult:
    """Create BacktestResult by calling engine._generate_result with fixture data."""
    engine = BacktestEngine.__new__(BacktestEngine)
    engine.risk_free_rate = rf
    engine.benchmark = None
    engine.initial_capital = 1_000_000
    engine.start_date = datetime(2025, 1, 2)
    engine.end_date = datetime(2025, 1, 8)
    engine.data_loader = MagicMock()
    engine.broker = MagicMock()
    engine.broker.trade_history = []
    engine.daily_values = _build_values_df(daily_returns, 1_000_000)
    return engine._generate_result()


# ---------------------------------------------------------------------------
# Benchmark integration tests (full engine with real DataLoader + fixtures)
# ---------------------------------------------------------------------------

class BenchmarkMetricsTest(unittest.TestCase):
    """Test benchmark metrics with fixture parquet data."""

    def setUp(self):
        self.env = TempProjectEnv.under_cwd(self._testMethodName).patch_data_dirs().start()
        self.tmp_path = self.env.data_dir
        _make_engine_fixtures(self.tmp_path)

    def tearDown(self):
        self.env.stop()

    def _run_engine(self, benchmark: str | None = None, rf: float = 0.0) -> BacktestResult:
        engine = BacktestEngine(
            start_date="20250102",
            end_date="20250108",
            initial_capital=1_000_000,
            commission_rate=0.0003,
            slippage=0.0,
            prepare_data=True,
            risk_free_rate=rf,
            benchmark=benchmark,
            enable_reports=False,
        )

        def init(ctx):
            ctx["order"]("000001.SZ", 100, "buy")

        def next_func(ctx):
            pass

        engine.set_strategy(init, next_func)
        return engine.run()

    def test_no_benchmark_fields_are_none(self):
        result = self._run_engine(benchmark=None)
        self.assertFalse(result.benchmark_available)
        self.assertIsNone(result.benchmark_return)
        self.assertIsNone(result.excess_return)
        self.assertIsNone(result.alpha)
        self.assertIsNone(result.beta)
        self.assertIsNone(result.tracking_error)
        self.assertIsNone(result.information_ratio)

    def test_benchmark_hs300_resolves(self):
        result = self._run_engine(benchmark="hs300")
        self.assertTrue(result.benchmark_available)
        self.assertIsNotNone(result.benchmark_return)
        self.assertIsNotNone(result.beta)

    def test_benchmark_by_code(self):
        result = self._run_engine(benchmark="000300.SH")
        self.assertTrue(result.benchmark_available)

    def test_benchmark_excess_return(self):
        result = self._run_engine(benchmark="hs300")
        self.assertIsNotNone(result.excess_return)
        # Strategy total_return vs benchmark total_return
        expected_excess = result.total_return - result.benchmark_return
        self.assertAlmostEqual(result.excess_return, expected_excess, places=6)

    def test_benchmark_beta(self):
        result = self._run_engine(benchmark="hs300")
        self.assertIsNotNone(result.beta)
        # Beta should be a finite number
        self.assertTrue(np.isfinite(result.beta))

    def test_benchmark_tracking_error(self):
        result = self._run_engine(benchmark="hs300")
        self.assertIsNotNone(result.tracking_error)
        self.assertGreaterEqual(result.tracking_error, 0.0)

    def test_benchmark_information_ratio(self):
        result = self._run_engine(benchmark="hs300")
        self.assertIsNotNone(result.information_ratio)
        self.assertTrue(np.isfinite(result.information_ratio))

    def test_benchmark_curve_populated(self):
        result = self._run_engine(benchmark="hs300")
        self.assertIsNotNone(result.benchmark_curve)
        self.assertGreater(len(result.benchmark_curve), 0)

    def test_benchmark_daily_returns_populated(self):
        result = self._run_engine(benchmark="hs300")
        self.assertIsNotNone(result.benchmark_daily_returns)
        self.assertGreater(len(result.benchmark_daily_returns), 0)

    def test_benchmark_degrades_on_missing_data(self):
        result = self._run_engine(benchmark="nonexistent.SH")
        self.assertFalse(result.benchmark_available)
        self.assertIsNone(result.benchmark_return)

    def test_benchmark_degrades_on_unknown_key(self):
        result = self._run_engine(benchmark="unknown_key")
        self.assertFalse(result.benchmark_available)

    def test_sharpe_with_rf_uses_excess_returns(self):
        r0 = self._run_engine(benchmark=None, rf=0.0)
        r1 = self._run_engine(benchmark=None, rf=0.05)
        self.assertLess(r1.sharpe_ratio, r0.sharpe_ratio)


class ExecutionModeTest(unittest.TestCase):
    """Engine execution timing should be explicit and preserve the default model."""

    def setUp(self):
        self.env = TempProjectEnv.under_cwd(self._testMethodName).patch_data_dirs().start()
        self.tmp_path = self.env.data_dir
        _make_engine_fixtures(self.tmp_path)

        daily_bar_path = self.tmp_path / "daily_bar" / "2025" / "daily_bar.parquet"
        bars = pd.read_parquet(daily_bar_path)
        bars.loc[bars["trade_date"] == "2025-01-02", "open"] = 9.0
        bars.loc[bars["trade_date"] == "2025-01-02", "close"] = 11.0
        bars.loc[bars["trade_date"] == "2025-01-02", "pre_close"] = 10.5
        bars.loc[bars["trade_date"] == "2025-01-03", "open"] = 20.0
        bars.loc[bars["trade_date"] == "2025-01-03", "close"] = 21.0
        bars.loc[bars["trade_date"] == "2025-01-03", "pre_close"] = 19.5
        bars.to_parquet(daily_bar_path, index=False)

    def tearDown(self):
        self.env.stop()

    def _run_timing_strategy(self, execution_mode: str = "next_open") -> BacktestResult:
        engine = BacktestEngine(
            start_date="20250102",
            end_date="20250103",
            initial_capital=1_000_000,
            commission_rate=0.0,
            slippage=1e-12,
            prepare_data=True,
            enable_reports=False,
            execution_mode=execution_mode,
        )

        def init(ctx):
            pass

        def next_func(ctx):
            if ctx["current_date"].strftime("%Y-%m-%d") == "2025-01-02":
                ctx["order"]("000001.SZ", 100, "buy")

        engine.set_strategy(init, next_func)
        return engine.run()

    def test_default_execution_mode_fills_next_open(self):
        result = self._run_timing_strategy()
        self.assertEqual(len(result.trades), 1)
        self.assertAlmostEqual(float(result.trades.iloc[0]["price"]), 20.0, places=4)

    def test_same_close_execution_mode_fills_current_close(self):
        result = self._run_timing_strategy(execution_mode="same_close")
        self.assertEqual(len(result.trades), 1)
        self.assertAlmostEqual(float(result.trades.iloc[0]["price"]), 11.0, places=4)


class BenchmarkMapTest(unittest.TestCase):
    def test_known_keys(self):
        self.assertEqual(BENCHMARK_MAP["hs300"], "000300.SH")
        self.assertEqual(BENCHMARK_MAP["zz500"], "000905.SH")
        self.assertEqual(BENCHMARK_MAP["zz1000"], "000852.SH")


class GetIndexHistoryTest(unittest.TestCase):
    """Test DataLoader.get_index_history() with fixture data."""

    def setUp(self):
        self.env = TempProjectEnv.under_cwd(self._testMethodName).patch_data_dirs().start()
        self.tmp_path = self.env.data_dir
        _make_engine_fixtures(self.tmp_path)

        self.loader = DataLoader()

    def tearDown(self):
        self.loader.close()
        self.env.stop()

    def test_returns_data_for_existing_index(self):
        df = self.loader.get_index_history("000300.SH", "2025-01-02", "2025-01-08")
        self.assertFalse(df.empty)
        self.assertIn("trade_date", df.columns)
        self.assertIn("close", df.columns)
        self.assertEqual(len(df), 5)

    def test_returns_ascending_order(self):
        df = self.loader.get_index_history("000300.SH", "2025-01-02", "2025-01-08")
        dates = pd.to_datetime(df["trade_date"]).tolist()
        self.assertEqual(dates, sorted(dates))

    def test_returns_empty_for_missing_index(self):
        df = self.loader.get_index_history("999999.SH", "2025-01-02", "2025-01-08")
        self.assertTrue(df.empty)

    def test_date_filtering(self):
        df = self.loader.get_index_history("000300.SH", "2025-01-03", "2025-01-07")
        self.assertEqual(len(df), 3)

    def test_custom_fields(self):
        df = self.loader.get_index_history(
            "000300.SH", "2025-01-02", "2025-01-08", fields=["trade_date", "close"]
        )
        self.assertEqual(list(df.columns), ["trade_date", "close"])


if __name__ == "__main__":
    unittest.main()
