from __future__ import annotations

import ast

from backend.services.code_validator_base import (
    ValidationResult,
    find_banned_usage,
    find_class_by_base_name,
)


class EventAnalysisValidator:
    """对事件分析代码做基础静态校验。

    注意：这是"减少误用"的校验器，不是安全沙箱。事件分析代码依然会在本地
    Python 进程内执行，因此只能运行你自己信任的代码。
    """

    def validate(self, code: str) -> ValidationResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ValidationResult(False, "failed", f"语法错误: {exc.msg}，第 {exc.lineno} 行")

        banned = find_banned_usage(tree)
        if banned:
            return ValidationResult(False, "failed", f"事件分析代码包含不允许的用法: {', '.join(banned)}")

        class_node = find_class_by_base_name(tree, "EventAnalysisTemplate")
        if class_node is None:
            return ValidationResult(False, "failed", "未找到继承 EventAnalysisTemplate 的事件分析类")

        method_names = {node.name for node in class_node.body if isinstance(node, ast.FunctionDef)}
        if "scan" not in method_names:
            return ValidationResult(False, "failed", "事件分析类缺少必要方法: scan")

        dependencies = self._infer_dependencies(tree)
        return ValidationResult(
            ok=True,
            status="passed",
            message="校验通过：语法、事件类结构和基础安全规则均满足要求",
            class_name=class_node.name,
            dependencies=dependencies,
        )

    def _infer_dependencies(self, tree: ast.AST) -> list[str]:
        text = ast.unparse(tree) if hasattr(ast, "unparse") else ""
        dependencies = {"daily_bar"}
        keyword_map = {
            "daily_basic": "daily_basic",
            "stk_limit": "stk_limit",
            "suspend_d": "suspend_d",
            "instruments": "instruments",
            "adj_factor": "adj_factor",
        }
        for keyword, dependency in keyword_map.items():
            if keyword in text:
                dependencies.add(dependency)
        return sorted(dependencies)
