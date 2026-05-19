from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from backend.db.database import EVENT_ANALYSIS_RESULT_DIR, get_conn
from backend.schemas import EventAnalysisCreate, EventAnalysisResultOut, EventAnalysisTaskOut
from backend.services.task_logging import TaskLogCapture
from event_analysis.engine import EventAnalysisEngine
from event_analysis.loader import EventAnalysisLoader

logger = logging.getLogger(__name__)

EXECUTOR = ThreadPoolExecutor(max_workers=2)


class EventAnalysisService:
    def __init__(self):
        self.loader = EventAnalysisLoader()

    def _persist_runtime_logs(self, task_id: int, snapshot: list[dict]) -> None:
        self._update_task(
            task_id,
            runtime_logs_json=json.dumps(snapshot, ensure_ascii=False),
        )

    def list_tasks(self) -> list[EventAnalysisTaskOut]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM event_analysis_tasks ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [self._row_to_out(row) for row in rows]

    def list_tasks_page(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        keyword: str | None = None,
    ) -> dict:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        conditions: list[str] = []
        params: list = []
        if status:
            conditions.append("t.status = ?")
            params.append(status)
        if keyword:
            conditions.append(
                "(e.key LIKE ? OR e.name LIKE ? OR CAST(t.id AS TEXT) LIKE ?)"
            )
            like = f"%{keyword}%"
            params.extend([like, like, like])

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        base_from = (
            "FROM event_analysis_tasks t "
            "LEFT JOIN event_definitions e ON e.id = t.event_definition_id"
        )

        with get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt {base_from}{where}", params
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT t.* {base_from}{where} "
                "ORDER BY t.created_at DESC, t.id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()

        return {
            "items": [self._row_to_out(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def batch_delete_tasks(self, ids: list[int]) -> dict:
        deleted_ids: list[int] = []
        failed: list[dict[str, str | int]] = []
        for task_id in ids:
            try:
                success = self.delete_task(task_id)
                if success:
                    deleted_ids.append(task_id)
                else:
                    failed.append({"id": task_id, "reason": "任务不存在"})
            except ValueError as exc:
                failed.append({"id": task_id, "reason": str(exc)})
        return {"ok": len(failed) == 0, "deleted_ids": deleted_ids, "failed": failed}

    def get_task(self, task_id: int) -> EventAnalysisTaskOut | None:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM event_analysis_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_out(row) if row else None

    def get_result(self, task_id: int) -> EventAnalysisResultOut | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        payload = {
            "runtime": {
                "status": task.status,
                "logs": task.runtime_logs,
            },
        }
        if task.result_json_path:
            path = Path(task.result_json_path)
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                runtime_block = payload.setdefault("runtime", {})
                runtime_block.setdefault("status", task.status)
                runtime_block["logs"] = task.runtime_logs
        return EventAnalysisResultOut(task=task, payload=payload)

    def create_task(self, payload: EventAnalysisCreate) -> EventAnalysisTaskOut:
        definition = self._get_definition_with_version(payload.event_definition_id)
        if definition is None:
            raise ValueError("事件分析定义不存在或尚未保存可运行版本")
        self._validate_payload(payload)
        with get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO event_analysis_tasks (
                    event_definition_id, event_definition_version_id, status,
                    start_date, end_date, windows_json, entry_rule, dedup_rule, universe, filters_json,
                    progress, created_at
                )
                VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    payload.event_definition_id,
                    definition["version_id"],
                    payload.start_date,
                    payload.end_date,
                    json.dumps(payload.windows, ensure_ascii=False),
                    payload.entry_rule,
                    payload.dedup_rule,
                    payload.universe,
                    json.dumps(payload.filters, ensure_ascii=False),
                    self._now(),
                ),
            )
            task_id = int(cursor.lastrowid)
        EXECUTOR.submit(self._run_task, task_id)
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("事件分析任务创建失败")
        return task

    def cancel_task(self, task_id: int) -> EventAnalysisTaskOut | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.status in {"success", "failed", "cancelled"}:
            raise ValueError("只能终止排队中或运行中的事件分析")
        self._update_task(
            task_id,
            status="cancelled",
            progress=100,
            error_message="用户手动终止事件分析",
            finished_at=self._now(),
        )
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        if task.status in {"queued", "running"}:
            raise ValueError("请先终止运行中或排队中的事件分析")
        if task.result_json_path:
            path = Path(task.result_json_path)
            try:
                if path.exists() and path.is_file():
                    path.unlink()
            except OSError:
                pass
        with get_conn() as conn:
            conn.execute("DELETE FROM event_analysis_tasks WHERE id = ?", (task_id,))
        return True

    def _run_task(self, task_id: int) -> None:
        self._update_task(task_id, status="running", progress=5, started_at=self._now())
        with TaskLogCapture(on_append=lambda snapshot: self._persist_runtime_logs(task_id, snapshot)) as log_capture:
            try:
                task_context = self._get_task_context(task_id)
                if task_context is None:
                    raise ValueError("任务上下文不存在")
                analysis = self.loader.load(
                    file_path=task_context["file_path"],
                    module_key=f'{task_context["event_key"]}_{task_context["version"]}_{task_id}',
                    code=task_context["code"],
                )
                engine = EventAnalysisEngine(
                    start_date=task_context["start_date"],
                    end_date=task_context["end_date"],
                    windows=json.loads(task_context["windows_json"] or "[]"),
                    entry_rule=task_context["entry_rule"],
                    dedup_rule=task_context["dedup_rule"],
                    universe=task_context["universe"],
                    filters=json.loads(task_context["filters_json"] or "[]"),
                )
                engine.set_scan(analysis.scan)
                self._update_task(task_id, progress=25)
                if self._is_cancelled(task_id):
                    self._update_task(
                        task_id,
                        runtime_logs_json=json.dumps(log_capture.snapshot(), ensure_ascii=False),
                    )
                    return
                result = engine.run()
                if self._is_cancelled(task_id):
                    self._update_task(
                        task_id,
                        runtime_logs_json=json.dumps(log_capture.snapshot(), ensure_ascii=False),
                    )
                    return
                EVENT_ANALYSIS_RESULT_DIR.mkdir(parents=True, exist_ok=True)
                result_path = EVENT_ANALYSIS_RESULT_DIR / f"event_analysis_task_{task_id}.json"
                payload = {
                    "task_id": task_id,
                    "name": getattr(analysis, "name", task_context["event_name"]),
                    "start_date": result.start_date,
                    "end_date": result.end_date,
                    "entry_rule": task_context["entry_rule"],
                    "dedup_rule": task_context["dedup_rule"],
                    "universe": task_context["universe"],
                    "filters": json.loads(task_context["filters_json"] or "[]"),
                    "windows": json.loads(task_context["windows_json"] or "[]"),
                    "summary": result.summary,
                    "details": result.details,
                    "runtime": {
                        "status": "success",
                        "logs": log_capture.snapshot(),
                    },
                }
                result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                self._update_task(
                    task_id,
                    status="success",
                    progress=100,
                    sample_count=result.sample_count,
                    summary_json=json.dumps(result.summary, ensure_ascii=False),
                    result_json_path=str(result_path),
                    runtime_logs_json=json.dumps(log_capture.snapshot(), ensure_ascii=False),
                    finished_at=self._now(),
                )
            except Exception as exc:
                logger.exception("event analysis task failed: %s", task_id)
                log_capture.capture_exception(exc, source=__name__)
                self._update_task(
                    task_id,
                    status="failed",
                    progress=100,
                    runtime_logs_json=json.dumps(log_capture.snapshot(), ensure_ascii=False),
                    error_message=str(exc),
                    finished_at=self._now(),
                )

    def _get_definition_with_version(self, definition_id: int):
        with get_conn() as conn:
            return conn.execute(
                """
                SELECT
                    e.id AS event_definition_id,
                    e.key AS event_key,
                    e.name AS event_name,
                    e.status AS status,
                    v.id AS version_id,
                    v.version AS version,
                    v.file_path AS file_path
                FROM event_definitions e
                JOIN event_definition_versions v ON v.id = e.current_version_id
                WHERE e.id = ?
                """,
                (definition_id,),
            ).fetchone()

    def _get_task_context(self, task_id: int):
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

    def _validate_payload(self, payload: EventAnalysisCreate) -> None:
        if not payload.start_date or not payload.end_date:
            raise ValueError("事件分析起止日期不能为空")
        if payload.start_date > payload.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if not payload.windows:
            raise ValueError("至少需要一个收益窗口")

    def _update_task(self, task_id: int, **fields) -> None:
        if not fields:
            return
        columns = [f"{key} = ?" for key in fields]
        values = list(fields.values())
        values.append(task_id)
        with get_conn() as conn:
            conn.execute(f"UPDATE event_analysis_tasks SET {', '.join(columns)} WHERE id = ?", values)

    def _is_cancelled(self, task_id: int) -> bool:
        with get_conn() as conn:
            row = conn.execute("SELECT status FROM event_analysis_tasks WHERE id = ?", (task_id,)).fetchone()
        return row is not None and row["status"] == "cancelled"

    def _row_to_out(self, row) -> EventAnalysisTaskOut:
        summary = None
        runtime_logs = []
        if row["summary_json"]:
            try:
                summary = json.loads(row["summary_json"])
            except json.JSONDecodeError:
                summary = None
        if row["runtime_logs_json"]:
            try:
                runtime_logs = json.loads(row["runtime_logs_json"])
            except json.JSONDecodeError:
                runtime_logs = []
        return EventAnalysisTaskOut(
            id=row["id"],
            event_definition_id=row["event_definition_id"],
            event_definition_version_id=row["event_definition_version_id"],
            status=row["status"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            windows=json.loads(row["windows_json"] or "[]"),
            entry_rule=row["entry_rule"],
            dedup_rule=row["dedup_rule"],
            universe=row["universe"],
            filters=json.loads((row["filters_json"] or "[]")),
            progress=row["progress"],
            sample_count=row["sample_count"],
            summary=summary,
            result_json_path=row["result_json_path"],
            runtime_logs=runtime_logs,
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
