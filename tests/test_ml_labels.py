# tests/test_ml_labels.py
import pandas as pd
import pytest
from unittest.mock import MagicMock


def test_build_labels_basic():
    """build_labels computes forward return correctly."""
    from ml_research.labels import build_labels

    cs_t0 = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "trade_date": ["2025-01-10", "2025-01-10"],
        "close": [10.0, 20.0],
    })
    cs_t5 = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "trade_date": ["2025-01-17", "2025-01-17"],
        "close": [11.0, 18.0],
    })

    def mock_cs(trade_date, fields=None, adjust=None):
        td_str = str(trade_date)
        if "2025-01-10" in td_str or "20250110" in td_str:
            return cs_t0
        return cs_t5

    dl = MagicMock()
    dl.get_cross_section.side_effect = mock_cs
    dl.get_trade_calendar.return_value = pd.DataFrame({
        "trade_date": ["2025-01-10", "2025-01-13", "2025-01-14", "2025-01-15", "2025-01-16", "2025-01-17"],
    })

    result = build_labels(dl, ["2025-01-10"], forward_days=5)

    assert len(result) == 2
    assert set(result.columns) >= {"ts_code", "trade_date", "ret_5d"}

    row_a = result[result["ts_code"] == "000001.SZ"].iloc[0]
    assert abs(row_a["ret_5d"] - 0.1) < 1e-6  # 11/10 - 1 = 0.1

    row_b = result[result["ts_code"] == "000002.SZ"].iloc[0]
    assert abs(row_b["ret_5d"] - (-0.1)) < 1e-6  # 18/20 - 1 = -0.1
