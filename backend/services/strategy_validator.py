from __future__ import annotations

import ast

from backend.services.code_validator_base import (
    ValidationResult,
    find_banned_usage,
    find_class_by_base_name,
)


class StrategyValidator:
    """对前端提交的 Python 策略代码做基础静态校验。

    注意：这是"减少误用"的校验器，不是安全沙箱。策略代码依然会在本地 Python
    进程内执行，因此只能运行你自己信任的代码。
    """

    def validate(self, code: str) -> ValidationResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ValidationResult(False, "failed", f"语法错误: {exc.msg}，第 {exc.lineno} 行")

        banned = find_banned_usage(tree)
        if banned:
            return ValidationResult(False, "failed", f"策略代码包含不允许的用法: {', '.join(banned)}")

        class_node = find_class_by_base_name(tree, "StrategyTemplate")
        if class_node is None:
            return ValidationResult(False, "failed", "未找到继承 StrategyTemplate 的策略类")

        method_names = {node.name for node in class_node.body if isinstance(node, ast.FunctionDef)}
        missing = [name for name in ("init", "next") if name not in method_names]
        if missing:
            return ValidationResult(False, "failed", f"策略类缺少必要方法: {', '.join(missing)}")

        dependencies = self._infer_dependencies(tree)
        return ValidationResult(
            ok=True,
            status="passed",
            message="校验通过：语法、策略类结构和基础安全规则均满足要求",
            class_name=class_node.name,
            dependencies=dependencies,
        )

    def _infer_dependencies(self, tree: ast.AST) -> list[str]:
        text = ast.unparse(tree) if hasattr(ast, "unparse") else ""
        dependencies = {"daily_bar"}
        keyword_map = {
            "get_cross_section": "daily_bar",
            "daily_basic": "daily_basic",
            "stk_limit": "stk_limit",
            "suspend": "suspend_d",
            "adj_factor": "adj_factor",
        }
        for keyword, dependency in keyword_map.items():
            if keyword in text:
                dependencies.add(dependency)
        return sorted(dependencies)
