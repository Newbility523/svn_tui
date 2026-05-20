from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from svn_tui.app import SvnTui
from svn_tui.ui.screens.log import LogScreen
from svn_tui.ui.screens.status import StatusScreen


class AppTests(unittest.TestCase):
    def test_default_screen_is_status_screen(self) -> None:
        app = SvnTui(Path("."))

        self.assertIsInstance(app.get_default_screen(), StatusScreen)

    def test_log_initial_screen_uses_log_screen(self) -> None:
        app = SvnTui(Path("."), initial_screen="log")

        self.assertIsInstance(app.get_default_screen(), LogScreen)

    def test_status_initial_screen_uses_parent_when_target_is_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            selected_file = root / "selected.py"
            selected_file.write_text("content", encoding="utf-8")
            app = SvnTui(selected_file, initial_screen="status")

            screen = app.get_default_screen()

        self.assertIsInstance(screen, StatusScreen)
        self.assertEqual(screen.client.target, root.resolve())

    def test_log_initial_screen_keeps_file_target(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            selected_file = root / "selected.py"
            selected_file.write_text("content", encoding="utf-8")
            app = SvnTui(selected_file, initial_screen="log")

            screen = app.get_default_screen()

        self.assertIsInstance(screen, LogScreen)
        self.assertEqual(screen.client.target, selected_file.resolve())


if __name__ == "__main__":
    unittest.main()
