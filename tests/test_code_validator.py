from __future__ import annotations

import unittest

from backend.services.event_analysis_validator import EventAnalysisValidator
from backend.services.strategy_validator import StrategyValidator


VALID_STRATEGY = """
from backtest.strategy import StrategyTemplate


class DemoStrategy(StrategyTemplate):
    def init(self, context):
        pass

    def next(self, context):
        pass
""".strip()


VALID_EVENT = """
from event_analysis.template import EventAnalysisTemplate


class DemoEvent(EventAnalysisTemplate):
    def scan(self, context):
        return context["data"].head(0)
""".strip()


class CodeValidatorSecurityTest(unittest.TestCase):
    def test_strategy_validator_rejects_introspection_calls(self):
        code = VALID_STRATEGY.replace("pass", "globals()", 1)
        result = StrategyValidator().validate(code)
        self.assertFalse(result.ok)
        self.assertIn("globals", result.message)

    def test_strategy_validator_rejects_dunder_attribute_chain(self):
        code = VALID_STRATEGY.replace("pass", "x = ().__class__.__mro__", 1)
        result = StrategyValidator().validate(code)
        self.assertFalse(result.ok)
        self.assertIn("__class__", result.message)

    def test_strategy_validator_rejects_pickle_import(self):
        code = "import pickle\n" + VALID_STRATEGY
        result = StrategyValidator().validate(code)
        self.assertFalse(result.ok)
        self.assertIn("import pickle", result.message)

    def test_event_validator_rejects_introspection_calls(self):
        code = VALID_EVENT.replace('return context["data"].head(0)', "return locals()")
        result = EventAnalysisValidator().validate(code)
        self.assertFalse(result.ok)
        self.assertIn("locals", result.message)

    def test_valid_code_still_passes(self):
        self.assertTrue(StrategyValidator().validate(VALID_STRATEGY).ok)
        self.assertTrue(EventAnalysisValidator().validate(VALID_EVENT).ok)


if __name__ == "__main__":
    unittest.main()
