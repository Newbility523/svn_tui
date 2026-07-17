from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.app import App

from svn_tui.models import SvnStatusEntry
from svn_tui.services.shelves import ShelfService, ShelfStore
from svn_tui.shelf_models import WorkingCopyIdentity
from svn_tui.ui.dialogs import ConfirmActionDialog, ShelfSaveDialog
from svn_tui.ui.screens.shelves import ShelfManagerScreen, ShelfRow, ShelfVersionRow
from svn_tui.ui.styles import APP_CSS


PATCH = """Index: src/app.py
===================================================================
--- src/app.py\t(revision 5)
+++ src/app.py\t(working copy)
@@ -1 +1,2 @@
 base
+local
"""


class FakeSvnClient:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.display_root = self.root
        self.target = self.root
        self.current_status: list[SvnStatusEntry] = []
        self.reverted: list[list[Path]] = []
        self.applied: list[Path] = []

    async def working_copy_identity(self) -> WorkingCopyIdentity:
        return WorkingCopyIdentity(
            wc_root=self.root,
            repo_uuid="ui-repo",
            repo_root_url="https://example.test/svn/project",
            target_relative_path="trunk",
            base_revision="5",
        )

    def relative_working_copy_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    async def diff_paths(self, paths: list[Path]) -> str:
        return PATCH

    async def path_base_revisions(self, paths: list[Path]) -> dict[str, str]:
        return {self.relative_working_copy_path(path): "5" for path in paths}

    async def revert_paths(self, paths: list[Path]) -> str:
        self.reverted.append(paths)
        return "Reverted selected paths"

    async def status_paths(self, paths: list[Path]) -> list[SvnStatusEntry]:
        return self.current_status

    async def apply_patch(self, patch_path: Path) -> str:
        self.applied.append(patch_path)
        return "U         src/app.py\n"


class ShelfTestApp(App[None]):
    CSS = APP_CSS

    def __init__(self, screen: ShelfManagerScreen) -> None:
        super().__init__()
        self.shelf_screen = screen

    def get_default_screen(self) -> ShelfManagerScreen:
        return self.shelf_screen


class ShelfManagerScreenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wc = self.root / "wc"
        (self.wc / "src").mkdir(parents=True)
        self.path = self.wc / "src" / "app.py"
        self.path.write_text("base\nlocal\n", encoding="utf-8")
        self.entry = SvnStatusEntry(self.path.resolve(), "M", " ", "M")
        self.client = FakeSvnClient(self.wc)
        self.store = ShelfStore(self.root / "data")
        self.service = ShelfService(self.client, self.store)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def app(self, entries: list[SvnStatusEntry] | None = None) -> ShelfTestApp:
        return ShelfTestApp(
            ShelfManagerScreen(
                self.client,  # type: ignore[arg-type]
                entries if entries is not None else [self.entry],
                service=self.service,
            )
        )

    async def test_empty_screen_has_three_panes_and_auto_name_dialog(self) -> None:
        app = self.app()

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            self.assertIsInstance(screen, ShelfManagerScreen)
            self.assertEqual(len(screen.query(ShelfRow)), 0)

            await pilot.press("n")
            await pilot.pause(0.1)

            self.assertIsInstance(app.screen, ShelfSaveDialog)
            await pilot.press("ctrl+j")
            await pilot.pause(0.3)

            self.assertIs(app.screen, screen)
            self.assertEqual(len(screen.query(ShelfRow)), 1)
            shelf = screen.current_shelf()
            self.assertIsNotNone(shelf)
            assert shelf is not None
            self.assertRegex(shelf.name, r"^shelf-\d{8}-\d{6}$")
            self.assertEqual(len(screen.query(ShelfVersionRow)), 1)

    async def test_no_selected_entries_blocks_new_shelf(self) -> None:
        app = self.app([])

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("n")
            await pilot.pause(0.1)

            self.assertIsInstance(app.screen, ShelfManagerScreen)
            self.assertEqual(self.store.list_shelves(await self.service.initialize()), [])

    async def test_running_operation_blocks_leaving_shelf_screen(self) -> None:
        app = self.app()

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            assert isinstance(screen, ShelfManagerScreen)
            screen.busy = True

            await pilot.press("ctrl+l")
            await pilot.pause(0.1)

            self.assertIs(app.screen, screen)

    async def test_shelve_selected_requires_confirmation_and_saves_new_version(self) -> None:
        await self.service.new_shelf([self.entry], name="feature-a")
        app = self.app()

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("s")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, ShelfSaveDialog)

            await pilot.press("ctrl+j")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, ConfirmActionDialog)

            await pilot.press("ctrl+j")
            await pilot.pause(0.3)

            versions = await self.service.list_versions("feature-a")
            self.assertEqual([version.kind for version in versions], ["checkpoint", "shelve"])
            self.assertEqual(len(self.client.reverted), 1)

    async def test_unshelve_conflict_requires_confirmation_and_applies_selected_version(self) -> None:
        version = await self.service.new_shelf([self.entry], name="feature-a")
        self.client.current_status = [self.entry]
        app = self.app()

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("u")
            await pilot.pause(0.2)

            self.assertIsInstance(app.screen, ConfirmActionDialog)
            await pilot.press("ctrl+j")
            await pilot.pause(0.3)

            self.assertEqual(self.client.applied, [version.patch_path])
            self.assertEqual(self.client.reverted, [[self.entry.path]])

    async def test_export_delete_open_and_copy_management_actions(self) -> None:
        version = await self.service.new_shelf([self.entry], name="feature-a")
        app = self.app()

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            screen = app.screen
            assert isinstance(screen, ShelfManagerScreen)

            await screen.export_patch(version, self.root / "exports")
            self.assertTrue((self.root / "exports" / "feature-a-v001.diff").is_file())

            with patch("svn_tui.ui.screens.shelves.open_directory") as open_mock:
                await pilot.press("o")
                open_mock.assert_called_once_with(screen.current_shelf().path)

            with patch.object(app, "copy_to_clipboard") as copy_mock:
                await pilot.press("y")
                copy_mock.assert_called_once_with(str(version.patch_path))

            await pilot.press("d")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, ConfirmActionDialog)
            await pilot.press("ctrl+j")
            await pilot.pause(0.2)
            self.assertEqual(await self.service.list_versions("feature-a"), [])

            await pilot.press("D")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, ConfirmActionDialog)
            await pilot.press("ctrl+j")
            await pilot.pause(0.2)
            self.assertEqual(await self.service.list_shelves(), [])


if __name__ == "__main__":
    unittest.main()
