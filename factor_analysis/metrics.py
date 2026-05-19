from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


def compute_ic(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    method: str = "spearman",
) -> pd.DataFrame:
    merged = _merge_factor_return(factor_df, return_df)
    if merged.empty:
        return pd.DataFrame(columns=["trade_date", "ic", "n"])

    def _ic_group(g: pd.DataFrame) -> pd.Series:
        if len(g) < 3:
            return pd.Series({"ic": np.nan, "n": len(g)})
        if method == "pearson":
            corr, _ = stats.pearsonr(g["factor"], g["ret"])
        else:
            corr, _ = stats.spearmanr(g["factor"], g["ret"])
        return pd.Series({"ic": corr, "n": len(g)})

    return merged.groupby("trade_date").apply(_ic_group).reset_index()


def compute_rank_ic(factor_df: pd.DataFrame, return_df: pd.DataFrame) -> pd.DataFrame:
    return compute_ic(factor_df, return_df, method="spearman")


def compute_group_returns(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    n_groups: int = 5,
) -> pd.DataFrame:
    merged = _merge_factor_return(factor_df, return_df)
    if merged.empty:
        return pd.DataFrame(columns=["trade_date", "group", "avg_ret", "n"])

    merged = merged.copy()
    groups = []
    for _td, g in merged.groupby("trade_date"):
        if len(g) < n_groups or g["factor"].nunique(dropna=True) < 2:
            groups.append(pd.Series(1, index=g.index))
        else:
            groups.append(pd.qcut(g["factor"], n_groups, labels=False, duplicates="drop") + 1)
    merged["group"] = pd.concat(groups)
    result = merged.groupby(["trade_date", "group"])["ret"].agg(["mean", "count"]).reset_index()
    result.columns = ["trade_date", "group", "avg_ret", "n"]
    return result


def compute_long_short_returns(
    group_df: pd.DataFrame,
    n_groups: int = 5,
    factor_direction: str = "higher_better",
) -> pd.DataFrame:
    if group_df.empty:
        return pd.DataFrame(columns=["trade_date", "long_group", "short_group", "long_ret", "short_ret", "long_short_ret"])
    high_group = int(n_groups)
    low_group = 1
    long_group = low_group if factor_direction == "lower_better" else high_group
    short_group = high_group if factor_direction == "lower_better" else low_group
    pivot = group_df.pivot_table(index="trade_date", columns="group", values="avg_ret", aggfunc="mean")
    if long_group not in pivot.columns or short_group not in pivot.columns:
        return pd.DataFrame(columns=["trade_date", "long_group", "short_group", "long_ret", "short_ret", "long_short_ret"])
    result = pd.DataFrame(
        {
            "trade_date": pivot.index.astype(str),
            "long_group": long_group,
            "short_group": short_group,
            "long_ret": pivot[long_group].values,
            "short_ret": pivot[short_group].values,
        }
    )
    result["long_short_ret"] = result["long_ret"] - result["short_ret"]
    return result


def compute_coverage(
    factor_df: pd.DataFrame,
    total_stocks_per_date: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if factor_df.empty:
        return pd.DataFrame(columns=["trade_date", "coverage", "factor_count", "total_count"])

    valid = _normalize_trade_date(factor_df).dropna(subset=["factor"])
    counts = valid.groupby("trade_date")["ts_code"].nunique().reset_index()
    counts.columns = ["trade_date", "factor_count"]

    if total_stocks_per_date is not None and not total_stocks_per_date.empty:
        total = _normalize_trade_date(total_stocks_per_date).groupby("trade_date")["ts_code"].nunique().reset_index()
        total.columns = ["trade_date", "total_count"]
        merged = counts.merge(total, on="trade_date", how="left")
    else:
        max_count = counts["factor_count"].max()
        merged = counts.copy()
        merged["total_count"] = max_count

    merged["coverage"] = merged["factor_count"] / merged["total_count"].replace(0, np.nan)
    return merged[["trade_date", "coverage", "factor_count", "total_count"]]


def build_summary(
    ic_df: pd.DataFrame,
    group_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
    long_short_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {}

    if not ic_df.empty:
        valid_ic = ic_df.dropna(subset=["ic"])
        summary["ic"] = {
            "mean": float(valid_ic["ic"].mean()) if not valid_ic.empty else None,
            "std": float(valid_ic["ic"].std()) if not valid_ic.empty else None,
            "icir": (
                float(valid_ic["ic"].mean() / valid_ic["ic"].std())
                if not valid_ic.empty and valid_ic["ic"].std() > 0
                else None
            ),
            "positive_rate": float((valid_ic["ic"] > 0).mean()) if not valid_ic.empty else None,
            "count": len(valid_ic),
        }
    else:
        summary["ic"] = {"mean": None, "std": None, "icir": None, "positive_rate": None, "count": 0}

    if not group_df.empty:
        latest_date = group_df["trade_date"].max()
        latest = group_df[group_df["trade_date"] == latest_date]
        summary["latest_group_returns"] = {
            str(int(row["group"])): float(row["avg_ret"])
            for _, row in latest.iterrows()
        }
        avg_by_group = group_df.groupby("group")["avg_ret"].mean()
        summary["avg_group_returns"] = {
            str(int(g)): float(v) for g, v in avg_by_group.items()
        }
    else:
        summary["latest_group_returns"] = {}
        summary["avg_group_returns"] = {}

    if long_short_df is not None and not long_short_df.empty:
        valid_ls = long_short_df.dropna(subset=["long_short_ret"])
        summary["long_short"] = {
            "mean": float(valid_ls["long_short_ret"].mean()) if not valid_ls.empty else None,
            "win_rate": float((valid_ls["long_short_ret"] > 0).mean()) if not valid_ls.empty else None,
            "count": len(valid_ls),
        }
    else:
        summary["long_short"] = {"mean": None, "win_rate": None, "count": 0}

    if not coverage_df.empty:
        summary["coverage"] = {
            "mean": float(coverage_df["coverage"].mean()),
            "min": float(coverage_df["coverage"].min()),
            "max": float(coverage_df["coverage"].max()),
            "count": len(coverage_df),
        }
    else:
        summary["coverage"] = {"mean": None, "min": None, "max": None, "count": 0}

    return summary


def summarize_by_window(df: pd.DataFrame, value_col: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if df.empty or "window" not in df.columns:
        return result
    for window, group in df.groupby("window"):
        valid = group.dropna(subset=[value_col])
        result[f"{int(window)}d"] = {
            "mean": float(valid[value_col].mean()) if not valid.empty else None,
            "std": float(valid[value_col].std()) if not valid.empty else None,
            "positive_rate": float((valid[value_col] > 0).mean()) if not valid.empty else None,
            "count": len(valid),
        }
    return result


def _merge_factor_return(factor_df: pd.DataFrame, return_df: pd.DataFrame) -> pd.DataFrame:
    required_f = {"ts_code", "trade_date", "factor"}
    required_r = {"ts_code", "trade_date", "ret"}
    if not required_f.issubset(factor_df.columns):
        missing = required_f - set(factor_df.columns)
        raise ValueError(f"factor_df 缺少列: {missing}")
    if not required_r.issubset(return_df.columns):
        missing = required_r - set(return_df.columns)
        raise ValueError(f"return_df 缺少列: {missing}")

    left = _normalize_trade_date(factor_df)
    right = _normalize_trade_date(return_df)
    left["ts_code"] = left["ts_code"].astype(str)
    right["ts_code"] = right["ts_code"].astype(str)
    merged = left.merge(right, on=["ts_code", "trade_date"], how="inner")
    return merged.dropna(subset=["factor", "ret"])


def _normalize_trade_date(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "trade_date" in work.columns:
        work["trade_date"] = pd.to_datetime(work["trade_date"]).dt.strftime("%Y-%m-%d")
    return work
