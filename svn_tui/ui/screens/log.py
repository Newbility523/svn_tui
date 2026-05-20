from __future__ import annotations

import asyncio
import subprocess

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, ListItem, ListView, Static

from svn_tui.config import (
    LOG_ACTION_MENU_WIDTH,
    LOG_COPY_MENU_WIDTH,
    PATH_SCROLL_SECONDS,
    PATH_SCROLL_SEPARATOR,
)
from svn_tui.models import SvnLogEntry, SvnLogPathEntry
from svn_tui.services.svn import SvnClient
from svn_tui.ui.formatters import (
    display_width,
    format_log_header,
    format_log_path_header,
    format_search_label,
)
from svn_tui.ui.navigation import NavigationBar
from svn_tui.ui.search import find_list_match, list_match_position, log_row_search_text
from svn_tui.ui.widgets import (
    LogEntryRow,
    LogPathRow,
    OverlayMenuItem,
    TextPreviewView,
)
from svn_tui.utils.paths import repo_relative_path


class LogScreen(Screen[None]):
    BINDINGS = [
        Binding("ctrl+l", "close", "Back"),
        Binding("tab", "focus_next_pane", "Switch pane"),
        Binding("shift+tab", "focus_previous_pane", "Prev pane", show=False),
        Binding("p", "open_log_action_menu", "Popup"),
        Binding("L", "enter_submenu", "Submenu", show=False),
        Binding("enter", "activate_current", "Select"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("n", "search_next", "Next", show=False),
        Binding("N", "search_previous", "Previous", show=False),
        Binding("escape", "dismiss_overlay", "Close", show=False),
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

    def __init__(self, client: SvnClient) -> None:
        super().__init__()
        self.client = client
        self.navigation_bar = NavigationBar()
        self.log_list_header = Static(id="log-list-header")
        self.log_list = ListView(id="log-list")
        self.log_search_label = Static(id="log-search-label")
        self.log_search = Input(id="log-search", compact=True)
        self.log_message = Static(id="log-message")
        self.file_list_header = Static(id="log-file-list-header")
        self.file_list = ListView(id="log-file-list")
        self.file_search_label = Static(id="log-file-search-label")
        self.file_search = Input(id="log-file-search", compact=True)
        self.action_menu = ListView(
            OverlayMenuItem("revert_to_this", "revert to this"),
            OverlayMenuItem("revert_changes_from", "revert changes from"),
            OverlayMenuItem("copy", "copy", has_submenu=True),
            id="log-action-menu",
        )
        self.copy_menu = ListView(
            OverlayMenuItem("revision", "revision"),
            OverlayMenuItem("author", "author"),
            OverlayMenuItem("message", "message"),
            id="log-copy-menu",
        )
        self.preview = TextPreviewView(id="log-preview")
        self.preview_title = Static("Diff Preview", id="log-preview-title")
        self.logs: list[SvnLogEntry] = []
        self.path_request_id = 0
        self.preview_request_id = 0
        self.file_path_scroll_offset = 0
        self.active_overlay: str | None = None
        self.copy_menu_reopen_locked = False
        self.load_logs_task: asyncio.Task[None] | None = None
        self.diff_task: asyncio.Task[None] | None = None
        self.log_search_query = ""
        self.file_search_query = ""
        self.log_search_match: tuple[int, int] | None = None
        self.file_search_match: tuple[int, int] | None = None
        self.search_list: ListView | None = None

    def compose(self) -> ComposeResult:
        yield self.navigation_bar
        yield Static(
            f"Recent Log  {self.client.display_root}",
            id="log-banner",
        )
        with Horizontal(id="log-body"):
            with Vertical(id="log-left"):
                with Vertical(classes="log-pane", id="log-list-pane"):
                    yield Static("Recent Logs", classes="log-pane-title")
                    yield self.log_list_header
                    yield self.log_list
                    yield self.log_search_label
                    yield self.log_search
                with Vertical(classes="log-pane", id="log-message-pane"):
                    yield Static("Message", classes="log-pane-title")
                    yield self.log_message
                with Vertical(classes="log-pane", id="log-files-pane"):
                    yield Static("Changed Files", classes="log-pane-title")
                    yield self.file_list_header
                    yield self.file_list
                    yield self.file_search_label
                    yield self.file_search
            with Vertical(classes="log-pane", id="log-right"):
                yield self.preview_title
                yield self.preview
        yield self.action_menu
        yield self.copy_menu
        yield Footer()

    def on_mount(self) -> None:
        self.log_list.focus()
        self.refresh_navigation_bar()
        self.refresh_layout()
        self.set_interval(PATH_SCROLL_SECONDS, self.tick_path_scroll)
        self.preview_title.update("Diff Preview")
        self.preview.set_message(Text("Loading recent log...", style="dim"))
        self.log_message.update(Text("Loading log message...", style="dim"))
        self.action_menu.display = False
        self.copy_menu.display = False
        self.log_search.display = False
        self.file_search.display = False
        self.refresh_search_lines()
        self.load_logs_task = asyncio.create_task(self.load_logs())

    def on_screen_resume(self, event: object) -> None:
        del event
        self.refresh_navigation_bar()

    def refresh_navigation_bar(self) -> None:
        self.navigation_bar.refresh_from_screens(self.app.screen_stack)

    def on_resize(self, event: object) -> None:
        del event
        self.refresh_layout()

    async def load_logs(self) -> None:
        self.preview_title.update("Diff Preview")
        self.preview.set_message(Text("Loading recent log...", style="dim"))
        try:
            logs = await self.client.recent_logs()
        except FileNotFoundError as exc:
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            self.preview.set_message(Text("Unable to load svn log.", style="red"))
            self.log_message.update(Text("Unable to load svn log.", style="red"))
            return
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.notify(message, title="svn log failed", severity="error")
            self.preview.set_message(Text(message, style="red"))
            self.log_message.update(Text(message, style="red"))
            return
        except asyncio.CancelledError:
            return

        self.logs = logs
        await self.log_list.clear()
        await self.file_list.clear()
        if not logs:
            await self.log_list.append(ListItem(Label("No recent log entries.")))
            self.preview.set_message(Text("No recent log entries.", style="dim"))
            self.log_message.update(Text("No recent log entries.", style="dim"))
            return

        await self.log_list.extend(LogEntryRow(log_entry) for log_entry in logs)
        self.log_list.index = 0
        self.refresh_layout()
        self.update_log_message(logs[0])
        await self.load_changed_paths(logs[0])

    def on_unmount(self) -> None:
        if self.load_logs_task is not None:
            self.load_logs_task.cancel()
        if self.diff_task is not None:
            self.diff_task.cancel()

    def refresh_layout(self) -> None:
        log_width = max(self.log_list.size.width, 80)
        file_width = self.log_file_row_width()
        self.log_list_header.update(format_log_header(log_width))
        self.file_list_header.update(format_log_path_header(file_width))
        for child in self.log_list.children:
            if isinstance(child, LogEntryRow):
                child.refresh_label(log_width)
        current_path_row = self.current_path_row()
        for child in self.file_list.children:
            if isinstance(child, LogPathRow):
                is_highlighted = child is current_path_row
                child.refresh_label(
                    file_width,
                    is_highlighted,
                    self.file_path_scroll_offset if is_highlighted else 0,
                )

    def update_log_message(self, log_entry: SvnLogEntry) -> None:
        message = log_entry.message.strip() or "(no message)"
        self.log_message.update(Text(message))

    def hide_overlay_menus(self) -> None:
        self.action_menu.display = False
        self.copy_menu.display = False
        self.active_overlay = None
        self.copy_menu_reopen_locked = False

    def action_dismiss_overlay(self) -> None:
        if self.active_overlay is None:
            return
        if self.active_overlay == "copy":
            self.copy_menu.display = False
            self.active_overlay = "action"
            self.copy_menu_reopen_locked = True
            self.action_menu.focus()
            return
        self.hide_overlay_menus()
        self.log_list.focus()

    def action_search(self) -> None:
        if self.active_overlay is not None:
            return
        list_view = self.file_list if self.file_list.has_focus else self.log_list
        search_input = self.search_input_for_list(list_view)
        search_label = self.search_label_for_list(list_view)
        search_label.display = False
        search_input.value = self.search_query_for_list(list_view)
        search_input.display = True
        search_input.focus()
        search_input.cursor_position = len(search_input.value)

    def action_search_next(self) -> None:
        self.jump_to_search_match(self.focused_list(), 1)

    def action_search_previous(self) -> None:
        self.jump_to_search_match(self.focused_list(), -1)

    def jump_to_search_match(self, list_view: ListView, direction: int) -> None:
        search_query = self.search_query_for_list(list_view)
        if not search_query:
            self.notify("Start a search with / first.", title="search", severity="warning")
            return
        index = find_list_match(list_view, search_query, direction, log_row_search_text)
        if index is None:
            self.notify(f"No match: {search_query}", title="search", severity="warning")
            self.set_search_match(list_view, None)
            list_view.focus()
            self.refresh_search_lines(force=True)
            return
        list_view.index = index
        self.set_search_match(list_view, list_match_position(list_view, search_query, index, log_row_search_text))
        list_view.focus()
        self.refresh_search_lines(force=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is not self.log_search and event.input is not self.file_search:
            return
        event.stop()
        query = event.value.strip()
        list_view = self.log_list if event.input is self.log_search else self.file_list
        if event.input is self.log_search:
            self.log_search_query = query
        else:
            self.file_search_query = query
        self.search_list = list_view
        if not query:
            self.set_search_match(list_view, None)
            list_view.focus()
            self.refresh_search_lines(force=True)
            return
        self.jump_to_search_match(list_view, 1)

    def search_input_for_list(self, list_view: ListView) -> Input:
        return self.file_search if list_view is self.file_list else self.log_search

    def search_label_for_list(self, list_view: ListView) -> Static:
        return self.file_search_label if list_view is self.file_list else self.log_search_label

    def search_query_for_list(self, list_view: ListView) -> str:
        return self.file_search_query if list_view is self.file_list else self.log_search_query

    def set_search_match(
        self,
        list_view: ListView,
        match: tuple[int, int] | None,
    ) -> None:
        if list_view is self.file_list:
            self.file_search_match = match
        else:
            self.log_search_match = match

    def search_match_for_list(self, list_view: ListView) -> tuple[int, int] | None:
        return self.file_search_match if list_view is self.file_list else self.log_search_match

    def refresh_search_lines(self, force: bool = False) -> None:
        self.refresh_search_line(
            self.log_list,
            self.log_search_label,
            self.log_search,
            force,
        )
        self.refresh_search_line(
            self.file_list,
            self.file_search_label,
            self.file_search,
            force,
        )

    def refresh_search_line(
        self,
        list_view: ListView,
        search_label: Static,
        search_input: Input,
        force: bool = False,
    ) -> None:
        is_active = list_view.has_focus or search_input.has_focus
        if not is_active:
            search_label.display = False
            search_input.display = False
            return
        query = self.search_query_for_list(list_view)
        if search_input.has_focus and not force:
            search_label.display = False
            search_input.display = True
            return
        search_input.display = False
        search_input.value = ""
        search_label.display = True
        search_label.update(format_search_label(
            query,
            self.search_match_for_list(list_view),
            search_label.size.width,
        ))

    def action_open_log_action_menu(self) -> None:
        if not self.log_list.has_focus and self.active_overlay is None:
            return
        if self.current_log_row() is None:
            return
        self.copy_menu.display = False
        self.copy_menu_reopen_locked = False
        self.position_action_menu()
        self.action_menu.display = True
        self.active_overlay = "action"
        self.action_menu.index = 0
        self.action_menu.focus()

    def position_action_menu(self) -> None:
        x, y = self.log_menu_anchor()
        self.action_menu.styles.offset = (x, y)

    def position_copy_menu(self) -> None:
        x, y = self.log_menu_anchor()
        copy_x = min(self.size.width - LOG_COPY_MENU_WIDTH, x + LOG_ACTION_MENU_WIDTH)
        self.copy_menu.styles.offset = (copy_x, y)

    def log_menu_anchor(self) -> tuple[int, int]:
        row = self.current_log_row()
        if row is not None and row.size.width:
            row_right = row.region.x + row.size.width
            row_top = row.region.y
        else:
            row_index = self.log_list.index or 0
            visible_y = max(0, row_index - int(self.log_list.scroll_y))
            row_right = self.log_list.region.x + self.log_list.size.width
            row_top = self.log_list.region.y + visible_y

        x = min(self.size.width - LOG_ACTION_MENU_WIDTH, row_right)
        y = min(self.size.height - 6, row_top)
        return max(0, x), max(0, y)

    def current_overlay_item(self) -> OverlayMenuItem | None:
        menu = self.copy_menu if self.active_overlay == "copy" else self.action_menu
        highlighted = menu.highlighted_child
        if isinstance(highlighted, OverlayMenuItem):
            return highlighted
        if menu.index is None or menu.index >= len(menu.children):
            return None
        indexed = menu.children[menu.index]
        return indexed if isinstance(indexed, OverlayMenuItem) else None

    def action_activate_current(self) -> None:
        if self.active_overlay == "action":
            item = self.current_overlay_item()
            if item is None:
                return
            self.activate_action_menu_item(item.option_id)
            return
        if self.active_overlay == "copy":
            item = self.current_overlay_item()
            if item is None:
                return
            self.copy_log_field(item.option_id)
            return

    def action_enter_submenu(self) -> None:
        if self.active_overlay != "action":
            return
        item = self.current_overlay_item()
        if item is None or item.option_id != "copy":
            return
        if self.copy_menu_reopen_locked:
            return
        self.position_copy_menu()
        self.copy_menu.display = True
        self.active_overlay = "copy"
        self.copy_menu.index = 0
        self.copy_menu.focus()

    def activate_action_menu_item(self, option_id: str) -> None:
        if option_id == "copy":
            return
        if option_id == "revert_to_this":
            self.notify("revert to this: not implemented yet", title="log action")
        elif option_id == "revert_changes_from":
            self.notify("revert changes from: not implemented yet", title="log action")
        self.hide_overlay_menus()
        self.log_list.focus()

    def copy_log_field(self, option_id: str) -> None:
        row = self.current_log_row()
        if row is None:
            return
        value_map = {
            "revision": row.log_entry.revision,
            "author": row.log_entry.author,
            "message": row.log_entry.message.strip() or "(no message)",
        }
        value = value_map.get(option_id)
        if value is None:
            return
        self.app.copy_to_clipboard(value)
        self.notify(f"Copied {option_id}.", title="clipboard")
        self.hide_overlay_menus()
        self.log_list.focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is self.log_list and isinstance(event.item, LogEntryRow):
            if self.active_overlay is not None:
                self.hide_overlay_menus()
            self.refresh_search_lines()
            self.update_log_message(event.item.log_entry)
            asyncio.create_task(self.load_changed_paths(event.item.log_entry))
            return
        if event.list_view is self.file_list and isinstance(event.item, LogPathRow):
            if self.active_overlay is not None:
                self.hide_overlay_menus()
            self.refresh_search_lines()
            self.file_path_scroll_offset = 0
            self.refresh_layout()
            log_row = self.current_log_row()
            if log_row is None:
                return
            self.schedule_diff(log_row.log_entry, event.item.path_entry)
            return
        if event.list_view is self.action_menu and isinstance(event.item, OverlayMenuItem):
            if event.item.option_id != "copy":
                self.copy_menu.display = False
                self.copy_menu_reopen_locked = False
            return

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view is self.action_menu and isinstance(event.item, OverlayMenuItem):
            self.activate_action_menu_item(event.item.option_id)
            event.stop()
            return
        if event.list_view is self.copy_menu and isinstance(event.item, OverlayMenuItem):
            self.copy_log_field(event.item.option_id)
            event.stop()

    async def load_changed_paths(self, log_entry: SvnLogEntry) -> None:
        self.path_request_id += 1
        request_id = self.path_request_id
        await self.file_list.clear()
        if request_id != self.path_request_id:
            return

        if not log_entry.changed_paths:
            await self.file_list.append(ListItem(Label("No changed paths.")))
            self.preview_title.update(f"Diff Preview r{log_entry.revision}")
            self.preview.set_message(Text(log_entry.message or "(no message)", style="dim"))
            return

        shown_rows = [
            LogPathRow(path_entry, repo_relative_path(path_entry.path, self.client.target_repo_path))
            for path_entry in log_entry.changed_paths
        ]
        await self.file_list.extend(shown_rows)
        if request_id != self.path_request_id:
            return
        self.file_list.index = 0
        self.file_path_scroll_offset = 0
        self.refresh_layout()
        self.schedule_diff(log_entry, log_entry.changed_paths[0])

    def schedule_diff(self, log_entry: SvnLogEntry, path_entry: SvnLogPathEntry) -> None:
        self.preview_request_id += 1
        request_id = self.preview_request_id
        if self.diff_task is not None:
            self.diff_task.cancel()
        shown_path = repo_relative_path(path_entry.path, self.client.target_repo_path)
        self.preview_title.update(f"Diff Preview r{log_entry.revision}  {shown_path}")
        self.preview.set_message(Text("Loading diff...", style="dim"))
        self.diff_task = asyncio.create_task(
            self.load_diff(log_entry, path_entry, request_id)
        )

    async def load_diff(
        self,
        log_entry: SvnLogEntry,
        path_entry: SvnLogPathEntry,
        request_id: int,
    ) -> None:
        try:
            diff_text = await self.client.diff_for_log_path(log_entry.revision, path_entry)
        except FileNotFoundError as exc:
            if request_id != self.preview_request_id:
                return
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            self.preview.set_message(Text("Unable to load svn diff.", style="red"))
            return
        except subprocess.CalledProcessError as exc:
            if request_id != self.preview_request_id:
                return
            message = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.notify(message, title="svn diff failed", severity="error")
            self.preview.set_message(Text(message, style="red"))
            return
        except asyncio.CancelledError:
            return

        if request_id != self.preview_request_id:
            return
        if not diff_text.strip():
            self.preview.set_message(Text("No textual diff for this path.", style="dim"))
            return
        self.preview.set_text(diff_text, lexer="diff", line_numbers=False)

    def current_log_row(self) -> LogEntryRow | None:
        highlighted = self.log_list.highlighted_child
        if isinstance(highlighted, LogEntryRow):
            return highlighted
        if self.log_list.index is None or self.log_list.index >= len(self.log_list.children):
            return None
        indexed = self.log_list.children[self.log_list.index]
        return indexed if isinstance(indexed, LogEntryRow) else None

    def current_path_row(self) -> LogPathRow | None:
        highlighted = self.file_list.highlighted_child
        if isinstance(highlighted, LogPathRow):
            return highlighted
        if self.file_list.index is None or self.file_list.index >= len(self.file_list.children):
            return None
        indexed = self.file_list.children[self.file_list.index]
        return indexed if isinstance(indexed, LogPathRow) else None

    def log_file_row_width(self) -> int:
        return max(self.file_list.size.width, self.file_list_header.size.width, 48)

    def tick_path_scroll(self) -> None:
        row = self.current_path_row()
        if row is None:
            return
        row_width = self.log_file_row_width()
        if not row.path_needs_scroll(row_width):
            if self.file_path_scroll_offset != 0:
                self.file_path_scroll_offset = 0
                self.refresh_layout()
            return
        cycle_width = display_width(row.shown_path + PATH_SCROLL_SEPARATOR)
        self.file_path_scroll_offset = (self.file_path_scroll_offset + 1) % cycle_width
        row.refresh_label(
            row_width,
            True,
            self.file_path_scroll_offset,
        )

    def focus_targets(self) -> list[ListView]:
        if self.file_list.children:
            return [self.log_list, self.file_list]
        return [self.log_list]

    def action_focus_next_pane(self) -> None:
        if self.active_overlay is not None:
            return
        targets = self.focus_targets()
        if len(targets) == 1:
            targets[0].focus()
            self.refresh_search_lines()
            return
        if self.file_list.has_focus:
            self.log_list.focus()
            self.refresh_search_lines()
            return
        self.file_list.focus()
        self.refresh_search_lines()

    def action_focus_previous_pane(self) -> None:
        self.action_focus_next_pane()

    def focused_list(self) -> ListView:
        if self.active_overlay == "copy":
            return self.copy_menu
        if self.active_overlay == "action":
            return self.action_menu
        if self.file_list.has_focus:
            return self.file_list
        return self.log_list

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
