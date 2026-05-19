"""
特征工程：从 DataLoader 构建截面特征矩阵
v2 — 批量 SQL 查询替代逐股 get_history()，大幅提升速度
"""
from typing import List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from backtest.data_loader import DataLoader


def _safe_log(s: pd.Series) -> pd.Series:
    return np.log(s.clip(lower=1e-8))


def build_feature_matrix(
    dl: DataLoader,
    trade_dates: List[str],
    momentum_windows: List[int] = (5, 10, 20, 60),
    volatility_window: int = 20,
) -> pd.DataFrame:
    """
    批量构建全时段特征矩阵。

    一次性获取所有需要的行情数据，按股票分组计算特征，
    再与截面数据合并。避免逐日逐股调用 get_history()。

    Returns:
        DataFrame: [ts_code, trade_date, feat_1, ...]
    """
    start_date = trade_dates[0]
    end_date = trade_dates[-1]

    # 需要的最长历史窗口（日历日估算）
    max_window = max(list(momentum_windows) + [volatility_window])
    lookback_days = int(max_window * 1.5) + 30
    lookback_start = (
        pd.to_datetime(start_date) - pd.Timedelta(days=lookback_days)
    ).strftime("%Y-%m-%d")

    logger.info(f"批量获取行情数据: {lookback_start} ~ {end_date}")

    # === 1. 批量获取所有股票的复权行情 ===
    raw = dl.conn.execute(f"""
        SELECT d.ts_code, d.trade_date, d.close, d.volume,
               COALESCE(a.adj_factor, 1.0) as af
        FROM {dl._daily_bar_source} d
        LEFT JOIN adj_factor a
            ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
        WHERE d.trade_date BETWEEN '{lookback_start}' AND '{end_date}'
        ORDER BY d.ts_code, d.trade_date
    """).fetchdf()

    if raw.empty:
        logger.error("批量查询返回空数据")
        return pd.DataFrame()

    # 前复权（归一化到最新日）
    raw["adj_close"] = raw["close"] * raw["af"]
    latest_af = raw.sort_values("trade_date").groupby("ts_code")["af"].last().to_dict()
    raw["adj_close_norm"] = raw.apply(
        lambda r: r["adj_close"] / latest_af.get(r["ts_code"], 1.0), axis=1
    )
    raw["trade_date"] = pd.to_datetime(raw["trade_date"])

    logger.info(f"行情数据: {len(raw)} 行, {raw['ts_code'].nunique()} 只股票")

    # === 2. 按股票分组计算历史特征 ===
    hist_parts = []
    for code, grp in raw.groupby("ts_code"):
        vals = grp.sort_values("trade_date")
        dates = vals["trade_date"].values
        prices = vals["adj_close_norm"].values
        volumes = vals["volume"].values

        # 只处理在 trade_dates 范围内的日期
        masks = []
        for td in trade_dates:
            mask = dates == pd.Timestamp(td)
            if mask.any():
                idx = np.where(mask)[0][0]
                td_str = str(td) if isinstance(td, str) else pd.Timestamp(td).strftime("%Y-%m-%d")
                rec = {"ts_code": code, "trade_date": td_str}

                # Momentum
                for w in momentum_windows:
                    if idx >= w:
                        rec[f"mom_{w}d"] = prices[idx] / prices[idx - w] - 1
                    else:
                        rec[f"mom_{w}d"] = np.nan

                # Volatility
                if idx >= volatility_window:
                    rets = np.diff(np.log(prices[idx - volatility_window: idx + 1]))
                    rec[f"vol_{volatility_window}d"] = np.std(rets)
                else:
                    rec[f"vol_{volatility_window}d"] = np.nan

                # Volume ratio
                if idx >= 20:
                    rec["vol_ratio_20d"] = volumes[idx] / (np.mean(volumes[idx - 20: idx]) + 1e-8)
                else:
                    rec["vol_ratio_20d"] = np.nan

                masks.append(rec)

        if masks:
            hist_parts.extend(masks)

    if not hist_parts:
        return pd.DataFrame()

    hist_df = pd.DataFrame(hist_parts)
    logger.info(f"历史特征: {len(hist_df)} 行, {hist_df['ts_code'].nunique()} 只股票")

    # === 3. 获取截面数据并合并 ===
    cs_parts = []
    for i, td in enumerate(trade_dates):
        if i % 50 == 0:
            logger.info(f"处理截面数据: {i}/{len(trade_dates)}")
        cs = dl.get_cross_section(td)
        if not cs.empty:
            cs = cs.copy()
            cs["trade_date"] = pd.to_datetime(cs["trade_date"]).dt.strftime("%Y-%m-%d")
            cs_parts.append(cs)

    if not cs_parts:
        return pd.DataFrame()

    cs_all = pd.concat(cs_parts, ignore_index=True)

    # 截面特征
    cs_all["log_circ_mv"] = _safe_log(cs_all.get("circ_mv", pd.Series(dtype=float)))
    cs_all["log_pe_ttm"] = _safe_log(cs_all.get("pe_ttm", pd.Series(dtype=float)).abs())
    cs_all["log_pb"] = _safe_log(cs_all.get("pb", pd.Series(dtype=float)).abs())
    cs_all["turnover_rate"] = cs_all.get("turnover_rate", pd.Series(dtype=float))

    base_cols = ["ts_code", "trade_date", "log_circ_mv", "log_pe_ttm", "log_pb", "turnover_rate"]
    base_cols = [c for c in base_cols if c in cs_all.columns]
    base_df = cs_all[base_cols]

    # === 4. 合并 ===
    result = base_df.merge(hist_df, on=["ts_code", "trade_date"], how="outer")
    logger.info(f"最终特征矩阵: {len(result)} 行, {result['ts_code'].nunique()} 只股票")

    return result


def rank_normalize(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    """
    截面排名归一化：每个 trade_date 内，将特征值转为 [0, 1] 排名百分位。
    """
    df = df.copy()
    for col in feature_cols:
        if col in df.columns:
            df[col] = df.groupby("trade_date")[col].rank(pct=True)
    return df
