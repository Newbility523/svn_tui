from __future__ import annotations

import sys
import unittest
from pathlib import Path

from textual.widgets import Button, Static

from svn_tui.app import SvnTui
from svn_tui.ui.dialogs import SvnCommandDialog


def button_label(button: Button) -> str:
    label = button.label
    return label.plain if hasattr(label, "plain") else str(label)


class SvnCommandDialogTests(unittest.IsolatedAsyncioTestCase):
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
