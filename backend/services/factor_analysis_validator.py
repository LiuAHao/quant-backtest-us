from __future__ import annotations

import ast

from backend.services.code_validator_base import (
    ValidationResult,
    find_banned_usage,
    find_class_by_base_name,
)


FUTURE_RETURN_NAMES = {
    "ret_1d",
    "ret_5d",
    "ret_10d",
    "ret_20d",
    "future_return",
    "forward_return",
}
TRADING_NAMES = {"order", "buy", "sell", "order_target_percent"}


class FactorAnalysisValidator:
    """因子分析代码静态校验器。"""

    def validate(self, code: str) -> ValidationResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ValidationResult(False, "failed", f"语法错误: {exc.msg}，第 {exc.lineno} 行")

        banned = find_banned_usage(tree)
        extra_banned = self._find_factor_banned_names(tree)
        all_banned = [*banned, *extra_banned]
        if all_banned:
            return ValidationResult(False, "failed", f"因子分析代码包含不允许的用法: {', '.join(sorted(set(all_banned)))}")

        class_node = find_class_by_base_name(tree, "FactorAnalysisTemplate")
        if class_node is None:
            return ValidationResult(False, "failed", "未找到继承 FactorAnalysisTemplate 的因子分析类")

        method_names = {node.name for node in class_node.body if isinstance(node, ast.FunctionDef)}
        if "compute" not in method_names:
            return ValidationResult(False, "failed", "因子分析类缺少必要方法: compute")

        return ValidationResult(
            ok=True,
            status="passed",
            message="校验通过：语法、因子类结构和基础安全规则均满足要求",
            class_name=class_node.name,
            dependencies=self._infer_dependencies(tree),
        )

    def _find_factor_banned_names(self, tree: ast.AST) -> list[str]:
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in FUTURE_RETURN_NAMES | TRADING_NAMES:
                found.append(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in FUTURE_RETURN_NAMES | TRADING_NAMES:
                found.append(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in FUTURE_RETURN_NAMES | TRADING_NAMES:
                    found.append(node.value)
        return found

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
