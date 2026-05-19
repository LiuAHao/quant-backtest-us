from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.database import get_conn
from backend.schemas import StrategyCreate, StrategyUpdate
from backend.services.strategy_loader import StrategyLoader
from backend.services.strategy_service import StrategyService
from backtest.engine import BacktestEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成前端可识别的标准化回测结果。")
    parser.add_argument("--strategy-file", required=True, help="策略代码文件路径")
    parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--strategy-key", help="策略 key，可选")
    parser.add_argument("--strategy-name", help="策略名称，可选")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api", help="后端 API 地址")
    parser.add_argument("--initial-capital", type=float, default=1_000_000)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--slippage", type=float, default=0.001)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    return parser.parse_args()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_key(raw: str) -> str:
    import re

    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", raw.strip()).strip("_").lower()
    return normalized or f"strategy_{int(time.time())}"


def try_api_mode(args: argparse.Namespace, strategy_code: str) -> int | None:
    payload = {
        "strategy_code": strategy_code,
        "strategy_key": args.strategy_key,
        "strategy_name": args.strategy_name,
        "start_date": args.start,
        "end_date": args.end,
        "initial_capital": args.initial_capital,
        "commission_rate": args.commission_rate,
        "slippage": args.slippage,
    }

    try:
        with httpx.Client(timeout=15) as client:
            health = client.get(f"{args.base_url}/health")
            health.raise_for_status()
            response = client.post(f"{args.base_url}/backtests/quick", json=payload)
            response.raise_for_status()
            task = response.json()
            task_id = task["id"]
            print(json.dumps({"mode": "api", "task_id": task_id, "status": task["status"]}, ensure_ascii=False))

            deadline = time.time() + args.timeout
            while time.time() < deadline:
                detail = client.get(f"{args.base_url}/backtests/{task_id}")
                detail.raise_for_status()
                task = detail.json()
                status = task["status"]
                print(json.dumps({"mode": "api", "task_id": task_id, "status": status, "progress": task.get("progress", 0)}, ensure_ascii=False))
                if status == "success":
                    report = client.get(f"{args.base_url}/reports/{task_id}")
                    report.raise_for_status()
                    payload = report.json()
                    hero = (payload.get("payload") or {}).get("hero") or {}
                    print(json.dumps({
                        "mode": "api",
                        "task_id": task_id,
                        "status": status,
                        "report_json_path": task.get("report_json_path"),
                        "report_html_path": task.get("report_html_path"),
                        "return_pct": hero.get("return_pct"),
                        "max_drawdown": hero.get("max_drawdown"),
                        "sharpe_ratio": hero.get("sharpe_ratio"),
                    }, ensure_ascii=False))
                    return 0
                if status in {"failed", "cancelled"}:
                    print(json.dumps({
                        "mode": "api",
                        "task_id": task_id,
                        "status": status,
                        "error_message": task.get("error_message"),
                    }, ensure_ascii=False), file=sys.stderr)
                    return 2
                time.sleep(args.poll_interval)
        print(json.dumps({"mode": "api", "status": "timeout", "task_id": task_id}, ensure_ascii=False), file=sys.stderr)
        return 3
    except Exception:
        return None


def ensure_strategy(args: argparse.Namespace, strategy_code: str):
    service = StrategyService()
    key = normalize_key(args.strategy_key or Path(args.strategy_file).stem)
    fallback_name = args.strategy_name or Path(args.strategy_file).stem
    metadata = service.derive_metadata_from_code(strategy_code, fallback_name=fallback_name)
    name = str(metadata.get("name") or fallback_name)
    description = str(metadata.get("description") or fallback_name)
    tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
    existing = next((item for item in service.list_strategies() if item.key == key), None)
    if existing is None:
        strategy = service.create_strategy(
            StrategyCreate(
                key=key,
                name=name,
                description=description,
                source="manual",
                tags=tags,
                code=strategy_code,
                status="enabled",
            )
        )
    else:
        should_replace_metadata = service._has_generic_metadata(existing.description, existing.tags)
        next_description = description if should_replace_metadata or not (existing.description or "").strip() else existing.description
        next_tags = tags if should_replace_metadata or not existing.tags else existing.tags
        strategy = service.update_strategy(
            existing.id,
            StrategyUpdate(
                name=name,
                description=next_description,
                source="manual",
                tags=next_tags,
                code=strategy_code,
                status=existing.status,
            ),
        )
    if strategy is None:
        raise RuntimeError("策略保存失败")
    return strategy


def create_local_task(strategy_id: int, strategy_version_id: int, args: argparse.Namespace) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO backtest_tasks (
                strategy_id, strategy_version_id, status, start_date, end_date,
                initial_capital, commission_rate, slippage, progress, created_at, started_at
            )
            VALUES (?, ?, 'running', ?, ?, ?, ?, ?, 5, ?, ?)
            """,
            (
                strategy_id,
                strategy_version_id,
                args.start,
                args.end,
                args.initial_capital,
                args.commission_rate,
                args.slippage,
                now_text(),
                now_text(),
            ),
        )
        return int(cursor.lastrowid)


def update_local_task(task_id: int, **fields) -> None:
    if not fields:
        return
    columns = [f"{key} = ?" for key in fields]
    values = list(fields.values())
    values.append(task_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE backtest_tasks SET {', '.join(columns)} WHERE id = ?", values)


def get_task_context(task_id: int):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT
                t.*,
                s.key AS strategy_key,
                v.version AS version,
                v.file_path AS file_path,
                v.code AS code
            FROM backtest_tasks t
            JOIN strategies s ON s.id = t.strategy_id
            JOIN strategy_versions v ON v.id = t.strategy_version_id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()


def run_local_mode(args: argparse.Namespace, strategy_code: str) -> int:
    strategy = ensure_strategy(args, strategy_code)
    if strategy.current_version_id is None:
        raise RuntimeError("策略没有可运行版本")

    task_id = create_local_task(strategy.id, strategy.current_version_id, args)
    print(json.dumps({"mode": "local", "task_id": task_id, "status": "running"}, ensure_ascii=False))

    try:
        task_context = get_task_context(task_id)
        if task_context is None:
            raise RuntimeError("任务上下文不存在")

        loader = StrategyLoader()
        strategy_instance = loader.load(
            file_path=task_context["file_path"],
            module_key=f'{task_context["strategy_key"]}_{task_context["version"]}_{task_id}',
            code=task_context["code"],
        )
        init_func, next_func = strategy_instance.get_callbacks()

        engine = BacktestEngine(
            start_date=args.start.replace("-", ""),
            end_date=args.end.replace("-", ""),
            initial_capital=float(args.initial_capital),
            commission_rate=float(args.commission_rate),
            slippage=float(args.slippage),
            enable_reports=True,
        )
        engine.set_strategy(init_func, next_func)
        update_local_task(task_id, progress=20)
        result = engine.run()
        report_json = str(engine.last_report_paths.get("json", "")) or None
        report_html = str(engine.last_report_paths.get("html", "")) or None
        update_local_task(
            task_id,
            status="success",
            progress=100,
            report_json_path=report_json,
            report_html_path=report_html,
            total_return=result.total_return,
            max_drawdown=result.max_drawdown,
            sharpe_ratio=result.sharpe_ratio,
            finished_at=now_text(),
        )
        print(json.dumps({
            "mode": "local",
            "task_id": task_id,
            "status": "success",
            "report_json_path": report_json,
            "report_html_path": report_html,
            "return_pct": result.total_return,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        update_local_task(
            task_id,
            status="failed",
            progress=100,
            error_message=str(exc),
            finished_at=now_text(),
        )
        print(json.dumps({
            "mode": "local",
            "task_id": task_id,
            "status": "failed",
            "error_message": str(exc),
        }, ensure_ascii=False), file=sys.stderr)
        return 2


def main() -> int:
    args = parse_args()
    strategy_path = Path(args.strategy_file)
    if not strategy_path.exists():
        print(f"策略文件不存在: {strategy_path}", file=sys.stderr)
        return 1

    strategy_code = strategy_path.read_text(encoding="utf-8")

    api_result = try_api_mode(args, strategy_code)
    if api_result is not None:
        return api_result

    return run_local_mode(args, strategy_code)


if __name__ == "__main__":
    raise SystemExit(main())
