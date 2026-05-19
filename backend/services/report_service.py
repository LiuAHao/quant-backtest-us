from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backend.db.database import get_conn


def _patch_monthly_returns(payload: dict) -> None:
    charts = payload.get("charts", {})
    if charts.get("monthly_returns"):
        return
    equity_points = charts.get("equity_curve", [])
    if not equity_points:
        return
    dates = [p["date"] for p in equity_points]
    values = [p["value"] for p in equity_points]
    equity_curve = pd.Series(values, index=pd.to_datetime(dates))
    monthly_last = equity_curve.resample("ME").last()
    monthly_return = monthly_last.pct_change()
    first_ts = monthly_last.index[0]
    initial_value = equity_curve.iloc[0]
    first_ret = (monthly_last.loc[first_ts] / initial_value) - 1.0 if initial_value != 0 else 0.0
    results = []
    for idx, value in monthly_return.items():
        month_str = pd.to_datetime(idx).strftime("%Y-%m")
        ret = first_ret if (pd.isna(value) or idx == first_ts) else float(value)
        results.append({"month": month_str, "return": ret})
    charts["monthly_returns"] = results


def _format_pct(value) -> str | None:
    if value is None:
        return None
    try:
        num = float(value)
        return f"{'+' if num >= 0 else ''}{num * 100:.2f}%"
    except (ValueError, TypeError):
        return None


def _format_number(value) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return None


class ReportService:
    def list_reports(
        self,
        report_type: str | None = None,
        keyword: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        backtest_items = self._query_backtest_reports()
        event_items = self._query_event_reports()
        factor_items = self._query_factor_reports()

        all_items = backtest_items + event_items + factor_items
        all_items.sort(key=lambda item: (item.get("finished_at") or "", item.get("id") or 0), reverse=True)

        filtered = []
        for item in all_items:
            if report_type and item["type"] != report_type:
                continue
            if status and item["status"] != status:
                continue
            if keyword:
                keyword_lower = keyword.lower()
                searchable = [
                    item.get("title", ""),
                    item.get("source_name", ""),
                    str(item.get("id", "")),
                ]
                if not any(keyword_lower in str(s).lower() for s in searchable):
                    continue
            if start_date:
                item_date = (item.get("finished_at") or item.get("created_at") or "")[:10]
                if item_date and item_date < start_date:
                    continue
            if end_date:
                item_date = (item.get("finished_at") or item.get("created_at") or "")[:10]
                if item_date and item_date > end_date:
                    continue
            filtered.append(item)

        total = len(filtered)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated = filtered[start_idx:end_idx]

        return {
            "items": paginated,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def _query_backtest_reports(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT bt.id, bt.strategy_id, bt.status, bt.start_date, bt.end_date,
                       bt.report_json_path, bt.report_html_path, bt.created_at, bt.finished_at,
                       bt.total_return, bt.max_drawdown, bt.sharpe_ratio,
                       s.name AS strategy_name
                FROM backtest_tasks bt
                LEFT JOIN strategies s ON s.id = bt.strategy_id
                WHERE bt.report_json_path IS NOT NULL
                """
            ).fetchall()

        items = []
        for row in rows:
            payload = dict(row)
            strategy_name = payload.get('strategy_name') or f'策略 #{payload["strategy_id"]}'
            items.append({
                "id": payload["id"],
                "type": "backtest",
                "title": f"{strategy_name} 回测报告",
                "source_name": strategy_name,
                "source_id": payload["strategy_id"],
                "status": payload["status"],
                "created_at": payload["created_at"],
                "finished_at": payload["finished_at"],
                "period": {
                    "start_date": payload["start_date"],
                    "end_date": payload["end_date"],
                },
                "summary": {
                    "primary_label": "总收益",
                    "primary_value": payload.get("total_return"),
                    "primary_display": _format_pct(payload.get("total_return")),
                    "secondary_label": "最大回撤",
                    "secondary_value": payload.get("max_drawdown"),
                    "secondary_display": _format_pct(payload.get("max_drawdown")),
                },
                "artifacts": {
                    "json": bool(payload.get("report_json_path")),
                    "html": bool(payload.get("report_html_path")),
                },
                "open_target": {
                    "tab": "result",
                    "id": payload["id"],
                },
                "download_kind": "backtest",
            })
        return items

    def _query_event_reports(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT et.id, et.event_definition_id, et.status, et.start_date, et.end_date,
                       et.result_json_path, et.created_at, et.finished_at,
                       et.sample_count, et.summary_json,
                       ed.name AS definition_name
                FROM event_analysis_tasks et
                LEFT JOIN event_definitions ed ON ed.id = et.event_definition_id
                WHERE et.result_json_path IS NOT NULL
                """
            ).fetchall()

        items = []
        for row in rows:
            payload = dict(row)
            summary_json = payload.get("summary_json")
            summary_data = json.loads(summary_json) if summary_json else {}
            windows = summary_data.get("windows", [])
            first_window = windows[0] if windows else {}
            definition_name = payload.get('definition_name') or f'事件 #{payload["event_definition_id"]}'

            items.append({
                "id": payload["id"],
                "type": "event_analysis",
                "title": f"{definition_name} 事件分析",
                "source_name": definition_name,
                "source_id": payload["event_definition_id"],
                "status": payload["status"],
                "created_at": payload["created_at"],
                "finished_at": payload["finished_at"],
                "period": {
                    "start_date": payload["start_date"],
                    "end_date": payload["end_date"],
                },
                "summary": {
                    "primary_label": "首窗口均值",
                    "primary_value": first_window.get("avg_return"),
                    "primary_display": _format_pct(first_window.get("avg_return")),
                    "secondary_label": "样本数",
                    "secondary_value": payload.get("sample_count"),
                    "secondary_display": str(payload.get("sample_count", 0)),
                },
                "artifacts": {
                    "json": bool(payload.get("result_json_path")),
                    "html": False,
                },
                "open_target": {
                    "tab": "event_analyses",
                    "id": payload["id"],
                },
                "download_kind": "event_analysis",
            })
        return items

    def _query_factor_reports(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT ft.id, ft.factor_definition_id, ft.status, ft.start_date, ft.end_date,
                       ft.result_json_path, ft.created_at, ft.finished_at,
                       ft.sample_count, ft.summary_json,
                       fd.name AS definition_name
                FROM factor_analysis_tasks ft
                LEFT JOIN factor_definitions fd ON fd.id = ft.factor_definition_id
                WHERE ft.result_json_path IS NOT NULL
                """
            ).fetchall()

        items = []
        for row in rows:
            payload = dict(row)
            summary_json = payload.get("summary_json")
            summary_data = json.loads(summary_json) if summary_json else {}
            ic_data = summary_data.get("ic") or {}
            first_key = next(iter(ic_data), None) if isinstance(ic_data, dict) else None
            first_ic = ic_data.get(first_key, {}) if first_key else {}
            definition_name = payload.get("definition_name") or f'因子 #{payload["factor_definition_id"]}'

            items.append({
                "id": payload["id"],
                "type": "factor_analysis",
                "title": f"{definition_name} 因子分析",
                "source_name": definition_name,
                "source_id": payload["factor_definition_id"],
                "status": payload["status"],
                "created_at": payload["created_at"],
                "finished_at": payload["finished_at"],
                "period": {
                    "start_date": payload["start_date"],
                    "end_date": payload["end_date"],
                },
                "summary": {
                    "primary_label": "首窗口 IC",
                    "primary_value": first_ic.get("mean"),
                    "primary_display": _format_number(first_ic.get("mean")),
                    "secondary_label": "样本数",
                    "secondary_value": payload.get("sample_count"),
                    "secondary_display": str(payload.get("sample_count", 0)),
                },
                "artifacts": {
                    "json": bool(payload.get("result_json_path")),
                    "html": False,
                },
                "open_target": {
                    "tab": "factor_results",
                    "id": payload["id"],
                },
                "download_kind": "factor_analysis",
            })
        return items

    def get_report(self, task_id: int, kind: str = "backtest") -> dict | None:
        if kind == "factor_analysis":
            return self._get_factor_analysis_report(task_id)
        if kind == "event_analysis":
            return self._get_event_analysis_report(task_id)
        return self._get_backtest_report(task_id)

    def _get_backtest_report(self, task_id: int) -> dict | None:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM backtest_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        runtime_logs = self._parse_logs(row["runtime_logs_json"])
        if not row["report_json_path"]:
            payload = {"runtime": {"status": row["status"], "logs": runtime_logs}}
            return {"task": dict(row), "payload": payload}

        path = Path(row["report_json_path"])
        if not path.exists():
            payload = {"runtime": {"status": row["status"], "logs": runtime_logs}}
            return {"task": dict(row), "payload": payload, "warning": "报告文件不存在"}

        payload = json.loads(path.read_text(encoding="utf-8"))
        _patch_monthly_returns(payload)
        runtime_block = payload.setdefault("runtime", {})
        runtime_block["status"] = row["status"]
        runtime_block["logs"] = runtime_logs
        return {"task": dict(row), "payload": payload}

    def _get_event_analysis_report(self, task_id: int) -> dict | None:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM event_analysis_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        runtime_logs = self._parse_logs(row["runtime_logs_json"])
        if not row["result_json_path"]:
            payload = {"runtime": {"status": row["status"], "logs": runtime_logs}}
            return {"task": dict(row), "payload": payload}

        path = Path(row["result_json_path"])
        if not path.exists():
            payload = {"runtime": {"status": row["status"], "logs": runtime_logs}}
            return {"task": dict(row), "payload": payload, "warning": "结果文件不存在"}

        payload = json.loads(path.read_text(encoding="utf-8"))
        runtime_block = payload.setdefault("runtime", {})
        runtime_block.setdefault("status", row["status"])
        runtime_block["logs"] = runtime_logs
        return {"task": dict(row), "payload": payload}

    def _get_factor_analysis_report(self, task_id: int) -> dict | None:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM factor_analysis_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        runtime_logs = self._parse_logs(row["runtime_logs_json"])
        if not row["result_json_path"]:
            payload = {"runtime": {"status": row["status"], "logs": runtime_logs}}
            return {"task": dict(row), "payload": payload}

        path = Path(row["result_json_path"])
        if not path.exists():
            payload = {"runtime": {"status": row["status"], "logs": runtime_logs}}
            return {"task": dict(row), "payload": payload, "warning": "结果文件不存在"}

        payload = json.loads(path.read_text(encoding="utf-8"))
        runtime_block = payload.setdefault("runtime", {})
        runtime_block.setdefault("status", row["status"])
        runtime_block["logs"] = runtime_logs
        return {"task": dict(row), "payload": payload}

    def _parse_logs(self, payload: str | None) -> list[dict]:
        if not payload:
            return []
        try:
            data = json.loads(payload)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def get_report_file(self, task_id: int, file_format: str = "html", kind: str = "backtest") -> Path | None:
        if kind in {"event_analysis", "factor_analysis"}:
            if file_format != "json":
                return None
            column = "result_json_path"
            table = "factor_analysis_tasks" if kind == "factor_analysis" else "event_analysis_tasks"
        else:
            column = "report_html_path" if file_format == "html" else "report_json_path"
            table = "backtest_tasks"
        with get_conn() as conn:
            row = conn.execute(
                f"SELECT {column} AS path FROM {table} WHERE id = ?",
                (task_id,),
            ).fetchone()
        if row is None or not row["path"]:
            return None
        path = Path(row["path"])
        return path if path.exists() and path.is_file() else None

    def delete_report(self, task_id: int, kind: str = "backtest") -> bool:
        if kind == "factor_analysis":
            return self._delete_factor_analysis_report(task_id)
        if kind == "event_analysis":
            return self._delete_event_analysis_report(task_id)
        return self._delete_backtest_report(task_id)

    def _delete_backtest_report(self, task_id: int) -> bool:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT report_json_path, report_html_path, status FROM backtest_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] in ("queued", "running"):
                raise ValueError("运行中的任务不能删除，请先终止任务")
            for file_path in [row["report_json_path"], row["report_html_path"]]:
                if file_path:
                    path = Path(file_path)
                    if path.exists() and path.is_file():
                        path.unlink()
            conn.execute("DELETE FROM backtest_tasks WHERE id = ?", (task_id,))
        return True

    def _delete_event_analysis_report(self, task_id: int) -> bool:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT result_json_path, status FROM event_analysis_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] in ("queued", "running"):
                raise ValueError("运行中的任务不能删除，请先终止任务")
            if row["result_json_path"]:
                path = Path(row["result_json_path"])
                if path.exists() and path.is_file():
                    path.unlink()
            conn.execute("DELETE FROM event_analysis_tasks WHERE id = ?", (task_id,))
        return True

    def _delete_factor_analysis_report(self, task_id: int) -> bool:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT result_json_path, status FROM factor_analysis_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] in ("queued", "running"):
                raise ValueError("运行中的任务不能删除，请先终止任务")
            if row["result_json_path"]:
                path = Path(row["result_json_path"])
                if path.exists() and path.is_file():
                    path.unlink()
            conn.execute("DELETE FROM factor_analysis_tasks WHERE id = ?", (task_id,))
        return True
