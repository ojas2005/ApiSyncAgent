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


def scan_git_ref(backend, ref):
    backend = Path(backend).resolve()

    def git(*args, cwd=None):
        result = subprocess.run(["git", *args], cwd=str(cwd or backend), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise ValueError("git {} failed: {}".format(" ".join(args), result.stderr.strip()))
        return result.stdout

    root = Path(git("rev-parse", "--show-toplevel").strip())
    try:
        relative = backend.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("Backend must be inside the Git repository") from exc
    names = git("ls-tree", "-r", "--name-only", ref, "--", relative, cwd=root).splitlines()
    sources = []
    for name in names:
        if name.endswith(".py") and not any(part in SKIP_DIRS for part in Path(name).parts):
            content = git("show", "{}:{}".format(ref, name), cwd=root)
            sources.append((str(Path(name).relative_to(relative)), content))
    return parse_sources(sources)


def compare_contracts(before, after):
    changes = []

    def add(kind, model, field=None, old=None, new=None, breaking=False, route=None):
        changes.append({"kind": kind, "model": model, "field": field, "old": old,
                        "new": new, "breaking": breaking, "route": route})

    old_models, new_models = before["models"], after["models"]
    for model in sorted(old_models.keys() | new_models.keys()):
        if model not in new_models:
            add("model_removed", model, breaking=True)
            continue
        if model not in old_models:
            add("model_added", model)
            continue
        old_fields, new_fields = old_models[model]["fields"], new_models[model]["fields"]
        for field in sorted(old_fields.keys() | new_fields.keys()):
            if field not in new_fields:
                add("field_removed", model, field, old_fields[field], breaking=True)
            elif field not in old_fields:
                add("field_added", model, field, new=new_fields[field],
                    breaking=False)
            elif old_fields[field]["type"] != new_fields[field]["type"]:
                add("field_type_changed", model, field, old_fields[field], new_fields[field], True)
            elif old_fields[field]["required"] and not new_fields[field]["required"]:
                add("field_became_optional", model, field, old_fields[field], new_fields[field], True)
            elif not old_fields[field]["required"] and new_fields[field]["required"]:
                add("field_became_required", model, field, old_fields[field], new_fields[field])
    old_routes, new_routes = before["routes"], after["routes"]
    for route in sorted(old_routes.keys() | new_routes.keys()):
        if route not in new_routes:
            add("route_removed", ", ".join(old_routes[route]["models"]),
                old=old_routes[route]["response"], breaking=True, route=route)
        elif route not in old_routes:
            add("route_added", ", ".join(new_routes[route]["models"]),
                new=new_routes[route]["response"], route=route)
        elif old_routes[route]["response"] != new_routes[route]["response"]:
            add("route_response_changed", ", ".join(new_routes[route]["models"]),
                old=old_routes[route]["response"], new=new_routes[route]["response"],
                breaking=True, route=route)
    return changes


def frontend_uses(frontend, changes, before, after):
    """Find candidate consumer lines; these are hints, not a data-flow proof."""
    frontend = Path(frontend)
    if not frontend.is_dir():
        raise ValueError("Frontend directory does not exist: {}".format(frontend))
    files = sorted(path for path in frontend.rglob("*") if path.suffix in TS_EXTENSIONS
                   and not any(part in SKIP_DIRS for part in path.parts))
    route_paths = {}
    for contract in (before, after):
        for route, details in contract["routes"].items():
            path = route.split(" ", 1)[1]
            prefix = re.sub(r"\{[^}]+\}", "", path).rstrip("/")
            for model in details["models"]:
                route_paths.setdefault(model, set()).add(prefix)
    usage = {}
    for index, change in enumerate(changes):
        model = change["model"]
        field = change["field"]
        if ", " in model:
            model_names = model.split(", ")
        else:
            model_names = [model]
        hits = []
        for path in files:
            content = path.read_text(encoding="utf-8", errors="replace")
            relevant = any(re.search(r"\b{}\b".format(re.escape(name)), content) for name in model_names)
            relevant = relevant or any(prefix and prefix in content for name in model_names
                                       for prefix in route_paths.get(name, set()))
            if not relevant and not field:
                continue
            for line_no, line in enumerate(content.splitlines(), 1):
                if field:
                    pattern = r"(?:\.\s*|[\[\{]\s*['\"]?)" + re.escape(field) + r"\b"
                    declaration = r"\b" + re.escape(field) + r"\s*:"
                    if not (re.search(pattern, line) or re.search(declaration, line)):
                        continue
                elif not any(re.search(r"\b{}\b".format(re.escape(name)), line)
                             for name in model_names) and not any(
                                 prefix and prefix in line for name in model_names
                                 for prefix in route_paths.get(name, set())):
                    continue
                hits.append({"file": str(path.relative_to(frontend)), "line": line_no,
                             "text": line.strip()[:180], "confidence": "model/route" if relevant else "field-only"})
        usage[index] = sorted(hits, key=lambda hit: hit["confidence"] != "model/route")[:25]
    return usage


def ts_type(type_text, model_names=()):
    try:
        node = ast.parse(type_text, mode="eval").body
    except SyntaxError:
        return "unknown"

    def convert(n):
        if isinstance(n, ast.Name):
            mapped = {"str": "string", "int": "number", "float": "number", "bool": "boolean",
                    "None": "null", "Any": "unknown", "dict": "Record<string, unknown>",
                    "datetime": "string", "date": "string", "time": "string",
                    "UUID": "string", "Decimal": "string", "bytes": "string",
                    "EmailStr": "string", "HttpUrl": "string", "AnyUrl": "string",
                    "PositiveInt": "number", "NonNegativeInt": "number"}.get(n.id)
            return mapped if mapped is not None else (n.id if n.id in model_names else "unknown")
        if isinstance(n, ast.Constant):
            return "null" if n.value is None else json.dumps(n.value)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            return "{} | {}".format(convert(n.left), convert(n.right))
        if isinstance(n, ast.Subscript):
            name = short_name(n.value)
            args = n.slice.elts if isinstance(n.slice, ast.Tuple) else [n.slice]
            if name in {"list", "List", "Sequence", "set", "Set"}:
                return "Array<{}>".format(convert(args[0]))
            if name in {"dict", "Dict", "Mapping"} and len(args) == 2:
                return "Record<{}, {}>".format(convert(args[0]), convert(args[1]))
            if name == "Optional":
                return "{} | null".format(convert(args[0]))
            if name == "Union":
                return " | ".join(convert(arg) for arg in args)
            if name == "Literal":
                return " | ".join(convert(arg) for arg in args)
            if name in {"tuple", "Tuple"}:
                return "[{}]".format(", ".join(convert(arg) for arg in args))
            if name == "Annotated":
                return convert(args[0])
            return "unknown"
        if isinstance(n, ast.Attribute):
            return convert(ast.Name(id=n.attr, ctx=ast.Load()))
        return "unknown"

    return convert(node)


def render_types(contract):
    lines = ["// Generated by api-contract-sync. Do not edit by hand.", ""]
    for name, details in contract["models"].items():
        lines.append("export interface {} {{".format(name))
        for field, info in sorted(details["fields"].items()):
            key = field if re.fullmatch(r"[A-Za-z_$][\w$]*", field) else json.dumps(field)
            lines.append("  {}{}: {};".format(key, "" if info["required"] else "?",
                                              ts_type(info["type"], contract["models"])))
        lines.extend(["}", ""])
    return "\n".join(lines)


def render_report(changes, uses):
    breaking = sum(change["breaking"] for change in changes)
    lines = ["# API contract integration checklist", "",
             "{} change(s), {} potentially breaking.".format(len(changes), breaking), ""]
    if not changes:
        lines.append("No response contract changes detected.")
        return "\n".join(lines) + "\n"
    labels = {
        "model_removed": "Model removed", "model_added": "Model added",
        "field_removed": "Field removed", "field_added": "Field added",
        "field_type_changed": "Field type changed", "field_became_optional": "Field became optional",
        "field_became_required": "Field became required", "route_removed": "Route removed",
        "route_added": "Route added", "route_response_changed": "Route response changed",
    }
    additions = {}
    for change in changes:
        if change["kind"] == "field_added":
            additions.setdefault(change["model"], []).append(change)
    for index, change in enumerate(changes):
        target = change["route"] or change["model"]
        if change["field"]:
            target += "." + change["field"]
        lines.append("- [ ] **{}:** {} — {}{}".format(
            "BREAKING" if change["breaking"] else "Review", labels[change["kind"]],
            target, " ({} → {})".format(change["old"], change["new"])
            if change["old"] is not None and change["new"] is not None else ""))
        if change["kind"] == "field_removed":
            candidates = [c["field"] for c in additions.get(change["model"], [])
                          if c["new"]["type"] == change["old"]["type"]]
            if len(candidates) == 1:
                lines.append("  - Possible rename: update `{}.{}` to `{}.{}` after confirming API semantics.".format(
                    change["model"], change["field"], change["model"], candidates[0]))
        if change["kind"] in {"field_type_changed", "field_became_optional"}:
            lines.append("  - Update frontend handling for the new value type or missing value.")
        for hit in uses.get(index, []):
            lines.append("  - Candidate consumer ({}): `{}:{}` — `{}`".format(
                hit["confidence"], hit["file"], hit["line"], hit["text"].replace("`", "'")))
        if change["breaking"] and not uses.get(index):
            lines.append("  - Search frontend callers and tests for this contract.")
    lines.extend(["", "## Integration steps", "",
                  "- [ ] Review each candidate consumer and update field access, types, and UI behavior.",
                  "- [ ] Regenerate TypeScript interfaces and review the diff.",
                  "- [ ] Run frontend type checks and integration tests against the changed API.",
                  "- [ ] Deploy compatible backend and frontend versions together, or provide a migration window.", ""])
    return "\n".join(lines)
