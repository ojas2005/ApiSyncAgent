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
