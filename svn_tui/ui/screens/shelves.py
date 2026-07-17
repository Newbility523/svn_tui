from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Label, ListItem, ListView, Static

from svn_tui.models import SvnStatusEntry
from svn_tui.services.shelves import (
    ShelfError,
    ShelfOperationError,
    ShelfOverwriteRequired,
    ShelfSelectionError,
    ShelfService,
    open_directory,
)
from svn_tui.services.svn import SvnClient
from svn_tui.shelf_models import Shelf, ShelfVersion
from svn_tui.ui.dialogs import (
    ConfirmActionDialog,
    ExportPatchDialog,
    ShelfSaveDialog,
    ShelfSaveRequest,
)
from svn_tui.ui.navigation import NavigationBar
from svn_tui.ui.widgets import TextPreviewView


class ShelfRow(ListItem):
    def __init__(self, shelf: Shelf) -> None:
        super().__init__()
        self.shelf = shelf

    def compose(self) -> ComposeResult:
        latest = f"v{self.shelf.latest_version:03d}" if self.shelf.latest_version else "-"
        kind = self.shelf.latest_kind.title() if self.shelf.latest_kind else "Empty"
        date = display_timestamp(self.shelf.updated_at)
        yield Label(
            f"{self.shelf.name}  {latest}  {kind}  "
            f"{self.shelf.version_count} version(s)  {date}"
        )


class ShelfVersionRow(ListItem):
    def __init__(self, version: ShelfVersion) -> None:
        super().__init__()
        self.version = version

    def compose(self) -> ComposeResult:
        yield Label(
            f"{self.version.label}  {self.version.kind.title():<10}  "
            f"{len(self.version.paths)} file(s)  {display_timestamp(self.version.created_at)}"
        )


class ShelfManagerScreen(Screen[None]):
    BINDINGS = [
        Binding("q", "quit_guarded", "Quit"),
        Binding("ctrl+l", "close", "Back"),
        Binding("tab", "focus_next_pane", "Switch pane"),
        Binding("shift+tab", "focus_previous_pane", "Prev pane", show=False),
        Binding("n", "new_shelf", "New Shelf"),
        Binding("c", "save_checkpoint", "Checkpoint"),
        Binding("s", "shelve_selected", "Shelve"),
        Binding("u", "unshelve_version", "Unshelve"),
        Binding("e", "export_patch", "Export"),
        Binding("d", "delete_version", "Delete version"),
        Binding("D", "delete_shelf", "Delete shelf", show=False),
        Binding("o", "open_folder", "Open folder"),
        Binding("y", "copy_path", "Copy path"),
        Binding("r", "refresh_shelves", "Refresh"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("ctrl+f", "page_down", "Page down", show=False),
        Binding("ctrl+b", "page_up", "Page up", show=False),
        Binding("ctrl+e", "preview_scroll_down", "Preview down", show=False),
        Binding("ctrl+y", "preview_scroll_up", "Preview up", show=False),
    ]

    def __init__(
        self,
        client: SvnClient,
        selected_entries: list[SvnStatusEntry] | None = None,
        *,
        service: ShelfService | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.selected_entries = list(selected_entries or [])
        self.service = service or ShelfService(client)
        self.navigation_bar = NavigationBar()
        self.banner = Static(id="shelf-banner")
        self.shelf_list = ListView(id="shelf-list")
        self.version_list = ListView(id="shelf-version-list")
        self.detail = Static(id="shelf-detail")
        self.patch_preview = TextPreviewView(id="shelf-patch-preview")
        self.operation_status = Static(id="shelf-operation-status")
        self.busy = False

    def compose(self) -> ComposeResult:
        yield self.navigation_bar
        yield self.banner
        with Horizontal(id="shelf-body"):
            with Vertical(classes="shelf-pane", id="shelf-list-pane"):
                yield Static("Shelves", classes="shelf-pane-title")
                yield self.shelf_list
            with Vertical(classes="shelf-pane", id="shelf-version-pane"):
                yield Static("Versions", classes="shelf-pane-title")
                yield self.version_list
            with Vertical(classes="shelf-pane", id="shelf-detail-pane"):
                yield Static("Version Details", classes="shelf-pane-title")
                yield self.detail
                yield Static("Patch Preview", classes="shelf-pane-title")
                yield self.patch_preview
        yield self.operation_status
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_navigation_bar()
        self.banner.update(
            f"Shelf Manager  {self.client.display_root}  "
            f"Selected status paths: {len(self.selected_entries)}"
        )
        self.detail.update(Text("Loading Shelves...", style="dim"))
        self.patch_preview.set_message(Text("Select a Shelf version.", style="dim"))
        self.operation_status.update("Ready")
        self.shelf_list.focus()
        asyncio.create_task(self.load_shelves())

    def on_screen_resume(self, event: object) -> None:
        del event
        self.refresh_navigation_bar()

    def refresh_navigation_bar(self) -> None:
        self.navigation_bar.refresh_from_screens(self.app.screen_stack)

    async def load_shelves(self, selected_name: str | None = None) -> None:
        try:
            shelves = await self.service.list_shelves()
        except (ShelfError, OSError, subprocess.CalledProcessError) as exc:
            self.show_error(exc, "Unable to load Shelves")
            return
        await self.shelf_list.clear()
        await self.version_list.clear()
        if not shelves:
            await self.shelf_list.append(ListItem(Label("No Shelves yet. Press n to create one.")))
            self.detail.update(Text("No Shelf selected.", style="dim"))
            self.patch_preview.set_message(Text("No Shelf versions.", style="dim"))
            return
        await self.shelf_list.extend(ShelfRow(shelf) for shelf in shelves)
        selected_index = next(
            (index for index, shelf in enumerate(shelves) if shelf.name == selected_name),
            0,
        )
        self.shelf_list.index = selected_index
        self.shelf_list.focus()
        await self.load_versions(shelves[selected_index])

    async def load_versions(
        self,
        shelf: Shelf,
        selected_number: int | None = None,
    ) -> None:
        try:
            versions = await self.service.list_versions(shelf.name)
        except (ShelfError, OSError) as exc:
            self.show_error(exc, "Unable to load Shelf versions")
            return
        await self.version_list.clear()
        if not versions:
            await self.version_list.append(ListItem(Label("No versions.")))
            self.detail.update(Text(f"Shelf: {shelf.name}\nNo saved versions.", style="dim"))
            self.patch_preview.set_message(Text("No patch selected.", style="dim"))
            return
        shown = list(reversed(versions))
        await self.version_list.extend(ShelfVersionRow(version) for version in shown)
        selected_index = next(
            (index for index, version in enumerate(shown) if version.number == selected_number),
            0,
        )
        self.version_list.index = selected_index
        self.show_version(shown[selected_index])

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is self.shelf_list and isinstance(event.item, ShelfRow):
            await self.load_versions(event.item.shelf)
        elif event.list_view is self.version_list and isinstance(event.item, ShelfVersionRow):
            self.show_version(event.item.version)

    def show_version(self, version: ShelfVersion) -> None:
        paths = "\n".join(f"  {path}" for path in version.paths)
        note = version.note or "(none)"
        self.detail.update(
            "\n".join(
                [
                    f"Shelf: {version.shelf_name}",
                    f"Version: {version.label} ({version.kind})",
                    f"Created: {version.created_at}",
                    f"Base revision: {version.base_revision}",
                    f"Note: {note}",
                    "Paths:",
                    paths,
                ]
            )
        )
        try:
            patch = version.patch_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.patch_preview.set_message(Text(str(exc), style="red"))
            return
        self.patch_preview.set_text(patch, lexer="diff", line_numbers=False)

    def current_shelf(self) -> Shelf | None:
        item = self.shelf_list.highlighted_child
        if isinstance(item, ShelfRow):
            return item.shelf
        if self.shelf_list.index is not None and self.shelf_list.index < len(self.shelf_list.children):
            indexed = self.shelf_list.children[self.shelf_list.index]
            return indexed.shelf if isinstance(indexed, ShelfRow) else None
        return None

    def current_version(self) -> ShelfVersion | None:
        item = self.version_list.highlighted_child
        if isinstance(item, ShelfVersionRow):
            return item.version
        if self.version_list.index is not None and self.version_list.index < len(self.version_list.children):
            indexed = self.version_list.children[self.version_list.index]
            return indexed.version if isinstance(indexed, ShelfVersionRow) else None
        return None

    def action_new_shelf(self) -> None:
        if not self.action_allowed():
            return
        if not self.require_selected_entries():
            return
        self.app.push_screen(
            ShelfSaveDialog("New Shelf", include_name=True, confirm_label="Save Checkpoint"),
            self.handle_new_shelf_request,
        )

    def handle_new_shelf_request(self, request: ShelfSaveRequest | None) -> None:
        if request is not None:
            asyncio.create_task(self.create_new_shelf(request))

    async def create_new_shelf(self, request: ShelfSaveRequest) -> None:
        if not self.begin_operation("Saving first checkpoint..."):
            return
        try:
            version = await self.service.new_shelf(
                self.selected_entries,
                name=request.name,
                note=request.note,
            )
        except (ShelfError, OSError, subprocess.CalledProcessError) as exc:
            self.show_error(exc, "New Shelf failed")
        else:
            self.show_success(f"Saved {version.shelf_name} {version.label}.")
            await self.load_shelves(version.shelf_name)
        finally:
            self.busy = False

    def action_save_checkpoint(self) -> None:
        if not self.action_allowed():
            return
        shelf = self.require_shelf_and_entries()
        if shelf is None:
            return
        self.app.push_screen(
            ShelfSaveDialog("Save Checkpoint", include_name=False, confirm_label="Save"),
            lambda request: self.handle_checkpoint_request(shelf, request),
        )

    def handle_checkpoint_request(
        self,
        shelf: Shelf,
        request: ShelfSaveRequest | None,
    ) -> None:
        if request is not None:
            asyncio.create_task(self.save_checkpoint(shelf, request))

    async def save_checkpoint(self, shelf: Shelf, request: ShelfSaveRequest) -> None:
        if not self.begin_operation("Saving checkpoint..."):
            return
        try:
            version = await self.service.save_checkpoint(
                shelf.name,
                self.selected_entries,
                note=request.note,
            )
        except (ShelfError, OSError, subprocess.CalledProcessError) as exc:
            self.show_error(exc, "Save Checkpoint failed")
        else:
            self.show_success(f"Saved {shelf.name} {version.label}; working copy unchanged.")
            await self.load_shelves(shelf.name)
            current = self.current_shelf()
            if current is not None:
                await self.load_versions(current, version.number)
        finally:
            self.busy = False

    def action_shelve_selected(self) -> None:
        if not self.action_allowed():
            return
        shelf = self.require_shelf_and_entries()
        if shelf is None:
            return
        self.app.push_screen(
            ShelfSaveDialog("Shelve Selected", include_name=False, confirm_label="Continue"),
            lambda request: self.confirm_shelve_request(shelf, request),
        )

    def confirm_shelve_request(
        self,
        shelf: Shelf,
        request: ShelfSaveRequest | None,
    ) -> None:
        if request is None:
            return
        paths = "\n".join(f"- {entry.path.name}" for entry in self.selected_entries[:6])
        self.app.push_screen(
            ConfirmActionDialog(
                "Confirm Shelve Selected",
                f"The patch will be saved first, then these local changes will be reverted:\n\n{paths}",
                confirm_label="Shelve",
            ),
            lambda confirmed: self.handle_shelve_confirmation(shelf, request, confirmed),
        )

    def handle_shelve_confirmation(
        self,
        shelf: Shelf,
        request: ShelfSaveRequest,
        confirmed: bool,
    ) -> None:
        if confirmed:
            asyncio.create_task(self.shelve_selected(shelf, request))

    async def shelve_selected(self, shelf: Shelf, request: ShelfSaveRequest) -> None:
        if not self.begin_operation("Saving and reverting selected paths..."):
            return
        try:
            version, output = await self.service.shelve_selected(
                shelf.name,
                self.selected_entries,
                note=request.note,
            )
        except ShelfOperationError as exc:
            if exc.saved_version is not None:
                await self.load_shelves(exc.saved_version.shelf_name)
            self.show_error(exc, "Shelve partially completed", output=exc.output)
        except (ShelfError, OSError, subprocess.CalledProcessError) as exc:
            self.show_error(exc, "Shelve failed")
        else:
            self.show_success(
                f"Saved {shelf.name} {version.label} and reverted selected paths.",
                output,
            )
            await self.load_shelves(shelf.name)
        finally:
            self.busy = False

    def action_unshelve_version(self) -> None:
        if not self.action_allowed():
            return
        version = self.current_version()
        if version is None:
            self.notify("Select a Shelf version first.", title="Unshelve", severity="warning")
            return
        asyncio.create_task(self.prepare_unshelve(version))

    async def prepare_unshelve(self, version: ShelfVersion) -> None:
        if not self.begin_operation(f"Checking {version.shelf_name} {version.label}..."):
            return
        try:
            conflicts = await self.service.unshelve_conflicts(version)
        except (ShelfError, OSError, subprocess.CalledProcessError) as exc:
            self.show_error(exc, "Unshelve preflight failed")
            self.busy = False
            return
        self.busy = False
        if not conflicts:
            asyncio.create_task(self.unshelve(version, allow_overwrite=False))
            return
        paths = "\n".join(f"- {entry.path.name} ({entry.status_label})" for entry in conflicts[:6])
        self.app.push_screen(
            ConfirmActionDialog(
                "Overwrite Local Changes?",
                "Unshelve will discard current changes on the saved version paths only:\n\n"
                f"{paths}",
                confirm_label="Unshelve",
            ),
            lambda confirmed: self.handle_unshelve_confirmation(version, confirmed),
        )

    def handle_unshelve_confirmation(self, version: ShelfVersion, confirmed: bool) -> None:
        if confirmed:
            asyncio.create_task(self.unshelve(version, allow_overwrite=True))

    async def unshelve(
        self,
        version: ShelfVersion,
        *,
        allow_overwrite: bool,
    ) -> None:
        if not self.begin_operation(f"Restoring {version.shelf_name} {version.label}..."):
            return
        try:
            output = await self.service.unshelve(
                version,
                allow_overwrite=allow_overwrite,
            )
        except ShelfOverwriteRequired as exc:
            self.show_error(exc, "Unshelve needs confirmation")
        except ShelfOperationError as exc:
            self.show_error(exc, "Unshelve failed", output=exc.output)
        except (ShelfError, OSError, subprocess.CalledProcessError) as exc:
            self.show_error(exc, "Unshelve failed")
        else:
            self.show_success(f"Restored {version.shelf_name} {version.label}.", output)
        finally:
            self.busy = False

    def action_export_patch(self) -> None:
        if not self.action_allowed():
            return
        version = self.current_version()
        if version is None:
            self.notify("Select a Shelf version first.", title="Export", severity="warning")
            return
        self.app.push_screen(
            ExportPatchDialog(Path.cwd()),
            lambda destination: self.handle_export_destination(version, destination),
        )

    def handle_export_destination(
        self,
        version: ShelfVersion,
        destination: Path | None,
    ) -> None:
        if destination is not None:
            asyncio.create_task(self.export_patch(version, destination))

    async def export_patch(self, version: ShelfVersion, destination: Path) -> None:
        try:
            exported = await self.service.export_patch(
                version.shelf_name,
                version.number,
                destination,
            )
        except (ShelfError, OSError) as exc:
            self.show_error(exc, "Export failed")
            return
        self.show_success(f"Exported patch to {exported}")

    def action_delete_version(self) -> None:
        if not self.action_allowed():
            return
        version = self.current_version()
        if version is None:
            return
        self.app.push_screen(
            ConfirmActionDialog(
                "Delete Shelf Version?",
                f"Delete {version.shelf_name} {version.label}? The saved patch cannot be restored.",
                confirm_label="Delete Version",
            ),
            lambda confirmed: self.handle_delete_version(version, confirmed),
        )

    def handle_delete_version(self, version: ShelfVersion, confirmed: bool) -> None:
        if confirmed:
            asyncio.create_task(self.delete_version(version))

    async def delete_version(self, version: ShelfVersion) -> None:
        try:
            await self.service.delete_version(version.shelf_name, version.number)
        except (ShelfError, OSError) as exc:
            self.show_error(exc, "Delete version failed")
            return
        self.show_success(f"Deleted {version.shelf_name} {version.label}.")
        await self.load_shelves(version.shelf_name)

    def action_delete_shelf(self) -> None:
        if not self.action_allowed():
            return
        shelf = self.current_shelf()
        if shelf is None:
            return
        self.app.push_screen(
            ConfirmActionDialog(
                "Delete Shelf?",
                f"Delete {shelf.name} and all {shelf.version_count} saved version(s)?",
                confirm_label="Delete Shelf",
            ),
            lambda confirmed: self.handle_delete_shelf(shelf, confirmed),
        )

    def handle_delete_shelf(self, shelf: Shelf, confirmed: bool) -> None:
        if confirmed:
            asyncio.create_task(self.delete_shelf(shelf))

    async def delete_shelf(self, shelf: Shelf) -> None:
        try:
            await self.service.delete_shelf(shelf.name)
        except (ShelfError, OSError) as exc:
            self.show_error(exc, "Delete Shelf failed")
            return
        self.show_success(f"Deleted Shelf {shelf.name}.")
        await self.load_shelves()

    def action_open_folder(self) -> None:
        if not self.action_allowed():
            return
        shelf = self.current_shelf()
        if shelf is not None:
            open_directory(shelf.path)

    def action_copy_path(self) -> None:
        if not self.action_allowed():
            return
        version = self.current_version()
        shelf = self.current_shelf()
        path = version.patch_path if version is not None else shelf.path if shelf is not None else None
        if path is None:
            return
        self.app.copy_to_clipboard(str(path))
        self.notify(str(path), title="Path copied")

    def action_refresh_shelves(self) -> None:
        if not self.action_allowed():
            return
        asyncio.create_task(self.load_shelves(self.current_shelf().name if self.current_shelf() else None))

    def action_allowed(self) -> bool:
        if not self.busy:
            return True
        self.notify(
            "Wait for the current Shelf operation to finish.",
            title="Shelf operation running",
            severity="warning",
        )
        return False

    def require_selected_entries(self) -> bool:
        if self.selected_entries:
            return True
        self.notify(
            "Return to Status, check one or more modified text files, then open Shelves again.",
            title="No selected paths",
            severity="warning",
        )
        return False

    def require_shelf_and_entries(self) -> Shelf | None:
        shelf = self.current_shelf()
        if shelf is None:
            self.notify("Select a Shelf first.", title="Shelf", severity="warning")
            return None
        return shelf if self.require_selected_entries() else None

    def begin_operation(self, message: str) -> bool:
        if self.busy:
            self.notify("A Shelf operation is already running.", title="Shelf", severity="warning")
            return False
        self.busy = True
        self.operation_status.update(Text(message, style="yellow"))
        return True

    def show_success(self, message: str, output: str = "") -> None:
        self.operation_status.update(Text(message, style="green"))
        if output.strip():
            self.detail.update(f"{message}\n\nCommand output:\n{output.strip()}")
        self.notify(message, title="Shelf")

    def show_error(
        self,
        error: BaseException,
        title: str,
        *,
        output: str = "",
    ) -> None:
        details = shelf_error_message(error)
        if output.strip():
            details = f"{details}\n\n{output.strip()}"
        self.operation_status.update(Text(details, style="red"))
        self.detail.update(details)
        self.notify(details.splitlines()[0], title=title, severity="error")

    def focus_targets(self) -> list[ListView]:
        targets = [self.shelf_list]
        if any(isinstance(child, ShelfVersionRow) for child in self.version_list.children):
            targets.append(self.version_list)
        return targets

    def action_focus_next_pane(self) -> None:
        targets = self.focus_targets()
        if len(targets) == 1 or self.version_list.has_focus:
            targets[0].focus()
        else:
            targets[1].focus()

    def action_focus_previous_pane(self) -> None:
        self.action_focus_next_pane()

    def focused_list(self) -> ListView:
        return self.version_list if self.version_list.has_focus else self.shelf_list

    def action_cursor_down(self) -> None:
        self.focused_list().action_cursor_down()

    def action_cursor_up(self) -> None:
        self.focused_list().action_cursor_up()

    def action_page_down(self) -> None:
        self.focused_list().action_page_down()

    def action_page_up(self) -> None:
        self.focused_list().action_page_up()

    def action_preview_scroll_down(self) -> None:
        self.patch_preview.scroll_relative(y=1, animate=False, immediate=True)

    def action_preview_scroll_up(self) -> None:
        self.patch_preview.scroll_relative(y=-1, animate=False, immediate=True)

    def action_close(self) -> None:
        if not self.action_allowed():
            return
        self.app.pop_screen()

    def action_quit_guarded(self) -> None:
        if not self.action_allowed():
            return
        self.app.exit()


def shelf_error_message(error: BaseException) -> str:
    if isinstance(error, ShelfSelectionError) and error.unsupported_paths:
        paths = "\n".join(f"- {path}" for path in error.unsupported_paths[:8])
        return f"{error}\n{paths}"
    if isinstance(error, subprocess.CalledProcessError):
        return (error.stderr or error.output or str(error)).strip()
    return str(error)


def display_timestamp(value: str) -> str:
    return value.replace("T", " ")[:16]
