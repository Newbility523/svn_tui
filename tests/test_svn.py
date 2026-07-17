from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from svn_tui.services.svn import (
    append_svn_ignore_pattern,
    build_svn_add_args,
    build_svn_cat_args,
    build_svn_cleanup_args,
    build_svn_commit_args,
    build_svn_diff_args,
    build_svn_propget_args,
    build_svn_propset_args,
    build_svn_patch_args,
    build_svn_revert_args,
    build_svn_resolve_args,
    build_svn_update_args,
    parse_svn_log_xml,
    parse_svn_status_line,
    run_command_text,
)


class SvnCommandTests(unittest.TestCase):
    def test_build_svn_commit_args_keeps_paths_after_separator(self) -> None:
        self.assertEqual(
            build_svn_commit_args("message", [Path("a b.txt")]),
            ["svn", "commit", "-m", "message", "--", "a b.txt"],
        )

    def test_build_svn_add_args_targets_multiple_paths(self) -> None:
        self.assertEqual(
            build_svn_add_args([Path("a b.txt"), Path("c.txt")]),
            ["svn", "add", "--", "a b.txt", "c.txt"],
        )

    def test_build_svn_update_args_targets_single_path(self) -> None:
        self.assertEqual(
            build_svn_update_args([Path("a b.txt"), Path("c.txt")]),
            ["svn", "update", "--", "a b.txt", "c.txt"],
        )

    def test_build_svn_diff_args_targets_multiple_paths(self) -> None:
        self.assertEqual(
            build_svn_diff_args([Path("a b.txt"), Path("c.txt")]),
            ["svn", "diff", "--", "a b.txt", "c.txt"],
        )

    def test_build_svn_revert_args_targets_multiple_paths(self) -> None:
        self.assertEqual(
            build_svn_revert_args([Path("a b.txt"), Path("c.txt")]),
            ["svn", "revert", "--", "a b.txt", "c.txt"],
        )

    def test_build_svn_resolve_args_uses_working_accept_by_default(self) -> None:
        self.assertEqual(
            build_svn_resolve_args([Path("a b.txt"), Path("c.txt")]),
            [
                "svn",
                "resolve",
                "--accept",
                "working",
                "--",
                "a b.txt",
                "c.txt",
            ],
        )

    def test_build_svn_cleanup_args_targets_directory(self) -> None:
        self.assertEqual(
            build_svn_cleanup_args(Path("work copy")),
            ["svn", "cleanup", "--", "work copy"],
        )

    def test_build_svn_cleanup_args_can_remove_unversioned(self) -> None:
        self.assertEqual(
            build_svn_cleanup_args(Path("work copy"), remove_unversioned=True),
            ["svn", "cleanup", "--remove-unversioned", "--", "work copy"],
        )

    def test_build_svn_propget_args_targets_property(self) -> None:
        self.assertEqual(
            build_svn_propget_args("svn:ignore", Path("src")),
            ["svn", "propget", "svn:ignore", "src"],
        )

    def test_build_svn_propset_args_sets_property_value(self) -> None:
        self.assertEqual(
            build_svn_propset_args("svn:ignore", "*.pyc\n.cache", Path("src")),
            ["svn", "propset", "svn:ignore", "*.pyc\n.cache", "src"],
        )

    def test_append_svn_ignore_pattern_preserves_existing_patterns(self) -> None:
        self.assertEqual(
            append_svn_ignore_pattern("*.pyc\n.cache\n", "build"),
            "*.pyc\n.cache\nbuild",
        )

    def test_append_svn_ignore_pattern_returns_none_when_present(self) -> None:
        self.assertIsNone(append_svn_ignore_pattern("*.pyc\nbuild\n", "build"))

    def test_build_svn_cat_args_uses_requested_revision(self) -> None:
        self.assertEqual(
            build_svn_cat_args(Path("file.py"), "HEAD"),
            ["svn", "cat", "-r", "HEAD", "file.py"],
        )

    def test_build_svn_patch_args_targets_working_copy(self) -> None:
        self.assertEqual(
            build_svn_patch_args(Path("saved.patch")),
            ["svn", "patch", "saved.patch", "."],
        )


class SvnParsingTests(unittest.TestCase):
    def test_parse_svn_status_line_uses_working_copy_root(self) -> None:
        root = Path("work-copy").resolve()

        entry = parse_svn_status_line("M       src/app.py", root)

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.path, (root / "src/app.py").resolve())
        self.assertEqual(entry.text_status, "M")
        self.assertEqual(entry.prop_status, " ")
        self.assertEqual(entry.raw_status, "M")

    def test_parse_svn_status_line_keeps_property_status(self) -> None:
        root = Path("work-copy").resolve()

        entry = parse_svn_status_line(" M      src/app.py", root)

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.text_status, " ")
        self.assertEqual(entry.prop_status, "M")
        self.assertEqual(entry.status_label, "M")

    def test_parse_svn_status_line_ignores_separator_output(self) -> None:
        self.assertIsNone(parse_svn_status_line("--- Changelist 'x':", Path(".")))

    def test_parse_svn_log_xml_reads_entries_and_changed_paths(self) -> None:
        entries = parse_svn_log_xml(
            """
            <log>
              <logentry revision="42">
                <author>alice</author>
                <date>not-a-date</date>
                <msg>Fix thing\n\nDetails</msg>
                <paths>
                  <path action="M" kind="file">/trunk/app.py</path>
                  <path action="A" kind="dir">/trunk/docs</path>
                </paths>
              </logentry>
            </log>
            """
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].revision, "42")
        self.assertEqual(entries[0].author, "alice")
        self.assertEqual(entries[0].date, "not-a-date")
        self.assertEqual(entries[0].summary, "Fix thing")
        self.assertEqual(entries[0].changed_paths[0].path, "/trunk/app.py")
        self.assertEqual(entries[0].changed_paths[1].node_kind, "dir")


class RunCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_command_text_returns_stdout(self) -> None:
        output = await run_command_text(
            [sys.executable, "-c", "print('hello')"]
        )

        self.assertEqual(output.splitlines(), ["hello"])

    async def test_run_command_text_uses_requested_working_directory(self) -> None:
        output = await run_command_text(
            [sys.executable, "-c", "from pathlib import Path; print(Path.cwd())"],
            cwd=Path("tests").resolve(),
        )

        self.assertEqual(Path(output.strip()), Path("tests").resolve())

    async def test_run_command_text_raises_with_output_and_stderr(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            await run_command_text(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        "print('stdout text'); "
                        "print('stderr text', file=sys.stderr); "
                        "sys.exit(7)"
                    ),
                ]
            )

        self.assertEqual(raised.exception.returncode, 7)
        self.assertIn("stdout text", raised.exception.output)
        self.assertIn("stderr text", raised.exception.stderr)


if __name__ == "__main__":
    unittest.main()
