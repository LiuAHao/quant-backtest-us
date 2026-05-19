from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.services.strategy_loader import StrategyLoader, StrategyLoadError
from event_analysis.loader import EventAnalysisLoader, EventAnalysisLoadError


VALID_STRATEGY_CODE = """
from backtest.strategy import StrategyTemplate


class DemoStrategy(StrategyTemplate):
    def init(self, context):
        pass

    def next(self, context):
        pass
""".strip()


VALID_EVENT_CODE = """
from event_analysis.template import EventAnalysisTemplate


class DemoEvent(EventAnalysisTemplate):
    def __init__(self):
        super().__init__("demo")

    def scan(self, context):
        return context["data"].head(0)
""".strip()


DANGEROUS_CODES_STRATEGY = {
    "os_import": (
        "import os\n" + VALID_STRATEGY_CODE,
        "import os",
    ),
    "requests_import": (
        "import requests\n" + VALID_STRATEGY_CODE,
        "import requests",
    ),
    "eval_call": (
        VALID_STRATEGY_CODE.replace("pass", "eval('1+1')", 1),
        "eval",
    ),
    "open_call": (
        VALID_STRATEGY_CODE.replace("pass", "open('/etc/passwd')", 1),
        "open",
    ),
    "globals_call": (
        VALID_STRATEGY_CODE.replace("pass", "globals()", 1),
        "globals",
    ),
    "dunder_mro": (
        VALID_STRATEGY_CODE.replace("pass", "x = ().__class__.__mro__", 1),
        "__class__",
    ),
}

DANGEROUS_CODES_EVENT = {
    "os_import": (
        "import os\n" + VALID_EVENT_CODE,
        "import os",
    ),
    "requests_import": (
        "import requests\n" + VALID_EVENT_CODE,
        "import requests",
    ),
    "eval_call": (
        VALID_EVENT_CODE.replace(
            'return context["data"].head(0)', "return eval('1+1')"
        ),
        "eval",
    ),
    "open_call": (
        VALID_EVENT_CODE.replace(
            'return context["data"].head(0)', "open('/tmp/x')"
        ),
        "open",
    ),
    "locals_call": (
        VALID_EVENT_CODE.replace(
            'return context["data"].head(0)', "return locals()"
        ),
        "locals",
    ),
    "dunder_mro": (
        VALID_EVENT_CODE.replace(
            'return context["data"].head(0)', "x = ().__class__.__mro__"
        ),
        "__class__",
    ),
}


class StrategyLoaderValidationTest(unittest.TestCase):
    def test_valid_strategy_code_loads(self):
        loader = StrategyLoader()
        strategy = loader.load(None, "test_valid", code=VALID_STRATEGY_CODE)
        self.assertTrue(hasattr(strategy, "init"))
        self.assertTrue(hasattr(strategy, "next"))

    def test_valid_strategy_file_loads(self):
        loader = StrategyLoader()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(VALID_STRATEGY_CODE)
            f.flush()
            strategy = loader.load(f.name, "test_valid_file")
        self.assertTrue(hasattr(strategy, "init"))

    def test_dangerous_code_string_rejected(self):
        loader = StrategyLoader()
        for name, (code, fragment) in DANGEROUS_CODES_STRATEGY.items():
            with self.subTest(name=name):
                with self.assertRaises(StrategyLoadError) as ctx:
                    loader.load(None, f"test_{name}", code=code)
                self.assertIn(fragment, str(ctx.exception))

    def test_dangerous_code_file_rejected(self):
        loader = StrategyLoader()
        for name, (code, fragment) in DANGEROUS_CODES_STRATEGY.items():
            with self.subTest(name=name):
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, encoding="utf-8"
                ) as f:
                    f.write(code)
                    f.flush()
                    with self.assertRaises(StrategyLoadError) as ctx:
                        loader.load(f.name, f"test_file_{name}")
                self.assertIn(fragment, str(ctx.exception))

    def test_validator_error_propagated(self):
        loader = StrategyLoader()
        code = "import os\n" + VALID_STRATEGY_CODE
        with self.assertRaises(StrategyLoadError) as ctx:
            loader.load(None, "test_err_msg", code=code)
        self.assertIn("不允许的用法", str(ctx.exception))

    def test_syntax_error_rejected(self):
        loader = StrategyLoader()
        code = "def broken("
        with self.assertRaises(StrategyLoadError) as ctx:
            loader.load(None, "test_syntax", code=code)
        self.assertIn("语法错误", str(ctx.exception))

    def test_missing_template_class_rejected(self):
        loader = StrategyLoader()
        code = "x = 1\n"
        with self.assertRaises(StrategyLoadError):
            loader.load(None, "test_no_class", code=code)


class EventAnalysisLoaderValidationTest(unittest.TestCase):
    def test_valid_event_code_loads(self):
        loader = EventAnalysisLoader()
        analysis = loader.load(None, "test_valid", code=VALID_EVENT_CODE)
        self.assertTrue(hasattr(analysis, "scan"))

    def test_valid_event_file_loads(self):
        loader = EventAnalysisLoader()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(VALID_EVENT_CODE)
            f.flush()
            analysis = loader.load(f.name, "test_valid_file")
        self.assertTrue(hasattr(analysis, "scan"))

    def test_dangerous_code_string_rejected(self):
        loader = EventAnalysisLoader()
        for name, (code, fragment) in DANGEROUS_CODES_EVENT.items():
            with self.subTest(name=name):
                with self.assertRaises(EventAnalysisLoadError) as ctx:
                    loader.load(None, f"test_{name}", code=code)
                self.assertIn(fragment, str(ctx.exception))

    def test_dangerous_code_file_rejected(self):
        loader = EventAnalysisLoader()
        for name, (code, fragment) in DANGEROUS_CODES_EVENT.items():
            with self.subTest(name=name):
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, encoding="utf-8"
                ) as f:
                    f.write(code)
                    f.flush()
                    with self.assertRaises(EventAnalysisLoadError) as ctx:
                        loader.load(f.name, f"test_file_{name}")
                self.assertIn(fragment, str(ctx.exception))

    def test_validator_error_propagated(self):
        loader = EventAnalysisLoader()
        code = "import os\n" + VALID_EVENT_CODE
        with self.assertRaises(EventAnalysisLoadError) as ctx:
            loader.load(None, "test_err_msg", code=code)
        self.assertIn("不允许的用法", str(ctx.exception))

    def test_syntax_error_rejected(self):
        loader = EventAnalysisLoader()
        code = "def broken("
        with self.assertRaises(EventAnalysisLoadError) as ctx:
            loader.load(None, "test_syntax", code=code)
        self.assertIn("语法错误", str(ctx.exception))

    def test_missing_template_class_rejected(self):
        loader = EventAnalysisLoader()
        code = "x = 1\n"
        with self.assertRaises(EventAnalysisLoadError):
            loader.load(None, "test_no_class", code=code)


if __name__ == "__main__":
    unittest.main()
