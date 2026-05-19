from __future__ import annotations

from typing import Any


class FactorAnalysisTemplate:
    """因子分析模板基类。"""

    def __init__(self, name: str):
        self.name = name

    def compute(self, context: dict[str, Any]):
        raise NotImplementedError("因子分析类必须实现 compute(context)")
