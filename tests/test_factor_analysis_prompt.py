from __future__ import annotations

import unittest

from backend.services.ai_factor_analysis_prompt import FACTOR_ANALYSIS_SYSTEM_PROMPT
from backend.services.factor_definition_service import FactorDefinitionService


class FactorAnalysisPromptTest(unittest.TestCase):
    def test_prompt_documents_factor_boundaries_and_output_contract(self):
        required_phrases = [
            "FactorAnalysisTemplate",
            "compute(self, context)",
            "ts_code",
            "trade_date",
            "factor_value",
            "不要自己计算未来收益",
            "不要写账户、仓位、订单",
            "只输出一个 JSON 对象",
            "daily_bar",
            "daily_basic",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, FACTOR_ANALYSIS_SYSTEM_PROMPT)

    def test_parse_ai_json_accepts_fenced_json(self):
        content = """```json
{"name":"动量因子","key":"momentum_factor","description":"x","tags":["因子"],"code":"print(1)"}
```"""
        parsed = FactorDefinitionService()._parse_ai_json(content)
        self.assertEqual(parsed["key"], "momentum_factor")


if __name__ == "__main__":
    unittest.main()
