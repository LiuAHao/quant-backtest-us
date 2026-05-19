from __future__ import annotations

from typing import Iterable

import pandas as pd
from loguru import logger

from backtest.data_loader import DataLoader


SME_INDEX_CODE = "399101.SZ"


def _to_ymd(text: str) -> str:
    s = str(text)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return pd.Timestamp(s).strftime("%Y-%m-%d")


def is_mainboard_code(ts_code: str) -> bool:
    code = str(ts_code).split(".")[0]
    return code.startswith(("600", "601", "603", "605", "000", "001", "002"))


def get_st_codes(dl: DataLoader) -> set[str]:
    try:
        df = dl.conn.execute("SELECT ts_code FROM instruments WHERE symbol LIKE '%ST%'").fetchdf()
    except Exception as e:
        logger.warning(f"读取 ST 股票列表失败: {e}")
        return set()
    if df.empty:
        return set()
    return set(df["ts_code"].dropna().astype(str).tolist())


def get_mainboard_pool(
    dl: DataLoader,
    trade_date: str,
    *,
    exclude_st: bool = True,
) -> pd.DataFrame:
    date_str = _to_ymd(trade_date)
    market = dl.get_cross_section(date_str)
    if market is None or market.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date"])

    market = market.copy()
    market["trade_date"] = pd.to_datetime(market["trade_date"]).dt.strftime("%Y-%m-%d")
    market = market[market["trade_date"] == date_str]
    market = market[market["close"] > 0]
    market = market[market["ts_code"].astype(str).map(is_mainboard_code)]

    if exclude_st:
        st_codes = get_st_codes(dl)
        if st_codes:
            market = market[~market["ts_code"].isin(st_codes)]

    cols = [c for c in ["ts_code", "trade_date", "close", "amount", "turnover_rate", "circ_mv", "total_mv"] if c in market.columns]
    return market[cols].copy()


def get_sme_members(dl: DataLoader) -> set[str]:
    """获取中小板综成分股集合。"""
    try:
        df = dl.conn.execute(
            f"""
            SELECT DISTINCT con_code AS ts_code
            FROM index_member
            WHERE index_code = '{SME_INDEX_CODE}'
            """
        ).fetchdf()
    except Exception as e:
        logger.warning(f"读取 index_member 失败: {e}")
        return set()

    if df.empty:
        logger.warning("index_member 中未找到 399101.SZ 成分股")
        return set()
    return set(df["ts_code"].dropna().astype(str).tolist())


def get_profitable_by_latest_full_year(dl: DataLoader, trade_date: str, min_net_profit: float = 0.0) -> set[str]:
    """
    按交易日可见的最新完整年报盈利过滤。

    注意：当前本地 income_stmt 缺少净利润字段，因此这里退化为：
    - 最新完整年报 fina_indicator 的 eps > 0
    - 若存在 dt_eps，则优先要求 dt_eps > 0

    这是“当前数据结构下可运行的近似版”，不是 PTrade 原版“净利润 > 0”口径。
    """
    trade_date = _to_ymd(trade_date)
    try:
        fin = dl.get_financial_cross_section(
            trade_date,
            table="fina_indicator",
            fields=["ts_code", "ann_date", "end_date", "eps", "dt_eps"],
        )
    except Exception as e:
        logger.warning(f"读取 fina_indicator 失败: {e}")
        return set()

    if fin is None or fin.empty:
        return set()

    fin = fin.copy()
    fin["end_date"] = fin["end_date"].astype(str)
    fin = fin[fin["end_date"].str.replace("-", "").str.endswith("1231")]
    if fin.empty:
        return set()

    fin["eps"] = pd.to_numeric(fin.get("eps"), errors="coerce")
    if "dt_eps" in fin.columns:
        fin["dt_eps"] = pd.to_numeric(fin.get("dt_eps"), errors="coerce")
        passed = fin[(fin["dt_eps"].fillna(fin["eps"]) > float(min_net_profit))]
    else:
        passed = fin[(fin["eps"] > float(min_net_profit))]
    return set(passed["ts_code"].dropna().astype(str).tolist())


def get_candidate_pool(
    dl: DataLoader,
    trade_date: str,
    *,
    candidate_count: int = 100,
    min_net_profit: float = 0.0,
) -> pd.DataFrame:
    """
    方案2候选池：
    1) 中小板综成分股
    2) 按流通市值最小取前 candidate_count
    3) 若当前财务覆盖足够，则可额外叠加“最新完整年报盈利过滤”

    当前本地数据下，核心可运行部分是“中小板综池内 ML 二次排序”。
    """
    date_str = _to_ymd(trade_date)
    market = dl.get_cross_section(date_str)
    if market is None or market.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "circ_mv"])

    market = market.copy()
    market["trade_date"] = pd.to_datetime(market["trade_date"]).dt.strftime("%Y-%m-%d")
    market = market[market["trade_date"] == date_str]

    members = get_sme_members(dl)
    if not members:
        return pd.DataFrame(columns=["ts_code", "trade_date", "circ_mv"])
    market = market[market["ts_code"].isin(members)]

    # 当前财务覆盖很稀疏时，不强制盈利过滤，避免候选池为空。
    profitable = get_profitable_by_latest_full_year(dl, date_str, min_net_profit=min_net_profit)
    if len(profitable) >= 50:
        market = market[market["ts_code"].isin(profitable)]

    market["circ_mv"] = pd.to_numeric(market.get("circ_mv"), errors="coerce")
    market = market.dropna(subset=["circ_mv"])
    market = market[market["circ_mv"] > 0]
    market = market.sort_values(["circ_mv", "ts_code"]).head(int(candidate_count))

    return market[[c for c in ["ts_code", "trade_date", "circ_mv", "close", "up_limit", "down_limit"] if c in market.columns]].copy()


def filter_to_candidate_pool(
    df: pd.DataFrame,
    dl: DataLoader,
    *,
    candidate_count: int = 100,
    min_net_profit: float = 0.0,
    trade_dates: Iterable[str] | None = None,
) -> pd.DataFrame:
    """将任意 ts_code/trade_date 级别数据过滤到方案2候选池内。"""
    if df is None or df.empty:
        return df

    dates = sorted(set(trade_dates or df["trade_date"].astype(str).tolist()))
    pool_parts = []
    for i, td in enumerate(dates):
        if i % 50 == 0:
            logger.info(f"构建方案2候选池: {i}/{len(dates)}")
        pool = get_candidate_pool(
            dl,
            td,
            candidate_count=candidate_count,
            min_net_profit=min_net_profit,
        )
        if not pool.empty:
            pool_parts.append(pool[["ts_code", "trade_date"]])

    if not pool_parts:
        return df.iloc[0:0].copy()

    pool_df = pd.concat(pool_parts, ignore_index=True).drop_duplicates()
    out = df.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
    return out.merge(pool_df, on=["ts_code", "trade_date"], how="inner")


def filter_to_mainboard_pool(
    df: pd.DataFrame,
    dl: DataLoader,
    *,
    trade_dates: Iterable[str] | None = None,
    exclude_st: bool = True,
) -> pd.DataFrame:
    """将任意 ts_code/trade_date 级别数据过滤到主板非ST池。"""
    if df is None or df.empty:
        return df

    dates = sorted(set(trade_dates or df["trade_date"].astype(str).tolist()))
    pool_parts = []
    for i, td in enumerate(dates):
        if i % 50 == 0:
            logger.info(f"构建主板池: {i}/{len(dates)}")
        pool = get_mainboard_pool(dl, td, exclude_st=exclude_st)
        if not pool.empty:
            pool_parts.append(pool[["ts_code", "trade_date"]])

    if not pool_parts:
        return df.iloc[0:0].copy()

    pool_df = pd.concat(pool_parts, ignore_index=True).drop_duplicates()
    out = df.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
    return out.merge(pool_df, on=["ts_code", "trade_date"], how="inner")
