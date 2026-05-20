from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from svn_tui.app import SvnTui

SCREEN_NAMES = ("status", "log")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TUI client for reviewing svn status")
    parser.add_argument(
        "--screen",
        choices=SCREEN_NAMES,
        help="initial screen to open",
    )
    parser.add_argument(
        "screen_or_target",
        nargs="?",
        default=".",
        help="initial screen name or working copy path",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="working copy path to inspect when an initial screen is given",
    )
    args = parser.parse_args(argv)

    explicit_screen = args.screen
    first = args.screen_or_target
    second = args.target

    if explicit_screen is None and first in SCREEN_NAMES:
        args.screen = first
        args.target = second or "."
    else:
        args.screen = explicit_screen or "status"
        args.target = first

    del args.screen_or_target
    return args


def main() -> None:
    args = parse_args()
    SvnTui(Path(args.target), initial_screen=args.screen).run()
