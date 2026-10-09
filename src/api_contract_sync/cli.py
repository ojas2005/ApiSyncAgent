"""Command-line interface for API contract synchronization."""

import argparse
import json
import sys
from pathlib import Path

from .core import (compare_contracts, frontend_uses, render_report, render_types,
                   scan_directory, scan_git_ref)


