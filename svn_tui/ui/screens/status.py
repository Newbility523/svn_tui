from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, ListItem, ListView, Static

from svn_tui.config import (
    DEFAULT_THEME,
    PATH_SCROLL_SECONDS,
    PATH_SCROLL_SEPARATOR,
    PREVIEW_DEBOUNCE_SECONDS,
    PREVIEW_ENABLED,
    STATUS_ACTION_MENU_WIDTH,
)
from svn_tui.models import SvnStatusEntry
from svn_tui.services.preview import (
    PreviewCancelToken,
    PreviewCancelled,
    PreviewDocument,
    PreviewMessage,
    build_preview_document,
    continue_preview_document_index,
)
from svn_tui.services.svn import (
    SvnClient,
    build_svn_cleanup_args,
    build_svn_commit_args,
)
from svn_tui.ui.dialogs import (
    CommitMessageDialog,
    ConfirmActionDialog,
    HelpDialog,
    SvnCommandDialog,
    SvnCommandResult,
)
from svn_tui.ui.formatters import (
    commit_success_message,
    display_width,
    file_type_style,
    format_search_label,
    format_status_header,
    status_style,
)
from svn_tui.ui.navigation import NavigationBar
from svn_tui.ui.screens.log import LogScreen
from svn_tui.ui.screens.shelves import ShelfManagerScreen
from svn_tui.ui.search import find_list_match, list_match_position, status_row_search_text
from svn_tui.ui.status_actions import (
    DIRECTORY_STATUS_ACTIONS,
    StatusAction,
    batch_status_actions_for_entries,
    is_addable_entry,
    single_status_actions_for_entry,
    status_action_for_key,
)
from svn_tui.ui.widgets import OverlayMenuItem, PreviewView, StatusRow, TextPreviewView
from svn_tui.utils.paths import relative_path

STATUS_FILTERS = ("all", "checked", "conflicts", "unversioned")
STATUS_FILTER_LABELS = {
    "all": "All",
    "checked": "Checked",
    "conflicts": "Conflicts",
    "unversioned": "Unversioned",
}


class StatusScreen(Screen[None]):
    BINDINGS = [
        Binding("r", "refresh_status", "Refresh"),
        Binding("f", "cycle_status_filter", "Filter"),
        Binding("z", "open_status_action_menu", "Actions"),
        Binding("Z", "open_checked_action_menu", "Checked actions"),
        Binding("space", "toggle_entry", "Stage"),
        Binding("v", "visual_select", "Visual"),
        Binding("escape", "exit_visual_select", "Exit visual", show=False),
        Binding("c", "commit_entries", "Commit", show=False),
        Binding("l", "show_log_screen", "Logs"),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("enter", "activate_or_diff_entry", "Diff"),
        Binding("d", "diff_entry", "Diff"),
        Binding("h", "diff_head_entry", "Diff Head", show=False),
        Binding("b", "blame_entry", "Blame"),
        Binding("a", "add_entry", "Add", show=False),
        Binding("i", "ignore_entry", "Ignore", show=False),
        Binding("s", "resolve_entry", "Resolve", show=False),
        Binding("u", "update_entry", "Update", show=False),
        Binding("U", "update_directory_entry", "Update directory", show=False),
        Binding("y", "copy_entry", "Copy", show=False),
        Binding("Y", "copy_entry", "Copy", show=False),
        Binding("R", "revert_directory_entry", "Revert directory", show=False),
        Binding("C", "cleanup_directory_entry", "Clean up directory", show=False),
        Binding(
            "X",
            "remove_unversioned_directory_entry",
            "Remove unversioned",
            show=False,
        ),
        Binding("S", "open_shelves", "Open Shelves", show=False),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("n", "search_next", "Next", show=False),
        Binding("N", "search_previous", "Previous", show=False),
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
        Binding("g", "vim_g", "Top", show=False),
        Binding("G", "list_bottom", "Bottom", show=False),
    ]

    def __init__(self, target: Path) -> None:
        super().__init__()
        self.client = SvnClient(target)
        self.entries: list[SvnStatusEntry] = []
        self.navigation_bar = NavigationBar()
        self.status_header = Static(format_status_header(), id="status-header")
        self.list_view = ListView(id="status-list")
        self.status_action_popup = Vertical(id="status-action-popup")
        self.status_action_title = Static(id="status-action-title")
        self.status_action_menu = ListView(id="status-action-menu")
        self.search_label = Static(id="status-search-label")
        self.search_input = Input(id="status-search", compact=True)
        self.detail = Static(id="details")
        self.output_title = Static("Output", id="operation-output-title")
        self.operation_output = TextPreviewView(id="operation-output")
        self.preview_title = Static("Preview", id="preview-title")
        self.preview = PreviewView(id="preview")
        self.diff_preview = TextPreviewView(id="diff-preview")
        self.status_theme = DEFAULT_THEME
        self.preview_task: asyncio.Task[None] | None = None
        self.preview_debounce_task: asyncio.Task[None] | None = None
        self.preview_index_task: asyncio.Task[None] | None = None
        self.preview_lock = asyncio.Lock()
        self.preview_cancel_token: PreviewCancelToken | None = None
        self.preview_request_id = 0
        self.preview_document: PreviewDocument | None = None
        self.status_request_id = 0
        self.path_scroll_offset = 0
        self.visual_anchor_index: int | None = None
        self.waiting_for_second_g = False
        self.search_query = ""
        self.search_match: tuple[int, int] | None = None
        self.status_action_rows: list[StatusRow] = []
        self.status_action_actions: list[StatusAction] = []
        self.selected_entry_paths: set[Path] = set()
        self.status_filter = "all"

    def compose(self) -> ComposeResult:
        yield self.navigation_bar
        with Horizontal(id="content"):
            with Vertical(id="main"):
                yield self.status_header
                yield self.list_view
                yield self.search_label
                yield self.search_input
                yield self.detail
                yield self.output_title
                yield self.operation_output
            with Vertical(id="side"):
                yield self.preview_title
                yield self.preview
                yield self.diff_preview
        with self.status_action_popup:
            yield self.status_action_title
            yield self.status_action_menu
        yield Footer()

    async def on_mount(self) -> None:
        self.app.title = "svn-tui"
        self.app.sub_title = str(self.client.target)
        self.refresh_navigation_bar()
        self.status_action_popup.display = False
        self.diff_preview.display = False
        self.operation_output.set_message(
            Text("No command output yet.", style="dim")
        )
        self.set_interval(PATH_SCROLL_SECONDS, self.tick_path_scroll)
        self.refresh_search_line()
        await self.load_status()

    def on_screen_resume(self, event: object) -> None:
        del event
        self.refresh_navigation_bar()

    def refresh_navigation_bar(self) -> None:
        self.navigation_bar.refresh_from_screens(self.app.screen_stack)

    @property
    def status_action_menu_open(self) -> bool:
        return bool(self.status_action_popup.display)

    async def action_open_status_action_menu(self) -> None:
        self.waiting_for_second_g = False
        row = self.current_row()
        if row is None:
            return
        await self.open_status_action_menu(
            [row],
            single_status_actions_for_entry(row.entry),
        )

    async def action_open_checked_action_menu(self) -> None:
        self.waiting_for_second_g = False
        rows = self.selected_rows()
        if not rows:
            await self.open_status_action_menu([], DIRECTORY_STATUS_ACTIONS)
            return
        await self.open_status_action_menu(
            rows,
            batch_status_actions_for_entries([row.entry for row in rows]),
        )

    async def open_status_action_menu(
        self,
        rows: list[StatusRow],
        actions: list[StatusAction],
    ) -> None:
        self.status_action_rows = rows
        self.status_action_actions = actions
        self.status_action_title.update(self.status_action_title_for_rows(rows))
        await self.status_action_menu.clear()
        await self.status_action_menu.extend(
            OverlayMenuItem(action.option_id, action.menu_text)
            for action in actions
        )
        self.status_action_popup.styles.width = STATUS_ACTION_MENU_WIDTH
        self.status_action_popup.styles.height = self.status_action_popup_height()
        self.status_action_menu.styles.height = len(actions)
        self.position_status_action_menu(rows[0] if rows else None)
        self.status_action_popup.display = True
        self.status_action_menu.index = 0
        self.status_action_menu.focus()

    def hide_status_action_menu(self) -> None:
        self.status_action_popup.display = False
        self.status_action_rows = []
        self.status_action_actions = []
        self.list_view.focus()

    def status_action_title_for_rows(self, rows: list[StatusRow]) -> str:
        if not rows:
            return "Directory"
        if len(rows) != 1:
            return "Multi"
        return rows[0].entry.path.name or str(rows[0].entry.path)

    def status_action_popup_height(self) -> int:
        return max(4, len(self.status_action_actions) + 3)

    def position_status_action_menu(self, row: StatusRow | None = None) -> None:
        row = row or self.current_row()
        if row is not None and row.size.width:
            row_right = row.region.x + row.size.width
            row_top = row.region.y
        else:
            row_index = self.list_view.index or 0
            visible_y = max(0, row_index - int(self.list_view.scroll_y))
            row_right = self.list_view.region.x + self.list_view.size.width
            row_top = self.list_view.region.y + visible_y

        x = min(self.size.width - STATUS_ACTION_MENU_WIDTH, row_right)
        y = min(self.size.height - self.status_action_popup_height(), row_top)
        self.status_action_popup.styles.offset = (max(0, x), max(0, y))

    def current_status_action_item(self) -> OverlayMenuItem | None:
        highlighted = self.status_action_menu.highlighted_child
        if isinstance(highlighted, OverlayMenuItem):
            return highlighted
        if (
            self.status_action_menu.index is None
            or self.status_action_menu.index >= len(self.status_action_menu.children)
        ):
            return None
        indexed = self.status_action_menu.children[self.status_action_menu.index]
        return indexed if isinstance(indexed, OverlayMenuItem) else None

    def activate_current_status_action(self) -> None:
        item = self.current_status_action_item()
        if item is None:
            return
        self.activate_status_action(item.option_id)

    def activate_status_action_hotkey(self, key: str) -> bool:
        if not self.status_action_menu_open:
            return False
        action = status_action_for_key(key, self.status_action_actions)
        if action is None:
            return False
        self.activate_status_action(action.option_id)
        return True

    def activate_status_action(self, option_id: str) -> None:
        rows = self.status_action_rows
        if option_id == "open_shelves":
            self.hide_status_action_menu()
            self.app.push_screen(
                ShelfManagerScreen(
                    self.client,
                    [row.entry for row in rows],
                ),
                lambda _: asyncio.create_task(self.load_status()),
            )
            return
        if option_id == "update_directory":
            self.hide_status_action_menu()
            asyncio.create_task(
                self.update_paths(
                    [self.status_directory_path()],
                    "Updating this directory...",
                    "svn update failed",
                    "svn update",
                )
            )
            return
        if option_id == "revert_directory":
            self.hide_status_action_menu()
            self.confirm_revert_paths(
                [self.status_directory_path()],
                "Reverting this directory...",
                "svn revert failed",
                "svn revert",
            )
            return
        if option_id == "cleanup_directory":
            self.hide_status_action_menu()
            self.open_cleanup_dialog(remove_unversioned=False)
            return
        if option_id == "remove_unversioned_directory":
            self.hide_status_action_menu()
            self.confirm_remove_unversioned_directory()
            return
        if not rows:
            self.hide_status_action_menu()
            return
        row = rows[0]

        if option_id == "log":
            self.hide_status_action_menu()
            self.app.push_screen(LogScreen(SvnClient(row.entry.path)))
            return
        if option_id == "blame":
            self.hide_status_action_menu()
            with self.app.suspend():
                error = self.client.open_blame(row.entry)
            if error:
                self.notify(error, title="svn blame failed", severity="warning")
            return
        if option_id == "diff_base":
            self.hide_status_action_menu()
            with self.app.suspend():
                self.client.open_diff(row.entry)
            return
        if option_id == "diff_head":
            self.hide_status_action_menu()
            with self.app.suspend():
                self.client.open_diff_head(row.entry)
            return
        if option_id == "copy":
            self.hide_status_action_menu()
            self.app.copy_to_clipboard("\n".join(str(row.entry.path) for row in rows))
            self.notify(f"Copied {len(rows)} path(s).", title="clipboard")
            return
        if option_id == "add":
            self.hide_status_action_menu()
            addable_rows = [row for row in rows if is_addable_entry(row.entry)]
            if addable_rows:
                asyncio.create_task(self.add_rows(addable_rows))
            return
        if option_id == "ignore":
            self.hide_status_action_menu()
            asyncio.create_task(self.ignore_rows(rows))
            return
        if option_id == "resolve":
            self.hide_status_action_menu()
            asyncio.create_task(self.resolve_rows(rows))
            return
        if option_id == "update":
            self.hide_status_action_menu()
            asyncio.create_task(self.update_rows(rows))
            return
        if option_id == "commit":
            self.hide_status_action_menu()
            self.app.push_screen(
                CommitMessageDialog(len(rows)),
                lambda message: self.handle_commit_message(rows, message),
            )
            return
        if option_id == "revert":
            self.hide_status_action_menu()
            self.confirm_revert_rows(rows)
            return

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is self.status_action_menu:
            return
        row = event.item
        if isinstance(row, StatusRow):
            self.path_scroll_offset = 0
            self.refresh_status_rows()
            self.refresh_search_line()
            self.update_detail(row)
            self.schedule_preview(row.entry)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view is self.status_action_menu and isinstance(event.item, OverlayMenuItem):
            self.activate_status_action(event.item.option_id)
            event.stop()

    def on_resize(self, event: object) -> None:
        del event
        self.refresh_status_layout()

    def on_unmount(self) -> None:
        if self.preview_debounce_task is not None:
            self.preview_debounce_task.cancel()
        if self.preview_task is not None:
            self.preview_task.cancel()
        if self.preview_index_task is not None:
            self.preview_index_task.cancel()
        if self.preview_cancel_token is not None:
            self.preview_cancel_token.cancel()

    async def action_refresh_status(self) -> None:
        if self.status_action_menu_open:
            self.activate_status_action_hotkey("r")
            return
        await self.load_status()

    async def action_toggle_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            return
        if self.visual_anchor_index is not None:
            rows = self.visual_rows()
            if not rows:
                return
            for row in rows:
                row.toggle_selected()
                self.remember_row_selection(row)
            if self.status_filter == "checked":
                await self.render_status_entries()
                return
            self.refresh_status_rows()
            self.update_detail(self.current_row())
            return

        row = self.current_row()
        if row is None:
            return
        row.toggle_selected()
        self.remember_row_selection(row)
        if self.status_filter == "checked":
            await self.render_status_entries()
            return
        self.refresh_status_rows()
        self.update_detail(row)

    def remember_row_selection(self, row: StatusRow) -> None:
        if row.selected_for_commit:
            self.selected_entry_paths.add(row.entry.path)
            return
        self.selected_entry_paths.discard(row.entry.path)

    def action_visual_select(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            return
        index = self.current_index()
        if index is None:
            return
        self.visual_anchor_index = index
        self.refresh_status_rows()
        self.update_detail(self.current_row())

    def action_exit_visual_select(self) -> None:
        if self.status_action_menu_open:
            self.hide_status_action_menu()
            return
        if self.visual_anchor_index is None:
            return
        self.visual_anchor_index = None
        self.refresh_status_rows()
        self.update_detail(self.current_row())

    def action_commit_entries(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("c"):
            return

    def handle_commit_message(
        self,
        rows: list[StatusRow],
        message: str | None,
    ) -> None:
        if message is None:
            return
        if not message.strip():
            self.notify(
                "Commit message cannot be empty.",
                title="commit cancelled",
                severity="warning",
            )
            return

        self.open_commit_command_dialog(rows, message.strip())

    def action_show_help(self) -> None:
        self.waiting_for_second_g = False
        self.app.push_screen(HelpDialog())

    def action_search(self) -> None:
        if self.status_action_menu_open:
            return
        self.waiting_for_second_g = False
        self.search_label.display = False
        self.search_input.value = self.search_query
        self.search_input.display = True
        self.search_input.focus()
        self.search_input.cursor_position = len(self.search_input.value)

    def action_search_next(self) -> None:
        self.waiting_for_second_g = False
        self.jump_to_search_match(1)

    def action_search_previous(self) -> None:
        self.waiting_for_second_g = False
        self.jump_to_search_match(-1)

    def jump_to_search_match(self, direction: int) -> None:
        if not self.search_query:
            self.notify("Start a search with / first.", title="search", severity="warning")
            return
        index = find_list_match(
            self.list_view,
            self.search_query,
            direction,
            lambda row: status_row_search_text(row, self.client.display_root),
        )
        if index is None:
            self.notify(f"No match: {self.search_query}", title="search", severity="warning")
            self.search_match = None
            self.list_view.focus()
            self.refresh_search_line(force=True)
            return
        self.list_view.index = index
        self.search_match = list_match_position(
            self.list_view,
            self.search_query,
            index,
            lambda row: status_row_search_text(row, self.client.display_root),
        )
        self.list_view.focus()
        self.refresh_search_line(force=True)
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is not self.search_input:
            return
        event.stop()
        self.search_query = event.value.strip()
        if not self.search_query:
            self.search_match = None
            self.list_view.focus()
            self.refresh_search_line(force=True)
            return
        self.jump_to_search_match(1)

    def refresh_search_line(self, force: bool = False) -> None:
        is_active = self.list_view.has_focus or self.search_input.has_focus
        if not is_active:
            self.search_label.display = False
            self.search_input.display = False
            return
        if self.search_input.has_focus and not force:
            self.search_label.display = False
            self.search_input.display = True
            return
        self.search_input.display = False
        self.search_input.value = ""
        self.search_label.display = True
        self.search_label.update(
            format_search_label(
                self.search_query,
                self.search_match,
                self.search_label.size.width,
            )
        )

    def action_show_log_screen(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("L"):
            return
        self.app.push_screen(LogScreen(self.client))

    def action_activate_or_diff_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            self.activate_current_status_action()
            return
        self.open_diff_for_current_row()

    def action_diff_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("D"):
            return
        self.open_diff_for_current_row()

    def open_diff_for_current_row(self) -> None:
        row = self.current_row()
        if row is None:
            return
        with self.app.suspend():
            self.client.open_diff(row.entry)

    def action_diff_head_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("H"):
            return

    def action_blame_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("B"):
            return
        row = self.current_row()
        if row is None:
            return
        with self.app.suspend():
            error = self.client.open_blame(row.entry)
        if error:
            self.notify(error, title="svn blame failed", severity="warning")

    def action_add_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("a"):
            return

    def action_ignore_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("i"):
            return

    def action_resolve_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("s"):
            return

    def action_update_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("u"):
            return

    def action_update_directory_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("U"):
            return

    def action_copy_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("y") or self.activate_status_action_hotkey("Y"):
            return

    def action_revert_directory_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("R"):
            return

    def action_cleanup_directory_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("C"):
            return

    def action_remove_unversioned_directory_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("X"):
            return

    def action_open_shelves(self) -> None:
        self.waiting_for_second_g = False
        if self.activate_status_action_hotkey("S"):
            return

    def action_cursor_down(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            self.status_action_menu.action_cursor_down()
            return
        self.list_view.action_cursor_down()
        self.refresh_search_line()
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

    def action_cursor_up(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            self.status_action_menu.action_cursor_up()
            return
        self.list_view.action_cursor_up()
        self.refresh_search_line()
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

    def action_page_down(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            self.status_action_menu.action_page_down()
            return
        self.list_view.action_page_down()
        self.refresh_search_line()
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

    def action_page_up(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            self.status_action_menu.action_page_up()
            return
        self.list_view.action_page_up()
        self.refresh_search_line()
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

    def action_preview_scroll_down(self) -> None:
        self.active_preview().scroll_relative(y=1, animate=False, immediate=True)

    def action_preview_scroll_up(self) -> None:
        self.active_preview().scroll_relative(y=-1, animate=False, immediate=True)

    def action_preview_half_page_down(self) -> None:
        active_preview = self.active_preview()
        active_preview.scroll_relative(
            y=max(1, active_preview.size.height // 2),
            animate=False,
            immediate=True,
        )

    def action_preview_half_page_up(self) -> None:
        active_preview = self.active_preview()
        active_preview.scroll_relative(
            y=-max(1, active_preview.size.height // 2),
            animate=False,
            immediate=True,
        )

    def action_preview_scroll_right(self) -> None:
        self.active_preview().scroll_relative(x=8, animate=False, immediate=True)

    def action_preview_scroll_left(self) -> None:
        self.active_preview().scroll_relative(x=-8, animate=False, immediate=True)

    def action_vim_g(self) -> None:
        if self.status_action_menu_open:
            return
        if self.waiting_for_second_g:
            self.waiting_for_second_g = False
            self.move_to_top()
            return
        self.waiting_for_second_g = True
        self.set_timer(0.8, self.clear_pending_vim_prefix)

    def action_list_bottom(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            return
        if self.list_view.children:
            self.list_view.index = len(self.list_view.children) - 1
            self.refresh_search_line()
            if self.visual_anchor_index is not None:
                self.refresh_status_rows()
                self.update_detail(self.current_row())

    def clear_pending_vim_prefix(self) -> None:
        self.waiting_for_second_g = False

    def move_to_top(self) -> None:
        if self.list_view.children:
            self.list_view.index = 0
            self.refresh_search_line()
            if self.visual_anchor_index is not None:
                self.refresh_status_rows()
                self.update_detail(self.current_row())

    def current_row(self) -> StatusRow | None:
        highlighted = self.list_view.highlighted_child
        if isinstance(highlighted, StatusRow):
            return highlighted
        if (
            self.list_view.index is not None
            and self.list_view.index < len(self.list_view.children)
        ):
            indexed = self.list_view.children[self.list_view.index]
            if isinstance(indexed, StatusRow):
                return indexed
        return None

    def current_index(self) -> int | None:
        if self.list_view.index is None:
            return None
        if self.list_view.index >= len(self.list_view.children):
            return None
        if isinstance(self.list_view.children[self.list_view.index], StatusRow):
            return self.list_view.index
        return None

    def visual_range(self) -> tuple[int, int] | None:
        if self.visual_anchor_index is None:
            return None
        current_index = self.current_index()
        if current_index is None:
            return None
        start = min(self.visual_anchor_index, current_index)
        end = max(self.visual_anchor_index, current_index)
        return start, end

    def visual_rows(self) -> list[StatusRow]:
        visual_range = self.visual_range()
        if visual_range is None:
            return []
        start, end = visual_range
        return [
            row
            for row in self.list_view.children[start : end + 1]
            if isinstance(row, StatusRow)
        ]

    def selected_rows(self) -> list[StatusRow]:
        return [
            row
            for row in self.list_view.children
            if isinstance(row, StatusRow) and row.selected_for_commit
        ]

    def open_commit_command_dialog(self, rows: list[StatusRow], message: str) -> None:
        paths = [row.entry.path for row in rows]
        self.app.push_screen(
            SvnCommandDialog(
                build_svn_commit_args(message, paths),
                title="SVN Commit",
            ),
            lambda result: self.handle_svn_command_result(
                result,
                success_title="commit finished",
                failure_title="svn commit failed",
                success_fallback=commit_success_message("", len(paths)),
            ),
        )

    async def add_rows(self, rows: list[StatusRow]) -> None:
        paths = [row.entry.path for row in rows]
        await self.add_paths(
            paths,
            f"Adding {len(paths)} path(s)...",
            "svn add failed",
            "svn add",
        )

    async def add_paths(
        self,
        paths: list[Path],
        detail_text: str,
        failure_title: str,
        success_title: str,
    ) -> None:
        self.detail.update(Text(detail_text, style="dim"))
        try:
            output = await self.client.add_paths(paths)
        except FileNotFoundError as exc:
            message_text = f"command not found: {exc.filename}"
            self.set_operation_output(message_text, "Command failed.")
            self.notify(message_text, title="command failed", severity="error")
            self.update_detail(self.current_row())
            return
        except subprocess.CalledProcessError as exc:
            message_text = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.set_operation_output(command_error_output(exc), message_text)
            self.notify(message_text, title=failure_title, severity="error")
            self.update_detail(self.current_row())
            return
        except asyncio.CancelledError:
            return

        lines = [line.strip() for line in output.splitlines() if line.strip()]
        fallback = lines[-1] if lines else "Add finished."
        self.set_operation_output(output, fallback)
        self.notify(fallback, title=success_title)
        await self.load_status()

    async def ignore_rows(self, rows: list[StatusRow]) -> None:
        paths = [row.entry.path for row in rows]
        await self.ignore_paths(
            paths,
            f"Ignoring {len(paths)} path(s)...",
            "svn ignore failed",
            "svn ignore",
        )

    async def ignore_paths(
        self,
        paths: list[Path],
        detail_text: str,
        failure_title: str,
        success_title: str,
    ) -> None:
        self.detail.update(Text(detail_text, style="dim"))
        try:
            output = await self.client.ignore_paths(paths)
        except FileNotFoundError as exc:
            message_text = f"command not found: {exc.filename}"
            self.set_operation_output(message_text, "Command failed.")
            self.notify(message_text, title="command failed", severity="error")
            self.update_detail(self.current_row())
            return
        except subprocess.CalledProcessError as exc:
            message_text = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.set_operation_output(command_error_output(exc), message_text)
            self.notify(message_text, title=failure_title, severity="error")
            self.update_detail(self.current_row())
            return
        except asyncio.CancelledError:
            return

        lines = [line.strip() for line in output.splitlines() if line.strip()]
        fallback = lines[-1] if lines else "Ignore finished."
        self.set_operation_output(output, fallback)
        self.notify(fallback, title=success_title)
        await self.load_status()

    async def resolve_rows(self, rows: list[StatusRow]) -> None:
        paths = [row.entry.path for row in rows]
        await self.resolve_paths(
            paths,
            f"Resolving {len(paths)} path(s) with working copy...",
            "svn resolve failed",
            "svn resolve",
        )

    async def resolve_paths(
        self,
        paths: list[Path],
        detail_text: str,
        failure_title: str,
        success_title: str,
    ) -> None:
        self.detail.update(Text(detail_text, style="dim"))
        try:
            output = await self.client.resolve_paths(paths)
        except FileNotFoundError as exc:
            message_text = f"command not found: {exc.filename}"
            self.set_operation_output(message_text, "Command failed.")
            self.notify(message_text, title="command failed", severity="error")
            self.update_detail(self.current_row())
            return
        except subprocess.CalledProcessError as exc:
            message_text = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.set_operation_output(command_error_output(exc), message_text)
            self.notify(message_text, title=failure_title, severity="error")
            self.update_detail(self.current_row())
            return
        except asyncio.CancelledError:
            return

        lines = [line.strip() for line in output.splitlines() if line.strip()]
        fallback = lines[-1] if lines else "Resolve finished."
        self.set_operation_output(output, fallback)
        self.notify(fallback, title=success_title)
        await self.load_status()

    async def update_rows(self, rows: list[StatusRow]) -> None:
        paths = [row.entry.path for row in rows]
        await self.update_paths(
            paths,
            f"Updating {len(paths)} path(s)...",
            "svn update failed",
            "svn update",
        )

    async def update_paths(
        self,
        paths: list[Path],
        detail_text: str,
        failure_title: str,
        success_title: str,
    ) -> None:
        self.detail.update(Text(detail_text, style="dim"))
        try:
            output = await self.client.update_paths(paths)
        except FileNotFoundError as exc:
            message_text = f"command not found: {exc.filename}"
            self.set_operation_output(message_text, "Command failed.")
            self.notify(message_text, title="command failed", severity="error")
            self.update_detail(self.current_row())
            return
        except subprocess.CalledProcessError as exc:
            message_text = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.set_operation_output(command_error_output(exc), message_text)
            self.notify(message_text, title=failure_title, severity="error")
            self.update_detail(self.current_row())
            return
        except asyncio.CancelledError:
            return

        lines = [line.strip() for line in output.splitlines() if line.strip()]
        fallback = lines[-1] if lines else "Update finished."
        self.set_operation_output(output, fallback)
        self.notify(fallback, title=success_title)
        await self.load_status()

    async def revert_rows(self, rows: list[StatusRow]) -> None:
        paths = [row.entry.path for row in rows]
        await self.revert_paths(
            paths,
            f"Reverting {len(paths)} path(s)...",
            "svn revert failed",
            "svn revert",
        )

    async def revert_paths(
        self,
        paths: list[Path],
        detail_text: str,
        failure_title: str,
        success_title: str,
    ) -> None:
        self.detail.update(Text(detail_text, style="dim"))
        try:
            output = await self.client.revert_paths(paths)
        except FileNotFoundError as exc:
            message_text = f"command not found: {exc.filename}"
            self.set_operation_output(message_text, "Command failed.")
            self.notify(message_text, title="command failed", severity="error")
            self.update_detail(self.current_row())
            return
        except subprocess.CalledProcessError as exc:
            message_text = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.set_operation_output(command_error_output(exc), message_text)
            self.notify(message_text, title=failure_title, severity="error")
            self.update_detail(self.current_row())
            return
        except asyncio.CancelledError:
            return

        lines = [line.strip() for line in output.splitlines() if line.strip()]
        fallback = lines[-1] if lines else "Revert finished."
        self.set_operation_output(output, fallback)
        self.notify(fallback, title=success_title)
        await self.load_status()

    def confirm_revert_rows(self, rows: list[StatusRow]) -> None:
        paths = [row.entry.path for row in rows]
        self.confirm_revert_paths(
            paths,
            f"Reverting {len(paths)} path(s)...",
            "svn revert failed",
            "svn revert",
        )

    def confirm_revert_paths(
        self,
        paths: list[Path],
        detail_text: str,
        failure_title: str,
        success_title: str,
    ) -> None:
        if not paths:
            return
        self.app.push_screen(
            ConfirmActionDialog(
                "Confirm SVN Revert",
                self.revert_confirmation_message(paths),
                confirm_label="Revert",
            ),
            lambda confirmed: self.handle_revert_confirmation(
                confirmed,
                paths,
                detail_text,
                failure_title,
                success_title,
            ),
        )

    def handle_revert_confirmation(
        self,
        confirmed: bool,
        paths: list[Path],
        detail_text: str,
        failure_title: str,
        success_title: str,
    ) -> None:
        if not confirmed:
            self.list_view.focus()
            return
        asyncio.create_task(
            self.revert_paths(paths, detail_text, failure_title, success_title)
        )

    def confirm_remove_unversioned_directory(self) -> None:
        path = self.status_directory_path()
        self.app.push_screen(
            ConfirmActionDialog(
                "Confirm Remove Unversioned",
                self.remove_unversioned_confirmation_message(path),
                confirm_label="Remove",
            ),
            lambda confirmed: self.handle_remove_unversioned_confirmation(
                confirmed,
                path,
            ),
        )

    def handle_remove_unversioned_confirmation(
        self,
        confirmed: bool,
        path: Path,
    ) -> None:
        if not confirmed:
            self.list_view.focus()
            return
        self.open_cleanup_dialog(remove_unversioned=True, path=path)

    def remove_unversioned_confirmation_message(self, path: Path) -> str:
        shown_path = relative_path(path, self.client.display_root)
        return "\n".join(
            [
                "This will delete unversioned files under:",
                "",
                str(shown_path),
                "",
                "SVN cannot restore those files.",
            ]
        )

    def open_cleanup_dialog(
        self,
        *,
        remove_unversioned: bool,
        path: Path | None = None,
    ) -> None:
        target = path or self.status_directory_path()
        title = "Remove Unversioned Files" if remove_unversioned else "SVN Cleanup"
        success_fallback = (
            "Remove unversioned finished."
            if remove_unversioned
            else "Cleanup finished."
        )
        self.app.push_screen(
            SvnCommandDialog(
                build_svn_cleanup_args(target, remove_unversioned=remove_unversioned),
                title=title,
            ),
            lambda result: self.handle_svn_command_result(
                result,
                success_title="svn cleanup",
                failure_title="svn cleanup failed",
                success_fallback=success_fallback,
            ),
        )

    def handle_svn_command_result(
        self,
        result: SvnCommandResult | None,
        *,
        success_title: str,
        failure_title: str,
        success_fallback: str,
    ) -> None:
        self.list_view.focus()
        if result is None:
            return
        message = self.svn_command_result_summary(result, success_fallback)
        self.set_operation_output(result.output, message)
        if result.cancelled:
            self.notify(message, title="command cancelled", severity="warning")
            return
        if result.succeeded:
            self.notify(message, title=success_title)
            asyncio.create_task(self.load_status())
            return
        self.notify(message, title=failure_title, severity="error")

    @staticmethod
    def svn_command_result_summary(
        result: SvnCommandResult,
        success_fallback: str,
    ) -> str:
        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        if result.cancelled:
            return "Command cancelled."
        if result.succeeded:
            return lines[-1] if lines else success_fallback
        if lines:
            return lines[-1]
        if result.return_code is None:
            return "Command failed."
        return f"Exited with code {result.return_code}."

    def revert_confirmation_message(self, paths: list[Path]) -> str:
        shown_paths = [
            str(relative_path(path, self.client.display_root))
            for path in paths
        ]
        preview_paths = shown_paths[:3]
        lines = [f"This will discard local changes for {len(paths)} path(s).", ""]
        lines.extend(f"- {path}" for path in preview_paths)
        remaining = len(shown_paths) - len(preview_paths)
        if remaining > 0:
            lines.append(f"... and {remaining} more")
        return "\n".join(lines)

    def status_directory_path(self) -> Path:
        return self.client.target if self.client.target.is_dir() else self.client.target.parent

    async def load_status(self) -> None:
        self.status_request_id += 1
        request_id = self.status_request_id
        self.detail.update(Text("Loading svn status...", style="dim"))
        try:
            entries = await self.client.status()
        except FileNotFoundError as exc:
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            return
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() if exc.stderr else str(exc)
            self.notify(message, title="svn failed", severity="error")
            return
        except asyncio.CancelledError:
            return

        if request_id != self.status_request_id:
            return

        self.entries = entries
        self.visual_anchor_index = None
        entry_paths = {entry.path for entry in entries}
        self.selected_entry_paths &= entry_paths

        await self.render_status_entries()

    async def render_status_entries(self) -> None:
        await self.list_view.clear()
        if not self.entries:
            await self.list_view.append(ListItem(Label("Working copy is clean")))
            self.refresh_status_layout()
            self.detail.update(self.format_detail())
            self.preview_document = None
            self.show_file_preview("Preview")
            self.preview.set_message(Text("No changed file selected.", style="dim"))
            return

        visible_entries = self.filtered_entries()
        if not visible_entries:
            await self.list_view.append(
                ListItem(Label(f"No entries for filter: {self.status_filter_label()}"))
            )
            self.refresh_status_layout()
            self.detail.update(self.format_detail())
            self.preview_document = None
            self.show_file_preview("Preview")
            self.preview.set_message(Text("No changed file selected.", style="dim"))
            return

        rows = [
            StatusRow(entry, self.client.display_root, self.status_theme)
            for entry in visible_entries
        ]
        for row in rows:
            row.selected_for_commit = row.entry.path in self.selected_entry_paths
        await self.list_view.extend(rows)
        self.list_view.index = 0
        self.list_view.focus()
        self.refresh_status_layout()
        row = self.current_row()
        if row is not None:
            self.update_detail(row)
            self.schedule_preview(row.entry)

    def filtered_entries(self) -> list[SvnStatusEntry]:
        if self.status_filter == "checked":
            return [
                entry
                for entry in self.entries
                if entry.path in self.selected_entry_paths
            ]
        if self.status_filter == "conflicts":
            return [
                entry
                for entry in self.entries
                if entry.text_status == "C" or entry.prop_status == "C"
            ]
        if self.status_filter == "unversioned":
            return [entry for entry in self.entries if entry.text_status == "?"]
        return list(self.entries)

    def status_filter_label(self) -> str:
        return STATUS_FILTER_LABELS.get(self.status_filter, self.status_filter)

    async def action_cycle_status_filter(self) -> None:
        self.waiting_for_second_g = False
        if self.status_action_menu_open:
            return
        current_index = STATUS_FILTERS.index(self.status_filter)
        self.status_filter = STATUS_FILTERS[(current_index + 1) % len(STATUS_FILTERS)]
        self.visual_anchor_index = None
        self.search_match = None
        await self.render_status_entries()
        self.notify(f"Filter: {self.status_filter_label()}", title="status filter")

    def status_row_width(self) -> int:
        return max(self.list_view.size.width, self.status_header.size.width, 80)

    def refresh_status_layout(self) -> None:
        row_width = self.status_row_width()
        self.status_header.update(format_status_header(row_width))
        self.refresh_status_rows(row_width)

    def refresh_status_rows(self, row_width: int | None = None) -> None:
        width = row_width if row_width is not None else self.status_row_width()
        current = self.current_row()
        visual_range = self.visual_range()
        for child_index, child in enumerate(self.list_view.children):
            if isinstance(child, StatusRow):
                is_highlighted = child is current
                is_in_visual_range = False
                if visual_range is not None:
                    is_in_visual_range = visual_range[0] <= child_index <= visual_range[1]
                child.refresh_label(
                    width,
                    is_highlighted,
                    is_in_visual_range,
                    self.path_scroll_offset if is_highlighted else 0,
                )

    def tick_path_scroll(self) -> None:
        row = self.current_row()
        if row is None:
            return
        row_width = self.status_row_width()
        if not row.path_needs_scroll(row_width):
            if self.path_scroll_offset != 0:
                self.path_scroll_offset = 0
                row.refresh_label(
                    row_width,
                    True,
                    row.is_in_visual_range,
                    self.path_scroll_offset,
                )
            return
        path_text = str(relative_path(row.entry.path, row.root))
        cycle_width = display_width(path_text + PATH_SCROLL_SEPARATOR)
        self.path_scroll_offset = (self.path_scroll_offset + 1) % cycle_width
        row.refresh_label(
            row_width,
            True,
            row.is_in_visual_range,
            self.path_scroll_offset,
        )

    def schedule_preview(self, entry: SvnStatusEntry) -> None:
        if not PREVIEW_ENABLED:
            self.show_file_preview("Preview")
            self.preview.set_message(Text("Preview disabled.", style="dim"))
            return
        self.preview_request_id += 1
        request_id = self.preview_request_id
        if self.preview_debounce_task is not None:
            self.preview_debounce_task.cancel()
        if self.preview_task is not None:
            self.preview_task.cancel()
        if self.preview_index_task is not None:
            self.preview_index_task.cancel()
        if self.preview_cancel_token is not None:
            self.preview_cancel_token.cancel()
        self.preview_document = None
        if self.should_show_inline_diff(entry):
            self.show_diff_preview("Diff Preview")
            self.diff_preview.set_message(Text("Loading diff...", style="dim"))
        else:
            self.show_file_preview("File Preview")
            self.preview.set_message(Text("Loading preview...", style="dim"))
        self.preview_debounce_task = asyncio.create_task(
            self.start_preview_after_delay(entry, request_id)
        )

    async def start_preview_after_delay(
        self,
        entry: SvnStatusEntry,
        request_id: int,
    ) -> None:
        try:
            await asyncio.sleep(PREVIEW_DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return
        if request_id != self.preview_request_id:
            return
        self.preview_task = asyncio.create_task(
            self.load_preview(entry, request_id)
        )

    async def load_preview(
        self,
        entry: SvnStatusEntry,
        request_id: int,
    ) -> None:
        if self.should_show_inline_diff(entry):
            await self.load_diff_preview(entry, request_id)
            return

        token = PreviewCancelToken()
        try:
            async with self.preview_lock:
                if request_id != self.preview_request_id:
                    return
                self.preview_cancel_token = token
                document = await asyncio.to_thread(
                    build_preview_document,
                    entry,
                    token,
                )
        except asyncio.CancelledError:
            token.cancel()
            return
        if request_id == self.preview_request_id:
            if isinstance(document, PreviewCancelled):
                return
            if isinstance(document, PreviewMessage):
                self.preview_document = None
                self.preview.set_message(Text(document.message, style=document.style))
                return
            self.preview_document = document
            self.preview.set_document(document)
            if document.continue_indexing:
                self.preview_index_task = asyncio.create_task(
                    self.continue_preview_index(document, token, request_id)
                )

    async def load_diff_preview(
        self,
        entry: SvnStatusEntry,
        request_id: int,
    ) -> None:
        try:
            diff_text = await self.client.diff_for_status_entry(entry)
        except FileNotFoundError as exc:
            if request_id != self.preview_request_id:
                return
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            self.diff_preview.set_message(Text("Unable to load svn diff.", style="red"))
            return
        except subprocess.CalledProcessError as exc:
            if request_id != self.preview_request_id:
                return
            message = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.notify(message, title="svn diff failed", severity="error")
            self.diff_preview.set_message(Text(message, style="red"))
            return
        except asyncio.CancelledError:
            return

        if request_id != self.preview_request_id:
            return
        self.preview_document = None
        self.show_diff_preview("Diff Preview")
        if not diff_text.strip():
            self.diff_preview.set_message(
                Text("No textual diff for this path.", style="dim")
            )
            return
        self.diff_preview.set_text(diff_text, lexer="diff", line_numbers=False)

    def should_show_inline_diff(self, entry: SvnStatusEntry) -> bool:
        if entry.text_status in {"?", "I"}:
            return False
        return not entry.path.is_dir()

    def show_file_preview(self, title: str) -> None:
        self.preview_title.update(title)
        self.diff_preview.display = False
        self.preview.display = True

    def show_diff_preview(self, title: str) -> None:
        self.preview_title.update(title)
        self.preview.display = False
        self.diff_preview.display = True

    def active_preview(self) -> PreviewView | TextPreviewView:
        return self.diff_preview if self.diff_preview.display else self.preview

    async def continue_preview_index(
        self,
        document: PreviewDocument,
        token: PreviewCancelToken,
        request_id: int,
    ) -> None:
        try:
            async with self.preview_lock:
                if request_id != self.preview_request_id or token.cancelled:
                    return
                result = await asyncio.to_thread(
                    continue_preview_document_index,
                    document,
                    token,
                )
        except asyncio.CancelledError:
            token.cancel()
            return
        if request_id != self.preview_request_id or token.cancelled:
            return
        if isinstance(result, PreviewCancelled):
            return
        self.preview.set_document(document, reset_scroll=False)

    def update_detail(self, row: StatusRow | None = None) -> None:
        self.detail.update(self.format_detail(row))

    def set_operation_output(self, output: str, fallback: str) -> None:
        if output.strip():
            self.operation_output.set_text(output, lexer="text", line_numbers=False)
            return
        self.operation_output.set_message(Text(fallback, style="dim"))

    def format_detail(self, row: StatusRow | None = None) -> Text:
        visible_count = len(self.filtered_entries()) if self.entries else 0
        detail = Text()
        detail.append(f"Changed: {len(self.entries)}  ")
        detail.append(f"Visible: {visible_count}  ")
        detail.append(f"Commit list: {len(self.selected_entry_paths)}  ")
        detail.append(f"Filter: {self.status_filter_label()}\n")
        if self.visual_anchor_index is not None:
            detail.append(
                f"Visual range: {len(self.visual_rows())}  "
                "Space inverts range, Esc exits\n",
                style="bold cyan",
            )
        detail.append(f"Path root: {self.client.display_root}\n")
        detail.append(f"SVN root: {self.client.root}\n")

        if row is not None:
            shown_path = relative_path(row.entry.path, self.client.display_root)
            detail.append("Status: ")
            detail.append(
                row.entry.status_label,
                style=status_style(row.entry, self.status_theme),
            )
            detail.append("  Path: ")
            detail.append(
                str(shown_path),
                style=file_type_style(row.entry.path, self.status_theme),
            )
            detail.append(f"  Full: {row.entry.path}\n")

        return detail


def command_error_output(exc: subprocess.CalledProcessError) -> str:
    parts = []
    if isinstance(exc.output, str) and exc.output.strip():
        parts.append(exc.output.strip())
    if isinstance(exc.stderr, str) and exc.stderr.strip():
        parts.append(exc.stderr.strip())
    return "\n".join(parts) or str(exc)
