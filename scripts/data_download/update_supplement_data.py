"""
补充量化数据下载脚本 — 涵盖所有缺失的关键数据

任务列表:
  index_daily     - 指数日线行情（12个关键指数）
  instruments     - 历史化股票列表（含退市/暂停，消除生存偏差）
  namechange      - 补全股票历史名称变更（ST摘帽/戴帽）
  industry        - 行业分类数据（申万+Tushare industry字段）
  fina            - 财务报表数据（利润表/资产负债表/现金流量表/财务指标）
  etf_daily       - ETF/基金日线行情
  adj_factor_fix  - 修复复权因子（过滤非交易日）
  adj_factor_dl   - 下载复权因子（按交易日）
  index_member_bs - 通过Baostock下载宽基指数历史成分股
  index_member_ak - 通过AkShare下载宽基指数当前成分股
  bs_express      - Baostock业绩快报（比正式财报早1-2月）
  bs_forecast     - Baostock业绩预告（比快报更早）
  bs_dividend     - Baostock分红送转（含除权日/登记日等关键日期）
  holder_number   - 股东人数变化（筹码集中度指标）

用法:
    python scripts/update_supplement_data.py --tasks all
    python scripts/update_supplement_data.py --tasks index_daily,instruments,industry
    python scripts/update_supplement_data.py --tasks fina --start 20200101
    python scripts/update_supplement_data.py --tasks bs_express,bs_forecast,bs_dividend,holder_number
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings


# ═══════════════════════════════════════════════════════════════
# Tushare 连接
# ═══════════════════════════════════════════════════════════════

API_DELAY = 0.5


def create_pro():
    if not settings.TUSHARE_TOKEN:
        raise ValueError("缺少 TUSHARE_TOKEN，请在项目根目录 .env 中配置。")
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    import tushare as ts
    from tushare.pro.client import DataApi
    if settings.TUSHARE_BASE_URL:
        DataApi._DataApi__http_url = settings.TUSHARE_BASE_URL
    return ts.pro_api(settings.TUSHARE_TOKEN)


def _fetch(pro, func: Callable, **kwargs) -> pd.DataFrame:
    max_retries = 3
    last_exc = None
    for i in range(max_retries):
        try:
            time.sleep(API_DELAY)
            df = func(**kwargs)
            return df if df is not None else pd.DataFrame()
        except Exception as exc:
            last_exc = exc
            if i < max_retries - 1:
                time.sleep(API_DELAY * (i + 2))
    raise RuntimeError(str(last_exc))


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _save_checkpoint(name: str, data):
    cp_path = settings.DATA_DIR / "supplement_checkpoint" / f"{name}.json"
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    cp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _load_checkpoint(name: str):
    cp_path = settings.DATA_DIR / "supplement_checkpoint" / f"{name}.json"
    if cp_path.exists():
        return json.loads(cp_path.read_text())
    return None


def _format_date(val) -> Optional[str]:
    if pd.isna(val) or val is None:
        return None
    s = str(val).replace("-", "")[:8]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _get_trade_dates(pro, start_date: str, end_date: str) -> List[str]:
    df = _fetch(pro, pro.trade_cal, exchange="SSE",
                start_date=start_date, end_date=end_date, is_open="1",
                fields="cal_date")
    if df.empty:
        return []
    return sorted(df["cal_date"].astype(str).tolist())


# ═══════════════════════════════════════════════════════════════
# 任务 1: 指数日线行情
# ═══════════════════════════════════════════════════════════════

KEY_INDEXES = [
    "399101.SZ",    # 中小板综
    "000985.CSI",   # 中证全指
    "000300.CSI",   # 沪深300
    "000905.CSI",   # 中证500
    "000852.CSI",   # 中证1000
    "399006.SZ",    # 创业板指
    "000001.SH",    # 上证综指
    "000688.CSI",   # 科创50
    "399001.SZ",    # 深证成指
    "399316.SZ",    # 创业板综
    "399673.SZ",    # 创业板50
    "000016.SH",    # 上证50
]


def update_index_daily(pro, start_date: str = "20100101", end_date: Optional[str] = None) -> int:
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    logger.info("=" * 50)
    logger.info(f"指数日线: {start_date} ~ {end_date}")

    idx_dir = settings.INDEX_DAILY_DIR
    _ensure_dir(idx_dir)
    total = 0

    for idx_code in KEY_INDEXES:
        try:
            df = _fetch(pro, pro.index_daily, ts_code=idx_code,
                        start_date=start_date.replace("-", ""),
                        end_date=end_date.replace("-", ""))
            if df.empty:
                logger.warning(f"{idx_code} 日线为空")
                continue

            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df["year"] = df["trade_date"].dt.year
            for year, group in df.groupby("year"):
                year_dir = idx_dir / f"ts_code={idx_code}" / f"year={year}"
                _ensure_dir(year_dir)
                group.to_parquet(year_dir / "part-000.parquet", index=False)
            total += len(df)
            logger.info(f"  {idx_code}: {len(df)} 条")
        except Exception as e:
            logger.warning(f"  {idx_code} 获取失败: {e}")

    logger.info(f"指数日线完成, 累计 {total} 条")
    return total


# ═══════════════════════════════════════════════════════════════
# 任务 2: 历史化股票列表（消除生存偏差）
# ═══════════════════════════════════════════════════════════════

def update_instruments_historical(pro) -> int:
    """获取全状态股票（上市L/退市D/暂停P），消除生存偏差"""
    logger.info("=" * 50)
    logger.info("历史化股票列表（含退市/暂停）")

    fields = (
        "ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,"
        "exchange,curr_type,list_status,list_date,delist_date,is_hs"
    )
    frames = []
    for status in ["L", "D", "P"]:
        try:
            df = _fetch(pro, pro.stock_basic, exchange="", list_status=status, fields=fields)
            if not df.empty:
                df["status"] = status
                frames.append(df)
                logger.info(f"  status={status}: {len(df)} 只")
        except Exception as e:
            logger.warning(f"  status={status} 获取失败: {e}")

    if not frames:
        logger.warning("股票列表为空")
        return 0

    result = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code", keep="first")

    # 统一字段格式
    result["symbol"] = result["name"]  # name -> symbol（股票简称）
    result["exchange"] = result["ts_code"].str.split(".").str[-1]
    for col in ["list_date", "delist_date"]:
        result[col] = result[col].apply(_format_date)

    output_path = settings.INSTRUMENTS_DIR / "instruments.parquet"
    _ensure_dir(settings.INSTRUMENTS_DIR)
    result[["ts_code", "symbol", "exchange", "list_date", "delist_date", "status"]].to_parquet(
        output_path, index=False
    )

    logger.info(f"股票列表完成: {len(result)} 只 (L={len(result[result.status=='L'])}, "
                f"D={len(result[result.status=='D'])}, P={len(result[result.status=='P'])})")
    return len(result)


# ═══════════════════════════════════════════════════════════════
# 任务 3: 补全股票历史名称变更
# ═══════════════════════════════════════════════════════════════

def update_namechange_full(pro) -> int:
    logger.info("=" * 50)
    logger.info("股票历史名称变更（全量）")

    try:
        df = _fetch(pro, pro.namechange, ts_code="",
                    fields="ts_code,name,start_date,end_date,ann_date,change_reason")
        if df.empty:
            logger.warning("namechange 为空")
            return 0

        for col in ["start_date", "end_date", "ann_date"]:
            df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")

        output_path = settings.NAMECHANGE_DIR / "namechange.parquet"
        _ensure_dir(settings.NAMECHANGE_DIR)
        df.to_parquet(output_path, index=False)

        logger.info(f"namechange 完成: {len(df)} 条, 覆盖 {df['ts_code'].nunique()} 只股票")
        return len(df)
    except Exception as e:
        logger.error(f"namechange 失败: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════
# 任务 4: 行业分类数据
# ═══════════════════════════════════════════════════════════════

def update_industry(pro) -> int:
    """获取行业分类数据（stock_basic中的industry字段 + 申万行业分类）"""
    logger.info("=" * 50)
    logger.info("行业分类数据")

    industry_dir = settings.DATA_DIR / "industry"
    _ensure_dir(industry_dir)
    total = 0

    # 4.1 从 stock_basic 获取 industry 字段（每只股票的行业归属）
    try:
        logger.info("  获取 stock_basic 行业字段...")
        frames = []
        for status in ["L", "D"]:
            df = _fetch(pro, pro.stock_basic, exchange="", list_status=status,
                        fields="ts_code,name,industry,market")
            if not df.empty:
                df["status"] = status
                frames.append(df)
        if frames:
            industry_map = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code", keep="first")
            industry_map.to_parquet(industry_dir / "stock_industry.parquet", index=False)
            total += len(industry_map)
            logger.info(f"  stock_basic 行业: {len(industry_map)} 只, "
                        f"{industry_map['industry'].nunique()} 个行业")
    except Exception as e:
        logger.warning(f"  stock_basic 行业获取失败: {e}")

    # 4.2 申万行业分类 index_classify
    try:
        logger.info("  获取申万一级行业分类...")
        sw_l1 = _fetch(pro, pro.index_classify, level="L1", src="SW2021")
        if not sw_l1.empty:
            sw_l1.to_parquet(industry_dir / "sw_index_l1.parquet", index=False)
            total += len(sw_l1)
            logger.info(f"  申万一级: {len(sw_l1)} 个行业")

            # 获取每个申万一级行业的成分股
            logger.info("  获取申万一级行业成分股...")
            member_frames = []
            for _, row in sw_l1.iterrows():
                idx_code = row["index_code"]
                try:
                    members = _fetch(pro, pro.index_member, index_code=idx_code)
                    if not members.empty:
                        members["index_code"] = idx_code
                        members["index_name"] = row.get("industry_name", "")
                        member_frames.append(members)
                except Exception as e:
                    logger.warning(f"    {idx_code} 成分股获取失败: {e}")

            if member_frames:
                sw_members = pd.concat(member_frames, ignore_index=True)
                sw_members.to_parquet(industry_dir / "sw_index_member.parquet", index=False)
                total += len(sw_members)
                logger.info(f"  申万成分股: {len(sw_members)} 条")
    except Exception as e:
        logger.warning(f"  申万行业获取失败: {e}")

    logger.info(f"行业分类完成, 累计 {total} 条")
    return total


# ═══════════════════════════════════════════════════════════════
# 任务 5: 财务报表数据
# ═══════════════════════════════════════════════════════════════

def update_financial(pro, start_date: str = "20140101") -> int:
    """获取财务报表数据（利润表/资产负债表/现金流量表/财务指标）"""
    logger.info("=" * 50)
    logger.info(f"财务报表数据: {start_date} ~ 今")

    fina_dir = settings.DATA_DIR / "financial"
    _ensure_dir(fina_dir)
    total = 0
    end_date = datetime.now().strftime("%Y%m%d")

    # 获取全市场股票列表
    try:
        stock_df = _fetch(pro, pro.stock_basic, exchange="", list_status="L",
                          fields="ts_code")
        stock_codes = stock_df["ts_code"].tolist()
        logger.info(f"  全市场 {len(stock_codes)} 只股票")
    except Exception as e:
        logger.error(f"  获取股票列表失败: {e}")
        return 0

    # 断点续传
    checkpoint = _load_checkpoint("financial") or {"done_codes": []}
    done_set = set(checkpoint["done_codes"])
    remaining = [c for c in stock_codes if c not in done_set]

    if not remaining:
        logger.info("财务报表已全部下载，跳过")
        return 0

    logger.info(f"  已完成 {len(done_set)}, 剩余 {len(remaining)}")

    # 按股票遍历下载
    income_frames = []
    balance_frames = []
    cashflow_frames = []
    fina_frames = []

    # 加载已有数据
    for name, frames in [("income", income_frames), ("balancesheet", balance_frames),
                         ("cashflow", cashflow_frames), ("fina_indicator", fina_frames)]:
        path = fina_dir / f"{name}.parquet"
        if path.exists():
            try:
                existing = pd.read_parquet(path)
                frames.append(existing)
            except Exception:
                pass

    for i, ts_code in enumerate(remaining, 1):
        try:
            # 利润表
            income = _fetch(pro, pro.income, ts_code=ts_code,
                            start_date=start_date, end_date=end_date,
                            fields="ts_code,ann_date,f_ann_date,end_date,report_type,"
                                   "basic_eps,diluted_eps,total_revenue,revenue")
            if not income.empty:
                income_frames.append(income)

            # 资产负债表
            balance = _fetch(pro, pro.balancesheet, ts_code=ts_code,
                             start_date=start_date, end_date=end_date,
                             fields="ts_code,ann_date,f_ann_date,end_date,report_type,"
                                    "total_assets,total_hldr_eqy_exc_min_int,"
                                    "total_hldr_eqy_inc_min_int,total_liab")
            if not balance.empty:
                balance_frames.append(balance)

            # 现金流量表
            cashflow = _fetch(pro, pro.cashflow, ts_code=ts_code,
                              start_date=start_date, end_date=end_date,
                              fields="ts_code,ann_date,f_ann_date,end_date,report_type,"
                                     "n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act")
            if not cashflow.empty:
                cashflow_frames.append(cashflow)

            # 财务指标
            fina_ind = _fetch(pro, pro.fina_indicator, ts_code=ts_code,
                              start_date=start_date, end_date=end_date,
                              fields="ts_code,ann_date,end_date,eps,dt_eps,roe,roa,"
                                     "debt_to_assets,gross_margin,current_ratio,quick_ratio")
            if not fina_ind.empty:
                fina_frames.append(fina_ind)

            done_set.add(ts_code)

            # 每100只保存一次
            if i % 100 == 0 or i == len(remaining):
                for name, frames in [("income", income_frames), ("balancesheet", balance_frames),
                                     ("cashflow", cashflow_frames), ("fina_indicator", fina_frames)]:
                    if frames:
                        merged = pd.concat(frames, ignore_index=True).drop_duplicates()
                        merged.to_parquet(fina_dir / f"{name}.parquet", index=False)
                        total = max(total, len(merged))

                _save_checkpoint("financial", {"done_codes": list(done_set)})
                logger.info(f"  进度: {i}/{len(remaining)}")

        except Exception as e:
            logger.warning(f"  {ts_code} 获取失败: {e}")
            done_set.add(ts_code)

    # 最终保存
    for name, frames in [("income", income_frames), ("balancesheet", balance_frames),
                         ("cashflow", cashflow_frames), ("fina_indicator", fina_frames)]:
        if frames:
            merged = pd.concat(frames, ignore_index=True).drop_duplicates()
            merged.to_parquet(fina_dir / f"{name}.parquet", index=False)
            cnt = len(merged)
            logger.info(f"    {name}: {cnt} 条")

    _save_checkpoint("financial", {"done_codes": list(done_set)})
    logger.info(f"财务报表完成")
    return total


# ═══════════════════════════════════════════════════════════════
# 任务 6: ETF/基金日线行情
# ═══════════════════════════════════════════════════════════════

def update_etf_daily(pro, start_date: str = "20140101") -> int:
    """获取ETF/基金日线行情"""
    logger.info("=" * 50)
    logger.info(f"ETF日线行情: {start_date} ~ 今")

    etf_dir = settings.DATA_DIR / "etf_daily"
    _ensure_dir(etf_dir)
    end_date = datetime.now().strftime("%Y%m%d")
    total = 0

    # 获取ETF列表
    try:
        fund_df = _fetch(pro, pro.fund_basic, market="E",
                         fields="ts_code,name,status,list_date,delist_date")
        if fund_df.empty:
            logger.warning("ETF列表为空")
            return 0
        etf_codes = fund_df[fund_df["status"] == "L"]["ts_code"].tolist()
        logger.info(f"  活跃ETF: {len(etf_codes)} 只")
    except Exception as e:
        logger.error(f"  获取ETF列表失败: {e}")
        return 0

    # 断点续传
    checkpoint = _load_checkpoint("etf_daily") or {"done_codes": []}
    done_set = set(checkpoint["done_codes"])
    remaining = [c for c in etf_codes if c not in done_set]

    if not remaining:
        logger.info("ETF日线已全部更新，跳过")
        return 0

    logger.info(f"  已完成 {len(done_set)}, 剩余 {len(remaining)}")

    for i, ts_code in enumerate(remaining, 1):
        try:
            df = _fetch(pro, pro.fund_daily, ts_code=ts_code,
                        start_date=start_date, end_date=end_date)
            if df.empty:
                done_set.add(ts_code)
                continue

            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df["year"] = df["trade_date"].dt.year
            for year, group in df.groupby("year"):
                year_dir = etf_dir / f"ts_code={ts_code}" / f"year={year}"
                _ensure_dir(year_dir)
                group.to_parquet(year_dir / "part-000.parquet", index=False)
            total += len(df)

            done_set.add(ts_code)
            if i % 50 == 0 or i == len(remaining):
                _save_checkpoint("etf_daily", {"done_codes": list(done_set)})
                logger.info(f"  进度: {i}/{len(remaining)}, 累计 {total} 条")
        except Exception as e:
            logger.warning(f"  {ts_code} 获取失败: {e}")
            done_set.add(ts_code)

    _save_checkpoint("etf_daily", {"done_codes": list(done_set)})
    logger.info(f"ETF日线完成, 累计 {total} 条")
    return total


# ═══════════════════════════════════════════════════════════════
# 任务 7: 修复复权因子（过滤非交易日）
# ═══════════════════════════════════════════════════════════════

def fix_adj_factor_dates(pro) -> int:
    """将 adj_factor 中非交易日的分区清理掉，只保留交易日数据"""
    logger.info("=" * 50)
    logger.info("修复复权因子（过滤非交易日）")

    adj_dir = settings.ADJ_FACTOR_DIR
    if not adj_dir.exists():
        logger.warning("adj_factor 目录不存在")
        return 0

    # 获取交易日历（YYYYMMDD格式），统一转为 YYYY-MM-DD
    raw_dates = _get_trade_dates(pro, "20100101", datetime.now().strftime("%Y%m%d"))
    trade_date_set = set()
    for d in raw_dates:
        trade_date_set.add(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
    logger.info(f"  交易日历: {len(trade_date_set)} 个交易日")

    # 扫描现有分区
    existing_partitions = []
    for d in adj_dir.iterdir():
        if d.is_dir() and d.name.startswith("trade_date="):
            date_str = d.name.replace("trade_date=", "")
            existing_partitions.append((date_str, d))

    logger.info(f"  现有分区: {len(existing_partitions)} 个")

    # 找出非交易日分区
    non_trading = [(ds, p) for ds, p in existing_partitions if ds not in trade_date_set]
    logger.info(f"  非交易日分区: {len(non_trading)} 个")

    if not non_trading:
        logger.info("  无需修复，所有分区都是交易日")
        return 0

    # 删除非交易日分区
    removed = 0
    for date_str, partition_path in non_trading:
        try:
            import shutil
            shutil.rmtree(partition_path)
            removed += 1
        except Exception as e:
            logger.warning(f"  删除 {date_str} 失败: {e}")

    logger.info(f"复权因子修复完成: 删除 {removed} 个非交易日分区")
    return removed


# ═══════════════════════════════════════════════════════════════
# 任务 8: 重新下载复权因子（按交易日）
# ═══════════════════════════════════════════════════════════════

def download_adj_factor(pro, start_date: str = "20140101", end_date: Optional[str] = None) -> int:
    """按交易日下载全市场复权因子"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    logger.info("=" * 50)
    logger.info(f"下载复权因子: {start_date} ~ {end_date}")

    adj_dir = settings.ADJ_FACTOR_DIR
    _ensure_dir(adj_dir)

    # 获取交易日历
    trade_dates = _get_trade_dates(pro, start_date, end_date)
    logger.info(f"  交易日: {len(trade_dates)} 天")

    # 断点续传
    checkpoint = _load_checkpoint("adj_factor") or {"done_dates": []}
    done_set = set(checkpoint["done_dates"])
    remaining = [d for d in trade_dates if d not in done_set]

    if not remaining:
        logger.info("复权因子已全部下载，跳过")
        return 0

    logger.info(f"  已完成 {len(done_set)}, 剩余 {len(remaining)}")

    total = 0
    for i, trade_date in enumerate(remaining, 1):
        try:
            df = _fetch(pro, pro.adj_factor, trade_date=trade_date,
                        fields="ts_code,trade_date,adj_factor")
            if df.empty:
                done_set.add(trade_date)
                continue

            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
            date_str = df["trade_date"].iloc[0].strftime("%Y-%m-%d")
            partition_dir = adj_dir / f"trade_date={date_str}"
            _ensure_dir(partition_dir)
            df.to_parquet(partition_dir / "part-000.parquet", index=False)

            total += len(df)
            done_set.add(trade_date)

            if i % 50 == 0 or i == len(remaining):
                _save_checkpoint("adj_factor", {"done_dates": list(done_set)})
                logger.info(f"  进度: {i}/{len(remaining)}, 累计 {total} 条")
        except Exception as e:
            logger.warning(f"  {trade_date} 获取失败: {e}")

    _save_checkpoint("adj_factor", {"done_dates": list(done_set)})
    logger.info(f"复权因子下载完成, 累计 {total} 条")
    return total


# ═══════════════════════════════════════════════════════════════
# 任务 9: Baostock 宽基指数历史成分股
# ═══════════════════════════════════════════════════════════════

# Baostock 支持的宽基指数
BAOSTOCK_INDEXES = {
    "000300": {"name": "沪深300", "func": "query_hs300_stocks"},
    "000905": {"name": "中证500", "func": "query_zz500_stocks"},
    "000016": {"name": "上证50",  "func": "query_sz50_stocks"},
}


def _baostock_code_to_ts(code: str) -> str:
    """Baostock 代码转 Tushare 格式: sh.600000 → 600000.SH"""
    parts = code.split(".")
    if len(parts) == 2:
        prefix, num = parts
        suffix = "SH" if prefix == "sh" else "SZ" if prefix == "sz" else "BJ"
        return f"{num}.{suffix}"
    return code


def _generate_monthly_dates(start_year: int, end_year: int, end_month: int) -> List[str]:
    """生成月末日期列表: ['2014-01-31', '2014-02-28', ...]"""
    dates = []
    for year in range(start_year, end_year + 1):
        m_end = end_month if year == end_year else 12
        for month in range(1, m_end + 1):
            if month == 12:
                last_day = 31
            elif month in [4, 6, 9, 11]:
                last_day = 30
            elif month == 2:
                last_day = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
            else:
                last_day = 31
            dates.append(f"{year}-{month:02d}-{last_day:02d}")
    return dates


def download_index_member_baostock(start_date: str = "20140101") -> int:
    """通过 Baostock 下载宽基指数历史成分股"""
    logger.info("=" * 50)
    logger.info("Baostock 宽基指数历史成分股")

    try:
        import baostock as bs
    except ImportError:
        logger.error("baostock 未安装，请运行: pip install baostock")
        return 0

    lg = bs.login()
    if lg.error_code != "0":
        logger.error(f"Baostock 登录失败: {lg.error_msg}")
        return 0

    member_dir = settings.DATA_DIR / "index_member"
    _ensure_dir(member_dir)

    # 解析起始日期
    start_year = int(start_date[:4])
    start_month = int(start_date[4:6])
    now = datetime.now()
    end_year = now.year
    end_month = now.month

    # 生成月末日期列表（从 start_month 开始）
    all_dates = _generate_monthly_dates(start_year, end_year, end_month)
    # 过滤掉早于 start_date 的日期
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    query_dates = [d for d in all_dates if datetime.strptime(d, "%Y-%m-%d") >= start_dt]

    logger.info(f"  查询范围: {start_date} ~ {now.strftime('%Y%m%d')}")
    logger.info(f"  查询日期: {len(query_dates)} 个月末")
    logger.info(f"  目标指数: {', '.join(v['name'] for v in BAOSTOCK_INDEXES.values())}")

    # 断点续传
    checkpoint = _load_checkpoint("index_member_bs") or {"done_dates": {}}
    done_dates = checkpoint.get("done_dates", {})

    all_frames = []

    for idx_code, idx_info in BAOSTOCK_INDEXES.items():
        func_name = idx_info["func"]
        idx_name = idx_info["name"]
        query_func = getattr(bs, func_name)

        done_set = set(done_dates.get(idx_code, []))
        remaining = [d for d in query_dates if d not in done_set]

        if not remaining:
            logger.info(f"  {idx_name}({idx_code}): 已全部完成")
            # 加载已有数据
            existing_path = member_dir / f"baostock_{idx_code}.parquet"
            if existing_path.exists():
                all_frames.append(pd.read_parquet(existing_path))
            continue

        logger.info(f"  {idx_name}({idx_code}): 已完成 {len(done_set)}, 剩余 {len(remaining)}")

        frames = []
        for i, date_str in enumerate(remaining, 1):
            try:
                rs = query_func(date=date_str)
                df = rs.get_data()
                if not df.empty:
                    df["index_code"] = f"{idx_code}.CSI"
                    df["con_code"] = df["code"].apply(_baostock_code_to_ts)
                    df["in_date"] = date_str.replace("-", "")
                    df["out_date"] = None
                    df["is_new"] = "Y" if date_str == query_dates[-1] else "N"
                    df = df[["index_code", "con_code", "in_date", "out_date", "is_new"]]
                    frames.append(df)

                done_set.add(date_str)

                if i % 24 == 0 or i == len(remaining):
                    done_dates[idx_code] = list(done_set)
                    _save_checkpoint("index_member_bs", {"done_dates": done_dates})
                    logger.info(f"    {idx_name} 进度: {i}/{len(remaining)}")
            except Exception as e:
                logger.warning(f"    {idx_name} {date_str} 失败: {e}")

        if frames:
            merged = pd.concat(frames, ignore_index=True)
            # 去重：同一 index_code + con_code + in_date
            merged = merged.drop_duplicates(subset=["index_code", "con_code", "in_date"], keep="last")
            merged.to_parquet(member_dir / f"baostock_{idx_code}.parquet", index=False)
            all_frames.append(merged)
            logger.info(f"    {idx_name}: {len(merged)} 条")

    bs.logout()

    # 合并到 index_member.parquet
    if all_frames:
        new_data = pd.concat(all_frames, ignore_index=True)
        existing_path = member_dir / "index_member.parquet"
        if existing_path.exists():
            existing = pd.read_parquet(existing_path)
            # 去掉已有的 baostock 数据（同 index_code）
            existing_idx_codes = set(new_data["index_code"].unique())
            existing = existing[~existing["index_code"].isin(existing_idx_codes)]
            merged_all = pd.concat([existing, new_data], ignore_index=True)
        else:
            merged_all = new_data
        merged_all.to_parquet(existing_path, index=False)
        total = len(new_data)
        logger.info(f"宽基指数成分股完成: {total} 条, 已合并到 index_member.parquet")
        return total

    return 0


# ═══════════════════════════════════════════════════════════════
# 任务 10: AkShare 宽基指数当前成分股（补充 Baostock 不支持的）
# ═══════════════════════════════════════════════════════════════

# AkShare 支持的宽基指数（Baostock 不支持历史查询的）
# CSI 系列用 index_stock_cons_csindex（数据准确，无重复）
# 非 CSI 系列用 index_stock_cons
AKSHARE_INDEXES = {
    "000852": {"name": "中证1000", "code": "000852.CSI", "source": "csindex"},
    "932000": {"name": "中证2000", "code": "932000.CSI", "source": "csindex"},
    "000510": {"name": "中证A500", "code": "000510.CSI", "source": "csindex"},
    "399303": {"name": "国证2000", "code": "399303.SZ",  "source": "cons"},
}


def download_index_member_akshare() -> int:
    """通过 AkShare 下载宽基指数当前成分股（Baostock 不支持的）

    CSI 系列指数使用 index_stock_cons_csindex（数据准确，无重复），
    非 CSI 系列使用 index_stock_cons。
    """
    logger.info("=" * 50)
    logger.info("AkShare 宽基指数当前成分股")

    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare 未安装，请运行: pip install akshare")
        return 0

    member_dir = settings.DATA_DIR / "index_member"
    _ensure_dir(member_dir)
    total = 0

    for idx_symbol, idx_info in AKSHARE_INDEXES.items():
        idx_code = idx_info["code"]
        idx_name = idx_info["name"]
        source = idx_info.get("source", "csindex")

        try:
            logger.info(f"  {idx_name}({idx_symbol})...")

            if source == "csindex":
                df = ak.index_stock_cons_csindex(symbol=idx_symbol)
                code_col = "成分券代码"
            else:
                df = ak.index_stock_cons(symbol=idx_symbol)
                # 去重：同一股票可能有多条纳入记录，取最新
                df = df.sort_values("纳入日期", ascending=False).drop_duplicates(
                    subset=["品种代码"], keep="first"
                )
                code_col = "品种代码"

            if df.empty:
                logger.warning(f"    {idx_name} 返回空数据")
                continue

            # 转换格式
            today = datetime.now().strftime("%Y%m%d")
            result = pd.DataFrame({
                "index_code": idx_code,
                "con_code": df[code_col].apply(lambda x: _akshare_code_to_ts(str(x))),
                "in_date": today,
                "out_date": None,
                "is_new": "Y",
            })

            # 保存
            output_path = member_dir / f"akshare_{idx_symbol}.parquet"
            result.to_parquet(output_path, index=False)

            # 合并到 index_member.parquet
            existing_path = member_dir / "index_member.parquet"
            if existing_path.exists():
                existing = pd.read_parquet(existing_path)
                existing = existing[existing["index_code"] != idx_code]
                merged = pd.concat([existing, result], ignore_index=True)
            else:
                merged = result
            merged.to_parquet(existing_path, index=False)

            total += len(result)
            logger.info(f"    {idx_name}: {len(result)} 只")
        except Exception as e:
            logger.warning(f"    {idx_name} 失败: {e}")

    logger.info(f"AkShare 宽基指数完成, 累计 {total} 条")
    return total


def _akshare_code_to_ts(code: str) -> str:
    """AkShare 代码转 Tushare 格式: 600000 → 600000.SH"""
    code = code.strip()
    if code.startswith("6"):
        return f"{code}.SH"
    elif code.startswith("0") or code.startswith("3"):
        return f"{code}.SZ"
    elif code.startswith("8") or code.startswith("4"):
        return f"{code}.BJ"
    return code


# ═══════════════════════════════════════════════════════════════
# 任务 11: Baostock 业绩快报
# ═══════════════════════════════════════════════════════════════

def download_performance_express(start_date: str = "20150101") -> int:
    """通过 Baostock 下载业绩快报（比正式财报早1-2个月）

    业绩快报包含: 营收、净利润、扣非净利润、EPS、ROE 等。
    公告日期(pubDate)用于避免前视偏差。
    """
    logger.info("=" * 50)
    logger.info(f"Baostock 业绩快报: {start_date} ~ 今")

    try:
        import baostock as bs
    except ImportError:
        logger.error("baostock 未安装")
        return 0

    lg = bs.login()
    if lg.error_code != "0":
        logger.error(f"Baostock 登录失败: {lg.error_msg}")
        return 0

    out_dir = settings.DATA_DIR / "financial"
    _ensure_dir(out_dir)

    # 获取全市场股票列表
    rs = bs.query_all_stock(day="")
    stock_list = rs.get_data()
    if stock_list.empty:
        logger.error("获取股票列表失败")
        bs.logout()
        return 0

    stocks = stock_list[stock_list["type"] == "1"]  # 只要股票，不要指数
    stock_codes = stocks["code"].tolist()
    logger.info(f"  全市场 {len(stock_codes)} 只股票")

    # 断点续传
    checkpoint = _load_checkpoint("bs_express") or {"done_codes": []}
    done_set = set(checkpoint["done_codes"])
    remaining = [c for c in stock_codes if c not in done_set]

    if not remaining:
        logger.info("业绩快报已全部下载，跳过")
        bs.logout()
        return 0

    logger.info(f"  已完成 {len(done_set)}, 剩余 {len(remaining)}")

    frames = []
    # 加载已有数据
    existing_path = out_dir / "performance_express.parquet"
    if existing_path.exists():
        try:
            frames.append(pd.read_parquet(existing_path))
        except Exception:
            pass

    for i, code in enumerate(remaining, 1):
        try:
            rs = bs.query_performance_express_report(
                code, start_date=start_date, end_date=datetime.now().strftime("%Y-%m-%d")
            )
            df = rs.get_data()
            if not df.empty:
                df["ts_code"] = _baostock_code_to_ts(code)
                frames.append(df)

            done_set.add(code)

            if i % 200 == 0 or i == len(remaining):
                if frames:
                    merged = pd.concat(frames, ignore_index=True).drop_duplicates()
                    merged.to_parquet(existing_path, index=False)
                _save_checkpoint("bs_express", {"done_codes": list(done_set)})
                logger.info(f"  进度: {i}/{len(remaining)}")
        except Exception as e:
            logger.warning(f"  {code} 失败: {e}")
            done_set.add(code)

    bs.logout()

    if frames:
        merged = pd.concat(frames, ignore_index=True).drop_duplicates()
        merged.to_parquet(existing_path, index=False)
        _save_checkpoint("bs_express", {"done_codes": list(done_set)})
        logger.info(f"业绩快报完成: {len(merged)} 条")
        return len(merged)
    return 0


# ═══════════════════════════════════════════════════════════════
# 任务 12: Baostock 业绩预告
# ═══════════════════════════════════════════════════════════════

def download_forecast(start_date: str = "20150101") -> int:
    """通过 Baostock 下载业绩预告（比业绩快报更早）

    业绩预告包含: 预告类型(预增/预减/扭亏/续亏等)、变动幅度上下限。
    可用于事件驱动策略（业绩超预期）。
    """
    logger.info("=" * 50)
    logger.info(f"Baostock 业绩预告: {start_date} ~ 今")

    try:
        import baostock as bs
    except ImportError:
        logger.error("baostock 未安装")
        return 0

    lg = bs.login()
    if lg.error_code != "0":
        logger.error(f"Baostock 登录失败: {lg.error_msg}")
        return 0

    out_dir = settings.DATA_DIR / "financial"
    _ensure_dir(out_dir)

    rs = bs.query_all_stock(day="")
    stock_list = rs.get_data()
    if stock_list.empty:
        logger.error("获取股票列表失败")
        bs.logout()
        return 0

    stocks = stock_list[stock_list["type"] == "1"]
    stock_codes = stocks["code"].tolist()
    logger.info(f"  全市场 {len(stock_codes)} 只股票")

    checkpoint = _load_checkpoint("bs_forecast") or {"done_codes": []}
    done_set = set(checkpoint["done_codes"])
    remaining = [c for c in stock_codes if c not in done_set]

    if not remaining:
        logger.info("业绩预告已全部下载，跳过")
        bs.logout()
        return 0

    logger.info(f"  已完成 {len(done_set)}, 剩余 {len(remaining)}")

    frames = []
    existing_path = out_dir / "forecast.parquet"
    if existing_path.exists():
        try:
            frames.append(pd.read_parquet(existing_path))
        except Exception:
            pass

    for i, code in enumerate(remaining, 1):
        try:
            rs = bs.query_forecast_report(
                code, start_date=start_date, end_date=datetime.now().strftime("%Y-%m-%d")
            )
            df = rs.get_data()
            if not df.empty:
                df["ts_code"] = _baostock_code_to_ts(code)
                frames.append(df)

            done_set.add(code)

            if i % 200 == 0 or i == len(remaining):
                if frames:
                    merged = pd.concat(frames, ignore_index=True).drop_duplicates()
                    merged.to_parquet(existing_path, index=False)
                _save_checkpoint("bs_forecast", {"done_codes": list(done_set)})
                logger.info(f"  进度: {i}/{len(remaining)}")
        except Exception as e:
            logger.warning(f"  {code} 失败: {e}")
            done_set.add(code)

    bs.logout()

    if frames:
        merged = pd.concat(frames, ignore_index=True).drop_duplicates()
        merged.to_parquet(existing_path, index=False)
        _save_checkpoint("bs_forecast", {"done_codes": list(done_set)})
        logger.info(f"业绩预告完成: {len(merged)} 条")
        return len(merged)
    return 0


# ═══════════════════════════════════════════════════════════════
# 任务 13: Baostock 分红送转
# ═══════════════════════════════════════════════════════════════

def download_dividend(start_year: int = 2015) -> int:
    """通过 Baostock 下载分红送转数据

    包含: 每股派息(税前/税后)、每股送股、每股转增、
    除权登记日/除权日/派息日等关键日期。
    可用于高股息策略或除权套利。

    注意: Baostock 分红接口必须传具体股票代码，需遍历全市场。
    """
    logger.info("=" * 50)
    logger.info(f"Baostock 分红送转: {start_year} ~ 今")

    try:
        import baostock as bs
    except ImportError:
        logger.error("baostock 未安装")
        return 0

    lg = bs.login()
    if lg.error_code != "0":
        logger.error(f"Baostock 登录失败: {lg.error_msg}")
        return 0

    out_dir = settings.DATA_DIR / "financial"
    _ensure_dir(out_dir)

    # 获取全市场股票列表
    rs = bs.query_all_stock(day="")
    stock_list = rs.get_data()
    if stock_list.empty:
        logger.error("获取股票列表失败")
        bs.logout()
        return 0

    stocks = stock_list[stock_list["type"] == "1"]
    stock_codes = stocks["code"].tolist()
    logger.info(f"  全市场 {len(stock_codes)} 只股票")

    checkpoint = _load_checkpoint("bs_dividend") or {"done_codes": []}
    done_set = set(checkpoint["done_codes"])
    remaining = [c for c in stock_codes if c not in done_set]

    if not remaining:
        logger.info("分红送转已全部下载，跳过")
        bs.logout()
        return 0

    logger.info(f"  已完成 {len(done_set)}, 剩余 {len(remaining)}")

    frames = []
    existing_path = out_dir / "dividend.parquet"
    if existing_path.exists():
        try:
            frames.append(pd.read_parquet(existing_path))
        except Exception:
            pass

    end_year = datetime.now().year
    for i, code in enumerate(remaining, 1):
        try:
            for year in range(start_year, end_year + 1):
                rs = bs.query_dividend_data(code=code, year=str(year), yearType="report")
                df = rs.get_data()
                if not df.empty:
                    df["query_year"] = year
                    frames.append(df)

            done_set.add(code)

            if i % 200 == 0 or i == len(remaining):
                if frames:
                    merged = pd.concat(frames, ignore_index=True).drop_duplicates()
                    merged.to_parquet(existing_path, index=False)
                _save_checkpoint("bs_dividend", {"done_codes": list(done_set)})
                logger.info(f"  进度: {i}/{len(remaining)}")
        except Exception as e:
            logger.warning(f"  {code} 失败: {e}")
            done_set.add(code)

    bs.logout()

    if frames:
        merged = pd.concat(frames, ignore_index=True).drop_duplicates()
        merged.to_parquet(existing_path, index=False)
        _save_checkpoint("bs_dividend", {"done_codes": list(done_set)})
        logger.info(f"分红送转完成: {len(merged)} 条")
        return len(merged)
    return 0


# ═══════════════════════════════════════════════════════════════
# 任务 14: Tushare 股东人数
# ═══════════════════════════════════════════════════════════════

def download_holder_number(pro, start_date: str = "20140101") -> int:
    """通过 Tushare 下载股东人数变化数据

    股东人数骤减 → 筹码集中 → 主力建仓信号。
    股东人数骤增 → 筹码分散 → 散户接盘信号。
    可用于筹码集中度策略。
    """
    logger.info("=" * 50)
    logger.info(f"股东人数: {start_date} ~ 今")

    out_dir = settings.HOLDER_NUMBER_DIR
    _ensure_dir(out_dir)

    # 获取全市场股票列表
    try:
        stock_df = _fetch(pro, pro.stock_basic, exchange="", list_status="L",
                          fields="ts_code")
        stock_codes = stock_df["ts_code"].tolist()
        logger.info(f"  全市场 {len(stock_codes)} 只股票")
    except Exception as e:
        logger.error(f"  获取股票列表失败: {e}")
        return 0

    # 断点续传
    checkpoint = _load_checkpoint("holder_number") or {"done_codes": []}
    done_set = set(checkpoint["done_codes"])
    remaining = [c for c in stock_codes if c not in done_set]

    if not remaining:
        logger.info("股东人数已全部下载，跳过")
        return 0

    logger.info(f"  已完成 {len(done_set)}, 剩余 {len(remaining)}")

    frames = []
    existing_path = out_dir / "holder_number.parquet"
    if existing_path.exists():
        try:
            frames.append(pd.read_parquet(existing_path))
        except Exception:
            pass

    for i, ts_code in enumerate(remaining, 1):
        try:
            df = _fetch(pro, pro.stk_holdernumber, ts_code=ts_code,
                        fields="ts_code,end_date,ann_date,holder_num,holder_num_chg,hold_num_per")
            if not df.empty:
                frames.append(df)

            done_set.add(ts_code)

            if i % 200 == 0 or i == len(remaining):
                if frames:
                    merged = pd.concat(frames, ignore_index=True).drop_duplicates(
                        subset=["ts_code", "end_date"], keep="last"
                    )
                    merged.to_parquet(existing_path, index=False)
                _save_checkpoint("holder_number", {"done_codes": list(done_set)})
                logger.info(f"  进度: {i}/{len(remaining)}")
        except Exception as e:
            logger.warning(f"  {ts_code} 失败: {e}")
            done_set.add(ts_code)

    if frames:
        merged = pd.concat(frames, ignore_index=True).drop_duplicates(
            subset=["ts_code", "end_date"], keep="last"
        )
        merged.to_parquet(existing_path, index=False)
        _save_checkpoint("holder_number", {"done_codes": list(done_set)})
        logger.info(f"股东人数完成: {len(merged)} 条")
        return len(merged)
    return 0


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

TASKS = {
    "index_daily":       {"fn": None, "desc": "指数日线行情", "params": ["start_date"]},
    "instruments":       {"fn": None, "desc": "历史化股票列表", "params": []},
    "namechange":        {"fn": None, "desc": "股票名称变更历史", "params": []},
    "industry":          {"fn": None, "desc": "行业分类数据", "params": []},
    "fina":              {"fn": None, "desc": "财务报表数据", "params": ["start_date"]},
    "etf_daily":         {"fn": None, "desc": "ETF日线行情", "params": ["start_date"]},
    "adj_factor_fix":    {"fn": None, "desc": "修复复权因子日期", "params": []},
    "adj_factor_dl":     {"fn": None, "desc": "下载复权因子", "params": ["start_date"]},
    "index_member_bs":   {"fn": None, "desc": "Baostock宽基指数成分股(历史)", "params": ["start_date"]},
    "index_member_ak":   {"fn": None, "desc": "AkShare宽基指数成分股(当前)", "params": []},
    "bs_express":        {"fn": None, "desc": "Baostock业绩快报", "params": ["start_date"]},
    "bs_forecast":       {"fn": None, "desc": "Baostock业绩预告", "params": ["start_date"]},
    "bs_dividend":       {"fn": None, "desc": "Baostock分红送转", "params": []},
    "holder_number":     {"fn": None, "desc": "股东人数变化", "params": ["start_date"]},
}


def parse_args():
    parser = argparse.ArgumentParser(description="补充量化数据")
    parser.add_argument("--tasks", type=str, default="all",
                        help=f"任务列表: {', '.join(TASKS.keys())}, 或 all")
    parser.add_argument("--start", type=str, default="20140101",
                        help="开始日期 YYYYMMDD (默认: 20140101)")
    parser.add_argument("--end", type=str, default=datetime.now().strftime("%Y%m%d"),
                        help="结束日期 YYYYMMDD")
    return parser.parse_args()


def main():
    args = parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    logger.add(settings.LOG_DIR / "update_supplement.log",
               rotation="50 MB", encoding="utf-8")

    pro = create_pro()

    if args.tasks == "all":
        task_names = list(TASKS.keys())
    else:
        task_names = [t.strip() for t in args.tasks.split(",")]

    for name in task_names:
        if name not in TASKS:
            logger.error(f"未知任务: {name}, 可选: {', '.join(TASKS.keys())}")
            sys.exit(1)

    results = {}

    # 按依赖顺序执行
    ordered = ["instruments", "namechange", "index_daily", "industry", "fina", "etf_daily", "adj_factor_fix", "adj_factor_dl", "index_member_bs", "index_member_ak", "bs_express", "bs_forecast", "bs_dividend", "holder_number"]
    to_run = [n for n in ordered if n in task_names]

    for name in to_run:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"开始任务: {TASKS[name]['desc']}")
        logger.info(f"{'=' * 60}")
        try:
            if name == "index_daily":
                rows = update_index_daily(pro, start_date=args.start, end_date=args.end)
            elif name == "instruments":
                rows = update_instruments_historical(pro)
            elif name == "namechange":
                rows = update_namechange_full(pro)
            elif name == "industry":
                rows = update_industry(pro)
            elif name == "fina":
                rows = update_financial(pro, start_date=args.start)
            elif name == "etf_daily":
                rows = update_etf_daily(pro, start_date=args.start)
            elif name == "adj_factor_fix":
                rows = fix_adj_factor_dates(pro)
            elif name == "adj_factor_dl":
                rows = download_adj_factor(pro, start_date=args.start)
            elif name == "index_member_bs":
                rows = download_index_member_baostock(start_date=args.start)
            elif name == "index_member_ak":
                rows = download_index_member_akshare()
            elif name == "bs_express":
                rows = download_performance_express(start_date=args.start)
            elif name == "bs_forecast":
                rows = download_forecast(start_date=args.start)
            elif name == "bs_dividend":
                rows = download_dividend(start_year=int(args.start[:4]))
            elif name == "holder_number":
                rows = download_holder_number(pro, start_date=args.start)
            else:
                rows = 0
            results[name] = {"status": "成功", "rows": rows}
        except Exception as e:
            logger.error(f"任务 {name} 失败: {e}")
            results[name] = {"status": "失败", "error": str(e)}

    # 汇总
    print(f"\n{'=' * 60}")
    print("补充数据更新汇总")
    print(f"{'=' * 60}")
    for name in to_run:
        result = results.get(name, {})
        desc = TASKS[name]["desc"]
        status = result.get("status", "未知")
        if status == "成功":
            print(f"  {desc}: ✅ {status}, {result.get('rows', 0)} 条")
        else:
            print(f"  {desc}: ❌ {status}, {result.get('error', '')}")


if __name__ == "__main__":
    main()
