from __future__ import annotations

import argparse
from pathlib import Path

from svn_tui.app import SvnTui


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TUI client for reviewing svn status")
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="working copy path to inspect",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    SvnTui(Path(args.target)).run()
