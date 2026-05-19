from __future__ import annotations

from unittest.mock import patch

import backend.db.database as database
import backend.services.backtest_service as backtest_service
from tests.helpers.api import ApiTestCase, NoopExecutor, create_backtest_task, create_strategy


class BacktestApiTest(ApiTestCase):
    def test_backtest_create_requires_valid_payload(self):
        response = self.client.post("/api/backtests", json={"strategy_id": None})
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        fields = {".".join(str(part) for part in item["loc"]) for item in detail}
        self.assertIn("body.strategy_id", fields)
        self.assertIn("body.start_date", fields)
        self.assertIn("body.end_date", fields)

    def test_backtest_create_rejects_invalid_date_ranges(self):
        strategy_id = create_strategy(self.client)["id"]

        response = self.client.post(
            "/api/backtests",
            json={
                "strategy_id": strategy_id,
                "start_date": "2026-02-01",
                "end_date": "2026-01-31",
                "initial_capital": 1000000,
                "commission_rate": 0.0003,
                "slippage": 0.001,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能晚于结束日期", response.json()["detail"])

        response = self.client.post(
            "/api/backtests",
            json={
                "strategy_id": strategy_id,
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "initial_capital": 1000000,
                "commission_rate": 0.0003,
                "slippage": 0.001,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("超出数据范围", response.json()["detail"])

    def test_backtest_templates_list_create_and_delete(self):
        response = self.client.get("/api/backtest-templates")
        self.assertEqual(response.status_code, 200)
        templates = response.json()
        self.assertEqual(len(templates), 3)
        self.assertTrue(all(item["kind"] == "builtin" for item in templates))

        create_response = self.client.post(
            "/api/backtest-templates",
            json={
                "name": "2025 开年至今",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "initial_capital": 2000000,
                "commission_rate": 0.0005,
                "slippage": 0.002,
                "benchmark": "zz500",
            },
        )
        self.assertEqual(create_response.status_code, 200)
        created = create_response.json()
        self.assertEqual(created["kind"], "saved")
        self.assertEqual(created["benchmark"], "zz500")
        self.assertIsNotNone(created["db_id"])

        response = self.client.get("/api/backtest-templates")
        self.assertEqual(response.status_code, 200)
        templates = response.json()
        self.assertEqual(len(templates), 4)
        self.assertEqual(templates[3]["id"], created["id"])

        delete_response = self.client.delete(f"/api/backtest-templates/{created['db_id']}")
        self.assertEqual(delete_response.status_code, 204)

    def test_backtest_template_rejects_invalid_range(self):
        response = self.client.post(
            "/api/backtest-templates",
            json={
                "name": "非法模板",
                "start_date": "2026-01-31",
                "end_date": "2026-01-01",
                "initial_capital": 1000000,
                "commission_rate": 0.0003,
                "slippage": 0.001,
                "benchmark": "hs300",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能晚于结束日期", response.json()["detail"])

    def test_backtest_page_default(self):
        strategy_id = create_strategy(self.client, key="page_strat", name="Page Strategy")["id"]
        for _ in range(3):
            create_backtest_task(self.client, strategy_id)
        resp = self.client.get("/api/backtests/page")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["page_size"], 20)
        self.assertEqual(len(body["items"]), 3)

    def test_backtest_page_with_pagination(self):
        strategy_id = create_strategy(self.client, key="page_strat2", name="Page Strategy 2")["id"]
        for _ in range(5):
            create_backtest_task(self.client, strategy_id)
        resp = self.client.get("/api/backtests/page?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 5)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["page_size"], 2)

        resp2 = self.client.get("/api/backtests/page?page=3&page_size=2")
        self.assertEqual(resp2.status_code, 200)
        body2 = resp2.json()
        self.assertEqual(body2["total"], 5)
        self.assertEqual(len(body2["items"]), 1)

    def test_backtest_page_filter_by_status(self):
        strategy_id = create_strategy(self.client, key="page_strat3", name="Page Strategy 3")["id"]
        t1 = create_backtest_task(self.client, strategy_id)
        t2 = create_backtest_task(self.client, strategy_id)
        with database.get_conn() as conn:
            conn.execute("UPDATE backtest_tasks SET status = 'success' WHERE id = ?", (t2["id"],))
        resp = self.client.get("/api/backtests/page?status=queued")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["id"], t1["id"])

    def test_backtest_page_keyword_search(self):
        strategy_id = create_strategy(self.client, key="search_me", name="Searchable Strategy")["id"]
        create_backtest_task(self.client, strategy_id)
        resp = self.client.get("/api/backtests/page?keyword=search_me")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)

        resp2 = self.client.get("/api/backtests/page?keyword=nonexistent")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["total"], 0)

    def test_backtest_batch_delete(self):
        strategy_id = create_strategy(self.client, key="batch_strat", name="Batch Strategy")["id"]
        t1 = create_backtest_task(self.client, strategy_id)
        t2 = create_backtest_task(self.client, strategy_id)
        with database.get_conn() as conn:
            conn.execute("UPDATE backtest_tasks SET status = 'success' WHERE id IN (?, ?)", (t1["id"], t2["id"]))
        resp = self.client.post("/api/backtests/batch-delete", json={"ids": [t1["id"], t2["id"], 99999]})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(sorted(body["deleted_ids"]), sorted([t1["id"], t2["id"]]))
        self.assertEqual(len(body["failed"]), 1)
        self.assertEqual(body["failed"][0]["id"], 99999)

    def test_backtest_batch_delete_refuses_running(self):
        strategy_id = create_strategy(self.client, key="batch_strat2", name="Batch Strategy 2")["id"]
        t1 = create_backtest_task(self.client, strategy_id)
        resp = self.client.post("/api/backtests/batch-delete", json={"ids": [t1["id"]]})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(len(body["deleted_ids"]), 0)
        self.assertIn("终止", body["failed"][0]["reason"])

    def test_backtest_batch_delete_all_missing(self):
        resp = self.client.post("/api/backtests/batch-delete", json={"ids": [99991, 99992]})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["deleted_ids"], [])
        self.assertEqual(len(body["failed"]), 2)

    def test_backtest_list_unchanged(self):
        strategy_id = create_strategy(self.client, key="compat_strat", name="Compat Strategy")["id"]
        create_backtest_task(self.client, strategy_id)
        resp = self.client.get("/api/backtests")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)
        self.assertEqual(len(resp.json()), 1)

    def test_backtest_benchmark_exposed_in_api(self):
        strategy_id = create_strategy(self.client, key="bm_strat", name="Benchmark Strategy")["id"]
        with patch.object(backtest_service, "EXECUTOR", NoopExecutor()):
            create_resp = self.client.post(
                "/api/backtests",
                json={
                    "strategy_id": strategy_id,
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                    "initial_capital": 1000000,
                    "commission_rate": 0.0003,
                    "slippage": 0.001,
                    "benchmark": "zz500",
                },
            )
        self.assertEqual(create_resp.status_code, 200)
        task = create_resp.json()
        self.assertEqual(task["benchmark"], "zz500")
        task_id = task["id"]

        get_resp = self.client.get(f"/api/backtests/{task_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["benchmark"], "zz500")

        list_resp = self.client.get("/api/backtests")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.json()[0]["benchmark"], "zz500")

        page_resp = self.client.get("/api/backtests/page")
        self.assertEqual(page_resp.status_code, 200)
        self.assertEqual(page_resp.json()["items"][0]["benchmark"], "zz500")
