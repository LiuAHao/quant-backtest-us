from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from backtest.strategy import StrategyTemplate
from backend.services.strategy_validator import StrategyValidator


class StrategyLoadError(RuntimeError):
    pass


class StrategyLoader:
    """从已落盘的策略源码文件中加载 StrategyTemplate 子类。"""

    def __init__(self) -> None:
        self._validator = StrategyValidator()

    def load(self, file_path: str | None, module_key: str, code: str | None = None) -> StrategyTemplate:
        module_name = f"backend_generated_strategy_{module_key}"
        if code is not None:
            module = self._load_module_from_code(module_name, code)
        else:
            path = Path(str(file_path))
            if not path.exists():
                raise StrategyLoadError(f"策略文件不存在: {path}")
            module = self._load_module(module_name, path)
        strategy_class = self._find_strategy_class(module)
        try:
            strategy = strategy_class()
        except TypeError as exc:
            raise StrategyLoadError("策略类必须支持无参数初始化") from exc
        return strategy

    def _validate(self, code: str) -> None:
        result = self._validator.validate(code)
        if not result.ok:
            raise StrategyLoadError(result.message)

    def _load_module(self, module_name: str, path: Path) -> ModuleType:
        code = path.read_text(encoding="utf-8")
        self._validate(code)
        module = ModuleType(module_name)
        module.__file__ = str(path)
        sys.modules[module_name] = module
        exec(compile(code, module.__file__, "exec"), module.__dict__)
        return module

    def _load_module_from_code(self, module_name: str, code: str) -> ModuleType:
        self._validate(code)
        module = ModuleType(module_name)
        module.__file__ = f"<{module_name}>"
        sys.modules[module_name] = module
        exec(compile(code, module.__file__, "exec"), module.__dict__)
        return module

    def _find_strategy_class(self, module: ModuleType):
        for value in module.__dict__.values():
            if isinstance(value, type) and value is not StrategyTemplate and issubclass(value, StrategyTemplate):
                return value
        raise StrategyLoadError("未找到继承 StrategyTemplate 的策略类")
