from __future__ import annotations

import json

import backend.db.database as database
import backend.services.backtest_service as backtest_service
from tests.helpers.api import ApiTestCase, NoopExecutor, VALID_STRATEGY_CODE, create_strategy
from unittest.mock import patch


class ReportApiTest(ApiTestCase):
    def test_report_download_includes_runtime_logs_and_escapes_html(self):
        strategy_id = create_strategy(self.client, key="report_demo_strategy", name="Report Demo Strategy", code=VALID_STRATEGY_CODE)["id"]

        with patch.object(backtest_service, "EXECUTOR", NoopExecutor()):
            create_task = self.client.post(
                "/api/backtests",
                json={
                    "strategy_id": strategy_id,
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                    "initial_capital": 1000000,
                    "commission_rate": 0.0003,
                    "slippage": 0.001,
                },
            )
        self.assertEqual(create_task.status_code, 200)
        task_id = create_task.json()["id"]

        report_json = self.tmp_path / "report.json"
        report_html = self.tmp_path / "report.html"
        runtime_logs = [
            {
                "timestamp": "2026-05-06 09:34:03",
                "level": "ERROR",
                "source": "demo.source",
                "message": 'failure <script>alert("x")</script>',
            }
        ]
        report_json.write_text(json.dumps({"runtime": {"status": "success", "logs": []}}, ensure_ascii=False), encoding="utf-8")
        report_html.write_text("<html><body><h1>Report</h1></body></html>", encoding="utf-8")

        with database.get_conn() as conn:
            conn.execute(
                """
                UPDATE backtest_tasks
                SET status = 'success',
                    report_json_path = ?,
                    report_html_path = ?,
                    runtime_logs_json = ?,
                    finished_at = '2026-05-06 09:34:03'
                WHERE id = ?
                """,
                (str(report_json), str(report_html), json.dumps(runtime_logs, ensure_ascii=False), task_id),
            )

        json_response = self.client.get(f"/api/reports/{task_id}/download?kind=backtest&format=json")
        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(json_response.json()["runtime"]["logs"][0]["timestamp"], "2026-05-06 09:34:03")

        html_response = self.client.get(f"/api/reports/{task_id}/download?kind=backtest&format=html")
        self.assertEqual(html_response.status_code, 200)
        body = html_response.text
        self.assertIn("运行日志", body)
        self.assertIn("2026-05-06 09:34:03", body)
        self.assertIn("demo.source", body)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", body)
        self.assertNotIn('<script>alert("x")</script>', body)

    def test_cancelled_task_cleans_orphan_reports(self):
        strategy_id = create_strategy(self.client, key="cleanup_strategy", name="Cleanup Strategy", code=VALID_STRATEGY_CODE)["id"]

        with patch.object(backtest_service, "EXECUTOR", NoopExecutor()):
            task_response = self.client.post(
                "/api/backtests",
                json={
                    "strategy_id": strategy_id,
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                    "initial_capital": 1000000,
                    "commission_rate": 0.0003,
                    "slippage": 0.001,
                },
            )
        self.assertEqual(task_response.status_code, 200)
        task_id = task_response.json()["id"]

        report_json = self.tmp_path / "orphan.json"
        report_html = self.tmp_path / "orphan.html"

        service = backtest_service.BacktestService()

        class FakeStrategy:
            @staticmethod
            def get_callbacks():
                return (lambda context: None, lambda context: None)

        class FakeResult:
            total_return = 0.0
            max_drawdown = 0.0
            sharpe_ratio = 0.0

        class FakeEngine:
            def __init__(self, *args, **kwargs):
                self.last_report_paths = {"json": report_json, "html": report_html}
                self.report_enricher = None

            def set_strategy(self, init_func, next_func):
                return None

            def set_report_enricher(self, enricher):
                self.report_enricher = enricher

            def run(self):
                report_json.write_text("{}", encoding="utf-8")
                report_html.write_text("<html></html>", encoding="utf-8")
                service._update_task(
                    task_id,
                    status="cancelled",
                    progress=100,
                    error_message="用户手动终止回测",
                    finished_at=service._now(),
                )
                return FakeResult()

        with (
            patch.object(service.loader, "load", return_value=FakeStrategy()),
            patch.object(backtest_service, "BacktestEngine", FakeEngine),
        ):
            service._run_task(task_id)

        self.assertFalse(report_json.exists())
        self.assertFalse(report_html.exists())

        task = self.client.get(f"/api/backtests/{task_id}")
        self.assertEqual(task.status_code, 200)
        self.assertEqual(task.json()["status"], "cancelled")
