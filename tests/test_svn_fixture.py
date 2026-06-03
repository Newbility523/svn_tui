from __future__ import annotations

import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
