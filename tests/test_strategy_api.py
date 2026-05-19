from __future__ import annotations

from unittest.mock import patch

import backend.services.backtest_service as backtest_service
import backend.services.strategy_service as strategy_service
from tests.helpers.api import ApiTestCase, NoopExecutor, VALID_STRATEGY_CODE


class StrategyApiTest(ApiTestCase):
    def test_strategy_validate_and_create(self):
        validate_response = self.client.post("/api/strategies/validate", json={"code": VALID_STRATEGY_CODE})
        self.assertEqual(validate_response.status_code, 200)
        self.assertTrue(validate_response.json()["ok"])

        create_response = self.client.post(
            "/api/strategies",
            json={
                "key": "demo_strategy",
                "name": "Demo Strategy",
                "description": "测试策略",
                "source": "manual",
                "tags": ["测试"],
                "code": VALID_STRATEGY_CODE,
                "status": "enabled",
            },
        )
        self.assertEqual(create_response.status_code, 200)
        created = create_response.json()
        self.assertEqual(created["name"], "Demo Strategy")
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["validation_status"], "passed")

        list_response = self.client.get("/api/strategies")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

    def test_ai_fill_and_backtest_task_creation(self):
        ai_draft = {
            "name": "AI 策略草稿",
            "key": "ai_demo_strategy",
            "source": "AI生成",
            "description": "测试用 AI 策略草稿",
            "tags": ["AI生成", "策略草稿"],
            "code": VALID_STRATEGY_CODE,
        }
        with (
            patch.object(backtest_service, "EXECUTOR", NoopExecutor()),
            patch.object(strategy_service.StrategyService, "ai_fill", return_value=ai_draft),
        ):
            ai_response = self.client.post("/api/strategies/ai-fill", json={"prompt": "选出放量突破的小市值股票"})
            self.assertEqual(ai_response.status_code, 200)
            draft = ai_response.json()
            self.assertIn("code", draft)

            create_strategy = self.client.post(
                "/api/strategies",
                json={
                    "key": "ai_demo_strategy",
                    "name": draft["name"],
                    "description": draft["description"],
                    "source": "ai",
                    "tags": draft["tags"],
                    "code": draft["code"],
                    "status": "enabled",
                },
            )
            self.assertEqual(create_strategy.status_code, 200)
            strategy_id = create_strategy.json()["id"]

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
            task = create_task.json()
            self.assertEqual(task["strategy_id"], strategy_id)
            self.assertEqual(task["status"], "queued")

            list_tasks = self.client.get("/api/backtests")
            self.assertEqual(list_tasks.status_code, 200)
            self.assertEqual(len(list_tasks.json()), 1)

    def test_list_strategies_repairs_low_quality_ai_metadata_from_code(self):
        code = '''
from backtest.strategy import StrategyTemplate

"""
主板40日反转年报盈利低PE月调仓V2

Tags: ["主板", "40日反转", "年报盈利", "低PE", "月调仓"]
"""


class MainboardReversal40AnnualProfitLowPeMonthlyV2(StrategyTemplate):
    def __init__(self):
        super().__init__("主板40日反转年报盈利低PE月调仓V2")

    def init(self, context):
        pass

    def next(self, context):
        pass
'''.strip()
        create_response = self.client.post(
            "/api/strategies",
            json={
                "key": "mainboard_reversal40_annual_profit_low_pe_monthly_v2",
                "name": "MainboardReversal40AnnualProfitLowPeMonthlyV2",
                "description": "AI生成的Mainboard Reversal40 Annual Profit Low Pe Monthly V2策略",
                "source": "ai",
                "tags": ["AI生成", "量化策略"],
                "code": code,
                "status": "enabled",
            },
        )
        self.assertEqual(create_response.status_code, 200)

        list_response = self.client.get("/api/strategies")
        self.assertEqual(list_response.status_code, 200)
        repaired = next(item for item in list_response.json() if item["key"] == "mainboard_reversal40_annual_profit_low_pe_monthly_v2")
        self.assertEqual(repaired["name"], "主板40日反转年报盈利低PE月调仓V2")
        self.assertEqual(repaired["description"], "主板40日反转年报盈利低PE月调仓V2")
        self.assertEqual(repaired["tags"], ["主板", "40日反转", "年报盈利", "低PE", "月调仓"])

    def test_list_strategies_infers_tags_from_strategy_doc_when_tags_missing(self):
        code = '''
"""
沪深主板 市值+波动 策略 v1

逻辑：
1. 股票池：沪深主板（排除创业板/科创板/北交所/ST）
2. close > 0，按流通市值升序取前200只
3. 计算近20日波动率，剔除波动率最高30%
"""

from backtest.strategy import StrategyTemplate


class MainboardSizeLowVolV1(StrategyTemplate):
    def __init__(self):
        super().__init__("主板市值波动V1")

    def init(self, context):
        pass

    def next(self, context):
        pass
'''.strip()
        create_response = self.client.post(
            "/api/strategies",
            json={
                "key": "mainboard_size_lowvol_v1",
                "name": "主板市值波动V1",
                "description": "沪深主板 市值+波动 策略 v1",
                "source": "manual",
                "tags": [],
                "code": code,
                "status": "enabled",
            },
        )
        self.assertEqual(create_response.status_code, 200)

        list_response = self.client.get("/api/strategies")
        self.assertEqual(list_response.status_code, 200)
        repaired = next(item for item in list_response.json() if item["key"] == "mainboard_size_lowvol_v1")
        self.assertEqual(repaired["tags"], ["主板", "市值", "小市值", "波动", "低波"])

    def test_strategy_version_history(self):
        resp = self.client.post(
            "/api/strategies",
            json={
                "key": "ver_strategy",
                "name": "Version Strategy",
                "description": "版本测试",
                "source": "manual",
                "tags": [],
                "code": VALID_STRATEGY_CODE,
                "status": "enabled",
            },
        )
        self.assertEqual(resp.status_code, 200)
        strategy_id = resp.json()["id"]
        self.assertEqual(resp.json()["version"], 1)

        resp2 = self.client.put(
            f"/api/strategies/{strategy_id}",
            json={"code": VALID_STRATEGY_CODE.replace("count = 0", "count = 1")},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["version"], 2)

        versions_resp = self.client.get(f"/api/strategies/{strategy_id}/versions")
        self.assertEqual(versions_resp.status_code, 200)
        versions = versions_resp.json()
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["version"], 2)
        self.assertEqual(versions[1]["version"], 1)
        self.assertEqual(versions[0]["strategy_id"], strategy_id)
        self.assertIn("code_length", versions[0])
        self.assertIn("created_at", versions[0])
        self.assertIn("code_hash", versions[0])

    def test_strategy_version_history_404(self):
        resp = self.client.get("/api/strategies/99999/versions")
        self.assertEqual(resp.status_code, 404)
