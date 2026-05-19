from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from svn_tui.config import (
    DEFAULT_THEME,
    PATH_SCROLL_SECONDS,
    PATH_SCROLL_SEPARATOR,
    PREVIEW_DEBOUNCE_SECONDS,
    PREVIEW_ENABLED,
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
from svn_tui.services.svn import SvnClient
from svn_tui.ui.dialogs import CommitMessageDialog, HelpDialog
from svn_tui.ui.formatters import (
    commit_success_message,
    display_width,
    file_type_style,
    format_search_label,
    format_status_header,
    status_style,
)
from svn_tui.ui.screens.log import LogScreen
from svn_tui.ui.search import find_list_match, list_match_position, status_row_search_text
from svn_tui.ui.widgets import PreviewView, StatusRow
from svn_tui.utils.paths import relative_path


class StatusScreen(Screen[None]):
    BINDINGS = [
        Binding("r", "refresh_status", "Refresh"),
        Binding("space", "toggle_entry", "Stage"),
        Binding("v", "visual_select", "Visual"),
        Binding("escape", "exit_visual_select", "Exit visual", show=False),
        Binding("c", "commit_entries", "Commit"),
        Binding("l", "show_log_screen", "Logs"),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("enter", "diff_entry", "Diff"),
        Binding("d", "diff_entry", "Diff"),
        Binding("b", "blame_entry", "Blame"),
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
        self.status_header = Static(format_status_header(), id="status-header")
        self.list_view = ListView(id="status-list")
        self.search_label = Static(id="status-search-label")
        self.search_input = Input(id="status-search", compact=True)
        self.detail = Static(id="details")
        self.preview = PreviewView(id="preview")
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="content"):
            with Vertical(id="main"):
                yield self.status_header
                yield self.list_view
                yield self.search_label
                yield self.search_input
                yield self.detail
            with Vertical(id="side"):
                yield Static("Preview", id="preview-title")
                yield self.preview
        yield Footer()

    async def on_mount(self) -> None:
        self.app.title = "svn-tui"
        self.app.sub_title = str(self.client.target)
        self.set_interval(PATH_SCROLL_SECONDS, self.tick_path_scroll)
        self.refresh_search_line()
        await self.load_status()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        row = event.item
        if isinstance(row, StatusRow):
            self.path_scroll_offset = 0
            self.refresh_status_rows()
            self.refresh_search_line()
            self.update_detail(row)
            self.schedule_preview(row.entry)

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
        await self.load_status()

    def action_toggle_entry(self) -> None:
        self.waiting_for_second_g = False
        if self.visual_anchor_index is not None:
            rows = self.visual_rows()
            if not rows:
                return
            for row in rows:
                row.toggle_selected()
            self.refresh_status_rows()
            self.update_detail(self.current_row())
            return

        row = self.current_row()
        if row is None:
            return
        row.toggle_selected()
        self.refresh_status_rows()
        self.update_detail(row)

    def action_visual_select(self) -> None:
        self.waiting_for_second_g = False
        index = self.current_index()
        if index is None:
            return
        self.visual_anchor_index = index
        self.refresh_status_rows()
        self.update_detail(self.current_row())

    def action_exit_visual_select(self) -> None:
        if self.visual_anchor_index is None:
            return
        self.visual_anchor_index = None
        self.refresh_status_rows()
        self.update_detail(self.current_row())

    def action_commit_entries(self) -> None:
        self.waiting_for_second_g = False
        selected = self.selected_rows()
        if not selected:
            self.notify(
                "Select files with Space before committing.",
                title="nothing selected",
                severity="warning",
            )
            return

        self.app.push_screen(
            CommitMessageDialog(len(selected)),
            lambda message: self.handle_commit_message(selected, message),
        )

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

        asyncio.create_task(self.commit_rows(rows, message.strip()))

    def action_show_help(self) -> None:
        self.waiting_for_second_g = False
        self.app.push_screen(HelpDialog())

    def action_search(self) -> None:
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
        self.app.push_screen(LogScreen(self.client))

    def action_diff_entry(self) -> None:
        self.waiting_for_second_g = False
        row = self.current_row()
        if row is None:
            return
        with self.app.suspend():
            self.client.open_diff(row.entry)

    def action_blame_entry(self) -> None:
        self.waiting_for_second_g = False
        row = self.current_row()
        if row is None:
            return
        with self.app.suspend():
            error = self.client.open_blame(row.entry)
        if error:
            self.notify(error, title="svn blame failed", severity="warning")

    def action_cursor_down(self) -> None:
        self.waiting_for_second_g = False
        self.list_view.action_cursor_down()
        self.refresh_search_line()
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

    def action_cursor_up(self) -> None:
        self.waiting_for_second_g = False
        self.list_view.action_cursor_up()
        self.refresh_search_line()
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

    def action_page_down(self) -> None:
        self.waiting_for_second_g = False
        self.list_view.action_page_down()
        self.refresh_search_line()
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

    def action_page_up(self) -> None:
        self.waiting_for_second_g = False
        self.list_view.action_page_up()
        self.refresh_search_line()
        if self.visual_anchor_index is not None:
            self.refresh_status_rows()
            self.update_detail(self.current_row())

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

    def action_vim_g(self) -> None:
        if self.waiting_for_second_g:
            self.waiting_for_second_g = False
            self.move_to_top()
            return
        self.waiting_for_second_g = True
        self.set_timer(0.8, self.clear_pending_vim_prefix)

    def action_list_bottom(self) -> None:
        self.waiting_for_second_g = False
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

    async def commit_rows(self, rows: list[StatusRow], message: str) -> None:
        paths = [row.entry.path for row in rows]
        self.detail.update(Text(f"Committing {len(paths)} file(s)...", style="dim"))
        try:
            output = await self.client.commit(message, paths)
        except FileNotFoundError as exc:
            self.notify(
                f"command not found: {exc.filename}",
                title="command failed",
                severity="error",
            )
            self.update_detail(self.current_row())
            return
        except subprocess.CalledProcessError as exc:
            message_text = exc.stderr.strip() or exc.output.strip() or str(exc)
            self.notify(message_text, title="svn commit failed", severity="error")
            self.update_detail(self.current_row())
            return
        except asyncio.CancelledError:
            return

        commit_message = commit_success_message(output, len(paths))
        self.notify(commit_message, title="commit finished")
        await self.load_status()

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

        await self.list_view.clear()
        if not self.entries:
            await self.list_view.append(ListItem(Label("Working copy is clean")))
            self.refresh_status_layout()
            self.detail.update(self.format_detail())
            self.preview_document = None
            self.preview.set_message(Text("No changed file selected.", style="dim"))
        else:
            await self.list_view.extend(
                StatusRow(entry, self.client.display_root, self.status_theme)
                for entry in self.entries
            )
            self.list_view.index = 0
            self.list_view.focus()
            self.refresh_status_layout()
            row = self.current_row()
            if row is not None:
                self.update_detail(row)
                self.schedule_preview(row.entry)

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
            self.preview.update(Text("Preview disabled.", style="dim"))
            return
        self.preview_request_id += 1
        request_id = self.preview_request_id
        if self.preview_debounce_task is not None:
            self.preview_debounce_task.cancel()
        if self.preview_cancel_token is not None:
            self.preview_cancel_token.cancel()
        self.preview_document = None
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

    def format_detail(self, row: StatusRow | None = None) -> Text:
        selected = self.selected_rows()
        detail = Text()
        detail.append(f"Changed: {len(self.entries)}  ")
        detail.append(f"Commit list: {len(selected)}\n")
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
