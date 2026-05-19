from __future__ import annotations

from tests.helpers.api import ApiTestCase


class ConfigApiTest(ApiTestCase):
    def test_settings_include_data_window(self):
        response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"]["earliest_trade_date"], "2026-01-01")
        self.assertEqual(payload["data"]["latest_trade_date"], "2026-01-31")

    def test_settings_update_is_whitelisted_and_partial(self):
        response = self.client.put(
            "/api/settings",
            json={
                "backtest": {"initial_capital": 2000000},
                "AI_API_KEY": "should-not-be-stored",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["backtest"]["initial_capital"], 2000000)
        self.assertEqual(payload["backtest"]["commission_rate"], 0.0003)
        self.assertNotIn("AI_API_KEY", payload)

    def test_settings_patch_uses_same_schema(self):
        response = self.client.patch("/api/settings", json={"ui": {"theme": "dark"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ui"]["theme"], "dark")

    def test_settings_rejects_invalid_known_value(self):
        response = self.client.put("/api/settings", json={"backtest": {"commission_rate": 2}})
        self.assertEqual(response.status_code, 422)

    def test_config_presets_crud(self):
        resp = self.client.get("/api/config/presets")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

        create_resp = self.client.post(
            "/api/config/presets",
            json={
                "name": "测试预设",
                "description": "描述",
                "initial_capital": 2000000,
                "commission_rate": 0.0005,
                "slippage": 0.002,
                "benchmark": "zz500",
                "is_default": True,
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        preset = create_resp.json()
        self.assertEqual(preset["name"], "测试预设")
        self.assertEqual(preset["benchmark"], "zz500")
        self.assertTrue(preset["is_default"])
        preset_id = preset["id"]

        default_resp = self.client.get("/api/config/presets/default")
        self.assertEqual(default_resp.status_code, 200)
        self.assertEqual(default_resp.json()["id"], preset_id)

        get_resp = self.client.get(f"/api/config/presets/{preset_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["name"], "测试预设")

        update_resp = self.client.put(
            f"/api/config/presets/{preset_id}",
            json={
                "name": "更新预设",
                "description": "更新描述",
                "initial_capital": 3000000,
                "commission_rate": 0.0003,
                "slippage": 0.001,
                "benchmark": "hs300",
                "is_default": False,
            },
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["name"], "更新预设")
        self.assertFalse(update_resp.json()["is_default"])

        delete_resp = self.client.delete(f"/api/config/presets/{preset_id}")
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["ok"])

        get_after_delete = self.client.get(f"/api/config/presets/{preset_id}")
        self.assertEqual(get_after_delete.status_code, 404)

    def test_config_presets_404(self):
        resp = self.client.get("/api/config/presets/99999")
        self.assertEqual(resp.status_code, 404)

        resp2 = self.client.put(
            "/api/config/presets/99999",
            json={
                "name": "不存在",
                "description": "",
                "initial_capital": 1000000,
                "commission_rate": 0.0003,
                "slippage": 0.001,
                "benchmark": "hs300",
                "is_default": False,
            },
        )
        self.assertEqual(resp2.status_code, 404)

        resp3 = self.client.delete("/api/config/presets/99999")
        self.assertEqual(resp3.status_code, 404)

    def test_config_agents_crud(self):
        resp = self.client.get("/api/config/agents")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

        create_resp = self.client.post(
            "/api/config/agents",
            json={
                "name": "测试Agent",
                "description": "描述",
                "api_endpoint": "http://localhost:8000",
                "api_key": "secret-key-12345",
                "auto_run": True,
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        agent = create_resp.json()
        self.assertEqual(agent["name"], "测试Agent")
        self.assertTrue(agent["auto_run"])
        self.assertNotEqual(agent["api_key"], "secret-key-12345")
        agent_id = agent["id"]

        get_resp = self.client.get(f"/api/config/agents/{agent_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["name"], "测试Agent")

        update_resp = self.client.put(
            f"/api/config/agents/{agent_id}",
            json={
                "name": "更新Agent",
                "description": "更新描述",
                "api_endpoint": "http://localhost:9000",
                "api_key": "new-key-67890",
                "auto_run": False,
            },
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["name"], "更新Agent")
        self.assertFalse(update_resp.json()["auto_run"])

        delete_resp = self.client.delete(f"/api/config/agents/{agent_id}")
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["ok"])

        get_after_delete = self.client.get(f"/api/config/agents/{agent_id}")
        self.assertEqual(get_after_delete.status_code, 404)

    def test_config_agents_404(self):
        resp = self.client.get("/api/config/agents/99999")
        self.assertEqual(resp.status_code, 404)

        resp2 = self.client.put(
            "/api/config/agents/99999",
            json={
                "name": "不存在",
                "description": "",
                "api_endpoint": "http://localhost:8000",
            },
        )
        self.assertEqual(resp2.status_code, 404)

        resp3 = self.client.delete("/api/config/agents/99999")
        self.assertEqual(resp3.status_code, 404)

    def test_config_system_info(self):
        resp = self.client.get("/api/config/system-info")
        self.assertEqual(resp.status_code, 200)
        info = resp.json()
        self.assertIn("version", info)
        self.assertIn("data_dir", info)
        self.assertIn("db_path", info)
        self.assertIn("total_strategies", info)
        self.assertIn("total_backtests", info)
        self.assertIn("total_presets", info)
        self.assertIn("available_data_range", info)
