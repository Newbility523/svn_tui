from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Label, ListItem, ListView, Static

from svn_tui.models import SvnStatusEntry
from svn_tui.services.shelves import (
    Shelf,
    ShelfStore,
    ShelfVersion,
    ShelfWorkspace,
    build_shelf_workspace,
    shelfable_entries,
)
from svn_tui.services.svn import SvnClient
from svn_tui.ui.dialogs import ConfirmActionDialog, TextInputDialog
from svn_tui.ui.navigation import NavigationBar
from svn_tui.ui.widgets import TextPreviewView
from svn_tui.utils.paths import relative_path


class ShelfRow(ListItem):
    def __init__(self, shelf: Shelf) -> None:
        super().__init__()
        self.shelf = shelf
        self.label = Label(self.row_label())

    def compose(self) -> ComposeResult:
        yield self.label

    def row_label(self) -> Text:
        latest = self.shelf.latest_version
        if latest is None:
            return Text(f"{self.shelf.name:<28} -")
        return Text(
            f"{self.shelf.name:<28} v{latest.version:03d} "
            f"{latest.kind:<10} {len(latest.paths)} files"
        )


class ShelfVersionRow(ListItem):
    def __init__(self, version: ShelfVersion) -> None:
        super().__init__()
        self.version = version
        self.label = Label(self.row_label())

    def compose(self) -> ComposeResult:
        yield self.label

    def row_label(self) -> Text:
        return Text(
            f"v{self.version.version:03d}  "
            f"{self.version.kind:<10}  "
            f"{len(self.version.paths)} files"
        )


class ShelfManagerScreen(Screen[None]):
    BINDINGS = [
        Binding("ctrl+l", "close", "Back"),
        Binding("tab", "focus_next_pane", "Switch pane"),
        Binding("shift+tab", "focus_previous_pane", "Prev pane", show=False),
        Binding("n", "new_shelf", "New Shelf"),
        Binding("p", "save_checkpoint", "Checkpoint"),
        Binding("s", "shelve_selected", "Shelve"),
        Binding("u", "unshelve_version", "Unshelve"),
        Binding("d", "delete_version", "Delete version", show=False),
        Binding("D", "delete_shelf", "Delete shelf", show=False),
        Binding("y", "copy_patch_path", "Copy patch", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("ctrl+f", "page_down", "Page down", show=False),
        Binding("ctrl+b", "page_up", "Page up", show=False),
        Binding("ctrl+e", "preview_scroll_down", "Preview down", show=False),
        Binding("ctrl+y", "preview_scroll_up", "Preview up", show=False),
        Binding("ctrl+d", "preview_half_page_down", "Preview half down", show=False),
        Binding("ctrl+u", "preview_half_page_up", "Preview half up", show=False),
        Binding("shift+right", "preview_scroll_right", "Preview right", show=False),
        Binding("shift+left", "preview_scroll_left", "Preview left", show=False),
    ]

    def __init__(
        self,
        client: SvnClient,
        pending_entries: list[SvnStatusEntry],
        *,
        store: ShelfStore | None = None,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.pending_entries = pending_entries
        self.store = store or ShelfStore()
        self.on_changed = on_changed
        self.navigation_bar = NavigationBar()
        self.banner = Static(id="shelf-banner")
        self.pending = Static(id="shelf-pending")
        self.shelf_list = ListView(id="shelf-list")
        self.version_list = ListView(id="shelf-version-list")
        self.detail = Static(id="shelf-detail")
        self.preview_title = Static("Patch Preview", id="shelf-preview-title")
        self.preview = TextPreviewView(id="shelf-preview")
        self.workspace: ShelfWorkspace | None = None
        self.shelves: list[Shelf] = []
        self.load_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield self.navigation_bar
        yield self.banner
        with Horizontal(id="shelf-body"):
            with Vertical(classes="shelf-pane", id="shelf-left"):
                yield Static("Pending Changes", classes="shelf-pane-title")
                yield self.pending
                yield Static("Shelves", classes="shelf-pane-title")
                yield self.shelf_list
            with Vertical(classes="shelf-pane", id="shelf-middle"):
                yield Static("Versions", classes="shelf-pane-title")
                yield self.version_list
            with Vertical(classes="shelf-pane", id="shelf-right"):
                yield self.preview_title
                yield self.preview
                yield self.detail
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_navigation_bar()
        self.banner.update(f"Shelves  {self.client.display_root}")
        self.preview.set_message(Text("Loading shelves...", style="dim"))
        self.detail.update(Text("Loading shelf metadata...", style="dim"))
        self.refresh_pending()
        self.load_task = asyncio.create_task(self.load_shelves())

    def on_unmount(self) -> None:
        if self.load_task is not None:
            self.load_task.cancel()

    def refresh_navigation_bar(self) -> None:
        self.navigation_bar.refresh_from_screens(self.app.screen_stack)

    def refresh_pending(self) -> None:
        entries = shelfable_entries(self.pending_entries)
        if entries:
            self.pending.update(
                Text(f"{len(entries)} selected versioned path(s)", style="bold")
            )
            return
        self.pending.update(Text("No selected versioned changes.", style="dim"))

    async def load_shelves(self, *, select_storage_id: str | None = None) -> None:
        try:
            self.workspace = await build_shelf_workspace(self.client)
        except FileNotFoundError as exc:
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            self.preview.set_message(Text("Unable to load shelf metadata.", style="red"))
            return
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.notify(message, title="svn info failed", severity="error")
            self.preview.set_message(Text(message, style="red"))
            return
        except asyncio.CancelledError:
            return

        self.shelves = self.store.list_shelves(self.workspace)
        await self.refresh_shelf_list(select_storage_id=select_storage_id)

    async def refresh_shelf_list(self, *, select_storage_id: str | None = None) -> None:
        await self.shelf_list.clear()
        if not self.shelves:
            await self.shelf_list.append(ListItem(Label("No shelves yet.")))
            await self.version_list.clear()
            self.preview.set_message(Text("Create a shelf with n.", style="dim"))
            self.detail.update(Text("New Shelf saves the first checkpoint.", style="dim"))
            self.shelf_list.focus()
            return

        await self.shelf_list.extend(ShelfRow(shelf) for shelf in self.shelves)
        index = 0
        if select_storage_id is not None:
            for position, shelf in enumerate(self.shelves):
                if shelf.storage_id == select_storage_id:
                    index = position
                    break
        self.shelf_list.index = index
        self.shelf_list.focus()
        await self.refresh_versions_for_current_shelf()

    async def refresh_versions_for_current_shelf(self) -> None:
        shelf = self.current_shelf()
        await self.version_list.clear()
        if shelf is None:
            self.preview.set_message(Text("No shelf selected.", style="dim"))
            self.detail.update(Text(""))
            return
        if not shelf.versions:
            await self.version_list.append(ListItem(Label("No versions yet.")))
            self.preview.set_message(Text("Save a checkpoint with p.", style="dim"))
            self.detail.update(Text(""))
            return
        await self.version_list.extend(
            ShelfVersionRow(version) for version in shelf.versions
        )
        self.version_list.index = 0
        self.update_version_preview(shelf.versions[0])

    def current_shelf(self) -> Shelf | None:
        highlighted = self.shelf_list.highlighted_child
        if isinstance(highlighted, ShelfRow):
            return highlighted.shelf
        if self.shelf_list.index is None:
            return None
        if self.shelf_list.index >= len(self.shelves):
            return None
        return self.shelves[self.shelf_list.index]

    def current_version(self) -> ShelfVersion | None:
        highlighted = self.version_list.highlighted_child
        if isinstance(highlighted, ShelfVersionRow):
            return highlighted.version
        shelf = self.current_shelf()
        if shelf is None or self.version_list.index is None:
            return None
        if self.version_list.index >= len(shelf.versions):
            return None
        return shelf.versions[self.version_list.index]

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is self.shelf_list:
            await self.refresh_versions_for_current_shelf()
            return
        if event.list_view is self.version_list:
            version = self.current_version()
            if version is not None:
                self.update_version_preview(version)

    def update_version_preview(self, version: ShelfVersion) -> None:
        patch_text = version.patch_path.read_text(encoding="utf-8")
        if patch_text.strip():
            self.preview.set_text(patch_text, lexer="diff", line_numbers=False)
        else:
            self.preview.set_message(Text("No textual diff saved.", style="dim"))
        paths = "\n".join(f"- {path}" for path in version.paths)
        self.detail.update(
            Text(
                "\n".join(
                    [
                        f"{version.shelf_name} v{version.version:03d}",
                        f"Kind: {version.kind}",
                        f"Created: {version.created_at}",
                        "",
                        paths or "(no paths)",
                    ]
                )
            )
        )

    def action_new_shelf(self) -> None:
        self.app.push_screen(
            TextInputDialog(
                "New Shelf",
                placeholder="Shelf name",
                confirm_label="Create",
            ),
            self.handle_new_shelf_name,
        )

    def handle_new_shelf_name(self, shelf_name: str | None) -> None:
        if shelf_name is None:
            self.shelf_list.focus()
            return
        if not shelf_name.strip():
            self.notify("Enter a shelf name.", title="shelves", severity="warning")
            self.shelf_list.focus()
            return
        asyncio.create_task(self.save_version(shelf_name.strip(), "checkpoint"))

    def action_save_checkpoint(self) -> None:
        shelf = self.current_shelf()
        if shelf is None:
            self.notify("Create or select a shelf first.", title="shelves", severity="warning")
            return
        asyncio.create_task(self.save_version(shelf.name, "checkpoint"))

    def action_shelve_selected(self) -> None:
        shelf = self.current_shelf()
        if shelf is None:
            self.notify("Create or select a shelf first.", title="shelves", severity="warning")
            return
        entries = shelfable_entries(self.pending_entries)
        if not entries:
            self.notify(
                "Select versioned changes before shelving.",
                title="shelves",
                severity="warning",
            )
            return
        self.app.push_screen(
            ConfirmActionDialog(
                "Shelve Selected",
                self.shelve_confirmation_message(entries),
                confirm_label="Shelve",
            ),
            lambda confirmed: self.handle_shelve_confirmation(
                confirmed,
                shelf.name,
            ),
        )

    def handle_shelve_confirmation(self, confirmed: bool, shelf_name: str) -> None:
        if not confirmed:
            self.shelf_list.focus()
            return
        asyncio.create_task(self.shelve_selected(shelf_name))

    async def save_version(
        self,
        shelf_name: str,
        kind: str,
    ) -> ShelfVersion | None:
        if self.workspace is None:
            self.notify("Shelf metadata is still loading.", title="shelves", severity="warning")
            return None
        entries = shelfable_entries(self.pending_entries)
        if not entries:
            self.notify(
                "Select versioned text changes before saving a shelf version.",
                title="shelves",
                severity="warning",
            )
            return None
        paths = [entry.path for entry in entries]
        try:
            patch_text = await self.client.diff_paths(paths)
        except FileNotFoundError as exc:
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            return None
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.notify(message, title="svn diff failed", severity="error")
            return None
        except asyncio.CancelledError:
            return None

        if not patch_text.strip():
            self.notify("No textual diff to save.", title="shelves", severity="warning")
            return None
        version = self.store.create_version(
            self.workspace,
            shelf_name,
            kind,  # type: ignore[arg-type]
            patch_text,
            entries,
        )
        await self.load_shelves(select_storage_id=version.storage_id)
        self.notify(
            f"Saved {shelf_name} v{version.version:03d}.",
            title="shelves",
        )
        return version

    async def shelve_selected(self, shelf_name: str) -> None:
        version = await self.save_version(shelf_name, "shelve")
        if version is None or self.workspace is None:
            return
        paths = [self.workspace.working_copy_root / path for path in version.paths]
        try:
            await self.client.revert_paths(paths)
        except FileNotFoundError as exc:
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            return
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.notify(message, title="svn revert failed", severity="error")
            return
        except asyncio.CancelledError:
            return
        self.notify(
            f"Shelved and reverted {len(paths)} path(s).",
            title="shelves",
        )
        self.notify_changed()

    def action_unshelve_version(self) -> None:
        version = self.current_version()
        if version is None:
            self.notify("Select a shelf version first.", title="shelves", severity="warning")
            return
        asyncio.create_task(self.confirm_or_unshelve(version))

    async def confirm_or_unshelve(self, version: ShelfVersion) -> None:
        if self.workspace is None:
            return
        paths = [self.workspace.working_copy_root / path for path in version.paths]
        try:
            changed = await self.client.status_paths(paths)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            message = getattr(exc, "stderr", "") or getattr(exc, "output", "") or str(exc)
            self.notify(str(message).strip(), title="svn status failed", severity="error")
            return
        if changed:
            self.app.push_screen(
                ConfirmActionDialog(
                    "Unshelve Version",
                    self.unshelve_confirmation_message(version, changed),
                    confirm_label="Unshelve",
                ),
                lambda confirmed: self.handle_unshelve_confirmation(
                    confirmed,
                    version,
                ),
            )
            return
        await self.unshelve_version(version)

    def handle_unshelve_confirmation(
        self,
        confirmed: bool,
        version: ShelfVersion,
    ) -> None:
        if not confirmed:
            self.version_list.focus()
            return
        asyncio.create_task(self.unshelve_version(version))

    async def unshelve_version(self, version: ShelfVersion) -> None:
        if self.workspace is None:
            return
        paths = [self.workspace.working_copy_root / path for path in version.paths]
        try:
            await self.client.revert_paths(paths)
            await self.client.patch_file(version.patch_path)
        except FileNotFoundError as exc:
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            return
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.notify(message, title="unshelve failed", severity="error")
            return
        except asyncio.CancelledError:
            return
        self.notify(
            f"Unshelved {version.shelf_name} v{version.version:03d}.",
            title="shelves",
        )
        self.notify_changed()

    def action_delete_version(self) -> None:
        version = self.current_version()
        if version is None:
            return
        self.app.push_screen(
            ConfirmActionDialog(
                "Delete Shelf Version",
                f"Delete {version.shelf_name} v{version.version:03d}?",
                confirm_label="Delete",
            ),
            lambda confirmed: self.handle_delete_version_confirmation(
                confirmed,
                version,
            ),
        )

    def handle_delete_version_confirmation(
        self,
        confirmed: bool,
        version: ShelfVersion,
    ) -> None:
        if not confirmed:
            self.version_list.focus()
            return
        self.store.delete_version(version)
        asyncio.create_task(self.load_shelves(select_storage_id=version.storage_id))

    def action_delete_shelf(self) -> None:
        shelf = self.current_shelf()
        if shelf is None:
            return
        self.app.push_screen(
            ConfirmActionDialog(
                "Delete Shelf",
                f"Delete shelf {shelf.name} and all versions?",
                confirm_label="Delete",
            ),
            lambda confirmed: self.handle_delete_shelf_confirmation(confirmed, shelf),
        )

    def handle_delete_shelf_confirmation(self, confirmed: bool, shelf: Shelf) -> None:
        if not confirmed:
            self.shelf_list.focus()
            return
        self.store.delete_shelf(shelf)
        asyncio.create_task(self.load_shelves())

    def action_copy_patch_path(self) -> None:
        version = self.current_version()
        if version is None:
            return
        self.app.copy_to_clipboard(str(version.patch_path))
        self.notify("Copied patch path.", title="clipboard")

    def notify_changed(self) -> None:
        if self.on_changed is not None:
            self.on_changed()

    def shelve_confirmation_message(self, entries: list[SvnStatusEntry]) -> str:
        paths = "\n".join(
            f"- {relative_path(entry.path, self.client.root)}" for entry in entries
        )
        return "\n".join(
            [
                "Save a shelf version and revert only these selected paths:",
                "",
                paths,
                "",
                "Other local changes will not be touched.",
            ]
        )

    def unshelve_confirmation_message(
        self,
        version: ShelfVersion,
        changed: list[SvnStatusEntry],
    ) -> str:
        paths = "\n".join(
            f"- {relative_path(entry.path, self.client.root)}" for entry in changed
        )
        return "\n".join(
            [
                f"Unshelve {version.shelf_name} v{version.version:03d}?",
                "",
                "Current local changes on these saved paths will be discarded:",
                "",
                paths,
                "",
                "Other local changes will not be touched.",
            ]
        )

    def focused_list(self) -> ListView:
        if self.version_list.has_focus:
            return self.version_list
        return self.shelf_list

    def focus_targets(self) -> list[ListView]:
        return [self.shelf_list, self.version_list]

    def action_focus_next_pane(self) -> None:
        targets = self.focus_targets()
        if self.version_list.has_focus:
            self.shelf_list.focus()
            return
        self.version_list.focus()

    def action_focus_previous_pane(self) -> None:
        self.action_focus_next_pane()

    def action_cursor_down(self) -> None:
        self.focused_list().action_cursor_down()

    def action_cursor_up(self) -> None:
        self.focused_list().action_cursor_up()

    def action_page_down(self) -> None:
        self.focused_list().action_page_down()

    def action_page_up(self) -> None:
        self.focused_list().action_page_up()

    def action_preview_scroll_down(self) -> None:
        self.preview.scroll_relative(y=1, animate=False, immediate=True)

    def action_preview_scroll_up(self) -> None:
        self.preview.scroll_relative(y=-1, animate=False, immediate=True)

    def action_preview_half_page_down(self) -> None:
        self.preview.scroll_relative(
            y=max(1, self.preview.size.height // 2),
            animate=False,
            immediate=True,
        )

    def action_preview_half_page_up(self) -> None:
        self.preview.scroll_relative(
            y=-max(1, self.preview.size.height // 2),
            animate=False,
            immediate=True,
        )

    def action_preview_scroll_right(self) -> None:
        self.preview.scroll_relative(x=8, animate=False, immediate=True)

    def action_preview_scroll_left(self) -> None:
        self.preview.scroll_relative(x=-8, animate=False, immediate=True)

    def action_close(self) -> None:
        self.app.pop_screen()
