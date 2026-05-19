"""
指数 / 概念板块 / ETF 数据补充下载脚本

从 Tushare 补充指数成分股、概念板块、指数日线、基金基本资料等数据，
存储为 parquet 格式，供回测系统使用。

用法：
    python scripts/update_index_data.py --tasks all
    python scripts/update_index_data.py --tasks concept,fund_basic
    python scripts/update_index_data.py --tasks index_member --max-stocks 200
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings


# ═══════════════════════════════════════════════════════════════
# Tushare 连接配置
# ═══════════════════════════════════════════════════════════════

API_DELAY = 1.5  # 每次 API 调用间隔秒数


def create_pro():
    """创建 Tushare pro 连接"""
    if not settings.TUSHARE_TOKEN:
        raise ValueError("缺少 TUSHARE_TOKEN，请在项目根目录 .env 中配置。")
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    import tushare as ts
    from tushare.pro.client import DataApi

    if settings.TUSHARE_BASE_URL:
        DataApi._DataApi__http_url = settings.TUSHARE_BASE_URL
    return ts.pro_api(settings.TUSHARE_TOKEN)


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════


def _fetch(pro, func: Callable, **kwargs) -> pd.DataFrame:
    """带重试的 API 调用"""
    max_retries = 3
    last_exc: Optional[Exception] = None
    for i in range(max_retries):
        try:
            time.sleep(API_DELAY)
            df = func(**kwargs)
            if df is not None:
                return df
            return pd.DataFrame()
        except Exception as exc:
            last_exc = exc
            logger.warning(f"API 调用失败 ({i+1}/{max_retries}): {exc}")
            if i < max_retries - 1:
                time.sleep(API_DELAY * (i + 2))
    raise RuntimeError(str(last_exc))


def _ensure_dir(path: Path):
    """确保目录存在"""
    path.mkdir(parents=True, exist_ok=True)


def _save_checkpoint(name: str, data):
    """保存断点数据"""
    cp_path = settings.DATA_DIR / "index_data_checkpoint" / f"{name}.json"
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    cp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _load_checkpoint(name: str):
    """读取断点数据"""
    cp_path = settings.DATA_DIR / "index_data_checkpoint" / f"{name}.json"
    if cp_path.exists():
        return json.loads(cp_path.read_text())
    return None


# ═══════════════════════════════════════════════════════════════
# 任务 1：概念板块列表 + 成分股
# ═══════════════════════════════════════════════════════════════


def update_concept(pro) -> int:
    """更新概念板块列表 + 成分股，返回写入总行数"""
    total = 0

    # 1.1 概念板块列表
    logger.info("=" * 50)
    logger.info("开始更新概念板块列表")
    concept_dir = settings.CONCEPT_DIR
    _ensure_dir(concept_dir)

    df_list = _fetch(pro, pro.concept)
    if df_list.empty:
        logger.warning("概念板块列表为空，跳过")
        return total

    df_list.to_parquet(concept_dir / "concept.parquet", index=False)
    total += len(df_list)
    logger.info(f"概念板块列表: {len(df_list)} 条")

    # 1.2 概念板块成分股（断点续传）
    logger.info("开始更新概念板块成分股")
    member_path = concept_dir / "concept_member.parquet"
    checkpoint = _load_checkpoint("concept_member") or {"done_codes": [], "rows": []}

    done_set = set(checkpoint["done_codes"])
    all_codes = df_list["code"].tolist()
    remaining = [c for c in all_codes if c not in done_set]

    if remaining:
        logger.info(f"概念板块成分股: 共 {len(all_codes)} 个, 已完成 {len(done_set)}, 剩余 {len(remaining)}")
        new_rows = []
        for i, code in enumerate(remaining, 1):
            try:
                df = _fetch(pro, pro.concept_detail, id=code)
                if not df.empty:
                    new_rows.append(df)
            except Exception as e:
                logger.warning(f"概念 {code} 成分股获取失败: {e}")

            done_set.add(code)
            if i % 50 == 0 or i == len(remaining):
                _save_checkpoint("concept_member", {"done_codes": list(done_set)})
                logger.info(f"概念板块成分股进度: {len(done_set)}/{len(all_codes)}")

        if new_rows:
            all_rows = pd.concat(new_rows, ignore_index=True)
            # 合并已有数据
            if member_path.exists():
                existing = pd.read_parquet(member_path)
                # 去重
                existing["_dup"] = existing["id"] + "|" + existing["ts_code"]
                all_rows["_dup"] = all_rows["id"] + "|" + all_rows["ts_code"]
                merged = pd.concat([existing, all_rows], ignore_index=True)
                merged = merged.drop_duplicates(subset="_dup", keep="last")
                merged = merged.drop(columns=["_dup"])
                merged.to_parquet(member_path, index=False)
                total += len(merged) - len(existing)
            else:
                all_rows = all_rows.drop(columns=["_dup"], errors="ignore")
                all_rows.to_parquet(member_path, index=False)
                total += len(all_rows)

        _save_checkpoint("concept_member", {"done_codes": list(done_set)})
        logger.info(f"概念板块成分股完成: 累计 {total} 条")
    else:
        logger.info("概念板块成分股已全部更新，跳过")

    return total


# ═══════════════════════════════════════════════════════════════
# 任务 2：指数成分股（按股票遍历）
# ═══════════════════════════════════════════════════════════════


def update_index_member(pro, max_stocks: Optional[int] = None) -> int:
    """更新指数成分股数据（遍历股票方式）

    因为 index_member(index_code=...) 在此代理上返回空，
    改为遍历每只股票查询其所属指数（index_member(ts_code=...)），
    反向构建 指数→成分股 映射。
    """
    logger.info("=" * 50)
    logger.info("开始更新指数成分股（按股票遍历）")

    member_dir = settings.INDEX_MEMBER_DIR
    _ensure_dir(member_dir)
    member_path = member_dir / "index_member.parquet"

    # 获取全市场上市股票
    df_stocks = _fetch(pro, pro.stock_basic, exchange="", list_status="L",
                       fields="ts_code,symbol,name,market,list_date")
    if df_stocks.empty:
        logger.warning("股票列表为空，跳过")
        return 0

    # 只保留 A 股主板/创业板/科创板（排除北交所等非主流）
    # SH/SZ 交易所的股票
    stock_codes = df_stocks["ts_code"].tolist()
    logger.info(f"全市场活跃 A 股: {len(stock_codes)} 只")

    if max_stocks and max_stocks < len(stock_codes):
        stock_codes = stock_codes[:max_stocks]
        logger.info(f"省略模式: 只处理前 {max_stocks} 只")

    # 断点续传
    checkpoint = _load_checkpoint("index_member") or {"done_codes": [], "total_rows": 0}
    done_set = set(checkpoint["done_codes"])
    remaining = [c for c in stock_codes if c not in done_set]

    if not remaining:
        logger.info("指数成分股已全部更新，跳过")
        return checkpoint.get("total_rows", 0)

    logger.info(f"已完成 {len(done_set)} 只, 剩余 {len(remaining)} 只")
    batch_rows: List[pd.DataFrame] = []
    batch_size = 100  # 每多少只保存一次

    for i, code in enumerate(remaining, 1):
        try:
            df = _fetch(pro, pro.index_member, ts_code=code, list_status="L")
            if not df.empty:
                batch_rows.append(df)
        except Exception as e:
            logger.warning(f"股票 {code} 指数成分查询失败: {e}")

        done_set.add(code)

        # 批量保存
        if i % batch_size == 0 or i == len(remaining):
            if batch_rows:
                new_df = pd.concat(batch_rows, ignore_index=True)
                # 合并到主文件
                if member_path.exists():
                    existing = pd.read_parquet(member_path)
                    # 去重 (index_code + con_code + in_date)
                    existing["_k"] = existing["index_code"] + "|" + existing["con_code"] + "|" + existing.get("in_date", "").astype(str)
                    new_df["_k"] = new_df["index_code"] + "|" + new_df["con_code"] + "|" + new_df.get("in_date", "").astype(str)
                    merged = pd.concat([existing, new_df], ignore_index=True)
                    merged = merged.drop_duplicates(subset="_k", keep="last")
                    merged = merged.drop(columns=["_k"])
                else:
                    merged = new_df
                merged.to_parquet(member_path, index=False)
                total_rows = len(merged)
                batch_rows = []
                logger.info(f"进度: {len(done_set)}/{len(stock_codes)}, 累计 {total_rows} 条记录")
            else:
                total_rows = checkpoint.get("total_rows", 0)

            _save_checkpoint("index_member", {
                "done_codes": list(done_set),
                "total_rows": total_rows,
            })

    logger.info(f"指数成分股更新完成, 累计 {_load_checkpoint('index_member').get('total_rows', 0)} 条")
    return _load_checkpoint("index_member").get("total_rows", 0)


# ═══════════════════════════════════════════════════════════════
# 任务 3：指数日线行情（关键指数）
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
    """更新关键指数的日线行情"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    logger.info("=" * 50)
    logger.info(f"开始更新指数日线: {start_date} ~ {end_date}")

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

            # 按年份分区存储
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df["year"] = df["trade_date"].dt.year
            for year, group in df.groupby("year"):
                year_dir = idx_dir / f"ts_code={idx_code}" / f"year={year}"
                _ensure_dir(year_dir)
                out_path = year_dir / "part-000.parquet"
                group.to_parquet(out_path, index=False)
            total += len(df)
            logger.info(f"{idx_code}: {len(df)} 条")
        except Exception as e:
            logger.warning(f"{idx_code} 获取失败: {e}")

    logger.info(f"指数日线更新完成, 累计 {total} 条")
    return total


# ═══════════════════════════════════════════════════════════════
# 任务 4：基金/ETF 基本资料
# ═══════════════════════════════════════════════════════════════


def update_fund_basic(pro) -> int:
    """更新基金基本资料"""
    logger.info("=" * 50)
    logger.info("开始更新基金基本资料")

    fund_dir = settings.FUND_BASIC_DIR
    _ensure_dir(fund_dir)
    fund_path = fund_dir / "fund_basic.parquet"

    try:
        # 先尝试获取全部基金
        df = _fetch(pro, pro.fund_basic, market="E",
                    fields="ts_code,name,管理人,托管人,成立日,maturity_date,delist_date,benchmark,issue_amount")
        if df.empty:
            # 不带 market 参数再试
            df = _fetch(pro, pro.fund_basic,
                        fields="ts_code,name,管理人,托管人,成立日,maturity_date,delist_date,benchmark,issue_amount")
        if df.empty:
            logger.warning("基金数据为空")
            return 0

        df.to_parquet(fund_path, index=False)
        logger.info(f"基金基本资料: {len(df)} 条")
        return len(df)
    except Exception as e:
        logger.warning(f"基金数据获取失败: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════


TASKS = {
    "concept": {"fn": update_concept, "desc": "概念板块"},
    "index_member": {"fn": update_index_member, "desc": "指数成分股"},
    "index_daily": {"fn": update_index_daily, "desc": "指数日线行情"},
    "fund_basic": {"fn": update_fund_basic, "desc": "基金基本资料"},
}


def parse_args():
    parser = argparse.ArgumentParser(description="指数/板块/ETF 数据补充下载")
    parser.add_argument(
        "--tasks",
        type=str,
        default="all",
        help=f"任务列表: {', '.join(TASKS.keys())}, 或 all (默认: all)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default="20100101",
        help="开始日期 YYYYMMDD (仅 index_daily 使用)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=datetime.now().strftime("%Y%m%d"),
        help="结束日期 YYYYMMDD",
    )
    parser.add_argument(
        "--max-stocks",
        type=int,
        default=None,
        help="最多处理多少只股票 (仅 index_member 使用，调试用)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    logger.add(settings.LOG_DIR / "update_index_data.log",
               rotation="50 MB", encoding="utf-8")

    pro = create_pro()

    # 解析任务
    if args.tasks == "all":
        task_names = list(TASKS.keys())
    else:
        task_names = [t.strip() for t in args.tasks.split(",")]

    # 验证任务名
    for name in task_names:
        if name not in TASKS:
            logger.error(f"未知任务: {name}, 可选: {', '.join(TASKS.keys())}")
            sys.exit(1)

    # 按依赖顺序执行
    ordered = ["concept", "fund_basic", "index_member", "index_daily"]
    to_run = [n for n in ordered if n in task_names]

    results = {}
    for name in to_run:
        info = TASKS[name]
        logger.info(f"\n{'=' * 60}")
        logger.info(f"开始任务: {info['desc']}")
        logger.info(f"{'=' * 60}")
        try:
            if name == "index_member":
                rows = info["fn"](pro, max_stocks=args.max_stocks)
            elif name == "index_daily":
                rows = info["fn"](pro, start_date=args.start, end_date=args.end)
            else:
                rows = info["fn"](pro)
            results[name] = {"status": "成功", "rows": rows}
        except Exception as e:
            logger.error(f"任务 {name} 失败: {e}")
            results[name] = {"status": "失败", "error": str(e)}

    # 汇总
    print(f"\n{'=' * 60}")
    print("数据更新汇总")
    print(f"{'=' * 60}")
    for name, result in results.items():
        desc = TASKS[name]["desc"]
        status = result["status"]
        if status == "成功":
            print(f"  {desc}: ✅ {status}, {result['rows']} 条")
        else:
            print(f"  {desc}: ❌ {status}, {result.get('error', '')}")


if __name__ == "__main__":
    main()
