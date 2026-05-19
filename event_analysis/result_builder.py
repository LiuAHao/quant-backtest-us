from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def build_summary(detail_df: pd.DataFrame, windows: list[int]) -> dict[str, Any]:
    detail_df = detail_df.copy()
    summary_windows: list[dict[str, Any]] = []
    for window in windows:
        col = f"ret_{window}d"
        if col not in detail_df.columns:
            summary_windows.append(
                {
                    "window": window,
                    "sample_count": 0,
                    "avg_return": None,
                    "median_return": None,
                    "win_rate": None,
                    "p10": None,
                    "p25": None,
                    "p75": None,
                    "p90": None,
                    "best": None,
                    "worst": None,
                }
            )
            continue
        raw = detail_df[col]
        if not isinstance(raw, pd.Series):
            raw = pd.Series([raw])
        series = pd.to_numeric(raw, errors="coerce").dropna()
        if series.empty:
            summary_windows.append(
                {
                    "window": window,
                    "sample_count": 0,
                    "avg_return": None,
                    "median_return": None,
                    "win_rate": None,
                    "p10": None,
                    "p25": None,
                    "p75": None,
                    "p90": None,
                    "best": None,
                    "worst": None,
                }
            )
            continue
        summary_windows.append(
            {
                "window": window,
                "sample_count": int(series.shape[0]),
                "avg_return": float(series.mean()),
                "median_return": float(series.median()),
                "win_rate": float((series > 0).mean()),
                "p10": float(series.quantile(0.10)),
                "p25": float(series.quantile(0.25)),
                "p75": float(series.quantile(0.75)),
                "p90": float(series.quantile(0.90)),
                "best": float(series.max()),
                "worst": float(series.min()),
            }
        )

    return {
        "sample_count": int(len(detail_df)),
        "stock_count": int(detail_df["ts_code"].nunique()) if "ts_code" in detail_df.columns else 0,
        "trade_date_count": int(detail_df["trade_date"].nunique()) if "trade_date" in detail_df.columns else 0,
        "windows": summary_windows,
    }
