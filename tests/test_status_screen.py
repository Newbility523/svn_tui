from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path

from rich.text import Text
from textual.widgets import Header

from svn_tui.app import SvnTui
from svn_tui.models import SvnStatusEntry
from svn_tui.ui.widgets import StatusRow


def label_plain_text(label) -> str:
    content = label.content
    if isinstance(content, Text):
        return content.plain
    return str(content)


class StatusScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_screen_does_not_render_textual_header(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)

            self.assertEqual(list(app.screen.query(Header)), [])

    async def test_status_action_menu_opens_with_hotkey_labels(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            await screen.list_view.clear()
            await screen.list_view.append(StatusRow(entry, Path(".").resolve()))
            screen.list_view.index = 0
            screen.list_view.focus()

            await pilot.press("z")
            await pilot.pause(0.1)

            labels = [
                label_plain_text(child.query_one("Label"))
                for child in screen.status_action_menu.children
            ]
            self.assertTrue(screen.status_action_popup.display)
            self.assertEqual(screen.status_action_title.content, "README.md")
            self.assertEqual(screen.status_action_menu.styles.height.value, len(labels))
            self.assertEqual(
                labels,
                [
                    "l/L   Log",
                    "b/B   Blame",
                    "d/D   Diff Base",
                    "h/H   Diff Head",
                    "y/Y   Copy",
                    "u     Update",
                    "r     Revert",
                ],
            )
            self.assertIsInstance(
                screen.status_action_menu.children[4].query_one("Label").content,
                Text,
            )

    async def test_checked_action_menu_without_selection_opens_directory_actions(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            await screen.list_view.clear()
            await screen.list_view.append(StatusRow(entry, Path(".").resolve()))
            screen.list_view.index = 0
            screen.list_view.focus()

            await pilot.press("Z")
            await pilot.pause(0.1)

            labels = [
                label_plain_text(child.query_one("Label"))
                for child in screen.status_action_menu.children
            ]
            self.assertTrue(screen.status_action_popup.display)
            self.assertEqual(screen.status_action_title.content, "Directory")
            self.assertEqual(
                labels,
                [
                    "U     Update this Directory",
                    "R     Revert this Directory",
                ],
            )

    async def test_checked_action_menu_uses_single_menu_for_one_checked_row(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            row = StatusRow(entry, Path(".").resolve())
            row.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(row)
            screen.list_view.index = 0
            screen.list_view.focus()

            await pilot.press("Z")
            await pilot.pause(0.1)

            labels = [
                label_plain_text(child.query_one("Label"))
                for child in screen.status_action_menu.children
            ]
            self.assertEqual(labels[0], "l/L   Log")
            self.assertEqual(screen.status_action_title.content, "README.md")
            self.assertEqual(screen.status_action_rows, [row])

    async def test_checked_action_menu_uses_batch_menu_for_multiple_checked_rows(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            second = StatusRow(
                SvnStatusEntry(Path("main.py").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            first.selected_for_commit = True
            second.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(first)
            await screen.list_view.append(second)
            screen.list_view.index = 0
            screen.list_view.focus()

            await pilot.press("Z")
            await pilot.pause(0.1)

            labels = [
                label_plain_text(child.query_one("Label"))
                for child in screen.status_action_menu.children
            ]
            self.assertEqual(
                labels,
                [
                    "u     Update",
                    "c     Commit",
                    "r     Revert",
                    "y/Y   Copy",
                    "U     Update this Directory",
                    "R     Revert this Directory",
                ],
            )
            self.assertEqual(screen.status_action_title.content, "Multi")
            self.assertEqual(screen.status_action_menu.styles.height.value, len(labels))
            self.assertEqual(screen.status_action_rows, [first, second])

    async def test_direct_c_does_not_open_commit_dialog(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            row = StatusRow(entry, Path(".").resolve())
            row.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(row)
            screen.list_view.index = 0
            screen.list_view.focus()

            await pilot.press("c")
            await pilot.pause(0.1)

            self.assertEqual(len(app.screen_stack), 1)

    async def test_status_action_menu_navigation_takes_priority(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            second = SvnStatusEntry(Path("main.py").resolve(), "M", " ", "M")
            await screen.list_view.clear()
            await screen.list_view.append(StatusRow(first, Path(".").resolve()))
            await screen.list_view.append(StatusRow(second, Path(".").resolve()))
            screen.list_view.index = 0
            screen.list_view.focus()

            await pilot.press("z")
            await pilot.press("j")
            await pilot.pause(0.1)

            self.assertEqual(screen.list_view.index, 0)
            self.assertEqual(screen.status_action_menu.index, 1)

    async def test_status_action_menu_hotkey_takes_priority_over_highlight(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            await screen.list_view.clear()
            await screen.list_view.append(StatusRow(entry, Path(".").resolve()))
            screen.list_view.index = 0
            screen.list_view.focus()
            diff_calls = []
            app.suspend = lambda: nullcontext()
            screen.client.open_diff = lambda selected: diff_calls.append(selected.path)

            await pilot.press("z")
            await pilot.press("d")
            await pilot.pause(0.1)

            self.assertEqual(diff_calls, [entry.path])
            self.assertFalse(screen.status_action_popup.display)

    async def test_status_action_menu_revert_hotkey_beats_refresh(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            row = StatusRow(entry, Path(".").resolve())
            await screen.list_view.clear()
            await screen.list_view.append(row)
            screen.list_view.index = 0
            screen.list_view.focus()
            reverted = []

            async def fake_revert_rows(rows):
                reverted.extend(rows)

            screen.revert_rows = fake_revert_rows

            await pilot.press("z")
            await pilot.press("r")
            await pilot.pause(0.1)

            self.assertEqual(reverted, [row])
            self.assertFalse(screen.status_action_popup.display)

    async def test_checked_action_menu_y_copies_multiple_paths(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            second = StatusRow(
                SvnStatusEntry(Path("main.py").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            first.selected_for_commit = True
            second.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(first)
            await screen.list_view.append(second)
            screen.list_view.index = 0
            screen.list_view.focus()
            copied = []
            app.copy_to_clipboard = lambda value: copied.append(value)

            await pilot.press("Z")
            await pilot.press("Y")
            await pilot.pause(0.1)

            self.assertEqual(copied, [f"{first.entry.path}\n{second.entry.path}"])
            self.assertFalse(screen.status_action_popup.display)

    async def test_checked_action_menu_lowercase_y_copies_multiple_paths(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            second = StatusRow(
                SvnStatusEntry(Path("main.py").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            first.selected_for_commit = True
            second.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(first)
            await screen.list_view.append(second)
            screen.list_view.index = 0
            screen.list_view.focus()
            copied = []
            app.copy_to_clipboard = lambda value: copied.append(value)

            await pilot.press("Z")
            await pilot.press("y")
            await pilot.pause(0.1)

            self.assertEqual(copied, [f"{first.entry.path}\n{second.entry.path}"])
            self.assertFalse(screen.status_action_popup.display)

    async def test_checked_action_menu_uppercase_u_updates_current_directory(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            second = StatusRow(
                SvnStatusEntry(Path("main.py").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            first.selected_for_commit = True
            second.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(first)
            await screen.list_view.append(second)
            screen.list_view.index = 0
            screen.list_view.focus()
            updated = []

            async def fake_update_paths(paths, detail_text, failure_title, success_title):
                updated.append((paths, detail_text, failure_title, success_title))

            screen.update_paths = fake_update_paths

            await pilot.press("Z")
            await pilot.press("U")
            await pilot.pause(0.1)

            self.assertEqual(updated[0][0], [screen.status_directory_path()])
            self.assertIn("directory", updated[0][1])
            self.assertFalse(screen.status_action_popup.display)

    async def test_checked_action_menu_lowercase_u_updates_selected_rows(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            second = StatusRow(
                SvnStatusEntry(Path("main.py").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            first.selected_for_commit = True
            second.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(first)
            await screen.list_view.append(second)
            screen.list_view.index = 0
            screen.list_view.focus()
            updated = []

            async def fake_update_rows(rows):
                updated.extend(rows)

            screen.update_rows = fake_update_rows

            await pilot.press("Z")
            await pilot.press("u")
            await pilot.pause(0.1)

            self.assertEqual(updated, [first, second])
            self.assertFalse(screen.status_action_popup.display)


if __name__ == "__main__":
    unittest.main()
