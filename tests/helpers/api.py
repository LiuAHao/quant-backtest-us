from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.db.database as database
import backend.services.backtest_service as backtest_service
import backend.services.strategy_service as strategy_service
from backend.main import app
from tests.helpers.market_data import write_calendar
from tests.helpers.temp_env import TempProjectEnv


VALID_STRATEGY_CODE = """
from backtest.strategy import StrategyTemplate


class DemoStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("Demo")

    def init(self, context):
        self.count = 0

    def next(self, context):
        self.count += 1
""".strip()


class NoopExecutor:
    def submit(self, func, *args, **kwargs):
        return None


class ApiTestCase(unittest.TestCase):
    client: TestClient

    def setUp(self):
        self.env = TempProjectEnv.under_cwd(self._testMethodName)
        self.tmp_path = self.env.root
        self.storage = self.env.storage
        self.data_dir = self.env.data_dir
        self.generated = self.storage / "strategies"
        write_calendar(
            self.data_dir,
            [
                {
                    "trade_date": "2026-01-01",
                    "is_open": 1,
                    "pretrade_date": None,
                    "next_trade_date": "2026-01-02",
                    "prev_trade_date": None,
                },
                {
                    "trade_date": "2026-01-02",
                    "is_open": 1,
                    "pretrade_date": "2026-01-01",
                    "next_trade_date": "2026-01-31",
                    "prev_trade_date": "2026-01-01",
                },
                {
                    "trade_date": "2026-01-31",
                    "is_open": 1,
                    "pretrade_date": "2026-01-02",
                    "next_trade_date": None,
                    "prev_trade_date": "2026-01-02",
                },
            ],
        )
        self.env.patch_data_dirs().patch_database(GENERATED_STRATEGY_DIR=self.generated).start()
        self.patchers = [
            patch.object(strategy_service, "GENERATED_STRATEGY_DIR", self.generated),
        ]
        for patcher in self.patchers:
            patcher.start()
        database.init_db()
        self.client = TestClient(app)

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.env.stop()


def create_strategy(client: TestClient, key: str = "demo_strategy", name: str = "Demo Strategy", code: str = VALID_STRATEGY_CODE) -> dict:
    response = client.post(
        "/api/strategies",
        json={
            "key": key,
            "name": name,
            "description": "测试策略",
            "source": "manual",
            "tags": ["测试"],
            "code": code,
            "status": "enabled",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_backtest_task(client: TestClient, strategy_id: int, **overrides) -> dict:
    payload = {
        "strategy_id": strategy_id,
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "initial_capital": 1000000,
        "commission_rate": 0.0003,
        "slippage": 0.001,
    }
    payload.update(overrides)
    with patch.object(backtest_service, "EXECUTOR", NoopExecutor()):
        response = client.post("/api/backtests", json=payload)
    assert response.status_code == 200, response.text
    return response.json()
