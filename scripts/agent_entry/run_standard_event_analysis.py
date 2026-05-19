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

from backend.db.database import EVENT_ANALYSIS_RESULT_DIR, get_conn
from backend.schemas import EventDefinitionCreate, EventDefinitionUpdate
from backend.services.event_definition_service import EventDefinitionService
from event_analysis.engine import EventAnalysisEngine
from event_analysis.loader import EventAnalysisLoader

VALID_FILTERS = {
    "exclude_st",
    "exclude_new_stock",
    "exclude_kcb_cyb",
    "exclude_main_board",
    "exclude_beijing",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成前端可识别的标准化事件分析结果。")
    parser.add_argument("--event-file", required=True, help="事件分析代码文件路径")
    parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--event-key", help="事件定义 key，可选")
    parser.add_argument("--event-name", help="事件定义名称，可选")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api", help="后端 API 地址")
    parser.add_argument("--windows", default="5,10,15", help="收益窗口，逗号分隔，如 5,10,15")
    parser.add_argument("--entry-rule", default="next_open", choices=["event_close", "next_open", "next_close"])
    parser.add_argument(
        "--dedup-rule",
        default="none",
        choices=["none", "per_stock_per_day", "per_stock_gap_5", "per_stock_gap_10"],
    )
    parser.add_argument("--universe", default="all_a", choices=["all_a", "exclude_beijing", "main_board_only"])
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        dest="filters",
        help="样本过滤条件，可重复传入，如 --filter exclude_st --filter exclude_new_stock",
    )
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    return parser.parse_args()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_key(raw: str) -> str:
    import re

    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", raw.strip()).strip("_").lower()
    return normalized or f"event_analysis_{int(time.time())}"


def parse_windows(raw: str) -> list[int]:
    values = []
    for part in str(raw).split(","):
        token = part.strip()
        if not token:
            continue
        value = int(token)
        if value > 0:
            values.append(value)
    windows = sorted(set(values))
    if not windows:
        raise ValueError("至少需要一个有效收益窗口")
    return windows


def parse_filters(raw_filters: list[str]) -> list[str]:
    parsed: list[str] = []
    for item in raw_filters:
        for part in str(item).split(","):
            token = part.strip()
            if not token:
                continue
            if token not in VALID_FILTERS:
                raise ValueError(f"不支持的过滤条件: {token}")
            if token not in parsed:
                parsed.append(token)
    return parsed


def try_api_mode(args: argparse.Namespace, event_code: str, windows: list[int], filters: list[str]) -> int | None:
    payload = {
        "event_code": event_code,
        "event_key": args.event_key,
        "event_name": args.event_name,
        "start_date": args.start,
        "end_date": args.end,
        "windows": windows,
        "entry_rule": args.entry_rule,
        "dedup_rule": args.dedup_rule,
        "universe": args.universe,
        "filters": filters,
    }

    try:
        with httpx.Client(timeout=15) as client:
            health = client.get(f"{args.base_url}/health")
            health.raise_for_status()
            response = client.post(f"{args.base_url}/event-analyses/quick", json=payload)
            response.raise_for_status()
            task = response.json()
            task_id = task["id"]
            print(json.dumps({"mode": "api", "task_id": task_id, "status": task["status"]}, ensure_ascii=False))

            deadline = time.time() + args.timeout
            while time.time() < deadline:
                detail = client.get(f"{args.base_url}/event-analyses/{task_id}")
                detail.raise_for_status()
                task = detail.json()
                status = task["status"]
                print(
                    json.dumps(
                        {"mode": "api", "task_id": task_id, "status": status, "progress": task.get("progress", 0)},
                        ensure_ascii=False,
                    )
                )
                if status == "success":
                    result = client.get(f"{args.base_url}/event-analyses/{task_id}/result")
                    result.raise_for_status()
                    payload = result.json().get("payload") or {}
                    summary = payload.get("summary") or {}
                    print(
                        json.dumps(
                            {
                                "mode": "api",
                                "task_id": task_id,
                                "status": status,
                                "result_json_path": task.get("result_json_path"),
                                "sample_count": task.get("sample_count"),
                                "summary": summary,
                            },
                            ensure_ascii=False,
                        )
                    )
                    return 0
                if status in {"failed", "cancelled"}:
                    print(
                        json.dumps(
                            {
                                "mode": "api",
                                "task_id": task_id,
                                "status": status,
                                "error_message": task.get("error_message"),
                            },
                            ensure_ascii=False,
                        ),
                        file=sys.stderr,
                    )
                    return 2
                time.sleep(args.poll_interval)
        print(json.dumps({"mode": "api", "status": "timeout", "task_id": task_id}, ensure_ascii=False), file=sys.stderr)
        return 3
    except Exception:
        return None


def ensure_event_definition(args: argparse.Namespace, event_code: str):
    service = EventDefinitionService()
    key = normalize_key(args.event_key or Path(args.event_file).stem)
    name = args.event_name or Path(args.event_file).stem
    existing = next((item for item in service.list_definitions() if item.key == key), None)
    if existing is None:
        definition = service.create_definition(
            EventDefinitionCreate(
                key=key,
                name=name,
                description="通过标准化事件分析脚本创建",
                source="manual",
                tags=["标准事件分析"],
                code=event_code,
                status="enabled",
            )
        )
    else:
        definition = service.update_definition(
            existing.id,
            EventDefinitionUpdate(
                name=name,
                description="通过标准化事件分析脚本更新",
                source="manual",
                tags=["标准事件分析"],
                code=event_code,
                status=existing.status,
            ),
        )
    if definition is None:
        raise RuntimeError("事件定义保存失败")
    return definition


def create_local_task(definition_id: int, definition_version_id: int, args: argparse.Namespace, windows: list[int], filters: list[str]) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO event_analysis_tasks (
                event_definition_id, event_definition_version_id, status,
                start_date, end_date, windows_json, entry_rule, dedup_rule, universe, filters_json,
                progress, created_at, started_at
            )
            VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, 5, ?, ?)
            """,
            (
                definition_id,
                definition_version_id,
                args.start,
                args.end,
                json.dumps(windows, ensure_ascii=False),
                args.entry_rule,
                args.dedup_rule,
                args.universe,
                json.dumps(filters, ensure_ascii=False),
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
        conn.execute(f"UPDATE event_analysis_tasks SET {', '.join(columns)} WHERE id = ?", values)


def get_task_context(task_id: int):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT
                t.*,
                e.key AS event_key,
                e.name AS event_name,
                v.version AS version,
                v.file_path AS file_path,
                v.code AS code
            FROM event_analysis_tasks t
            JOIN event_definitions e ON e.id = t.event_definition_id
            JOIN event_definition_versions v ON v.id = t.event_definition_version_id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()


def run_local_mode(args: argparse.Namespace, event_code: str, windows: list[int], filters: list[str]) -> int:
    definition = ensure_event_definition(args, event_code)
    if definition.current_version_id is None:
        raise RuntimeError("事件定义没有可运行版本")

    task_id = create_local_task(definition.id, definition.current_version_id, args, windows, filters)
    print(json.dumps({"mode": "local", "task_id": task_id, "status": "running"}, ensure_ascii=False))

    try:
        task_context = get_task_context(task_id)
        if task_context is None:
            raise RuntimeError("任务上下文不存在")

        loader = EventAnalysisLoader()
        analysis = loader.load(
            file_path=task_context["file_path"],
            module_key=f'{task_context["event_key"]}_{task_context["version"]}_{task_id}',
            code=task_context["code"],
        )

        engine = EventAnalysisEngine(
            start_date=args.start,
            end_date=args.end,
            windows=windows,
            entry_rule=args.entry_rule,
            dedup_rule=args.dedup_rule,
            universe=args.universe,
            filters=filters,
        )
        engine.set_scan(analysis.scan)
        update_local_task(task_id, progress=25)
        result = engine.run()

        EVENT_ANALYSIS_RESULT_DIR.mkdir(parents=True, exist_ok=True)
        result_path = EVENT_ANALYSIS_RESULT_DIR / f"event_analysis_task_{task_id}.json"
        payload = {
            "task_id": task_id,
            "name": getattr(analysis, "name", task_context["event_name"]),
            "start_date": result.start_date,
            "end_date": result.end_date,
            "entry_rule": args.entry_rule,
            "dedup_rule": args.dedup_rule,
            "universe": args.universe,
            "filters": filters,
            "windows": windows,
            "summary": result.summary,
            "details": result.details,
        }
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        update_local_task(
            task_id,
            status="success",
            progress=100,
            sample_count=result.sample_count,
            summary_json=json.dumps(result.summary, ensure_ascii=False),
            result_json_path=str(result_path),
            finished_at=now_text(),
        )
        print(
            json.dumps(
                {
                    "mode": "local",
                    "task_id": task_id,
                    "status": "success",
                    "result_json_path": str(result_path),
                    "sample_count": result.sample_count,
                    "summary": result.summary,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        update_local_task(
            task_id,
            status="failed",
            progress=100,
            error_message=str(exc),
            finished_at=now_text(),
        )
        print(
            json.dumps(
                {
                    "mode": "local",
                    "task_id": task_id,
                    "status": "failed",
                    "error_message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


def main() -> int:
    args = parse_args()
    event_path = Path(args.event_file)
    if not event_path.exists():
        print(json.dumps({"status": "failed", "error_message": f"事件分析文件不存在: {event_path}"}, ensure_ascii=False), file=sys.stderr)
        return 2

    try:
        windows = parse_windows(args.windows)
        filters = parse_filters(args.filters)
    except ValueError as exc:
        print(json.dumps({"status": "failed", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    event_code = event_path.read_text(encoding="utf-8")

    api_exit = try_api_mode(args, event_code, windows, filters)
    if api_exit is not None:
        return api_exit
    return run_local_mode(args, event_code, windows, filters)


if __name__ == "__main__":
    raise SystemExit(main())
