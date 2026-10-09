"""Command-line interface for API contract synchronization."""

import argparse
import json
import sys
from pathlib import Path

from .core import (compare_contracts, frontend_uses, render_report, render_types,
                   scan_directory, scan_git_ref)


def parser():
    top = argparse.ArgumentParser(prog="api-contract-sync",
                                  description="Compare Pydantic/FastAPI contracts and locate frontend consumers")
    sub = top.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot", help="Save a baseline JSON snapshot")
    snapshot.add_argument("--backend", required=True, type=Path)
    snapshot.add_argument("--output", required=True, type=Path)

    check = sub.add_parser("check", help="Compare current backend with a baseline")
    check.add_argument("--backend", required=True, type=Path)
    baseline = check.add_mutually_exclusive_group(required=True)
    baseline.add_argument("--base-ref", help="Git ref to compare against (for pull requests)")
    baseline.add_argument("--baseline", type=Path, help="JSON snapshot to compare against")
    check.add_argument("--frontend", type=Path, help="TypeScript/JavaScript source tree")
    check.add_argument("--types-out", type=Path, help="Generated TypeScript interface file")
    check.add_argument("--write-types", action="store_true", help="Write --types-out")
    check.add_argument("--verify-types", action="store_true", help="Fail if --types-out differs")
    check.add_argument("--report", type=Path, help="Write Markdown checklist")
    check.add_argument("--json-report", type=Path, help="Write machine-readable report")
    check.add_argument("--fail-on-breaking", action="store_true", help="Exit 2 for breaking changes")
    return top


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        current = scan_directory(args.backend)
        if args.command == "snapshot":
            write(args.output, json.dumps(current, indent=2, sort_keys=True) + "\n")
            print("Wrote {} model(s) and {} route(s) to {}".format(
                len(current["models"]), len(current["routes"]), args.output))
            return 0

        if args.write_types and args.verify_types:
            raise ValueError("Choose only one of --write-types and --verify-types")
        if (args.write_types or args.verify_types) and not args.types_out:
            raise ValueError("--types-out is required with --write-types or --verify-types")
        before = scan_git_ref(args.backend, args.base_ref) if args.base_ref else json.loads(
            args.baseline.read_text(encoding="utf-8"))
        if before.get("format_version") != 1:
            raise ValueError("Unsupported baseline format version")
        changes = compare_contracts(before, current)
        uses = frontend_uses(args.frontend, changes, before, current) if args.frontend else {}
        report = render_report(changes, uses)
        print(report, end="")
        if args.report:
            write(args.report, report)
        if args.json_report:
            write(args.json_report, json.dumps({"changes": changes, "consumers": uses}, indent=2) + "\n")
        if args.types_out:
            generated = render_types(current)
            if args.write_types:
                write(args.types_out, generated)
                print("Wrote TypeScript interfaces to {}".format(args.types_out))
            elif args.verify_types and (not args.types_out.exists() or
                                        args.types_out.read_text(encoding="utf-8") != generated):
                print("Generated TypeScript interfaces are out of date: {}".format(args.types_out),
                      file=sys.stderr)
                return 3
        if args.fail_on_breaking and any(c["breaking"] for c in changes):
            return 2
        return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print("api-contract-sync: {}".format(exc), file=sys.stderr)
        return 1
