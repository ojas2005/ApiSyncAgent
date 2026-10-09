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
