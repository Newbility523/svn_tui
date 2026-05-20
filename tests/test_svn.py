from __future__ import annotations

import unittest
from pathlib import Path

from svn_tui.services.svn import (
    build_svn_cat_args,
    build_svn_commit_args,
    build_svn_revert_args,
    build_svn_update_args,
)


class SvnCommandTests(unittest.TestCase):
    def test_build_svn_commit_args_keeps_paths_after_separator(self) -> None:
        self.assertEqual(
            build_svn_commit_args("message", [Path("a b.txt")]),
            ["svn", "commit", "-m", "message", "--", "a b.txt"],
        )

    def test_build_svn_update_args_targets_single_path(self) -> None:
        self.assertEqual(
            build_svn_update_args([Path("a b.txt"), Path("c.txt")]),
            ["svn", "update", "--", "a b.txt", "c.txt"],
        )

    def test_build_svn_revert_args_targets_multiple_paths(self) -> None:
        self.assertEqual(
            build_svn_revert_args([Path("a b.txt"), Path("c.txt")]),
            ["svn", "revert", "--", "a b.txt", "c.txt"],
        )

    def test_build_svn_cat_args_uses_requested_revision(self) -> None:
        self.assertEqual(
            build_svn_cat_args(Path("file.py"), "HEAD"),
            ["svn", "cat", "-r", "HEAD", "file.py"],
        )


if __name__ == "__main__":
    unittest.main()
