"""Tests for factor_analysis/engine.py using synthetic data."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from factor_analysis.engine import (
    build_summary,
    compute_coverage,
    compute_group_returns,
    compute_ic,
    compute_rank_ic,
)


def _make_factor_return_data(
    n_dates: int = 10,
    n_stocks: int = 20,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create synthetic factor and return DataFrames with known properties.

    The factor is positively correlated with returns (noise added).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-02", periods=n_dates, freq="B").strftime("%Y-%m-%d").tolist()
    codes = [f"{i:06d}.SZ" for i in range(1, n_stocks + 1)]

    factor_rows = []
    return_rows = []
    for dt in dates:
        factor_vals = rng.standard_normal(n_stocks)
        for j, c in enumerate(codes):
            factor_rows.append({"ts_code": c, "trade_date": dt, "factor": factor_vals[j]})
            # return = 0.3 * factor + noise
            return_rows.append({
                "ts_code": c,
                "trade_date": dt,
                "ret": 0.3 * factor_vals[j] + rng.standard_normal() * 0.5,
            })

    return pd.DataFrame(factor_rows), pd.DataFrame(return_rows)


class ICTest(unittest.TestCase):
    def test_ic_has_correct_columns(self):
        fdf, rdf = _make_factor_return_data()
        ic = compute_ic(fdf, rdf)
        self.assertIn("trade_date", ic.columns)
        self.assertIn("ic", ic.columns)
        self.assertIn("n", ic.columns)

    def test_ic_positive_for_correlated_data(self):
        fdf, rdf = _make_factor_return_data(n_dates=20, n_stocks=50, seed=123)
        ic = compute_ic(fdf, rdf)
        mean_ic = ic["ic"].mean()
        self.assertGreater(mean_ic, 0.0, "Mean IC should be positive for positively correlated data")

    def test_rank_ic_runs(self):
        fdf, rdf = _make_factor_return_data()
        ric = compute_rank_ic(fdf, rdf)
        self.assertEqual(len(ric), 10)

    def test_ic_empty_input(self):
        empty = pd.DataFrame(columns=["ts_code", "trade_date", "factor"])
        ret = pd.DataFrame(columns=["ts_code", "trade_date", "ret"])
        ic = compute_ic(empty, ret)
        self.assertTrue(ic.empty)

    def test_ic_insufficient_samples_returns_nan(self):
        """With < 3 stocks, IC should be NaN."""
        fdf = pd.DataFrame([
            {"ts_code": "A", "trade_date": "2025-01-02", "factor": 1.0},
            {"ts_code": "B", "trade_date": "2025-01-02", "factor": 2.0},
        ])
        rdf = pd.DataFrame([
            {"ts_code": "A", "trade_date": "2025-01-02", "ret": 0.01},
            {"ts_code": "B", "trade_date": "2025-01-02", "ret": 0.02},
        ])
        ic = compute_ic(fdf, rdf)
        self.assertTrue(pd.isna(ic.iloc[0]["ic"]))

    def test_ic_accepts_mixed_trade_date_types(self):
        fdf = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "2025-01-02", "factor": 1.0},
                {"ts_code": "000002.SZ", "trade_date": "2025-01-02", "factor": 2.0},
                {"ts_code": "000003.SZ", "trade_date": "2025-01-02", "factor": 3.0},
            ]
        )
        rdf = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": pd.Timestamp("2025-01-02"), "ret": 0.01},
                {"ts_code": "000002.SZ", "trade_date": pd.Timestamp("2025-01-02"), "ret": 0.02},
                {"ts_code": "000003.SZ", "trade_date": pd.Timestamp("2025-01-02"), "ret": 0.03},
            ]
        )
        ic = compute_ic(fdf, rdf)
        self.assertEqual(ic.iloc[0]["trade_date"], "2025-01-02")
        self.assertEqual(ic.iloc[0]["n"], 3)

    def test_ic_missing_columns_raises(self):
        bad = pd.DataFrame({"x": [1]})
        rdf = pd.DataFrame(columns=["ts_code", "trade_date", "ret"])
        with self.assertRaises(ValueError):
            compute_ic(bad, rdf)


class GroupReturnTest(unittest.TestCase):
    def test_group_returns_structure(self):
        fdf, rdf = _make_factor_return_data(n_dates=5, n_stocks=20)
        gr = compute_group_returns(fdf, rdf, n_groups=5)
        self.assertIn("trade_date", gr.columns)
        self.assertIn("group", gr.columns)
        self.assertIn("avg_ret", gr.columns)
        self.assertIn("n", gr.columns)

    def test_group_returns_correct_count(self):
        n_dates, n_stocks, n_groups = 5, 20, 5
        fdf, rdf = _make_factor_return_data(n_dates=n_dates, n_stocks=n_stocks)
        gr = compute_group_returns(fdf, rdf, n_groups=n_groups)
        # Each date should have up to n_groups rows
        max_rows = n_dates * n_groups
        self.assertLessEqual(len(gr), max_rows)

    def test_group_returns_sorted_by_factor(self):
        """Higher groups should tend to have higher average returns for correlated data."""
        fdf, rdf = _make_factor_return_data(n_dates=30, n_stocks=50, seed=99)
        gr = compute_group_returns(fdf, rdf, n_groups=5)
        avg_by_group = gr.groupby("group")["avg_ret"].mean()
        # Group 5 should have higher avg than Group 1
        self.assertGreater(avg_by_group[5], avg_by_group[1])

    def test_group_returns_few_stocks(self):
        """With fewer stocks than groups, all go to group 1."""
        fdf = pd.DataFrame([
            {"ts_code": "A", "trade_date": "2025-01-02", "factor": 1.0},
            {"ts_code": "B", "trade_date": "2025-01-02", "factor": 2.0},
        ])
        rdf = pd.DataFrame([
            {"ts_code": "A", "trade_date": "2025-01-02", "ret": 0.01},
            {"ts_code": "B", "trade_date": "2025-01-02", "ret": 0.02},
        ])
        gr = compute_group_returns(fdf, rdf, n_groups=5)
        self.assertTrue(all(g == 1 for g in gr["group"]))

    def test_group_returns_empty(self):
        empty = pd.DataFrame(columns=["ts_code", "trade_date", "factor"])
        ret = pd.DataFrame(columns=["ts_code", "trade_date", "ret"])
        gr = compute_group_returns(empty, ret)
        self.assertTrue(gr.empty)


class CoverageTest(unittest.TestCase):
    def test_coverage_basic(self):
        fdf, _ = _make_factor_return_data(n_dates=3, n_stocks=10)
        cov = compute_coverage(fdf)
        self.assertIn("trade_date", cov.columns)
        self.assertIn("coverage", cov.columns)
        self.assertEqual(len(cov), 3)

    def test_coverage_with_nan_factors(self):
        fdf, _ = _make_factor_return_data(n_dates=3, n_stocks=10)
        fdf.loc[0:2, "factor"] = np.nan
        cov = compute_coverage(fdf)
        # Some dates should have coverage < 1
        self.assertTrue(any(cov["coverage"] < 1.0))

    def test_coverage_with_total_stocks(self):
        fdf, _ = _make_factor_return_data(n_dates=3, n_stocks=10)
        total = pd.DataFrame({
            "ts_code": [f"{i:06d}.SZ" for i in range(1, 21)],
            "trade_date": "2025-01-02",
        })
        cov = compute_coverage(fdf, total_stocks_per_date=total)
        self.assertIn("total_count", cov.columns)

    def test_coverage_accepts_mixed_trade_date_types(self):
        fdf = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "2025-01-02", "factor": 1.0},
                {"ts_code": "000002.SZ", "trade_date": "2025-01-02", "factor": 2.0},
            ]
        )
        total = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": pd.Timestamp("2025-01-02")},
                {"ts_code": "000002.SZ", "trade_date": pd.Timestamp("2025-01-02")},
                {"ts_code": "000003.SZ", "trade_date": pd.Timestamp("2025-01-02")},
            ]
        )
        cov = compute_coverage(fdf, total_stocks_per_date=total)
        self.assertEqual(cov.iloc[0]["trade_date"], "2025-01-02")
        self.assertEqual(cov.iloc[0]["factor_count"], 2)
        self.assertEqual(cov.iloc[0]["total_count"], 3)

    def test_coverage_empty(self):
        empty = pd.DataFrame(columns=["ts_code", "trade_date", "factor"])
        cov = compute_coverage(empty)
        self.assertTrue(cov.empty)


class SummaryTest(unittest.TestCase):
    def test_build_summary_complete(self):
        fdf, rdf = _make_factor_return_data(n_dates=10, n_stocks=20)
        ic_df = compute_ic(fdf, rdf)
        gr_df = compute_group_returns(fdf, rdf, n_groups=5)
        cov_df = compute_coverage(fdf)
        summary = build_summary(ic_df, gr_df, cov_df)

        self.assertIn("ic", summary)
        self.assertIn("avg_group_returns", summary)
        self.assertIn("coverage", summary)
        self.assertIsNotNone(summary["ic"]["mean"])
        self.assertIsNotNone(summary["ic"]["icir"])

    def test_build_summary_json_serializable(self):
        import json
        fdf, rdf = _make_factor_return_data()
        ic_df = compute_ic(fdf, rdf)
        gr_df = compute_group_returns(fdf, rdf)
        cov_df = compute_coverage(fdf)
        summary = build_summary(ic_df, gr_df, cov_df)
        # Must not raise
        json.dumps(summary, ensure_ascii=False)

    def test_build_summary_empty_inputs(self):
        empty_ic = pd.DataFrame(columns=["trade_date", "ic", "n"])
        empty_gr = pd.DataFrame(columns=["trade_date", "group", "avg_ret", "n"])
        empty_cov = pd.DataFrame(columns=["trade_date", "coverage", "factor_count", "total_count"])
        summary = build_summary(empty_ic, empty_gr, empty_cov)
        self.assertIsNone(summary["ic"]["mean"])
        self.assertEqual(summary["coverage"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
