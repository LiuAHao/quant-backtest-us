"""
模型评估：IC、ICIR、分组收益、特征重要性
"""
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import numpy as np
from loguru import logger

from factor_analysis.engine import compute_ic, compute_group_returns, build_summary
from ml_research.models.base import BaseModel


def evaluate_predictions(
    pred_df: pd.DataFrame,
    label_df: pd.DataFrame,
    forward_days: int = 5,
    n_groups: int = 5,
) -> Dict[str, Any]:
    """
    评估模型预测质量。

    Args:
        pred_df: [ts_code, trade_date, pred] — 模型预测值
        label_df: [ts_code, trade_date, ret_{forward_days}d] — 真实标签
        forward_days: 前瞻天数（用于匹配列名）
        n_groups: 分组数

    Returns:
        dict with keys: ic_summary, group_returns, daily_ic
    """
    ret_col = f"ret_{forward_days}d"
    if ret_col not in label_df.columns:
        if "ret" in label_df.columns:
            label_df = label_df.rename(columns={"ret": ret_col})
        else:
            raise ValueError(f"label_df 缺少列 {ret_col}")

    # Prepare factor_df format for factor_analysis
    factor_df = pred_df.rename(columns={"pred": "factor"})[["ts_code", "trade_date", "factor"]]
    return_df = label_df[["ts_code", "trade_date", ret_col]].rename(columns={ret_col: "ret"})

    # IC
    ic_df = compute_ic(factor_df, return_df)

    # Group returns
    group_df = compute_group_returns(factor_df, return_df, n_groups=n_groups)

    # Summary
    from factor_analysis.engine import compute_coverage
    coverage_df = compute_coverage(factor_df)
    summary = build_summary(ic_df, group_df, coverage_df)

    return {
        "summary": summary,
        "daily_ic": ic_df,
        "group_returns": group_df,
    }


def print_evaluation(result: Dict[str, Any]) -> None:
    """打印评估结果到终端"""
    s = result["summary"]
    ic = s.get("ic", {})
    print(f"\n{'='*50}")
    if ic.get('mean') is not None:
        print(f"IC Mean:    {ic['mean']:.4f}")
    else:
        print("IC Mean:    N/A")
    if ic.get('std') is not None:
        print(f"IC Std:     {ic['std']:.4f}")
    else:
        print("IC Std:     N/A")
    if ic.get('icir') is not None:
        print(f"ICIR:       {ic['icir']:.4f}")
    else:
        print("ICIR:       N/A")
    if ic.get('positive_rate') is not None:
        print(f"IC > 0 %:   {ic['positive_rate']:.1%}")
    else:
        print("IC > 0 %:   N/A")
    print(f"IC Count:   {ic.get('count', 0)}")

    avg_gr = s.get("avg_group_returns", {})
    if avg_gr:
        print(f"\nGroup Returns (avg):")
        for g, v in sorted(avg_gr.items()):
            print(f"  Group {g}: {v:.4%}")
    print(f"{'='*50}\n")
