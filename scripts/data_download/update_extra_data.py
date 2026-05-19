"""
补充量化原始数据下载脚本。

当前通过 Tushare 依次尝试补充：
- 全状态股票基础表：上市、退市、暂停上市
- 每日基础指标 daily_basic
- 每日涨跌停价格 stk_limit
- 停复牌明细 suspend_d
- 股票历史名称变更 namechange
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.data_loader import DataLoader
from config import settings
from scripts.data_source.data_source_tushare import TushareDataSource
from scripts.data_download.update_daily import DataUpdater


@dataclass
class UpdateResult:
    name: str
    success: bool
    rows: int = 0
    message: str = ""
    failed_dates: List[str] = field(default_factory=list)
    skipped_dates: int = 0
    empty_dates: int = 0


class ExtraDataUpdater:
    def __init__(self, delay: float = 0.35, max_retries: int = 3, token: str | None = None, force: bool = False):
        token = token or settings.TUSHARE_TOKEN or os.getenv("TUSHARE_TOKEN") or None
        self.source = TushareDataSource(token=token, delay=delay, max_retries=max_retries)
        self.pro = self.source.pro
        self.updater = DataUpdater()
        self.delay = delay
        self.max_retries = max_retries
        self.force = force

    def close(self):
        self.updater.close()

    def _fetch(self, func: Callable, **kwargs) -> pd.DataFrame:
        last_exc: Optional[Exception] = None
        for i in range(self.max_retries):
            try:
                time.sleep(self.delay)
                df = func(**kwargs)
                return df if df is not None else pd.DataFrame()
            except Exception as exc:
                last_exc = exc
                if i < self.max_retries - 1:
                    time.sleep(self.delay * (i + 2))
        raise RuntimeError(str(last_exc))

    def _get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        df = self._fetch(
            self.pro.trade_cal,
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
            is_open="1",
            fields="cal_date,is_open",
        )
        if df.empty:
            return []
        dates = df["cal_date"].astype(str).tolist()
        dates.sort()
        return dates

    @staticmethod
    def _format_date_col(df: pd.DataFrame, col: str):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")

    @staticmethod
    def _has_partition(base_dir: Path, date_col: str, trade_date: str) -> bool:
        date_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        return (base_dir / f"{date_col}={date_str}" / "part-000.parquet").exists()

    def update_stock_basic_all(self) -> UpdateResult:
        frames = []
        fields = (
            "ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,"
            "exchange,curr_type,list_status,list_date,delist_date,is_hs"
        )
        try:
            for status in ["L", "D", "P"]:
                df = self._fetch(self.pro.stock_basic, exchange="", list_status=status, fields=fields)
                if df.empty:
                    continue
                df["status"] = status
                frames.append(df)

            if not frames:
                return UpdateResult("stock_basic_all", False, message="接口返回空数据")

            result = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code", keep="first")
            result["stock_code"] = result["symbol"]
            result["symbol"] = result["name"]
            result["exchange"] = result["ts_code"].str.split(".").str[-1]
            for col in ["list_date", "delist_date"]:
                result[col] = result[col].apply(
                    lambda x: f"{str(x)[:4]}-{str(x)[4:6]}-{str(x)[6:8]}"
                    if pd.notna(x) and len(str(x)) == 8
                    else None
                )
            self.updater.update_instruments(result)
            return UpdateResult("stock_basic_all", True, rows=len(result))
        except Exception as exc:
            return UpdateResult("stock_basic_all", False, message=str(exc))

    def update_namechange(self) -> UpdateResult:
        try:
            df = self._fetch(
                self.pro.namechange,
                ts_code="",
                fields="ts_code,name,start_date,end_date,ann_date,change_reason",
            )
            if df.empty:
                return UpdateResult("namechange", False, message="接口返回空数据")
            for col in ["start_date", "end_date", "ann_date"]:
                self._format_date_col(df, col)
            self.updater.update_namechange(df)
            return UpdateResult("namechange", True, rows=len(df))
        except Exception as exc:
            return UpdateResult("namechange", False, message=str(exc))

    def _update_by_trade_date(
        self,
        name: str,
        dates: List[str],
        fetcher: Callable[[str], pd.DataFrame],
        writer: Callable[[pd.DataFrame], None],
        output_dir: Path,
        date_col: str = "trade_date",
    ) -> UpdateResult:
        total_rows = 0
        failed_dates: List[str] = []
        skipped_dates = 0
        empty_dates = 0
        for idx, trade_date in enumerate(dates, start=1):
            if not self.force and self._has_partition(output_dir, date_col, trade_date):
                skipped_dates += 1
                logger.info("[{}/{}] {} {} 跳过: 分区已存在", idx, len(dates), name, trade_date)
                continue
            try:
                df = fetcher(trade_date)
                if df.empty:
                    logger.warning("[{}/{}] {} {} 返回空数据", idx, len(dates), name, trade_date)
                    empty_dates += 1
                    continue
                writer(df)
                total_rows += len(df)
                logger.info("[{}/{}] {} {} 成功: {} 条", idx, len(dates), name, trade_date, len(df))
            except Exception as exc:
                logger.warning("[{}/{}] {} {} 失败: {}", idx, len(dates), name, trade_date, exc)
                failed_dates.append(trade_date)
        return UpdateResult(
            name,
            total_rows > 0,
            rows=total_rows,
            failed_dates=failed_dates,
            skipped_dates=skipped_dates,
            empty_dates=empty_dates,
            message="" if total_rows > 0 else "没有成功写入任何日期",
        )

    def update_daily_basic(self, dates: List[str]) -> UpdateResult:
        fields = (
            "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
            "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,"
            "free_share,total_mv,circ_mv"
        )

        def fetcher(trade_date: str) -> pd.DataFrame:
            df = self._fetch(self.pro.daily_basic, trade_date=trade_date, fields=fields)
            self._format_date_col(df, "trade_date")
            return df

        return self._update_by_trade_date(
            "daily_basic", dates, fetcher, self.updater.update_daily_basic, settings.DAILY_BASIC_DIR
        )

    def update_stk_limit(self, dates: List[str]) -> UpdateResult:
        def fetcher(trade_date: str) -> pd.DataFrame:
            df = self._fetch(
                self.pro.stk_limit,
                trade_date=trade_date,
                fields="ts_code,trade_date,pre_close,up_limit,down_limit",
            )
            self._format_date_col(df, "trade_date")
            return df

        return self._update_by_trade_date(
            "stk_limit", dates, fetcher, self.updater.update_stk_limit, settings.STK_LIMIT_DIR
        )

    def update_suspend_d(self, dates: List[str]) -> UpdateResult:
        def fetcher(trade_date: str) -> pd.DataFrame:
            df = self._fetch(
                self.pro.suspend_d,
                trade_date=trade_date,
                fields="ts_code,trade_date,suspend_timing,suspend_type",
            )
            self._format_date_col(df, "trade_date")
            return df

        return self._update_by_trade_date(
            "suspend_d", dates, fetcher, self.updater.update_suspend_d, settings.SUSPEND_D_DIR
        )

    def run(self, start_date: str, end_date: str, tasks: List[str]) -> List[UpdateResult]:
        results: List[UpdateResult] = []
        task_set = set(tasks)

        if "stock_basic" in task_set:
            results.append(self.update_stock_basic_all())
        if "namechange" in task_set:
            results.append(self.update_namechange())

        date_tasks = {"daily_basic", "stk_limit", "suspend_d"} & task_set
        dates: List[str] = []
        if date_tasks:
            try:
                dates = self._get_trade_dates(start_date, end_date)
            except Exception as exc:
                for name in sorted(date_tasks):
                    results.append(UpdateResult(name, False, message=f"交易日历获取失败: {exc}"))
                return results
            if not dates:
                for name in sorted(date_tasks):
                    results.append(UpdateResult(name, False, message="未获取到交易日历"))
                return results

        if "daily_basic" in task_set:
            results.append(self.update_daily_basic(dates))
        if "stk_limit" in task_set:
            results.append(self.update_stk_limit(dates))
        if "suspend_d" in task_set:
            results.append(self.update_suspend_d(dates))

        return results


def infer_default_start() -> str:
    loader = DataLoader()
    try:
        max_date = loader.conn.execute("select max(trade_date) from daily_bar").fetchone()[0]
        if max_date is None:
            return "20140102"
        return (pd.to_datetime(max_date) + timedelta(days=1)).strftime("%Y%m%d")
    finally:
        loader.close()


def print_summary(results: List[UpdateResult]):
    print("\n========== 补充数据更新结果 ==========")
    for result in results:
        status = "成功" if result.success else "失败"
        fail_note = f", 失败日期 {len(result.failed_dates)} 个" if result.failed_dates else ""
        msg = f", 原因: {result.message}" if result.message else ""
        print(f"{result.name}: {status}, 写入 {result.rows} 条{fail_note}{msg}")
        if result.failed_dates:
            print(f"  失败日期样例: {', '.join(result.failed_dates[:10])}")


def main():
    parser = argparse.ArgumentParser(description="补充量化原始数据")
    parser.add_argument("--start", type=str, default="", help="开始日期 YYYYMMDD，默认从本地日线最新日后一日开始")
    parser.add_argument("--end", type=str, default=datetime.now().strftime("%Y%m%d"), help="结束日期 YYYYMMDD")
    parser.add_argument("--delay", type=float, default=0.35, help="接口请求间隔秒数")
    parser.add_argument("--token", type=str, default="", help="Tushare token；也可通过环境变量 TUSHARE_TOKEN 提供")
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=["stock_basic", "namechange", "daily_basic", "stk_limit", "suspend_d"],
        choices=["stock_basic", "namechange", "daily_basic", "stk_limit", "suspend_d"],
        help="要更新的数据项",
    )
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")
    logger.add(settings.LOG_DIR / "update_extra_data.log", rotation="50 MB", encoding="utf-8")

    start_date = args.start or infer_default_start()
    updater = ExtraDataUpdater(delay=args.delay, token=args.token or None)
    try:
        results = updater.run(start_date=start_date, end_date=args.end, tasks=args.tasks)
        print_summary(results)
    finally:
        updater.close()


if __name__ == "__main__":
    main()
