"""Static FastAPI/Pydantic contract extraction and frontend impact analysis."""

import ast
import json
import re
import subprocess
from pathlib import Path


ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
TS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage"}


def expression(node):
    return ast.unparse(node) if node is not None else ""


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def short_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return short_name(node.value)
    return ""


def model_references(node, known):
    return sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name) and n.id in known})


def field_details(statement):
    annotation = expression(statement.annotation)
    default = statement.value
    required = default is None or (isinstance(default, ast.Constant) and default.value is Ellipsis)
    alias = None
    serialization_alias = None
    if isinstance(default, ast.Call) and short_name(default.func) == "Field":
        for keyword in default.keywords:
            if keyword.arg in {"alias", "serialization_alias"}:
                value = literal(keyword.value)
                if isinstance(value, str):
                    if keyword.arg == "serialization_alias":
                        serialization_alias = value
                    else:
                        alias = value
            if keyword.arg in {"default", "default_factory"}:
                required = isinstance(keyword.value, ast.Constant) and keyword.value.value is Ellipsis
        if default.args:
            required = isinstance(default.args[0], ast.Constant) and default.args[0].value is Ellipsis
        elif not any(k.arg in {"default", "default_factory"} for k in default.keywords):
            required = True
    return {"name": serialization_alias or alias or statement.target.id,
            "type": annotation, "required": required}
