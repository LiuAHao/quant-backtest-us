"""
数据运维 CLI — 只读 status / validate 子命令。

用法:
    python scripts/data_utils/data_admin.py status
    python scripts/data_utils/data_admin.py validate [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--days N] [--json]
    python scripts/data_utils/data_admin.py validate --start 2026-01-01 --end 2026-04-29 --json
    python scripts/data_utils/data_admin.py validate --days 20

不执行任何下载、删除、覆盖等破坏性操作。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings
from scripts.data_utils.validate_data import DataValidator


def _count_parquet_files(directory: Path) -> int:
    """Count .parquet files under directory (non-recursive search)."""
    if not directory.exists():
        return 0
    return len(list(directory.rglob("*.parquet")))


def _count_partitions(directory: Path) -> int:
    """Count hive partitions (trade_date=...) under directory."""
    if not directory.exists():
        return 0
    return len(list(directory.glob("trade_date=*")))


def cmd_status(_args: argparse.Namespace) -> None:
    """Show dataset status: file counts and date ranges."""
    cal_path = settings.CALENDAR_DIR / "calendar.parquet"
    cal_range = ("N/A", "N/A")
    trading_days = 0
    if cal_path.exists():
        cal = pd.read_parquet(cal_path)
        cal["trade_date"] = pd.to_datetime(cal["trade_date"]).dt.strftime("%Y-%m-%d")
        open_days = sorted(cal[cal["is_open"] == 1]["trade_date"])
        trading_days = len(open_days)
        if open_days:
            cal_range = (open_days[0], open_days[-1])

    datasets = {
        "daily_bar": {
            "path": str(settings.DAILY_BAR_DIR),
            "partitions": _count_partitions(settings.DAILY_BAR_DIR),
        },
        "daily_basic": {
            "path": str(settings.DAILY_BASIC_DIR),
            "partitions": _count_partitions(settings.DAILY_BASIC_DIR),
        },
        "adj_factor": {
            "path": str(settings.ADJ_FACTOR_DIR),
            "partitions": _count_partitions(settings.ADJ_FACTOR_DIR),
        },
        "stk_limit": {
            "path": str(settings.STK_LIMIT_DIR),
            "partitions": _count_partitions(settings.STK_LIMIT_DIR),
        },
        "calendar": {
            "path": str(settings.CALENDAR_DIR),
            "files": _count_parquet_files(settings.CALENDAR_DIR),
        },
        "instruments": {
            "path": str(settings.INSTRUMENTS_DIR),
            "files": _count_parquet_files(settings.INSTRUMENTS_DIR),
        },
    }

    inst_path = settings.INSTRUMENTS_DIR / "instruments.parquet"
    stock_count = 0
    if inst_path.exists():
        try:
            stock_count = len(pd.read_parquet(inst_path))
        except Exception:
            pass

    output = {
        "calendar": {
            "earliest": cal_range[0],
            "latest": cal_range[1],
            "trading_days": trading_days,
        },
        "instruments": {"count": stock_count},
        "datasets": datasets,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_validate(args: argparse.Namespace) -> None:
    """Run data validation and print summary."""
    validator = DataValidator()

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


def main():
    parser = argparse.ArgumentParser(
        description="数据运维 CLI（只读）",
        epilog="不执行任何下载、删除、覆盖等破坏性操作。",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="显示数据集状态")

    vp = sub.add_parser("validate", help="运行数据质量校验")
    vp.add_argument("--start", help="起始日期 YYYY-MM-DD")
    vp.add_argument("--end", help="结束日期 YYYY-MM-DD")
    vp.add_argument("--days", type=int, default=10, help="最近 N 个交易日（默认 10）")
    vp.add_argument("--json", action="store_true", help="输出 JSON")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(args)
    elif args.command == "validate":
        cmd_validate(args)
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
