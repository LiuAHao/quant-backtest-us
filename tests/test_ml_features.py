# tests/test_ml_features.py
import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock


def test_build_single_day_features_basic():
    """build_single_day_features returns correct columns and shape."""
    from ml_research.features import build_single_day_features

    # Mock cross-section data (what DataLoader.get_cross_section returns)
    cs = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ", "600000.SH"],
        "trade_date": ["2025-01-10"] * 3,
        "close": [10.0, 20.0, 15.0],
        "volume": [1e6, 2e6, 1.5e6],
        "amount": [1e7, 4e7, 2.25e7],
        "circ_mv": [100e8, 200e8, 150e8],
        "pe_ttm": [10.0, 20.0, 15.0],
        "pb": [1.5, 2.0, 1.0],
        "turnover_rate": [3.0, 2.0, 4.0],
    })

    rng = np.random.default_rng(42)

    # Mock history data for momentum/volatility (get_history returns)
    def mock_get_history(ts_code, end_date, window, adjust="qfq"):
        dates = pd.date_range("2024-12-01", periods=window, freq="B")
        base = {"000001.SZ": 10.0, "000002.SZ": 20.0, "600000.SH": 15.0}[ts_code]
        close = base * (1 + rng.normal(0, 0.02, window))
        return pd.DataFrame({
            "ts_code": ts_code,
            "trade_date": dates.strftime("%Y-%m-%d"),
            "close": close,
            "volume": rng.integers(100_000, 10_000_000, window),
        })

    dl = MagicMock()
    dl.get_cross_section.return_value = cs
    dl.get_history.side_effect = mock_get_history

    result = build_single_day_features(dl, "2025-01-10")

    assert isinstance(result, pd.DataFrame)
    assert "ts_code" in result.columns
    assert "trade_date" in result.columns
    assert len(result) == 3
    # Should have feature columns
    feature_cols = [c for c in result.columns if c not in ("ts_code", "trade_date")]
    assert len(feature_cols) > 0
