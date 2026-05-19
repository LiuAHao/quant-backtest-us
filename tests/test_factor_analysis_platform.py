from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import backend.db.database as database
import config
from backend.main import app
from tests.helpers.market_data import write_calendar, write_daily_bar, write_daily_basic, write_instruments
from tests.helpers.temp_env import TempProjectEnv


VALID_FACTOR_CODE = """
from __future__ import annotations

import pandas as pd

from factor_analysis.template import FactorAnalysisTemplate


class CloseFactor(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__("收盘价因子")

    def compute(self, context):
        market_data = context["market_data"]
        return pd.DataFrame({
            "ts_code": market_data["ts_code"],
            "trade_date": context["current_date"].strftime("%Y-%m-%d"),
            "factor_value": market_data["close"],
        })
""".strip()


class NoopExecutor:
    def submit(self, func, *args, **kwargs):
        return None


def _write_fixture_market_data(data_dir: Path) -> None:
    dates = pd.date_range("2026-01-01", periods=40, freq="B").strftime("%Y-%m-%d").tolist()
    write_calendar(
        data_dir,
        [
            {
                "trade_date": date,
                "is_open": 1,
                "pretrade_date": dates[idx - 1] if idx else None,
                "next_trade_date": dates[idx + 1] if idx + 1 < len(dates) else None,
                "prev_trade_date": dates[idx - 1] if idx else None,
            }
            for idx, date in enumerate(dates)
        ],
    )

    rows = []
    basic_rows = []
    codes = ["000001.SZ", "000002.SZ", "600000.SH", "600001.SH"]
    for idx, date in enumerate(dates):
        for rank, code in enumerate(codes, start=1):
            close = 10 + rank + idx * rank
            rows.append(
                {
                    "ts_code": code,
                    "trade_date": date,
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": float(close),
                    "pre_close": float(close - rank if idx else close),
                    "volume": 1000 * rank,
                    "amount": 10000 * rank,
                }
            )
            basic_rows.append(
                {
                    "ts_code": code,
                    "trade_date": date,
                    "circ_mv": 100000 * rank,
                    "total_mv": 120000 * rank,
                    "total_share": 1000,
                    "float_share": 800,
                    "free_share": 700,
                    "turnover_rate": 1.0,
                    "pe_ttm": 10.0,
                    "pb": 1.0,
                }
            )
    write_daily_bar(data_dir, rows, partition="year=2026")
    write_daily_basic(data_dir, basic_rows, partition="year=2026")
    write_instruments(
        data_dir,
        [
            {"ts_code": "000001.SZ", "symbol": "平安银行", "exchange": "SZ", "status": "L", "list_date": "20200101"},
            {"ts_code": "000002.SZ", "symbol": "ST测试", "exchange": "SZ", "status": "L", "list_date": "20200101"},
            {"ts_code": "600000.SH", "symbol": "浦发银行", "exchange": "SH", "status": "L", "list_date": "20200101"},
            {"ts_code": "600001.SH", "symbol": "次新测试", "exchange": "SH", "status": "L", "list_date": "20251215"},
        ],
    )


class FactorAnalysisPlatformTest(unittest.TestCase):
    def setUp(self):
        self.env = TempProjectEnv.under_cwd(self._testMethodName)
        self.tmp_path = self.env.root
        self.storage = self.env.storage
        self.db_path = self.env.db_path
        self.data_dir = self.env.data_dir
        _write_fixture_market_data(self.data_dir)

        import backend.services.factor_definition_service as factor_definition_service
        import backend.services.factor_analysis_service as factor_analysis_service

        self.env.patch_data_dirs().patch_database(
            GENERATED_FACTOR_ANALYSIS_DIR=self.storage / "factor_analyses" / "generated",
            FACTOR_ANALYSIS_RESULT_DIR=self.storage / "factor_analyses" / "results",
        )
        self.patchers = [
            patch.object(factor_definition_service, "GENERATED_FACTOR_ANALYSIS_DIR", self.storage / "factor_analyses" / "generated"),
            patch.object(factor_analysis_service, "FACTOR_ANALYSIS_RESULT_DIR", self.storage / "factor_analyses" / "results"),
            patch.object(factor_analysis_service, "EXECUTOR", NoopExecutor()),
        ]
        self.env.start()
        for patcher in self.patchers:
            patcher.start()

        database.init_db()
        self.client = TestClient(app)

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.env.stop()

    def _create_definition(self, key: str = "close_factor", name: str = "收盘价因子", code: str = VALID_FACTOR_CODE):
        response = self.client.post(
            "/api/factor-definitions",
            json={
                "key": key,
                "name": name,
                "description": "测试因子",
                "source": "manual",
                "tags": ["测试", "因子分析"],
                "code": code,
                "status": "enabled",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _create_task(self, definition_id: int, **overrides):
        payload = {
            "factor_definition_id": definition_id,
            "start_date": "2026-01-01",
            "end_date": "2026-01-08",
            "windows": [1, 2],
            "quantiles": 2,
            "rebalance_rule": "daily",
            "ic_method": "spearman",
            "factor_direction": "higher_better",
        }
        payload.update(overrides)
        response = self.client.post("/api/factor-analyses", json=payload)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_factor_definition_validate_create_and_task_result(self):
        validate = self.client.post("/api/factor-definitions/validate", json={"code": VALID_FACTOR_CODE})
        self.assertEqual(validate.status_code, 200)
        self.assertTrue(validate.json()["ok"])

        definition = self._create_definition()
        self.assertEqual(definition["version"], 1)
        self.assertEqual(definition["validation_status"], "passed")

        task_payload = self._create_task(definition["id"])
        self.assertEqual(task_payload["status"], "queued")

        import backend.services.factor_analysis_service as factor_analysis_service

        factor_analysis_service.FactorAnalysisService()._run_task(task_payload["id"])
        result_response = self.client.get(f"/api/factor-analyses/{task_payload['id']}/result")
        self.assertEqual(result_response.status_code, 200)
        result = result_response.json()
        self.assertEqual(result["task"]["status"], "success")
        payload = result["payload"]
        self.assertEqual(payload["task_id"], task_payload["id"])
        self.assertIn("ic", payload["summary"])
        self.assertIn("group_returns", payload["summary"])
        self.assertIn("coverage_series", payload["charts"])
        self.assertGreater(payload["summary"]["sample_count"], 0)

    def test_factor_validator_rejects_future_return_and_trading_code(self):
        future_code = VALID_FACTOR_CODE.replace("factor_value", "ret_5d")
        response = self.client.post("/api/factor-definitions/validate", json={"code": future_code})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])

        trading_code = VALID_FACTOR_CODE.replace("return pd.DataFrame", "context['buy']('000001.SZ')\n        return pd.DataFrame")
        response = self.client.post("/api/factor-definitions/validate", json={"code": trading_code})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])

    def test_factor_filters_exclude_st_and_new_stock(self):
        definition = self._create_definition(key="filtered_close_factor", name="过滤收盘价因子")
        task = self._create_task(definition["id"], windows=[1], filters=["exclude_st", "exclude_new_stock"])

        import backend.services.factor_analysis_service as factor_analysis_service

        task_id = task["id"]
        factor_analysis_service.FactorAnalysisService()._run_task(task_id)
        result = self.client.get(f"/api/factor-analyses/{task_id}/result").json()
        payload = result["payload"]
        sample_codes = {row["ts_code"] for row in payload["details"]}
        self.assertEqual(sample_codes, {"000001.SZ", "600000.SH"})
        self.assertEqual(payload["summary"]["stock_count"], 2)

    def test_quick_factor_analysis_creates_definition_and_result(self):
        response = self.client.post(
            "/api/factor-analyses/quick",
            json={
                "factor_code": VALID_FACTOR_CODE,
                "start_date": "2026-01-01",
                "end_date": "2026-01-08",
                "windows": [1],
                "quantiles": 2,
            },
        )
        self.assertEqual(response.status_code, 200)
        task = response.json()
        self.assertEqual(task["status"], "queued")

        definitions = self.client.get("/api/factor-definitions")
        self.assertEqual(definitions.status_code, 200)
        items = definitions.json()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["key"].startswith("agent_factor_"))
        self.assertEqual(task["factor_definition_id"], items[0]["id"])

        import backend.services.factor_analysis_service as factor_analysis_service

        factor_analysis_service.FactorAnalysisService()._run_task(task["id"])
        result = self.client.get(f"/api/factor-analyses/{task['id']}/result")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["task"]["status"], "success")

    def test_quick_momentum_20_factor_runs_successfully(self):
        from backend.services.factor_definition_service import MOMENTUM_20_FACTOR_SQL_CODE
        import backend.services.factor_analysis_service as factor_analysis_service

        response = self.client.post(
            "/api/factor-analyses/quick",
            json={
                "factor_code": MOMENTUM_20_FACTOR_SQL_CODE,
                "factor_key": "momentum_20d_test",
                "factor_name": "20日动量因子",
                "start_date": "2026-02-02",
                "end_date": "2026-02-20",
                "windows": [1],
                "quantiles": 2,
                "filters": ["exclude_st", "exclude_new_stock"],
                "preprocessing": {"winsorize": "mad", "standardize": "zscore"},
            },
        )
        self.assertEqual(response.status_code, 200)
        task = response.json()

        factor_analysis_service.FactorAnalysisService()._run_task(task["id"])
        result = self.client.get(f"/api/factor-analyses/{task['id']}/result")
        self.assertEqual(result.status_code, 200)
        payload = result.json()
        self.assertEqual(payload["task"]["status"], "success")
        self.assertGreater(payload["payload"]["summary"]["sample_count"], 0)
        self.assertIn("ic_series", payload["payload"]["charts"])

    def test_factor_analysis_result_for_queued_and_failed_tasks(self):
        definition = self._create_definition()
        queued_task = self._create_task(definition["id"], windows=[1])
        queued_result = self.client.get(f"/api/factor-analyses/{queued_task['id']}/result")
        self.assertEqual(queued_result.status_code, 200)
        self.assertEqual(queued_result.json()["payload"]["runtime"]["status"], "queued")

        failing_code = VALID_FACTOR_CODE.replace(
            '        market_data = context["market_data"]\n        return pd.DataFrame({',
            '        raise RuntimeError("boom")\n        return pd.DataFrame({',
        )
        failing_definition = self._create_definition(key="failing_close_factor", name="失败收盘价因子", code=failing_code)

        import backend.services.factor_analysis_service as factor_analysis_service

        failed_task = self._create_task(failing_definition["id"], windows=[1])
        factor_analysis_service.FactorAnalysisService()._run_task(failed_task["id"])
        failed_result = self.client.get(f"/api/factor-analyses/{failed_task['id']}/result")
        self.assertEqual(failed_result.status_code, 200)
        failed_payload = failed_result.json()
        self.assertEqual(failed_payload["task"]["status"], "failed")
        self.assertIn("boom", failed_payload["task"]["error_message"])
        self.assertEqual(failed_payload["payload"]["runtime"]["status"], "failed")
        self.assertTrue(failed_payload["payload"]["runtime"]["logs"])

    def test_factor_analysis_cancel_delete_and_definition_delete_guard(self):
        definition = self._create_definition(key="cancel_factor", name="取消测试因子")
        task = self._create_task(definition["id"], windows=[1])

        delete_while_queued = self.client.delete(f"/api/factor-analyses/{task['id']}")
        self.assertEqual(delete_while_queued.status_code, 400)

        definition_delete_while_active = self.client.delete(f"/api/factor-definitions/{definition['id']}")
        self.assertEqual(definition_delete_while_active.status_code, 400)

        cancel = self.client.post(f"/api/factor-analyses/{task['id']}/cancel")
        self.assertEqual(cancel.status_code, 200)
        cancelled = cancel.json()
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["progress"], 100)
        self.assertEqual(cancelled["error_message"], "用户手动终止因子分析")

        delete_task = self.client.delete(f"/api/factor-analyses/{task['id']}")
        self.assertEqual(delete_task.status_code, 204)
        self.assertEqual(self.client.get(f"/api/factor-analyses/{task['id']}").status_code, 404)

        delete_definition = self.client.delete(f"/api/factor-definitions/{definition['id']}")
        self.assertEqual(delete_definition.status_code, 200)

    def test_factor_analysis_page_and_batch_delete(self):
        definition = self._create_definition(key="page_factor", name="分页测试因子")
        task_one = self._create_task(definition["id"], windows=[1])
        task_two = self._create_task(definition["id"], windows=[2])

        cancel = self.client.post(f"/api/factor-analyses/{task_two['id']}/cancel")
        self.assertEqual(cancel.status_code, 200)

        page = self.client.get("/api/factor-analyses/page", params={"page": 1, "page_size": 10, "status": "queued", "keyword": "分页测试因子"})
        self.assertEqual(page.status_code, 200)
        page_payload = page.json()
        self.assertEqual(page_payload["page"], 1)
        self.assertEqual(page_payload["page_size"], 10)
        self.assertEqual(page_payload["total"], 1)
        self.assertEqual(len(page_payload["items"]), 1)
        self.assertEqual(page_payload["items"][0]["id"], task_one["id"])

        batch = self.client.post("/api/factor-analyses/batch-delete", json={"ids": [task_one["id"], task_two["id"], 999999]})
        self.assertEqual(batch.status_code, 200)
        batch_payload = batch.json()
        self.assertFalse(batch_payload["ok"])
        self.assertCountEqual(batch_payload["deleted_ids"], [task_two["id"]])
        self.assertEqual(len(batch_payload["failed"]), 2)
        failed_by_id = {item["id"]: item["reason"] for item in batch_payload["failed"]}
        self.assertIn(task_one["id"], failed_by_id)
        self.assertIn("请先终止运行中或排队中的因子分析", failed_by_id[task_one["id"]])
        self.assertIn(999999, failed_by_id)

    def test_momentum_factor_uses_batched_sql_instead_of_per_stock_history(self):
        from backend.services.factor_definition_service import MOMENTUM_20_FACTOR_SQL_CODE
        from factor_analysis.loader import FactorAnalysisLoader
        from backtest.data_loader import DataLoader

        loader = DataLoader()
        factor = FactorAnalysisLoader().load(file_path="momentum_factor_test.py", module_key="momentum_factor_test", code=MOMENTUM_20_FACTOR_SQL_CODE)
        market_data = loader.get_cross_section(datetime(2026, 2, 25), fields=["ts_code", "close"], adjust=None)

        def fail_get_history(*args, **kwargs):
            raise AssertionError("optimized momentum factor should not call get_history")

        context = {
            "current_date": datetime(2026, 2, 25),
            "market_data": market_data,
            "conn": loader.conn,
            "get_history": fail_get_history,
        }
        result = factor.compute(context)
        self.assertFalse(result.empty)
        self.assertEqual(set(result.columns), {"ts_code", "trade_date", "factor_value"})
        self.assertTrue((result["trade_date"] == "2026-02-25").all())
        self.assertTrue(result["factor_value"].notna().all())
        self.assertEqual(set(result["ts_code"]), set(market_data["ts_code"].astype(str)))


if __name__ == "__main__":
    unittest.main()
