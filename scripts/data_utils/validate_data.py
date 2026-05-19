"""
数据校验模块：确保数据质量

校验规则：
1. 主键唯一性 (ts_code, trade_date)
2. OHLC 合法性
3. 成交字段合法性
4. 交易日完整性（基于交易日历，非 weekday）
5. 复权因子完整性
6. daily_basic 字段完整性
7. stk_limit 字段完整性
8. instruments 文件存在性

所有结果可 JSON 序列化，不依赖 meta DuckDB。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Configuration holder — tests can override these paths
# ---------------------------------------------------------------------------

class _Settings:
    """Minimal settings container; mirrors config.settings field names."""

    def __init__(self, data_dir: Path | None = None):
        root = data_dir or Path(__file__).resolve().parent.parent / "data"
        self.DATA_DIR = root
        self.DAILY_BAR_DIR = root / "daily_bar"
        self.DAILY_BASIC_DIR = root / "daily_basic"
        self.ADJ_FACTOR_DIR = root / "adj_factor"
        self.STK_LIMIT_DIR = root / "stk_limit"
        self.CALENDAR_DIR = root / "calendar"
        self.INSTRUMENTS_DIR = root / "instruments"


def _resolve_settings() -> _Settings:
    """Return project settings; tests inject via patching."""
    try:
        import config as _cfg
        return _Settings(data_dir=_cfg.settings.DATA_DIR)
    except Exception:
        return _Settings()


# ---------------------------------------------------------------------------
# Result dataclass — fully JSON-serializable
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Single check outcome."""
    dataset: str
    check_name: str
    passed: bool
    details: str
    trade_date: str  # ISO date string or ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------

class DataValidator:
    """Validate data quality using the trading calendar."""

    def __init__(self, settings: _Settings | None = None):
        self.s = settings or _resolve_settings()

    # ---- helpers -----------------------------------------------------------

    def _read_parquet_safe(self, path: Path) -> pd.DataFrame | None:
        if not path.exists():
            return None
        try:
            return pd.read_parquet(path)
        except Exception as exc:
            logger.warning(f"读取失败 {path}: {exc}")
            return None

    def _load_calendar(self) -> pd.DataFrame | None:
        cal_path = self.s.CALENDAR_DIR / "calendar.parquet"
        cal = self._read_parquet_safe(cal_path)
        if cal is None:
            return None
        cal["trade_date"] = pd.to_datetime(cal["trade_date"]).dt.strftime("%Y-%m-%d")
        return cal

    def _trading_days(self, start: str, end: str) -> list[str]:
        """Return sorted list of trading dates in [start, end] from calendar."""
        cal = self._load_calendar()
        if cal is None:
            return []
        open_days = cal[cal["is_open"] == 1]["trade_date"]
        return sorted(d for d in open_days if start <= d <= end)

    def _partition_path(self, base_dir: Path, trade_date: str) -> Path:
        return base_dir / f"trade_date={trade_date}" / "part-000.parquet"

    def _read_partition(self, base_dir: Path, trade_date: str) -> pd.DataFrame | None:
        return self._read_parquet_safe(self._partition_path(base_dir, trade_date))

    # ---- per-dataset checks -----------------------------------------------

    def check_daily_bar(self, trade_date: str) -> List[CheckResult]:
        """Check daily_bar: exists, pk unique, OHLC valid, volume/amount valid."""
        results: List[CheckResult] = []
        ds = "daily_bar"
        df = self._read_partition(self.s.DAILY_BAR_DIR, trade_date)
        if df is None:
            results.append(CheckResult(ds, "数据存在", False, f"{trade_date} 无 daily_bar 数据", trade_date))
            return results

        # PK uniqueness
        dups = df[df.duplicated(subset=["ts_code"], keep=False)]
        if len(dups) > 0:
            results.append(CheckResult(ds, "主键唯一性", False, f"{len(dups)} 条重复: {dups['ts_code'].head(5).tolist()}", trade_date))
        else:
            results.append(CheckResult(ds, "主键唯一性", True, f"{len(df)} 条记录", trade_date))

        # OHLC validity
        price_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
        if len(price_cols) == 4:
            bad_price = df[(df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)]
            bad_high = df[df["high"] < df[["open", "close", "low"]].max(axis=1)]
            bad_low = df[df["low"] > df[["open", "close", "high"]].min(axis=1)]
            issues = []
            if len(bad_price) > 0:
                issues.append(f"非正价格 {len(bad_price)} 条")
            if len(bad_high) > 0:
                issues.append(f"high 异常 {len(bad_high)} 条")
            if len(bad_low) > 0:
                issues.append(f"low 异常 {len(bad_low)} 条")
            if issues:
                results.append(CheckResult(ds, "OHLC 合法性", False, "; ".join(issues), trade_date))
            else:
                results.append(CheckResult(ds, "OHLC 合法性", True, "全部合法", trade_date))

        # Volume/amount
        for col in ["volume", "amount"]:
            if col in df.columns:
                neg = df[df[col] < 0]
                if len(neg) > 0:
                    results.append(CheckResult(ds, f"{col} 合法性", False, f"{len(neg)} 条负值", trade_date))
                else:
                    results.append(CheckResult(ds, f"{col} 合法性", True, "无负值", trade_date))

        return results

    def check_daily_basic(self, trade_date: str) -> List[CheckResult]:
        """Check daily_basic: exists, pk unique, key fields non-null."""
        ds = "daily_basic"
        df = self._read_partition(self.s.DAILY_BASIC_DIR, trade_date)
        if df is None:
            return [CheckResult(ds, "数据存在", False, f"{trade_date} 无 daily_basic 数据", trade_date)]

        results: List[CheckResult] = []
        dups = df[df.duplicated(subset=["ts_code"], keep=False)]
        if len(dups) > 0:
            results.append(CheckResult(ds, "主键唯一性", False, f"{len(dups)} 条重复", trade_date))
        else:
            results.append(CheckResult(ds, "主键唯一性", True, f"{len(df)} 条记录", trade_date))

        for col in ["ts_code", "trade_date"]:
            if col not in df.columns:
                results.append(CheckResult(ds, f"{col} 存在性", False, f"缺少列 {col}", trade_date))
            else:
                null_count = df[col].isna().sum()
                if null_count > 0:
                    results.append(CheckResult(ds, f"{col} 非空", False, f"{null_count} 条空值", trade_date))
                else:
                    results.append(CheckResult(ds, f"{col} 非空", True, "无空值", trade_date))

        return results

    def check_adj_factor(self, trade_date: str) -> List[CheckResult]:
        """Check adj_factor: exists, factors > 0, covers daily_bar stocks."""
        ds = "adj_factor"
        results: List[CheckResult] = []
        df = self._read_partition(self.s.ADJ_FACTOR_DIR, trade_date)
        if df is None:
            daily_df = self._read_partition(self.s.DAILY_BAR_DIR, trade_date)
            if daily_df is not None:
                results.append(CheckResult(ds, "数据存在", False, f"{trade_date} 有行情但无复权因子", trade_date))
            return results

        # Factor > 0
        if "adj_factor" in df.columns:
            bad = df[df["adj_factor"] <= 0]
            if len(bad) > 0:
                results.append(CheckResult(ds, "因子正值", False, f"{len(bad)} 条非正因子", trade_date))
            else:
                results.append(CheckResult(ds, "因子正值", True, "全部为正", trade_date))

        # Coverage vs daily_bar
        daily_df = self._read_partition(self.s.DAILY_BAR_DIR, trade_date)
        if daily_df is not None and "ts_code" in df.columns:
            daily_codes = set(daily_df["ts_code"].unique())
            adj_codes = set(df["ts_code"].unique())
            missing = daily_codes - adj_codes
            if missing:
                results.append(CheckResult(ds, "覆盖完整性", False, f"{len(missing)} 只股票缺少复权因子", trade_date))
            else:
                results.append(CheckResult(ds, "覆盖完整性", True, f"覆盖全部 {len(daily_codes)} 只股票", trade_date))

        return results

    def check_stk_limit(self, trade_date: str) -> List[CheckResult]:
        """Check stk_limit: exists, pk unique."""
        ds = "stk_limit"
        df = self._read_partition(self.s.STK_LIMIT_DIR, trade_date)
        if df is None:
            return [CheckResult(ds, "数据存在", False, f"{trade_date} 无 stk_limit 数据", trade_date)]

        results: List[CheckResult] = []
        dups = df[df.duplicated(subset=["ts_code"], keep=False)]
        if len(dups) > 0:
            results.append(CheckResult(ds, "主键唯一性", False, f"{len(dups)} 条重复", trade_date))
        else:
            results.append(CheckResult(ds, "主键唯一性", True, f"{len(df)} 条记录", trade_date))

        return results

    def check_calendar_integrity(self, trade_date: str) -> List[CheckResult]:
        """Check that the calendar file covers this date and is_open=1."""
        ds = "calendar"
        cal = self._load_calendar()
        if cal is None:
            return [CheckResult(ds, "文件存在", False, "calendar.parquet 不存在", "")]

        row = cal[cal["trade_date"] == trade_date]
        if len(row) == 0:
            return [CheckResult(ds, "日期覆盖", False, f"日历中无 {trade_date}", "")]
        if row.iloc[0]["is_open"] != 1:
            return [CheckResult(ds, "交易日标记", False, f"{trade_date} is_open != 1", trade_date)]
        return [CheckResult(ds, "交易日标记", True, f"{trade_date} 是交易日", trade_date)]

    def check_instruments(self) -> List[CheckResult]:
        """Check instruments file exists and has required columns."""
        ds = "instruments"
        inst_path = self.s.INSTRUMENTS_DIR / "instruments.parquet"
        df = self._read_parquet_safe(inst_path)
        if df is None:
            return [CheckResult(ds, "文件存在", False, "instruments.parquet 不存在", "")]
        required = {"ts_code", "list_date"}
        missing_cols = required - set(df.columns)
        if missing_cols:
            return [CheckResult(ds, "字段完整性", False, f"缺少列: {missing_cols}", "")]
        cols = set(df.columns)
        if "name" not in cols and "symbol" not in cols:
            return [CheckResult(ds, "字段完整性", False, "缺少名称列: 需要 name 或 symbol", "")]
        return [CheckResult(ds, "字段完整性", True, f"{len(df)} 条记录", "")]

    def check_trade_date_in_calendar(self, trade_date: str) -> CheckResult:
        """Check that daily_bar data only exists on calendar trading days."""
        ds = "daily_bar"
        cal = self._load_calendar()
        if cal is None:
            return CheckResult(ds, "交易日完整性", False, "交易日历不存在", trade_date)

        daily_df = self._read_partition(self.s.DAILY_BAR_DIR, trade_date)
        if daily_df is None:
            return CheckResult(ds, "交易日完整性", True, f"{trade_date} 无数据", trade_date)

        open_days = set(cal[cal["is_open"] == 1]["trade_date"])
        if trade_date not in open_days:
            return CheckResult(ds, "交易日完整性", False, f"{trade_date} 非交易日但有行情数据", trade_date)
        return CheckResult(ds, "交易日完整性", True, f"{trade_date} 是交易日", trade_date)

    # ---- batch validation -------------------------------------------------

    def validate_date(self, trade_date: str) -> List[CheckResult]:
        """Run all checks for a single trading date."""
        results: List[CheckResult] = []
        results.extend(self.check_calendar_integrity(trade_date))
        results.extend(self.check_daily_bar(trade_date))
        results.append(self.check_trade_date_in_calendar(trade_date))
        results.extend(self.check_daily_basic(trade_date))
        results.extend(self.check_adj_factor(trade_date))
        results.extend(self.check_stk_limit(trade_date))
        return results

    def validate_range(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        Validate data in [start_date, end_date].

        Only iterates over trading days from the calendar.
        Returns a JSON-serializable summary dict.
        """
        logger.info(f"开始校验数据: {start_date} ~ {end_date}")
        trading_days = self._trading_days(start_date, end_date)
        if not trading_days:
            logger.warning("交易日历为空或不在范围内")
            return self._build_summary([], start_date, end_date)

        all_results: List[CheckResult] = []
        for td in trading_days:
            all_results.extend(self.validate_date(td))

        # Also check date-independent items
        all_results.extend(self.check_instruments())

        summary = self._build_summary(all_results, start_date, end_date)
        logger.info(
            f"校验完成: 通过 {summary['passed']}/{summary['total_checks']} "
            f"({summary['pass_rate'] * 100:.1f}%)"
        )
        if summary["failed"] > 0:
            logger.warning(f"发现 {summary['failed']} 项校验失败")
        return summary

    def validate_latest(self, days: int = 10) -> Dict[str, Any]:
        """Validate the most recent *days* calendar trading days."""
        cal = self._load_calendar()
        if cal is None:
            return self._build_summary([], "", "")
        open_days = sorted(cal[cal["is_open"] == 1]["trade_date"])
        if not open_days:
            return self._build_summary([], "", "")
        recent = open_days[-days:]
        return self.validate_range(recent[0], recent[-1])

    # ---- summary builder --------------------------------------------------

    @staticmethod
    def _build_summary(
        results: List[CheckResult],
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """Build a JSON-serializable summary dict."""
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        failed_details = [r.to_dict() for r in results if not r.passed]
        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_checks": len(results),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(results) if results else 0.0,
            "failed_details": failed_details,
        }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    from config import settings as _s
    logger.add(_s.LOG_DIR / "validate.log", rotation="10 MB")

    import argparse
    parser = argparse.ArgumentParser(description="数据质量校验")
    parser.add_argument("--start", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=10, help="最近 N 个交易日（默认 10）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    validator = DataValidator()
    try:
        if args.start and args.end:
            result = validator.validate_range(args.start, args.end)
        else:
            result = validator.validate_latest(days=args.days)

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"校验范围: {result['start_date']} ~ {result['end_date']}")
            print(f"总检查: {result['total_checks']}  通过: {result['passed']}  失败: {result['failed']}")
            print(f"通过率: {result['pass_rate'] * 100:.1f}%")
            if result["failed_details"]:
                print("\n失败详情:")
                for d in result["failed_details"]:
                    print(f"  [{d['dataset']}] {d['check_name']}: {d['details']}")

        if result["failed"] > 0:
            raise SystemExit(1)
    finally:
        pass


if __name__ == "__main__":
    main()
