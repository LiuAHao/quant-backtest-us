from __future__ import annotations

import unittest

from tests.test_factor_analysis_platform import FactorAnalysisPlatformTest, VALID_FACTOR_CODE


class FactorReportApiTest(FactorAnalysisPlatformTest):
    def test_factor_report_download_json(self):
        definition = self._create_definition(key="report_factor", name="报告测试因子", code=VALID_FACTOR_CODE)
        task = self._create_task(definition["id"], windows=[1])

        import backend.services.factor_analysis_service as factor_analysis_service

        factor_analysis_service.FactorAnalysisService()._run_task(task["id"])
        response = self.client.get(f"/api/reports/{task['id']}/download?kind=factor_analysis&format=json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("summary", payload)
        self.assertIn("charts", payload)
        self.assertIn("tables", payload)
        self.assertIn("runtime", payload)

    def test_factor_report_download_rejects_html(self):
        definition = self._create_definition(key="html_report_factor", name="HTML报告测试因子", code=VALID_FACTOR_CODE)
        task = self._create_task(definition["id"], windows=[1])

        response = self.client.get(f"/api/reports/{task['id']}/download?kind=factor_analysis&format=html")
        self.assertEqual(response.status_code, 400)
        self.assertIn("只支持 json 下载", response.json()["detail"])

    def test_factor_report_download_includes_failed_runtime_logs(self):
        failing_code = VALID_FACTOR_CODE.replace(
            '        market_data = context["market_data"]\n        return pd.DataFrame({',
            '        raise RuntimeError("boom")\n        return pd.DataFrame({',
        )
        definition = self._create_definition(key="failed_report_factor", name="失败报告测试因子", code=failing_code)

        import backend.services.factor_analysis_service as factor_analysis_service

        task = self._create_task(definition["id"], windows=[1])
        factor_analysis_service.FactorAnalysisService()._run_task(task["id"])

        response = self.client.get(f"/api/reports/{task['id']}?kind=factor_analysis")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["task"]["status"], "failed")
        self.assertEqual(payload["payload"]["runtime"]["status"], "failed")
        self.assertTrue(payload["payload"]["runtime"]["logs"])


if __name__ == "__main__":
    unittest.main()
