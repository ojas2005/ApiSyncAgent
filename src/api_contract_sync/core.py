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


def parse_sources(sources):
    """Return a deterministic JSON-compatible contract from (path, source) pairs."""
    modules = []
    class_entries = {}
    for path, source in sources:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            raise ValueError("Cannot parse {}:{}: {}".format(path, exc.lineno, exc.msg)) from exc
        modules.append((path, tree))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_entries.setdefault(node.name, []).append((path, node))

    model_names = {name for name, entries in class_entries.items()
                   if any(short_name(base) == "BaseModel" for _, node in entries for base in node.bases)}
    changed = True
    while changed:
        old_size = len(model_names)
        model_names.update(name for name, entries in class_entries.items()
                           if any(short_name(base) in model_names
                                  for _, node in entries for base in node.bases))
        changed = len(model_names) != old_size
    for name in model_names:
        if len(class_entries[name]) > 1:
            raise ValueError("Duplicate model name '{}': {}. Use unique model names.".format(
                name, ", ".join(path for path, _ in class_entries[name])))
    classes = {name: entries[0] for name, entries in class_entries.items()}

    def collect_fields(name, stack=None):
        stack = stack or set()
        if name in stack:
            raise ValueError("Cyclic model inheritance involving {}".format(name))
        stack = stack | {name}
        _, node = classes[name]
        fields = {}
        for base in node.bases:
            parent = short_name(base)
            if parent in model_names:
                fields.update(collect_fields(parent, stack))
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                if short_name(statement.annotation) in {"ClassVar", "PrivateAttr"}:
                    continue
                field = field_details(statement)
                fields[statement.target.id] = field
        return fields

    models = {}
    for name in sorted(model_names):
        fields = {}
        for field in collect_fields(name).values():
            if field["name"] in fields:
                raise ValueError("Duplicate serialized field '{}' in {}".format(field["name"], name))
            fields[field["name"]] = {"type": field["type"], "required": field["required"]}
        models[name] = {"file": classes[name][0], "fields": fields}
    routes = {}
    for path, tree in modules:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr.lower()
                if method not in ROUTE_METHODS or not decorator.args:
                    continue
                url = literal(decorator.args[0])
                if not isinstance(url, str):
                    continue
                response = next((k.value for k in decorator.keywords if k.arg == "response_model"), None)
                if response is None:
                    response = node.returns
                if response is None:
                    continue
                refs = model_references(response, model_names)
                if not refs:
                    continue
                key = "{} {}".format(method.upper(), url)
                if key in routes:
                    raise ValueError("Duplicate route {}".format(key))
                routes[key] = {"file": path, "response": expression(response), "models": refs}
    return {"format_version": 1, "models": models, "routes": dict(sorted(routes.items()))}


def scan_directory(backend):
    backend = Path(backend)
    if not backend.is_dir():
        raise ValueError("Backend directory does not exist: {}".format(backend))
    files = sorted(path for path in backend.rglob("*.py")
                   if not any(part in SKIP_DIRS for part in path.parts))
    return parse_sources((str(path.relative_to(backend)), path.read_text(encoding="utf-8")) for path in files)
