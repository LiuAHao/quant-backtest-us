from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from backtest.data_loader import DataLoader
from backend.db.database import get_conn
from backend.schemas import BacktestCreate, BacktestTaskOut
from backend.services.task_logging import TaskLogCapture
from backend.services.strategy_loader import StrategyLoader
from backtest.engine import BacktestEngine

logger = logging.getLogger(__name__)

EXECUTOR = ThreadPoolExecutor(max_workers=2)


class BacktestService:
    def __init__(self):
        self.loader = StrategyLoader()
        self._backfill_metrics()
        self._date_bounds: tuple[str, str] | None = None

    def _backfill_metrics(self) -> None:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, status, report_json_path, finished_at, total_return, max_drawdown, sharpe_ratio FROM backtest_tasks "
                "WHERE report_json_path IS NOT NULL"
            ).fetchall()
            for row in rows:
                try:
                    path = Path(row["report_json_path"])
                    if not path.exists():
                        continue
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    hero = payload.get("hero", {})
                    updates: dict[str, object] = {}
                    if row["status"] in {"queued", "running"}:
                        updates["status"] = "success"
                        updates["progress"] = 100
                        updates["error_message"] = None
                    if not row["finished_at"]:
                        updates["finished_at"] = self._now()
                    if row["total_return"] is None:
                        updates["total_return"] = hero.get("return_pct")
                    if row["max_drawdown"] is None:
                        updates["max_drawdown"] = hero.get("max_drawdown")
                    if row["sharpe_ratio"] is None:
                        updates["sharpe_ratio"] = hero.get("sharpe_ratio")
                    if updates:
                        columns = ", ".join(f"{key} = ?" for key in updates)
                        conn.execute(
                            f"UPDATE backtest_tasks SET {columns} WHERE id = ?",
                            [*updates.values(), row["id"]],
                        )
                except Exception:
                    logger.debug("backfill metrics failed for task %s", row["id"], exc_info=True)
            conn.commit()

    def list_tasks(self) -> list[BacktestTaskOut]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_tasks ORDER BY created_at DESC, id DESC"
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
                "(s.key LIKE ? OR s.name LIKE ? OR CAST(t.id AS TEXT) LIKE ?)"
            )
            like = f"%{keyword}%"
            params.extend([like, like, like])

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        base_from = (
            "FROM backtest_tasks t "
            "LEFT JOIN strategies s ON s.id = t.strategy_id"
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

    def get_task(self, task_id: int) -> BacktestTaskOut | None:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM backtest_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_out(row) if row else None

    def cancel_task(self, task_id: int) -> BacktestTaskOut | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.status in {"success", "failed", "cancelled"}:
            raise ValueError("只能终止排队中或运行中的回测")
        self._update_task(
            task_id,
            status="cancelled",
            progress=100,
            error_message="用户手动终止回测",
            finished_at=self._now(),
        )
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        if task.status in {"queued", "running"}:
            raise ValueError("请先终止运行中或排队中的回测")

        for path_text in (task.report_json_path, task.report_html_path):
            if not path_text:
                continue
            path = Path(path_text)
            try:
                if path.exists() and path.is_file():
                    path.unlink()
            except OSError:
                pass

        with get_conn() as conn:
            conn.execute("DELETE FROM backtest_tasks WHERE id = ?", (task_id,))
        return True

    def create_task(self, payload: BacktestCreate) -> BacktestTaskOut:
        strategy = self._get_strategy_with_version(payload.strategy_id)
        if strategy is None:
            raise ValueError("策略不存在或尚未保存可运行版本")
        self._validate_payload(payload)

        with get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO backtest_tasks (
                    strategy_id, strategy_version_id, status, start_date, end_date,
                    initial_capital, commission_rate, slippage, progress, benchmark, created_at
                )
                VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    payload.strategy_id,
                    strategy["version_id"],
                    payload.start_date,
                    payload.end_date,
                    payload.initial_capital,
                    payload.commission_rate,
                    payload.slippage,
                    payload.benchmark,
                    self._now(),
                ),
            )
            task_id = int(cursor.lastrowid)

        EXECUTOR.submit(self._run_task, task_id)
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("回测任务创建失败")
        return task

    def _run_task(self, task_id: int) -> None:
        self._update_task(task_id, status="running", progress=5, started_at=self._now())
        with TaskLogCapture() as log_capture:
            try:
                task_context = self._get_task_context(task_id)
                if task_context is None:
                    raise ValueError("任务上下文不存在")

                strategy = self.loader.load(
                    file_path=task_context["file_path"],
                    module_key=f'{task_context["strategy_key"]}_{task_context["version"]}_{task_id}',
                    code=task_context["code"],
                )
                init_func, next_func = strategy.get_callbacks()

                engine = BacktestEngine(
                    start_date=self._date_to_engine(task_context["start_date"]),
                    end_date=self._date_to_engine(task_context["end_date"]),
                    initial_capital=float(task_context["initial_capital"]),
                    commission_rate=float(task_context["commission_rate"]),
                    slippage=float(task_context["slippage"]),
                    enable_reports=True,
                    benchmark=task_context["benchmark"],
                )
                engine.set_strategy(init_func, next_func)
                engine.set_report_enricher(lambda payload: {
                    "runtime": {
                        "status": "success",
                        "logs": log_capture.snapshot(),
                    },
                })
                self._update_task(task_id, progress=20)
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
                    self._cleanup_report_files(engine.last_report_paths.values())
                    return
                report_json = str(engine.last_report_paths.get("json", "")) or None
                report_html = str(engine.last_report_paths.get("html", "")) or None
                self._update_task(
                    task_id,
                    status="success",
                    progress=100,
                    report_json_path=report_json,
                    report_html_path=report_html,
                    runtime_logs_json=json.dumps(log_capture.snapshot(), ensure_ascii=False),
                    total_return=result.total_return,
                    max_drawdown=result.max_drawdown,
                    sharpe_ratio=result.sharpe_ratio,
                    finished_at=self._now(),
                )
            except Exception as exc:
                log_capture.capture_exception(exc, source=__name__)
                self._update_task(
                    task_id,
                    status="failed",
                    progress=100,
                    runtime_logs_json=json.dumps(log_capture.snapshot(), ensure_ascii=False),
                    error_message=str(exc),
                    finished_at=self._now(),
                )

    def _get_strategy_with_version(self, strategy_id: int):
        with get_conn() as conn:
            return conn.execute(
                """
                SELECT
                    s.id AS strategy_id,
                    s.key AS strategy_key,
                    s.status AS status,
                    v.id AS version_id,
                    v.version AS version,
                    v.file_path AS file_path
                FROM strategies s
                JOIN strategy_versions v ON v.id = s.current_version_id
                WHERE s.id = ?
                """,
                (strategy_id,),
            ).fetchone()

    def _get_task_context(self, task_id: int):
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

    def _update_task(self, task_id: int, **fields) -> None:
        if not fields:
            return
        columns = [f"{key} = ?" for key in fields]
        values = list(fields.values())
        values.append(task_id)
        with get_conn() as conn:
            conn.execute(f"UPDATE backtest_tasks SET {', '.join(columns)} WHERE id = ?", values)

    def _is_cancelled(self, task_id: int) -> bool:
        with get_conn() as conn:
            row = conn.execute("SELECT status FROM backtest_tasks WHERE id = ?", (task_id,)).fetchone()
        return row is not None and row["status"] == "cancelled"

    def _row_to_out(self, row) -> BacktestTaskOut:
        runtime_logs = []
        if row["runtime_logs_json"]:
            try:
                runtime_logs = json.loads(row["runtime_logs_json"])
            except json.JSONDecodeError:
                runtime_logs = []
        return BacktestTaskOut(
            id=row["id"],
            strategy_id=row["strategy_id"],
            strategy_version_id=row["strategy_version_id"],
            status=row["status"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            initial_capital=row["initial_capital"],
            commission_rate=row["commission_rate"],
            slippage=row["slippage"],
            progress=row["progress"],
            benchmark=row["benchmark"] if "benchmark" in row.keys() else None,
            report_json_path=row["report_json_path"],
            report_html_path=row["report_html_path"],
            runtime_logs=runtime_logs,
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            total_return=row["total_return"],
            max_drawdown=row["max_drawdown"],
            sharpe_ratio=row["sharpe_ratio"],
        )

    def _date_to_engine(self, value: str) -> str:
        return value.replace("-", "")

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _cleanup_report_files(self, paths) -> None:
        for path in paths:
            if not path:
                continue
            file_path = Path(path)
            try:
                if file_path.exists() and file_path.is_file():
                    file_path.unlink()
            except OSError:
                logger.debug("cleanup report file failed: %s", file_path, exc_info=True)

    def _validate_payload(self, payload: BacktestCreate) -> None:
        start_dt = self._parse_date(payload.start_date, "开始日期")
        end_dt = self._parse_date(payload.end_date, "结束日期")

        if start_dt > end_dt:
            raise ValueError("回测开始日期不能晚于结束日期")

        earliest, latest = self._get_date_bounds()
        if payload.start_date < earliest or payload.start_date > latest:
            raise ValueError(f"回测开始日期超出数据范围，可用区间为 {earliest} 至 {latest}")
        if payload.end_date < earliest or payload.end_date > latest:
            raise ValueError(f"回测结束日期超出数据范围，可用区间为 {earliest} 至 {latest}")

        if payload.initial_capital <= 0:
            raise ValueError("初始资金必须大于 0")
        if payload.commission_rate < 0:
            raise ValueError("手续费率不能小于 0")
        if payload.slippage < 0:
            raise ValueError("滑点不能小于 0")

    def _parse_date(self, value: str, label: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"{label}格式不正确，请使用 YYYY-MM-DD") from exc

    def _get_date_bounds(self) -> tuple[str, str]:
        if self._date_bounds is not None:
            return self._date_bounds

        loader = DataLoader()
        try:
            earliest = loader.conn.execute(
                """
                SELECT trade_date
                FROM calendar
                WHERE is_open = 1
                ORDER BY trade_date ASC
                LIMIT 1
                """
            ).fetchone()
            latest = loader.conn.execute(
                """
                SELECT trade_date
                FROM calendar
                WHERE is_open = 1
                ORDER BY trade_date DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            try:
                loader.conn.close()
            except Exception:
                logger.debug("close data loader failed", exc_info=True)

        if earliest is None or latest is None or not earliest[0] or not latest[0]:
            raise ValueError("交易日历不可用，无法创建回测")

        self._date_bounds = (self._normalize_trade_date(earliest[0]), self._normalize_trade_date(latest[0]))
        return self._date_bounds

    def _normalize_trade_date(self, value) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()
        return text[:10] if len(text) >= 10 else text
