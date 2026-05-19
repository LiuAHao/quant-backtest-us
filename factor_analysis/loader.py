from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from backend.services.factor_analysis_validator import FactorAnalysisValidator
from factor_analysis.template import FactorAnalysisTemplate


class FactorAnalysisLoadError(RuntimeError):
    pass


class FactorAnalysisLoader:
    """从代码或文件中加载因子分析定义。"""

    def __init__(self) -> None:
        self._validator = FactorAnalysisValidator()

    def load(self, file_path: str | None, module_key: str, code: str | None = None) -> FactorAnalysisTemplate:
        module_name = f"backend_generated_factor_analysis_{module_key}"
        if code is not None:
            module = self._load_module_from_code(module_name, code)
        else:
            path = Path(str(file_path))
            if not path.exists():
                raise FactorAnalysisLoadError(f"因子分析文件不存在: {path}")
            module = self._load_module(module_name, path)
        factor_class = self._find_factor_class(module)
        try:
            return factor_class()
        except TypeError as exc:
            raise FactorAnalysisLoadError("因子分析类必须支持无参数初始化") from exc

    def _validate(self, code: str) -> None:
        result = self._validator.validate(code)
        if not result.ok:
            raise FactorAnalysisLoadError(result.message)

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

    def _find_factor_class(self, module: ModuleType):
        for value in module.__dict__.values():
            if isinstance(value, type) and value is not FactorAnalysisTemplate and issubclass(value, FactorAnalysisTemplate):
                return value
        raise FactorAnalysisLoadError("未找到继承 FactorAnalysisTemplate 的因子分析类")
