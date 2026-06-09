from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.text import Text
from textual.widgets import Button, RichLog, Static, TextArea

from svn_tui.app import SvnTui
from svn_tui.ui.dialogs import (
    ERROR_OUTPUT_STYLE,
    CommitMessageDialog,
    ConfirmActionDialog,
    SvnCommandDialog,
)


def button_label(button: Button) -> str:
    label = button.label
    return label.plain if hasattr(label, "plain") else str(label)


class SvnCommandDialogTests(unittest.IsolatedAsyncioTestCase):
    async def test_commit_message_ctrl_enter_submits_from_text_area(self) -> None:
        app = SvnTui(Path("."))
        dialog = CommitMessageDialog(file_count=1)
        results = []

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            app.push_screen(dialog, results.append)
            await pilot.pause(0.1)

            dialog.query_one("#commit-message", TextArea).text = "ship it"
            await pilot.press("ctrl+enter")
            await pilot.pause(0.1)

            self.assertEqual(results, ["ship it"])
            self.assertIsNot(app.screen, dialog)

    async def test_commit_message_accepts_ctrl_j_as_hidden_terminal_fallback(
        self,
    ) -> None:
        app = SvnTui(Path("."))
        dialog = CommitMessageDialog(file_count=1)
        results = []

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            app.push_screen(dialog, results.append)
            await pilot.pause(0.1)

            dialog.query_one("#commit-message", TextArea).text = "ship it"
            await pilot.press("ctrl+j")
            await pilot.pause(0.1)

            self.assertEqual(results, ["ship it"])
            self.assertIsNot(app.screen, dialog)

    async def test_confirm_action_dialog_ctrl_enter_confirms(self) -> None:
        app = SvnTui(Path("."))
        dialog = ConfirmActionDialog(
            "Confirm Revert",
            "Really revert this path?",
            confirm_label="Revert",
        )
        results = []

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            app.push_screen(dialog, results.append)
            await pilot.pause(0.1)

            await pilot.press("ctrl+enter")
            await pilot.pause(0.1)

            self.assertEqual(results, [True])
            self.assertIsNot(app.screen, dialog)

    async def test_command_dialog_streams_output_and_closes_after_finish(self) -> None:
        app = SvnTui(Path("."))
        dialog = SvnCommandDialog(
            [sys.executable, "-c", "print('cleanup done')"],
            title="Test Command",
        )

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.2)
            app.push_screen(dialog)
            await pilot.pause(0.4)

            self.assertIs(app.screen, dialog)
            self.assertFalse(dialog.running)
            self.assertIsNotNone(dialog.result)
            assert dialog.result is not None
            self.assertTrue(dialog.result.succeeded)
            self.assertEqual(dialog.result.output, "cleanup done")
            self.assertEqual(
                dialog.query_one("#svn-command-status", Static).content,
                "Finished.",
            )
            self.assertEqual(
                button_label(dialog.query_one("#svn-command-cancel", Button)),
                "Esc Close",
            )

            await pilot.press("escape")
            await pilot.pause(0.1)

            self.assertIsNot(app.screen, dialog)

    async def test_command_dialog_displays_command_being_run(self) -> None:
        app = SvnTui(Path("."))
        dialog = SvnCommandDialog(
            [sys.executable, "-c", ""],
            command="svn cleanup 'work copy'",
            title="SVN Cleanup",
        )

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.2)
            app.push_screen(dialog)
            await pilot.pause(0.1)

            self.assertEqual(
                dialog.query_one("#svn-command-command", Static).content,
                "svn cleanup 'work copy'",
            )
            self.assertEqual(
                dialog.query_one("#svn-command-top").styles.height.value,
                7,
            )

    async def test_command_dialog_highlights_stderr_output(self) -> None:
        app = SvnTui(Path("."))
        dialog = SvnCommandDialog(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "print('normal output'); "
                    "print('fatal error', file=sys.stderr); "
                    "raise SystemExit(2)"
                ),
            ],
            title="Failing Command",
        )
        writes = []

        def capture_write(rich_log, content, *args, **kwargs):
            del args, kwargs
            writes.append(content)
            return rich_log

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.2)
            with patch.object(RichLog, "write", capture_write):
                app.push_screen(dialog)
                await pilot.pause(0.4)

            self.assertFalse(dialog.running)
            self.assertIsNotNone(dialog.result)
            assert dialog.result is not None
            self.assertFalse(dialog.result.succeeded)
            self.assertIn("normal output", dialog.result.output)
            self.assertIn("fatal error", dialog.result.output)
            self.assertTrue(
                any(
                    isinstance(content, Text)
                    and content.plain == "fatal error"
                    and str(content.style) == ERROR_OUTPUT_STYLE
                    for content in writes
                )
            )

    async def test_ctrl_enter_confirms_running_command_cancellation(self) -> None:
        app = SvnTui(Path("."))
        dialog = SvnCommandDialog(
            [
                sys.executable,
                "-u",
                "-c",
                "import time; print('start', flush=True); time.sleep(30)",
            ],
            title="Slow Command",
        )

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.2)
            app.push_screen(dialog)
            await pilot.pause(0.2)

            await pilot.press("escape")
            await pilot.pause(0.1)
            await pilot.press("ctrl+enter")
            await pilot.pause(0.1)

            self.assertFalse(dialog.running)
            self.assertIsNotNone(dialog.result)
            assert dialog.result is not None
            self.assertTrue(dialog.result.cancelled)
            self.assertIn("Command cancelled.", dialog.result.output)

    async def test_escape_while_running_requires_cancel_confirmation(self) -> None:
        app = SvnTui(Path("."))
        dialog = SvnCommandDialog(
            [
                sys.executable,
                "-u",
                "-c",
                "import time; print('start', flush=True); time.sleep(30)",
            ],
            title="Slow Command",
        )

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.2)
            app.push_screen(dialog)
            await pilot.pause(0.2)

            await pilot.press("escape")
            await pilot.pause(0.1)

            self.assertIs(app.screen, dialog)
            self.assertTrue(dialog.confirming_cancel)
            self.assertIn(
                "Cancel running command?",
                dialog.query_one("#svn-command-status", Static).content,
            )

            await pilot.press("enter")
            await pilot.pause(0.1)

            self.assertFalse(dialog.running)
            self.assertIsNotNone(dialog.result)
            assert dialog.result is not None
            self.assertTrue(dialog.result.cancelled)
            self.assertIn("Command cancelled.", dialog.result.output)

            await pilot.press("escape")
            await pilot.pause(0.1)

            self.assertIsNot(app.screen, dialog)


if __name__ == "__main__":
    unittest.main()
