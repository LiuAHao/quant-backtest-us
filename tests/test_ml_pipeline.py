# tests/test_ml_pipeline.py
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import numpy as np


def test_pipeline_end_to_end():
    """
    Integration test: run pipeline on a small synthetic dataset.
    Verifies features → labels → split → train → predict → evaluate chain.
    """
    from ml_research.config import MLConfig
    from ml_research.pipeline import run_pipeline

    # This test requires real data to be present.
    # If data dir is empty, skip.
    data_dir = Path(__file__).parent.parent / "data" / "daily_bar"
    if not data_dir.exists() or not any(data_dir.glob("*/*.parquet")):
        pytest.skip("No market data available — skipping integration test")

    cfg = MLConfig(
        momentum_windows=[5, 10],
        volatility_window=10,
        forward_days=5,
        train_days=60,
        test_days=20,
        step_days=20,
        lgb_params={
            "objective": "regression",
            "metric": "mse",
            "learning_rate": 0.1,
            "num_leaves": 15,
            "max_depth": 4,
            "n_estimators": 50,
            "verbose": -1,
            "n_jobs": -1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
        },
        experiment_name="test_run",
    )

    result = run_pipeline(
        start_date="2020-01-01",
        end_date="2020-12-31",
        config=cfg,
        cache_dir=None,  # No caching in tests
    )

    assert "predictions" in result
    assert "evaluation" in result
    assert len(result["predictions"]) > 0
    assert "summary" in result["evaluation"]
