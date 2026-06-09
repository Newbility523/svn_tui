from __future__ import annotations

import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tools import svn_fixture


class SvnFixtureTests(unittest.TestCase):
    def test_fixture_paths_derive_expected_children(self) -> None:
        root = Path("build") / "fixture"

        paths = svn_fixture.FixturePaths.from_root(root)

        self.assertEqual(paths.repo, paths.root / "repo")
        self.assertEqual(paths.wc, paths.root / "wc")
        self.assertEqual(paths.actor_wc, paths.root / "actor-wc")

    def test_list_command_does_not_require_svn(self) -> None:
        with redirect_stdout(StringIO()):
            self.assertEqual(svn_fixture.main(["list"]), 0)

    def test_menu_items_include_existing_commands(self) -> None:
        labels = [item.label for item in svn_fixture.build_menu_items()]

        self.assertIn("init", labels)
        self.assertIn("list", labels)
        self.assertIn("reset", labels)
        self.assertIn("path", labels)
        self.assertIn("open status", labels)
        self.assertIn("open log", labels)

    def test_menu_items_include_all_states(self) -> None:
        labels = [item.label for item in svn_fixture.build_menu_items()]

        for state_name in svn_fixture.STATES:
            self.assertIn(f"state {state_name}", labels)

    def test_no_command_in_noninteractive_terminal_prints_help(self) -> None:
        with (
            patch.object(svn_fixture, "terminal_is_interactive", return_value=False),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            exit_code = svn_fixture.main([])

        self.assertEqual(exit_code, 2)

    def test_refuses_to_delete_unmarked_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = svn_fixture.FixturePaths.from_root(Path(directory))

            with self.assertRaises(svn_fixture.FixtureError):
                svn_fixture.remove_fixture_root(paths)

    @unittest.skipUnless(
        shutil.which("svn") and shutil.which("svnadmin"),
        "svn and svnadmin are required for fixture smoke test",
    )
    def test_state_mixed_creates_working_copy_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = svn_fixture.main(["--root", str(root), "state", "mixed"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "wc" / ".svn").exists())
            self.assertTrue((root / "repo").exists())

    @unittest.skipUnless(
        shutil.which("svn") and shutil.which("svnadmin"),
        "svn and svnadmin are required for fixture smoke test",
    )
    def test_state_shelves_ready_creates_shelfable_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = svn_fixture.main(["--root", str(root), "state", "shelves-ready"])

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "shelf_checkpoint_label",
                (root / "wc" / "src" / "app.py").read_text(encoding="utf-8"),
            )
            self.assertTrue((root / "wc" / "shelf-unversioned-note.txt").exists())


if __name__ == "__main__":
    unittest.main()
