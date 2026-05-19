"""
标签生成：计算未来 N 日收益率
"""
from typing import List

import pandas as pd
from loguru import logger

from backtest.data_loader import DataLoader


def build_labels(
    dl: DataLoader,
    trade_dates: List[str],
    forward_days: int = 5,
) -> pd.DataFrame:
    """
    为 trade_dates 中的每个日期计算 forward_days 日后的收益率。

    对于每个日期 t:
      1. 获取 t 日截面的 close_t
      2. 获取 t+forward_days 交易日截面的 close_tn
      3. ret = close_tn / close_t - 1

    Returns:
        DataFrame: [ts_code, trade_date, ret_{forward_days}d]
    """
    calendar = dl.get_trade_calendar(
        start_date=min(trade_dates),
        end_date=None,
        only_open=True,
    )
    cal_dates = sorted(calendar["trade_date"].tolist())

    # 统一转成 YYYY-MM-DD 字符串作为 key
    date_to_idx = {}
    for i, d in enumerate(cal_dates):
        key = pd.Timestamp(d).strftime("%Y-%m-%d")
        date_to_idx[key] = i

    parts = []
    for i, td in enumerate(trade_dates):
        if i % 100 == 0:
            logger.info(f"Building labels: {i}/{len(trade_dates)}")

        td_str = pd.to_datetime(td).strftime("%Y-%m-%d")
        idx = date_to_idx.get(td_str)
        if idx is None:
            continue

        # 找 t+N 对应的交易日
        target_idx = idx + forward_days
        if target_idx >= len(cal_dates):
            continue

        future_date = cal_dates[target_idx]
        future_date_str = pd.Timestamp(future_date).strftime("%Y-%m-%d")

        # 获取两个日期的截面收盘价
        cs_now = dl.get_cross_section(td_str, fields=["ts_code", "trade_date", "close"])
        cs_future = dl.get_cross_section(future_date_str, fields=["ts_code", "trade_date", "close"])

        if cs_now.empty or cs_future.empty:
            continue

        merged = cs_now[["ts_code", "close"]].merge(
            cs_future[["ts_code", "close"]],
            on="ts_code",
            suffixes=("_now", "_future"),
        )

        merged["trade_date"] = td_str
        merged[f"ret_{forward_days}d"] = merged["close_future"] / merged["close_now"] - 1

        parts.append(merged[["ts_code", "trade_date", f"ret_{forward_days}d"]])

    if not parts:
        return pd.DataFrame(columns=["ts_code", "trade_date", f"ret_{forward_days}d"])

    return pd.concat(parts, ignore_index=True)
