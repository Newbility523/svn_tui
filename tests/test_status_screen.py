from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path

from rich.text import Text
from textual.widgets import Header

from svn_tui.app import SvnTui
from svn_tui.models import SvnStatusEntry
from svn_tui.ui.dialogs import ConfirmActionDialog, SvnCommandDialog
from svn_tui.ui.screens.shelves import ShelfManagerScreen
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

    async def test_status_preview_loads_inline_diff_for_versioned_file(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")

            async def fake_diff_for_status_entry(selected):
                self.assertEqual(selected, entry)
                return "Index: README.md\n+added line\n"

            screen.client.diff_for_status_entry = fake_diff_for_status_entry
            screen.preview_request_id += 1
            await screen.load_preview(entry, screen.preview_request_id)

            self.assertFalse(screen.preview.display)
            self.assertTrue(screen.diff_preview.display)
            self.assertEqual(screen.diff_preview.lines, ["Index: README.md", "+added line", ""])

    async def test_status_preview_uses_file_preview_for_unversioned_file(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("new.txt").resolve(), "?", " ", "?")

            self.assertFalse(screen.should_show_inline_diff(entry))
            screen.schedule_preview(entry)

            self.assertTrue(screen.preview.display)
            self.assertFalse(screen.diff_preview.display)
            self.assertEqual(screen.preview_title.content, "File Preview")

    async def test_operation_output_panel_keeps_command_output(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen

            screen.set_operation_output(
                "Sending        README.md\nCommitted revision 7.\n",
                "Committed revision 7.",
            )

            self.assertEqual(
                screen.operation_output.lines,
                ["Sending        README.md", "Committed revision 7.", ""],
            )

    async def test_status_filter_shows_only_conflicts(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            modified = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            conflict = SvnStatusEntry(Path("conflict.txt").resolve(), "C", " ", "C")
            unversioned = SvnStatusEntry(Path("new.txt").resolve(), "?", " ", "?")
            screen.entries = [modified, conflict, unversioned]
            screen.status_filter = "conflicts"

            await screen.render_status_entries()

            row = screen.current_row()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row.entry, conflict)
            self.assertEqual(len([child for child in screen.list_view.children if isinstance(child, StatusRow)]), 1)

    async def test_checked_filter_preserves_and_removes_selection(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            second = SvnStatusEntry(Path("new.txt").resolve(), "?", " ", "?")
            screen.entries = [first, second]
            screen.selected_entry_paths = {second.path}
            screen.status_filter = "checked"

            await screen.render_status_entries()

            row = screen.current_row()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row.entry, second)
            self.assertTrue(row.selected_for_commit)

            await screen.action_toggle_entry()

            self.assertEqual(screen.selected_entry_paths, set())
            self.assertIsNone(screen.current_row())

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
                    "S     Open Shelves",
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
                    "S     Open Shelves",
                    "U     Update this Directory",
                    "R     Revert this Directory",
                    "C     Clean Up this Directory",
                    "X     Remove Unversioned...",
                ],
            )

    async def test_checked_action_menu_uses_batch_menu_for_one_checked_row(self) -> None:
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
            self.assertEqual(
                labels,
                [
                    "u     Update",
                    "c     Commit",
                    "r     Revert",
                    "y/Y   Copy",
                    "S     Open Shelves",
                    "U     Update this Directory",
                    "R     Revert this Directory",
                    "C     Clean Up this Directory",
                    "X     Remove Unversioned...",
                ],
            )
            self.assertEqual(screen.status_action_title.content, "README.md")
            self.assertEqual(screen.status_action_menu.styles.height.value, len(labels))
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
                    "S     Open Shelves",
                    "U     Update this Directory",
                    "R     Revert this Directory",
                    "C     Clean Up this Directory",
                    "X     Remove Unversioned...",
                ],
            )
            self.assertEqual(screen.status_action_title.content, "Multi")
            self.assertEqual(screen.status_action_menu.styles.height.value, len(labels))
            self.assertEqual(screen.status_action_rows, [first, second])

    async def test_checked_action_menu_includes_add_for_unversioned_rows(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            second = StatusRow(
                SvnStatusEntry(Path("new.txt").resolve(), "?", " ", "?"),
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
                    "a     Add",
                    "u     Update",
                    "c     Commit",
                    "r     Revert",
                    "y/Y   Copy",
                    "S     Open Shelves",
                    "U     Update this Directory",
                    "R     Revert this Directory",
                    "C     Clean Up this Directory",
                    "X     Remove Unversioned...",
                ],
            )
            self.assertEqual(screen.status_action_title.content, "Multi")
            self.assertEqual(screen.status_action_rows, [first, second])

    async def test_checked_action_menu_lowercase_a_adds_only_unversioned_rows(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            first = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            second = StatusRow(
                SvnStatusEntry(Path("new.txt").resolve(), "?", " ", "?"),
                Path(".").resolve(),
            )
            first.selected_for_commit = True
            second.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(first)
            await screen.list_view.append(second)
            screen.list_view.index = 0
            screen.list_view.focus()
            added = []

            async def fake_add_rows(rows):
                added.extend(rows)

            screen.add_rows = fake_add_rows

            await pilot.press("Z")
            await pilot.press("a")
            await pilot.pause(0.1)

            self.assertEqual(added, [second])
            self.assertFalse(screen.status_action_popup.display)

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

    async def test_commit_message_opens_svn_command_dialog(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            row = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            pushed = []

            def fake_push_screen(dialog, callback=None):
                pushed.append((dialog, callback))

            app.push_screen = fake_push_screen

            screen.handle_commit_message([row], "ship it")

            self.assertEqual(len(pushed), 1)
            dialog, callback = pushed[0]
            self.assertIsInstance(dialog, SvnCommandDialog)
            self.assertEqual(dialog.dialog_title, "SVN Commit")
            self.assertEqual(
                dialog.args,
                (
                    "svn",
                    "commit",
                    "-m",
                    "ship it",
                    "--",
                    str(row.entry.path),
                ),
            )
            self.assertIsNotNone(callback)

    async def test_checked_action_menu_opens_shelf_manager(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            row = StatusRow(
                SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M"),
                Path(".").resolve(),
            )
            row.selected_for_commit = True
            await screen.list_view.clear()
            await screen.list_view.append(row)
            screen.list_view.index = 0
            screen.list_view.focus()
            pushed = []

            def fake_push_screen(dialog, callback=None):
                pushed.append((dialog, callback))

            app.push_screen = fake_push_screen

            await pilot.press("Z")
            await pilot.press("S")
            await pilot.pause(0.1)

            self.assertEqual(len(pushed), 1)
            dialog, callback = pushed[0]
            self.assertIsInstance(dialog, ShelfManagerScreen)
            self.assertEqual(dialog.pending_entries, [row.entry])
            self.assertIsNone(callback)

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

    async def test_status_action_menu_revert_hotkey_opens_confirmation(self) -> None:
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

            async def fake_revert_paths(paths, detail_text, failure_title, success_title):
                reverted.append((paths, detail_text, failure_title, success_title))

            screen.revert_paths = fake_revert_paths

            await pilot.press("z")
            await pilot.press("r")
            await pilot.pause(0.1)

            self.assertIsInstance(app.screen, ConfirmActionDialog)
            self.assertEqual(reverted, [])
            self.assertFalse(screen.status_action_popup.display)

            await pilot.press("y")
            await pilot.pause(0.1)

            self.assertEqual(reverted[0][0], [entry.path])
            self.assertEqual(reverted[0][2], "svn revert failed")

    async def test_status_action_menu_revert_cancel_does_not_run(self) -> None:
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

            async def fake_revert_paths(paths, detail_text, failure_title, success_title):
                reverted.append(paths)

            screen.revert_paths = fake_revert_paths

            await pilot.press("z")
            await pilot.press("r")
            await pilot.press("escape")
            await pilot.pause(0.1)

            self.assertEqual(reverted, [])
            self.assertIs(app.screen, screen)

    async def test_unversioned_status_action_menu_adds_path(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("new.txt").resolve(), "?", " ", "?")
            row = StatusRow(entry, Path(".").resolve())
            await screen.list_view.clear()
            await screen.list_view.append(row)
            screen.list_view.index = 0
            screen.list_view.focus()
            added = []

            async def fake_add_rows(rows):
                added.extend(rows)

            screen.add_rows = fake_add_rows

            await pilot.press("z")
            await pilot.pause(0.1)

            labels = [
                label_plain_text(child.query_one("Label"))
                for child in screen.status_action_menu.children
            ]
            self.assertEqual(
                labels,
                ["a     Add", "i     Ignore", "y/Y   Copy", "S     Open Shelves"],
            )

            await pilot.press("a")
            await pilot.pause(0.1)

            self.assertEqual(added, [row])
            self.assertFalse(screen.status_action_popup.display)

    async def test_unversioned_status_action_menu_ignores_path(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("new.txt").resolve(), "?", " ", "?")
            row = StatusRow(entry, Path(".").resolve())
            await screen.list_view.clear()
            await screen.list_view.append(row)
            screen.list_view.index = 0
            screen.list_view.focus()
            ignored = []

            async def fake_ignore_rows(rows):
                ignored.extend(rows)

            screen.ignore_rows = fake_ignore_rows

            await pilot.press("z")
            await pilot.press("i")
            await pilot.pause(0.1)

            self.assertEqual(ignored, [row])
            self.assertFalse(screen.status_action_popup.display)

    async def test_conflict_status_action_menu_resolves_path(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("conflict.txt").resolve(), "C", " ", "C")
            row = StatusRow(entry, Path(".").resolve())
            await screen.list_view.clear()
            await screen.list_view.append(row)
            screen.list_view.index = 0
            screen.list_view.focus()
            resolved = []

            async def fake_resolve_rows(rows):
                resolved.extend(rows)

            screen.resolve_rows = fake_resolve_rows

            await pilot.press("z")
            await pilot.pause(0.1)

            labels = [
                label_plain_text(child.query_one("Label"))
                for child in screen.status_action_menu.children
            ]
            self.assertIn("s     Resolve Working", labels)

            await pilot.press("s")
            await pilot.pause(0.1)

            self.assertEqual(resolved, [row])
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

    async def test_checked_action_menu_uppercase_r_confirms_current_directory(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            await screen.list_view.clear()
            await screen.list_view.append(StatusRow(entry, Path(".").resolve()))
            screen.list_view.index = 0
            screen.list_view.focus()
            reverted = []

            async def fake_revert_paths(paths, detail_text, failure_title, success_title):
                reverted.append((paths, detail_text, failure_title, success_title))

            screen.revert_paths = fake_revert_paths

            await pilot.press("Z")
            await pilot.press("R")
            await pilot.pause(0.1)

            self.assertIsInstance(app.screen, ConfirmActionDialog)
            self.assertEqual(reverted, [])

            await pilot.press("y")
            await pilot.pause(0.1)

            self.assertEqual(reverted[0][0], [screen.status_directory_path()])
            self.assertIn("directory", reverted[0][1])

    async def test_checked_action_menu_uppercase_c_opens_cleanup_dialog(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            await screen.list_view.clear()
            await screen.list_view.append(StatusRow(entry, Path(".").resolve()))
            screen.list_view.index = 0
            screen.list_view.focus()
            cleanup_calls = []

            def fake_open_cleanup_dialog(**kwargs):
                cleanup_calls.append(kwargs)

            screen.open_cleanup_dialog = fake_open_cleanup_dialog

            await pilot.press("Z")
            await pilot.press("C")
            await pilot.pause(0.1)

            self.assertEqual(cleanup_calls, [{"remove_unversioned": False}])
            self.assertFalse(screen.status_action_popup.display)

    async def test_checked_action_menu_uppercase_x_confirms_remove_unversioned(self) -> None:
        app = SvnTui(Path("."))

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            entry = SvnStatusEntry(Path("README.md").resolve(), "M", " ", "M")
            await screen.list_view.clear()
            await screen.list_view.append(StatusRow(entry, Path(".").resolve()))
            screen.list_view.index = 0
            screen.list_view.focus()
            cleanup_calls = []

            def fake_open_cleanup_dialog(**kwargs):
                cleanup_calls.append(kwargs)

            screen.open_cleanup_dialog = fake_open_cleanup_dialog

            await pilot.press("Z")
            await pilot.press("X")
            await pilot.pause(0.1)

            self.assertIsInstance(app.screen, ConfirmActionDialog)
            self.assertEqual(cleanup_calls, [])

            await pilot.press("y")
            await pilot.pause(0.1)

            self.assertEqual(
                cleanup_calls,
                [
                    {
                        "remove_unversioned": True,
                        "path": screen.status_directory_path(),
                    }
                ],
            )

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
