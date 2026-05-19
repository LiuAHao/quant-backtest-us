from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from event_analysis.template import EventAnalysisTemplate
from backend.services.event_analysis_validator import EventAnalysisValidator


class EventAnalysisLoadError(RuntimeError):
    pass


class EventAnalysisLoader:
    """从落盘代码中加载事件分析定义。"""

    def __init__(self) -> None:
        self._validator = EventAnalysisValidator()

    def load(self, file_path: str | None, module_key: str, code: str | None = None) -> EventAnalysisTemplate:
        module_name = f"backend_generated_event_analysis_{module_key}"
        if code is not None:
            module = self._load_module_from_code(module_name, code)
        else:
            path = Path(str(file_path))
            if not path.exists():
                raise EventAnalysisLoadError(f"事件分析文件不存在: {path}")
            module = self._load_module(module_name, path)
        event_class = self._find_event_class(module)
        try:
            analysis = event_class()
        except TypeError as exc:
            raise EventAnalysisLoadError("事件分析类必须支持无参数初始化") from exc
        return analysis

    def _validate(self, code: str) -> None:
        result = self._validator.validate(code)
        if not result.ok:
            raise EventAnalysisLoadError(result.message)

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

    def _find_event_class(self, module: ModuleType):
        for value in module.__dict__.values():
            if isinstance(value, type) and value is not EventAnalysisTemplate and issubclass(value, EventAnalysisTemplate):
                return value
        raise EventAnalysisLoadError("未找到继承 EventAnalysisTemplate 的事件分析类")
