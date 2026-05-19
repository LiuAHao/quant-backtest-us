from __future__ import annotations

from typing import Any


class EventAnalysisTemplate:
    """事件分析模板基类。"""

    def __init__(self, name: str):
        self.name = name

    def scan(self, context: dict[str, Any]):
        raise NotImplementedError("事件分析类必须实现 scan(context)")
