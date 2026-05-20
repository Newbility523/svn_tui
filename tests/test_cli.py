from __future__ import annotations

import unittest
from pathlib import Path

from svn_tui.cli import parse_args


class CliTests(unittest.TestCase):
    def test_legacy_single_target_defaults_to_status(self) -> None:
        args = parse_args(["/tmp/work-copy"])

        self.assertEqual(args.screen, "status")
        self.assertEqual(args.target, "/tmp/work-copy")

    def test_explicit_status_screen_accepts_target(self) -> None:
        args = parse_args(["status", "/tmp/work-copy"])

        self.assertEqual(args.screen, "status")
        self.assertEqual(args.target, "/tmp/work-copy")

    def test_explicit_log_screen_accepts_target(self) -> None:
        args = parse_args(["log", "/tmp/work-copy/file.py"])

        self.assertEqual(args.screen, "log")
        self.assertEqual(args.target, "/tmp/work-copy/file.py")

    def test_screen_option_accepts_log(self) -> None:
        args = parse_args(["--screen", "log", "/tmp/work-copy"])

        self.assertEqual(args.screen, "log")
        self.assertEqual(args.target, "/tmp/work-copy")

    def test_default_target_is_current_directory(self) -> None:
        args = parse_args([])

        self.assertEqual(args.screen, "status")
        self.assertEqual(Path(args.target), Path("."))


if __name__ == "__main__":
    unittest.main()
