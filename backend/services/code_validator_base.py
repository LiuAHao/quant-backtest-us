from __future__ import annotations

import ast
from dataclasses import dataclass, field


BANNED_IMPORTS = {
    "os",
    "subprocess",
    "socket",
    "shutil",
    "sys",
    "builtins",
    "importlib",
    "inspect",
    "site",
    "pkgutil",
    "ctypes",
    "sqlite3",
    "tempfile",
    "glob",
    "requests",
    "httpx",
    "urllib",
    "ftplib",
    "pathlib",
    "pickle",
    "marshal",
    "runpy",
    "multiprocessing",
    "threading",
}

BANNED_CALLS = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "input",
    "breakpoint",
}

BANNED_ATTR_CALLS = {
    "system",
    "popen",
    "remove",
    "unlink",
    "rmdir",
    "removedirs",
    "exec_module",
    "import_module",
}

BANNED_DUNDER_ATTRS = {
    "__bases__",
    "__base__",
    "__builtins__",
    "__class__",
    "__code__",
    "__dict__",
    "__getattribute__",
    "__globals__",
    "__mro__",
    "__subclasses__",
}


@dataclass
class ValidationResult:
    ok: bool
    status: str
    message: str
    class_name: str | None = None
    dependencies: list[str] = field(default_factory=list)


def find_banned_usage(tree: ast.AST) -> list[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BANNED_IMPORTS:
                    found.add(f"import {root}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BANNED_IMPORTS:
                found.add(f"from {root} import ...")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
                found.add(f"{node.func.id}(...)")
            if isinstance(node.func, ast.Attribute) and node.func.attr in BANNED_ATTR_CALLS:
                found.add(f".{node.func.attr}(...)")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_DUNDER_ATTRS:
            found.add(f".{node.attr}")
    return sorted(found)


def find_class_by_base_name(tree: ast.AST, base_name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == base_name:
                return node
            if isinstance(base, ast.Attribute) and base.attr == base_name:
                return node
    return None
