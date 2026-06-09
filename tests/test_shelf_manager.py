from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from svn_tui.app import SvnTui
from svn_tui.models import SvnStatusEntry
from svn_tui.services.shelves import ShelfStore, ShelfWorkspace
from svn_tui.services.svn import SvnClient
from svn_tui.ui.screens.shelves import ShelfManagerScreen


class ShelfManagerScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_shelf_saves_first_checkpoint(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = test_workspace(root)
            entry = SvnStatusEntry(workspace.working_copy_root / "a.py", "M", " ", "M")
            store = ShelfStore(root / "shelves")
            client = SvnClient(workspace.working_copy_root)
            client.diff_paths = async_return("Index: a.py\n+hello\n")
            screen = ShelfManagerScreen(client, [entry], store=store)
            app = SvnTui(Path("."))

            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause(0.2)
                with patch(
                    "svn_tui.ui.screens.shelves.build_shelf_workspace",
                    async_return(workspace),
                ):
                    app.push_screen(screen)
                    await pilot.pause(0.2)
                    screen.handle_new_shelf_name("fix a")
                    await pilot.pause(0.2)

            shelves = store.list_shelves(workspace)
            self.assertEqual(len(shelves), 1)
            self.assertEqual(shelves[0].name, "fix a")
            self.assertEqual(shelves[0].versions[0].kind, "checkpoint")
            self.assertEqual(shelves[0].versions[0].paths, (Path("a.py"),))

    async def test_shelve_selected_saves_and_reverts_version_paths(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = test_workspace(root)
            entry = SvnStatusEntry(workspace.working_copy_root / "a.py", "M", " ", "M")
            store = ShelfStore(root / "shelves")
            client = SvnClient(workspace.working_copy_root)
            reverted = []
            client.diff_paths = async_return("Index: a.py\n+hello\n")
            client.revert_paths = async_append(reverted)
            screen = ShelfManagerScreen(client, [entry], store=store)
            app = SvnTui(Path("."))

            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause(0.2)
                with patch(
                    "svn_tui.ui.screens.shelves.build_shelf_workspace",
                    async_return(workspace),
                ):
                    app.push_screen(screen)
                    await pilot.pause(0.2)
                    await screen.shelve_selected("fix a")
                    await pilot.pause(0.1)

            shelves = store.list_shelves(workspace)
            self.assertEqual(shelves[0].versions[0].kind, "shelve")
            self.assertEqual(reverted, [[workspace.working_copy_root / "a.py"]])

    async def test_unshelve_version_reverts_and_applies_patch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = test_workspace(root)
            entry = SvnStatusEntry(workspace.working_copy_root / "a.py", "M", " ", "M")
            store = ShelfStore(root / "shelves")
            version = store.create_version(
                workspace,
                "fix a",
                "checkpoint",
                "Index: a.py\n+hello\n",
                [entry],
            )
            client = SvnClient(workspace.working_copy_root)
            reverted = []
            patched = []
            client.revert_paths = async_append(reverted)
            client.patch_file = async_append(patched)
            screen = ShelfManagerScreen(client, [], store=store)
            screen.workspace = workspace
            app = SvnTui(Path("."))

            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause(0.2)
                app.push_screen(screen)
                await pilot.pause(0.1)
                await screen.unshelve_version(version)
                await pilot.pause(0.1)

            self.assertEqual(reverted, [[workspace.working_copy_root / "a.py"]])
            self.assertEqual(patched, [version.patch_path])


def test_workspace(root: Path) -> ShelfWorkspace:
    return ShelfWorkspace(
        fingerprint="abc123",
        working_copy_root=root / "wc",
        repo_uuid="uuid",
        repo_root_url="https://svn.example/repo",
        target_relpath="/trunk/app",
        base_revision="42",
    )


def async_return(value):
    async def inner(*args, **kwargs):
        del args, kwargs
        return value

    return inner


def async_append(target):
    async def inner(value):
        target.append(value)
        return ""

    return inner


if __name__ == "__main__":
    unittest.main()
