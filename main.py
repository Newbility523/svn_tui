from __future__ import annotations

import argparse
import asyncio
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event, Lock

from rich.segment import Segment
from rich.syntax import Syntax
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.screen import ModalScreen, Screen
from textual.strip import Strip
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static, TextArea


PREVIEW_ENABLED = True
PREVIEW_DEBOUNCE_SECONDS = 0.2
PREVIEW_MAX_COLUMNS = 240
PREVIEW_MAX_LINE_BYTES = 8_192
PREVIEW_RENDER_COLUMNS = PREVIEW_MAX_COLUMNS + 16
PREVIEW_LINE_CACHE_SIZE = 400
PREVIEW_FULL_INDEX_MAX_BYTES = 1 * 1024 * 1024
PREVIEW_BACKGROUND_INDEX_MAX_BYTES = 2 * 1024 * 1024
PREVIEW_INITIAL_INDEX_LINES = 1_200
CHECK_COLUMN_WIDTH = 6
STATUS_COLUMN_WIDTH = 8
EXTENSION_COLUMN_WIDTH = 10
SIZE_COLUMN_WIDTH = 8
PATH_COLUMN_MIN_WIDTH = 8
PATH_SCROLL_SEPARATOR = "   "
PATH_SCROLL_SECONDS = 0.25
LOG_ENTRY_LIMIT = 30
LOG_REVISION_WIDTH = 10
LOG_AUTHOR_WIDTH = 14
LOG_DATE_WIDTH = 16
LOG_ACTION_WIDTH = 4
LOG_KIND_WIDTH = 4
LOG_ACTION_MENU_WIDTH = 24
LOG_COPY_MENU_WIDTH = 18


@dataclass(frozen=True)
class StatusTheme:
    selected_marker: str
    unselected_marker: str
    marker_style: str
    default_status_style: str
    status_styles: dict[str, str]
    default_path_style: str
    file_type_styles: dict[str, str]


DEFAULT_THEME = StatusTheme(
    selected_marker="x",
    unselected_marker=" ",
    marker_style="bold cyan",
    default_status_style="white",
    status_styles={
        "A": "green",
        "C": "bold magenta",
        "D": "red",
        "I": "dim",
        "M": "yellow",
        "R": "blue",
        "X": "cyan",
        "?": "blue",
        "!": "red",
        "~": "orange1",
    },
    default_path_style="white",
    file_type_styles={
        ".c": "cyan",
        ".cc": "cyan",
        ".cpp": "cyan",
        ".css": "bright_blue",
        ".go": "cyan",
        ".h": "cyan",
        ".hpp": "cyan",
        ".html": "bright_blue",
        ".java": "yellow",
        ".js": "yellow",
        ".json": "green",
        ".lua": "blue",
        ".md": "magenta",
        ".py": "green",
        ".rs": "red",
        ".sh": "green",
        ".toml": "green",
        ".ts": "yellow",
        ".tsx": "yellow",
        ".xml": "bright_blue",
        ".yaml": "green",
        ".yml": "green",
    },
)


@dataclass(frozen=True)
class SvnStatusEntry:
    path: Path
    text_status: str
    prop_status: str
    raw_status: str

    @property
    def status_label(self) -> str:
        return self.raw_status.strip() or "?"


@dataclass(frozen=True)
class SvnLogPathEntry:
    action: str
    node_kind: str
    path: str


@dataclass(frozen=True)
class SvnLogEntry:
    revision: str
    author: str
    date: str
    message: str
    changed_paths: list[SvnLogPathEntry]

    @property
    def summary(self) -> str:
        first_line = self.message.splitlines()[0].strip() if self.message.strip() else ""
        return first_line or "(no message)"


@dataclass
class PreviewDocument:
    path: Path
    line_offsets: list[int]
    lexer: str
    file_size: int
    next_offset: int
    indexed_complete: bool
    continue_indexing: bool
    status_message: str | None = None
    line_lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    @property
    def line_count(self) -> int:
        with self.line_lock:
            extra_line = 1 if self.status_message else 0
            return len(self.line_offsets) + extra_line

    def line_offset_at(self, index: int) -> int | None:
        with self.line_lock:
            if index < 0 or index >= len(self.line_offsets):
                return None
            return self.line_offsets[index]

    def apply_index_result(
        self,
        new_offsets: list[int],
        next_offset: int,
        indexed_complete: bool,
        status_message: str | None,
    ) -> None:
        with self.line_lock:
            self.line_offsets.extend(new_offsets)
            self.next_offset = next_offset
            self.indexed_complete = indexed_complete
            self.continue_indexing = False
            self.status_message = status_message


class PreviewCancelToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class PreviewCancelled:
    pass


@dataclass(frozen=True)
class PreviewIndexScan:
    offsets: list[int]
    next_offset: int
    complete: bool
    status_message: str | None = None


async def run_command_text(args: list[str]) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode,
            args,
            output=stdout_text,
            stderr=stderr_text,
        )
    return stdout_text


def build_svn_commit_args(message: str, paths: list[Path]) -> list[str]:
    return ["svn", "commit", "-m", message, "--", *(str(path) for path in paths)]


class SvnClient:
    def __init__(self, target: Path) -> None:
        self.target = target.expanduser().resolve()
        self.display_root = self.target if self.target.is_dir() else self.target.parent
        self.root = self.display_root
        self.root_loaded = False
        self.repo_root_url = ""
        self.target_url = ""
        self.target_repo_path = ""
        self.repo_info_loaded = False

    async def ensure_working_copy_root(self) -> None:
        if self.root_loaded:
            return
        probe = self.target if self.target.is_dir() else self.target.parent
        stdout = await run_command_text(
            ["svn", "info", "--show-item", "wc-root", str(probe)]
        )
        self.root = Path(stdout.strip()).resolve()
        self.root_loaded = True

    async def status(self) -> list[SvnStatusEntry]:
        await self.ensure_working_copy_root()
        stdout = await run_command_text(["svn", "st", str(self.target)])
        entries: list[SvnStatusEntry] = []
        for line in stdout.splitlines():
            entry = parse_svn_status_line(line, self.root)
            if entry is not None:
                entries.append(entry)
        return entries

    async def commit(self, message: str, paths: list[Path]) -> str:
        return await run_command_text(build_svn_commit_args(message, paths))

    async def ensure_repository_metadata(self) -> None:
        if self.repo_info_loaded:
            return
        probe = self.target if self.target.is_dir() else self.target.parent
        repo_root_url = await run_command_text(
            ["svn", "info", "--show-item", "repos-root-url", str(probe)]
        )
        target_url = await run_command_text(["svn", "info", "--show-item", "url", str(probe)])
        self.repo_root_url = repo_root_url.strip().rstrip("/")
        self.target_url = target_url.strip()
        if self.repo_root_url and self.target_url.startswith(self.repo_root_url):
            suffix = self.target_url[len(self.repo_root_url) :].strip("/")
            self.target_repo_path = f"/{suffix}" if suffix else "/"
        else:
            self.target_repo_path = ""
        self.repo_info_loaded = True

    async def recent_logs(self, limit: int = LOG_ENTRY_LIMIT) -> list[SvnLogEntry]:
        await self.ensure_repository_metadata()
        stdout = await run_command_text(
            ["svn", "log", "--xml", "-v", "-l", str(limit), self.target_url]
        )
        return parse_svn_log_xml(stdout)

    async def diff_for_log_path(
        self,
        revision: str,
        path_entry: SvnLogPathEntry,
    ) -> str:
        await self.ensure_repository_metadata()
        url = self.repo_path_to_url(path_entry.path)
        revision_number = int(revision) if revision.isdigit() else None
        candidates: list[str] = []
        if revision_number is not None and path_entry.action == "D" and revision_number > 0:
            candidates.append(f"{url}@{revision_number - 1}")
        if revision_number is not None:
            candidates.append(f"{url}@{revision_number}")
        candidates.append(url)

        error: subprocess.CalledProcessError | None = None
        for candidate in dedupe_strings(candidates):
            try:
                return await run_command_text(["svn", "diff", "-c", revision, candidate])
            except subprocess.CalledProcessError as exc:
                error = exc
        if error is not None:
            raise error
        return ""

    def repo_path_to_url(self, repo_path: str) -> str:
        if repo_path.startswith("/") and self.repo_root_url:
            return f"{self.repo_root_url}{repo_path}"
        return repo_path

    def open_blame(self, entry: SvnStatusEntry) -> str | None:
        if entry.text_status in {"?", "I"}:
            return "Blame is unavailable for unversioned or ignored files."
        if entry.path.is_dir():
            return "Blame is unavailable for directories."
        if not entry.path.exists():
            return "Blame is unavailable because the file does not exist locally."

        blame = subprocess.run(
            ["svn", "blame", "--", str(entry.path)],
            check=False,
            capture_output=True,
        )
        if blame.returncode != 0:
            message = blame.stderr.decode("utf-8", errors="replace").strip()
            return message or "svn blame failed."

        suffix = entry.path.suffix
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f"svn-blame-{entry.path.stem}-",
            suffix=suffix,
            delete=False,
        ) as blame_file:
            blame_path = Path(blame_file.name)
            blame_file.write(blame.stdout)

        try:
            subprocess.run(["nvim", "-R", str(blame_path)])
        finally:
            blame_path.unlink(missing_ok=True)

        return None

    def open_diff(self, entry: SvnStatusEntry) -> None:
        if entry.text_status in {"?", "I"}:
            subprocess.run(["nvim", str(entry.path)])
            return

        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f"svn-base-{entry.path.name}-",
            delete=False,
        ) as base_file:
            base_path = Path(base_file.name)

        try:
            cat = subprocess.run(
                ["svn", "cat", "-r", "BASE", str(entry.path)],
                check=False,
                capture_output=True,
            )
            if cat.returncode != 0:
                subprocess.run(["nvim", str(entry.path)])
                return
            base_path.write_bytes(cat.stdout)
            if entry.text_status == "D":
                subprocess.run(["nvim", str(base_path)])
            else:
                subprocess.run(["nvim", "-d", str(base_path), str(entry.path)])
        finally:
            base_path.unlink(missing_ok=True)

class StatusRow(ListItem):
    def __init__(
        self,
        entry: SvnStatusEntry,
        root: Path,
        theme: StatusTheme = DEFAULT_THEME,
    ) -> None:
        super().__init__()
        self.entry = entry
        self.root = root
        self.theme = theme
        self.selected_for_commit = False
        self.label = Label()
        self.row_width = 0
        self.is_highlighted = False
        self.is_in_visual_range = False
        self.path_scroll_offset = 0

    def compose(self) -> ComposeResult:
        yield self.label

    def on_mount(self) -> None:
        self.refresh_label()

    def toggle_selected(self) -> None:
        self.selected_for_commit = not self.selected_for_commit
        self.refresh_label()

    def refresh_label(
        self,
        row_width: int | None = None,
        is_highlighted: bool | None = None,
        is_in_visual_range: bool | None = None,
        path_scroll_offset: int | None = None,
    ) -> None:
        if row_width is not None:
            self.row_width = row_width
        if is_highlighted is not None:
            self.is_highlighted = is_highlighted
        if is_in_visual_range is not None:
            self.is_in_visual_range = is_in_visual_range
        if path_scroll_offset is not None:
            self.path_scroll_offset = path_scroll_offset
        marker = (
            self.theme.selected_marker
            if self.selected_for_commit
            else self.theme.unselected_marker
        )
        shown_path = relative_path(self.entry.path, self.root)
        self.label.update(
            format_status_row(
                self.entry,
                shown_path,
                marker,
                self.theme,
                self.row_width,
                self.is_highlighted,
                self.is_in_visual_range,
                self.path_scroll_offset,
            )
        )

    def path_needs_scroll(self, row_width: int) -> bool:
        shown_path = relative_path(self.entry.path, self.root)
        return len(str(shown_path)) > path_column_width(row_width)


class PreviewView(ScrollView):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.document: PreviewDocument | None = None
        self.message: Text | None = Text("No changed file selected.", style="dim")
        self.line_cache: OrderedDict[int, Strip] = OrderedDict()

    def set_message(self, message: Text) -> None:
        self.document = None
        self.message = message
        self.line_cache.clear()
        self.virtual_size = Size(1, 1)
        self.scroll_to(x=0, y=0, animate=False, immediate=True)
        self.refresh(layout=True)

    def set_document(self, document: PreviewDocument, reset_scroll: bool = True) -> None:
        self.document = document
        self.message = None
        self.line_cache.clear()
        height = max(1, document.line_count)
        self.virtual_size = Size(PREVIEW_RENDER_COLUMNS, height)
        if reset_scroll:
            self.scroll_to(x=0, y=0, animate=False, immediate=True)
        self.refresh(layout=True)

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if width <= 0:
            return Strip.blank(0, self.visual_style.rich_style)

        if self.document is None:
            if y == 0 and self.message is not None:
                return self.render_text_line(self.message)
            return Strip.blank(width, self.visual_style.rich_style)

        document_y = int(self.scroll_y) + y
        if document_y < 0 or document_y >= self.document.line_count:
            return Strip.blank(width, self.visual_style.rich_style)

        strip = self.line_cache.get(document_y)
        if strip is None:
            strip = self.render_document_line(document_y)
            self.line_cache[document_y] = strip
            if len(self.line_cache) > PREVIEW_LINE_CACHE_SIZE:
                self.line_cache.popitem(last=False)
        else:
            self.line_cache.move_to_end(document_y)
        return strip.crop_pad(
            width,
            int(self.scroll_x),
            int(self.scroll_x) + width,
            self.visual_style.rich_style,
        )

    def render_document_line(self, y: int) -> Strip:
        assert self.document is not None
        offset = self.document.line_offset_at(y)
        if offset is None:
            if self.document.status_message is not None:
                return self.render_text_line(
                    Text(self.document.status_message, style="dim")
                )
            return Strip.blank(self.size.width, self.visual_style.rich_style)
        line = read_preview_line(self.document, y)
        syntax = Syntax(
            line,
            self.document.lexer,
            theme="ansi_dark",
            line_numbers=True,
            start_line=y + 1,
            word_wrap=False,
        )
        return self.render_rich_line(syntax)

    def render_text_line(self, text: Text) -> Strip:
        return self.render_rich_line(text)

    def render_rich_line(self, renderable: object) -> Strip:
        options = self.app.console.options.update_width(PREVIEW_RENDER_COLUMNS)
        lines = self.app.console.render_lines(renderable, options, pad=False)
        segments = lines[0] if lines else []
        normalized = [
            Segment(segment.text, segment.style or Style(), segment.control)
            for segment in segments
        ]
        return Strip(normalized)


class TextPreviewView(ScrollView):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.lines: list[str] | None = None
        self.message: Text | None = Text("No diff selected.", style="dim")
        self.lexer = "diff"
        self.line_numbers = False
        self.line_cache: OrderedDict[int, Strip] = OrderedDict()

    def set_message(self, message: Text) -> None:
        self.lines = None
        self.message = message
        self.line_cache.clear()
        self.virtual_size = Size(1, 1)
        self.scroll_to(x=0, y=0, animate=False, immediate=True)
        self.refresh(layout=True)

    def set_text(
        self,
        content: str,
        *,
        lexer: str = "diff",
        line_numbers: bool = False,
        reset_scroll: bool = True,
    ) -> None:
        self.lines = content.splitlines()
        if content.endswith("\n"):
            self.lines.append("")
        if not self.lines:
            self.lines = [""]
        self.message = None
        self.lexer = lexer
        self.line_numbers = line_numbers
        self.line_cache.clear()
        self.virtual_size = Size(PREVIEW_RENDER_COLUMNS, len(self.lines))
        if reset_scroll:
            self.scroll_to(x=0, y=0, animate=False, immediate=True)
        self.refresh(layout=True)

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if width <= 0:
            return Strip.blank(0, self.visual_style.rich_style)

        if self.lines is None:
            if y == 0 and self.message is not None:
                return self.render_rich_line(self.message)
            return Strip.blank(width, self.visual_style.rich_style)

        document_y = int(self.scroll_y) + y
        if document_y < 0 or document_y >= len(self.lines):
            return Strip.blank(width, self.visual_style.rich_style)

        strip = self.line_cache.get(document_y)
        if strip is None:
            syntax = Syntax(
                self.lines[document_y],
                self.lexer,
                theme="ansi_dark",
                line_numbers=self.line_numbers,
                start_line=document_y + 1,
                word_wrap=False,
            )
            strip = self.render_rich_line(syntax)
            self.line_cache[document_y] = strip
            if len(self.line_cache) > PREVIEW_LINE_CACHE_SIZE:
                self.line_cache.popitem(last=False)
        else:
            self.line_cache.move_to_end(document_y)

        return strip.crop_pad(
            width,
            int(self.scroll_x),
            int(self.scroll_x) + width,
            self.visual_style.rich_style,
        )

    def render_rich_line(self, renderable: object) -> Strip:
        options = self.app.console.options.update_width(PREVIEW_RENDER_COLUMNS)
        lines = self.app.console.render_lines(renderable, options, pad=False)
        segments = lines[0] if lines else []
        normalized = [
            Segment(segment.text, segment.style or Style(), segment.control)
            for segment in segments
        ]
        return Strip(normalized)


class LogEntryRow(ListItem):
    def __init__(self, log_entry: SvnLogEntry) -> None:
        super().__init__()
        self.log_entry = log_entry
        self.label = Label()
        self.row_width = 0

    def compose(self) -> ComposeResult:
        yield self.label

    def on_mount(self) -> None:
        self.refresh_label()

    def refresh_label(self, row_width: int | None = None) -> None:
        if row_width is not None:
            self.row_width = row_width
        self.label.update(format_log_row(self.log_entry, self.row_width))


class LogPathRow(ListItem):
    def __init__(self, path_entry: SvnLogPathEntry, shown_path: str) -> None:
        super().__init__()
        self.path_entry = path_entry
        self.shown_path = shown_path
        self.label = Label()
        self.row_width = 0
        self.is_highlighted = False
        self.path_scroll_offset = 0

    def compose(self) -> ComposeResult:
        yield self.label

    def on_mount(self) -> None:
        self.refresh_label()

    def refresh_label(
        self,
        row_width: int | None = None,
        is_highlighted: bool | None = None,
        path_scroll_offset: int | None = None,
    ) -> None:
        if row_width is not None:
            self.row_width = row_width
        if is_highlighted is not None:
            self.is_highlighted = is_highlighted
        if path_scroll_offset is not None:
            self.path_scroll_offset = path_scroll_offset
        self.label.update(
            format_log_path_row(
                self.path_entry,
                self.shown_path,
                self.row_width,
                self.is_highlighted,
                self.path_scroll_offset,
            )
        )

    def path_needs_scroll(self, row_width: int) -> bool:
        return len(self.shown_path) > log_path_width(row_width)


class OverlayMenuItem(ListItem):
    def __init__(
        self,
        option_id: str,
        label_text: str,
        *,
        has_submenu: bool = False,
    ) -> None:
        super().__init__()
        self.option_id = option_id
        self.label_text = label_text
        self.has_submenu = has_submenu

    def compose(self) -> ComposeResult:
        if self.has_submenu:
            yield Label(f"{self.label_text:<20}>")
            return
        yield Label(self.label_text)


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
        cycle_width = len(row.shown_path) + len(PATH_SCROLL_SEPARATOR)
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


class CommitMessageDialog(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+enter", "submit", "Commit"),
    ]

    def __init__(self, file_count: int) -> None:
        super().__init__()
        self.file_count = file_count

    def compose(self) -> ComposeResult:
        with Vertical(id="commit-dialog"):
            yield Label(f"Commit Message ({self.file_count} files)", id="commit-title")
            yield TextArea(
                "",
                id="commit-message",
                show_line_numbers=False,
                placeholder="Enter commit message",
            )
            with Horizontal(id="commit-actions"):
                yield Button("Esc Cancel", id="commit-cancel")
                yield Button("Ctrl+Enter Commit", variant="success", id="commit-confirm")

    def on_mount(self) -> None:
        self.query_one("#commit-message", TextArea).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        message = self.query_one("#commit-message", TextArea).text.strip()
        self.dismiss(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "commit-cancel":
            self.action_cancel()
            return
        if event.button.id == "commit-confirm":
            self.action_submit()


class HelpDialog(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("Help", id="help-title")
            yield Static(format_help_text(), id="help-content")

    def action_close(self) -> None:
        self.dismiss(None)


class StatusScreen(Screen[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #content {
        height: 1fr;
    }

    #main {
        width: 1fr;
        height: 1fr;
    }

    #status-header {
        height: 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #status-list {
        width: 1fr;
        height: 1fr;
    }

    #details {
        height: 10;
        padding: 1 0 0 0;
        border-top: solid $surface;
    }

    #side {
        width: 1fr;
        padding: 1 2;
        border-left: solid $surface;
    }

    #preview-title {
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
        text-style: bold;
    }

    #preview {
        width: 1fr;
        height: 1fr;
        overflow-y: auto;
        overflow-x: auto;
        scrollbar-gutter: stable;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: visible;
    }

    StatusRow {
        height: 1;
    }

    CommitMessageDialog {
        align: center middle;
    }

    #commit-dialog {
        width: 76;
        height: 18;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    #commit-title {
        height: 1;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
    }

    #commit-message {
        height: 7;
        margin-top: 1;
    }

    #commit-actions {
        width: 1fr;
        height: 3;
        margin-top: 1;
        align: right bottom;
    }

    #commit-actions Button {
        height: 3;
        margin-left: 1;
    }

    #commit-cancel {
        width: 14;
    }

    #commit-confirm {
        width: 24;
    }

    HelpDialog {
        align: center middle;
    }

    #help-dialog {
        width: 78;
        height: 23;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    #help-title {
        height: 1;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
    }

    #help-content {
        height: 1fr;
        margin-top: 1;
    }

    LogScreen {
        layout: vertical;
        layers: base overlay;
    }

    #log-banner {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #log-body {
        height: 1fr;
    }

    #log-left {
        width: 40%;
        min-width: 36;
    }

    #log-right {
        width: 1fr;
        border-left: solid $surface;
        padding: 0 1;
    }

    .log-pane {
        height: 1fr;
    }

    #log-list-pane {
        height: 2fr;
        border-bottom: solid $surface;
    }

    #log-message-pane {
        height: 7;
        border-bottom: solid $surface;
    }

    #log-files-pane {
        height: 1fr;
    }

    .log-pane-title {
        height: 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #log-list-header,
    #log-file-list-header {
        height: 1;
        color: $text-muted;
        text-style: bold;
    }

    #log-message {
        height: 1fr;
    }

    #log-preview-title {
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
        text-style: bold;
    }

    #log-list,
    #log-file-list,
    #log-preview {
        width: 1fr;
        height: 1fr;
    }

    #status-search-label,
    #log-search-label,
    #log-file-search-label,
    #status-search,
    #log-search,
    #log-file-search {
        height: 1;
        width: 1fr;
        border: none;
        padding: 0;
        background: $panel;
        color: $text-muted;
    }

    #status-search:focus,
    #log-search:focus,
    #log-file-search:focus {
        border: none;
        background: $panel;
    }

    #status-search > .input--placeholder,
    #log-search > .input--placeholder,
    #log-file-search > .input--placeholder {
        color: $text-muted;
    }

    #log-preview {
        overflow-y: auto;
        overflow-x: auto;
        scrollbar-gutter: stable;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: visible;
    }

    #log-action-menu,
    #log-copy-menu {
        layer: overlay;
        position: absolute;
        background: $surface;
        border: solid $primary;
    }

    #log-action-menu {
        width: 24;
        height: 5;
    }

    #log-copy-menu {
        width: 18;
        height: 5;
    }

    LogEntryRow,
    LogPathRow {
        height: 1;
    }

    OverlayMenuItem {
        height: 1;
    }
    """

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
        cycle_width = len(path_text) + len(PATH_SCROLL_SEPARATOR)
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
            if isinstance(document, Text):
                self.preview_document = None
                self.preview.set_message(document)
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


class SvnTui(App[None]):
    CSS = StatusScreen.CSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, target: Path) -> None:
        super().__init__()
        self.target = target

    def on_mount(self) -> None:
        self.push_screen(StatusScreen(self.target))


def find_list_match(
    list_view: ListView,
    query: str,
    direction: int,
    text_for_row: object,
) -> int | None:
    children = list(list_view.children)
    if not children:
        return None

    normalized_query = query.casefold()
    step = 1 if direction >= 0 else -1
    start = list_view.index if list_view.index is not None else -1
    for offset in range(1, len(children) + 1):
        index = (start + step * offset) % len(children)
        row_text = text_for_row(children[index])
        if normalized_query in row_text.casefold():
            return index
    return None


def list_match_position(
    list_view: ListView,
    query: str,
    matched_index: int,
    text_for_row: object,
) -> tuple[int, int]:
    normalized_query = query.casefold()
    match_indices = [
        index
        for index, row in enumerate(list_view.children)
        if normalized_query in text_for_row(row).casefold()
    ]
    total = len(match_indices)
    if total == 0:
        return (0, 0)
    try:
        current = match_indices.index(matched_index) + 1
    except ValueError:
        current = 0
    return current, total


def format_search_label(
    query: str,
    match: tuple[int, int] | None,
    width: int = 0,
) -> Text:
    if not query:
        return Text("Searching: / to search", style="dim")
    left = f"Searching: {query}"
    right_count = "[0/0]"
    if match is None:
        return align_search_label(left, right_count, width)
    current, total = match
    return align_search_label(left, f"[{current}/{total}]", width)


def align_search_label(left: str, right_count: str, width: int) -> Text:
    jump_hint = "Jump by n/N"
    right = f"{right_count} {jump_hint}"
    if width <= 0:
        gap = 1
    else:
        gap = max(1, width - len(left) - len(right))
    text = Text(left, style="dim")
    text.append(" " * gap)
    text.append(right_count, style="dim")
    text.append(" ")
    text.append(jump_hint, style="bold")
    return text


def status_row_search_text(row: object, display_root: Path) -> str:
    if not isinstance(row, StatusRow):
        return ""
    shown_path = relative_path(row.entry.path, display_root)
    return " ".join(
        [
            row.entry.raw_status,
            row.entry.status_label,
            str(shown_path),
            str(row.entry.path),
            file_extension(row.entry.path),
            file_size_label(row.entry.path),
        ]
    )


def log_row_search_text(row: object) -> str:
    if isinstance(row, LogEntryRow):
        return " ".join(
            [
                row.log_entry.revision,
                row.log_entry.author,
                row.log_entry.date,
                row.log_entry.summary,
                row.log_entry.message,
            ]
        )
    if isinstance(row, LogPathRow):
        return " ".join(
            [
                row.path_entry.action,
                row.path_entry.node_kind,
                row.path_entry.path,
                row.shown_path,
            ]
        )
    return ""


def parse_svn_status_line(line: str, root: Path) -> SvnStatusEntry | None:
    if not line:
        return None
    if line.startswith("--- "):
        return None

    raw_status = line[:7].rstrip()
    text_status = line[0]
    prop_status = line[1] if len(line) > 1 else " "
    path_text = line[8:].strip() if len(line) > 8 else ""
    if not path_text:
        return None
    if text_status == " " and prop_status == " ":
        return None

    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = root / path

    return SvnStatusEntry(
        path=path.resolve(),
        text_status=text_status,
        prop_status=prop_status,
        raw_status=raw_status,
    )


def parse_svn_log_xml(xml_text: str) -> list[SvnLogEntry]:
    root = ET.fromstring(xml_text)
    entries: list[SvnLogEntry] = []
    for element in root.findall("logentry"):
        revision = element.attrib.get("revision", "")
        author = (element.findtext("author") or "").strip() or "-"
        date = format_log_date(element.findtext("date") or "")
        message = (element.findtext("msg") or "").strip()
        changed_paths: list[SvnLogPathEntry] = []
        for path_element in element.findall("./paths/path"):
            action = path_element.attrib.get("action", "?")
            node_kind = path_element.attrib.get("kind", "")
            path_text = (path_element.text or "").strip()
            if path_text:
                changed_paths.append(
                    SvnLogPathEntry(
                        action=action,
                        node_kind=node_kind,
                        path=path_text,
                    )
                )
        entries.append(
            SvnLogEntry(
                revision=revision,
                author=author,
                date=date,
                message=message,
                changed_paths=changed_paths,
            )
        )
    return entries


def format_log_date(value: str) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value.replace("T", " ")[:16]
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def relative_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def repo_relative_path(path_text: str, target_repo_path: str) -> str:
    normalized_root = target_repo_path.rstrip("/")
    if not normalized_root or normalized_root == path_text:
        return path_text.lstrip("/") or "."
    prefix = f"{normalized_root}/"
    if path_text.startswith(prefix):
        relative = path_text[len(prefix) :]
        return relative or "."
    return path_text.lstrip("/") or "."


def format_status_row(
    entry: SvnStatusEntry,
    shown_path: Path,
    marker: str,
    theme: StatusTheme,
    row_width: int = 0,
    is_highlighted: bool = False,
    is_in_visual_range: bool = False,
    path_scroll_offset: int = 0,
) -> Text:
    path_width = path_column_width(row_width)
    row = Text()
    check = Text()
    check.append("[", style="dim")
    check.append(marker, style=theme.marker_style if marker.strip() else "dim")
    check.append("]", style="dim")
    check.append(" " * (CHECK_COLUMN_WIDTH - len(check.plain)))
    row.append_text(check)
    row.append(f"{entry.raw_status:<{STATUS_COLUMN_WIDTH}}", style=status_style(entry, theme))
    row.append(" ")
    row.append(
        fit_path_label(str(shown_path), path_width, is_highlighted, path_scroll_offset),
        style=file_type_style(entry.path, theme),
    )
    row.append(" ")
    row.append(f"{file_extension(entry.path):<{EXTENSION_COLUMN_WIDTH}}", style="cyan")
    row.append(" ")
    row.append(f"{file_size_label(entry.path):>{SIZE_COLUMN_WIDTH}}", style="dim")
    if is_in_visual_range:
        row.stylize("reverse")
    return row


def format_log_row(entry: SvnLogEntry, row_width: int = 0) -> Text:
    summary_width = log_summary_width(row_width)
    row = Text()
    row.append(f"{entry.revision:<{LOG_REVISION_WIDTH}}", style="bold cyan")
    row.append(" ")
    row.append(f"{entry.author:<{LOG_AUTHOR_WIDTH}}", style="green")
    row.append(" ")
    row.append(f"{entry.date:<{LOG_DATE_WIDTH}}", style="dim")
    row.append(" ")
    row.append(end_truncate(entry.summary, summary_width))
    return row


def format_log_path_row(
    path_entry: SvnLogPathEntry,
    shown_path: str,
    row_width: int = 0,
    is_highlighted: bool = False,
    path_scroll_offset: int = 0,
) -> Text:
    path_width = log_path_width(row_width)
    row = Text()
    row.append(f"{path_entry.action:<{LOG_ACTION_WIDTH}}", style=log_action_style(path_entry.action))
    row.append(" ")
    row.append(
        fit_path_label(
            shown_path,
            path_width,
            is_highlighted,
            path_scroll_offset,
        )
    )
    row.append(" ")
    row.append(f"{log_kind_label(path_entry):<{LOG_KIND_WIDTH}}", style=log_kind_style(path_entry))
    return row


def format_log_header(row_width: int = 0) -> Text:
    summary_width = log_summary_width(row_width)
    header = Text()
    header.append(f"{'Rev':<{LOG_REVISION_WIDTH}}", style="bold")
    header.append(" ")
    header.append(f"{'Author':<{LOG_AUTHOR_WIDTH}}", style="bold")
    header.append(" ")
    header.append(f"{'Date':<{LOG_DATE_WIDTH}}", style="bold")
    header.append(" ")
    header.append(f"{'Summary':<{summary_width}}", style="bold")
    return header


def format_log_path_header(row_width: int = 0) -> Text:
    path_width = log_path_width(row_width)
    header = Text()
    header.append(f"{'Act':<{LOG_ACTION_WIDTH}}", style="bold")
    header.append(" ")
    header.append(f"{'Path':<{path_width}}", style="bold")
    header.append(" ")
    header.append(f"{'Type':<{LOG_KIND_WIDTH}}", style="bold")
    return header


def format_status_header(row_width: int = 0) -> Text:
    path_width = path_column_width(row_width)
    header = Text()
    header.append(f"{'Check':<{CHECK_COLUMN_WIDTH}}", style="bold")
    header.append(f"{'Status':<{STATUS_COLUMN_WIDTH}}", style="bold")
    header.append(" ")
    header.append(f"{'Path':<{path_width}}", style="bold")
    header.append(" ")
    header.append(f"{'Extension':<{EXTENSION_COLUMN_WIDTH}}", style="bold")
    header.append(" ")
    header.append(f"{'Size':>{SIZE_COLUMN_WIDTH}}", style="bold")
    return header


def path_column_width(row_width: int) -> int:
    fixed_width = (
        CHECK_COLUMN_WIDTH
        + STATUS_COLUMN_WIDTH
        + EXTENSION_COLUMN_WIDTH
        + SIZE_COLUMN_WIDTH
        + 3
    )
    if row_width <= fixed_width:
        return PATH_COLUMN_MIN_WIDTH
    return max(PATH_COLUMN_MIN_WIDTH, row_width - fixed_width)


def log_summary_width(row_width: int) -> int:
    fixed_width = LOG_REVISION_WIDTH + LOG_AUTHOR_WIDTH + LOG_DATE_WIDTH + 3
    if row_width <= fixed_width:
        return PATH_COLUMN_MIN_WIDTH
    return max(PATH_COLUMN_MIN_WIDTH, row_width - fixed_width)


def log_path_width(row_width: int) -> int:
    fixed_width = LOG_ACTION_WIDTH + LOG_KIND_WIDTH + 2
    if row_width <= fixed_width:
        return PATH_COLUMN_MIN_WIDTH
    return max(PATH_COLUMN_MIN_WIDTH, row_width - fixed_width)


def fit_path_label(
    path_text: str,
    width: int,
    is_highlighted: bool,
    scroll_offset: int,
) -> str:
    if width <= 0:
        return ""
    if len(path_text) <= width:
        return f"{path_text:<{width}}"
    if is_highlighted:
        return scroll_path_label(path_text, width, scroll_offset)
    return middle_truncate(path_text, width)


def middle_truncate(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return f"{value:<{width}}"
    marker = "..."
    if width <= len(marker):
        return value[:width]
    remaining = width - len(marker)
    head_width = (remaining + 1) // 2
    tail_width = remaining - head_width
    return value[:head_width] + marker + value[-tail_width:]


def end_truncate(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return f"{value:<{width}}"
    marker = "..."
    if width <= len(marker):
        return value[:width]
    return f"{value[: width - len(marker)]}{marker}"


def scroll_path_label(path_text: str, width: int, scroll_offset: int) -> str:
    if width <= 0:
        return ""
    cycle = path_text + PATH_SCROLL_SEPARATOR
    offset = scroll_offset % len(cycle)
    visible = (cycle + cycle)[offset : offset + width]
    return f"{visible:<{width}}"


def commit_success_message(output: str, file_count: int) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if lines:
        return lines[-1]
    return f"Committed {file_count} file(s)."


def format_help_text() -> Text:
    help_text = Text()
    shortcuts = [
        ("?", "Open this help dialog"),
        ("Esc", "Close dialogs or exit visual select mode"),
        ("l", "Open the recent log screen for the current target"),
        ("q", "Quit"),
        ("r", "Refresh SVN status"),
        ("Space", "Check or uncheck the current entry"),
        ("v", "Enter visual select mode at the current entry"),
        ("Space in visual", "Invert checked state for every entry in the range"),
        ("c", "Open commit message dialog for checked entries"),
        ("Ctrl+Enter", "Commit from the commit message dialog"),
        ("Enter / d", "Open the current entry in nvim diff"),
        ("b", "Open svn blame for the current entry in read-only nvim"),
        ("j / k", "Move selection down or up"),
        ("Ctrl+f / Ctrl+b", "Page the status list down or up"),
        ("gg / G", "Jump to top or bottom of the status list"),
        ("Ctrl+e / Ctrl+y", "Scroll preview down or up one line"),
        ("Ctrl+d / Ctrl+u", "Scroll preview down or up half a page"),
        ("Shift+Right / Shift+Left", "Scroll preview horizontally"),
        ("Ctrl+l", "Return from the recent log screen"),
    ]
    for key, description in shortcuts:
        help_text.append(f"{key:<24}", style="bold cyan")
        help_text.append(f"{description}\n")
    return help_text


def status_style(entry: SvnStatusEntry, theme: StatusTheme) -> str:
    status = first_status_char(entry)
    return theme.status_styles.get(status, theme.default_status_style)


def log_action_style(action: str) -> str:
    return DEFAULT_THEME.status_styles.get(action[:1], DEFAULT_THEME.default_status_style)


def log_kind_label(path_entry: SvnLogPathEntry) -> str:
    if path_entry.node_kind == "dir":
        return "D"
    if path_entry.node_kind == "file":
        return "F"
    return "?"


def log_kind_style(path_entry: SvnLogPathEntry) -> str:
    if path_entry.node_kind == "dir":
        return "cyan"
    if path_entry.node_kind == "file":
        return "green"
    return "dim"


def first_status_char(entry: SvnStatusEntry) -> str:
    for status in (entry.text_status, entry.prop_status):
        if status != " ":
            return status
    return entry.status_label[:1]


def file_type_style(path: Path, theme: StatusTheme) -> str:
    return theme.file_type_styles.get(path.suffix.lower(), theme.default_path_style)


def file_extension(path: Path) -> str:
    if path.is_dir():
        return "-"
    suffix = path.suffix
    if not suffix:
        return "-"
    return suffix


def file_size_label(path: Path) -> str:
    if not path.is_file():
        return "-"
    try:
        size = path.stat().st_size
    except OSError:
        return "-"
    return format_byte_size(size)


def format_byte_size(size: int) -> str:
    one_mib = 1024 * 1024
    one_gib = 1024 * one_mib
    if size < one_mib:
        return format_size(size / 1024, "k")
    if size < one_gib:
        return format_size(size / one_mib, "m")
    return format_size(size / one_gib, "g")


def format_size(value: float, unit: str) -> str:
    number = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{number}{unit}"


def build_preview_document(
    entry: SvnStatusEntry,
    cancel_token: PreviewCancelToken,
) -> PreviewDocument | Text | PreviewCancelled:
    path = entry.path
    if path.is_dir():
        return Text(f"{path} is a directory.", style="dim")
    if not path.exists():
        return Text(f"{path} does not exist in the working copy.", style="yellow")

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        return Text(f"Unable to read {path}: {exc}", style="red")

    max_lines = (
        None
        if file_size <= PREVIEW_FULL_INDEX_MAX_BYTES
        else PREVIEW_INITIAL_INDEX_LINES
    )
    scan = scan_preview_offsets(path, cancel_token, max_lines=max_lines)
    if isinstance(scan, PreviewCancelled):
        return scan
    if isinstance(scan, Text):
        return scan
    if scan.status_message is not None:
        return Text(
            f"{path} looks like a binary file. Preview is unavailable.",
            style="yellow",
        )

    try:
        lexer = Syntax.guess_lexer(str(path), code="")
    except Exception:
        lexer = "text"

    continue_indexing = (
        not scan.complete
        and file_size <= PREVIEW_BACKGROUND_INDEX_MAX_BYTES
    )
    status_message = preview_index_status_message(
        file_size=file_size,
        indexed_lines=len(scan.offsets),
        continue_indexing=continue_indexing,
        complete=scan.complete,
    )

    return PreviewDocument(
        path=path,
        line_offsets=scan.offsets,
        lexer=lexer,
        file_size=file_size,
        next_offset=scan.next_offset,
        indexed_complete=scan.complete,
        continue_indexing=continue_indexing,
        status_message=status_message,
    )


def continue_preview_document_index(
    document: PreviewDocument,
    cancel_token: PreviewCancelToken,
) -> PreviewDocument | PreviewCancelled:
    scan = scan_preview_offsets(
        document.path,
        cancel_token,
        start_offset=document.next_offset,
    )
    if isinstance(scan, PreviewCancelled):
        return scan
    if isinstance(scan, Text):
        document.apply_index_result(
            [],
            document.next_offset,
            True,
            f"Preview indexing stopped: {scan.plain}",
        )
        return document

    document.apply_index_result(
        scan.offsets,
        scan.next_offset,
        scan.complete,
        scan.status_message,
    )
    return document


def scan_preview_offsets(
    path: Path,
    cancel_token: PreviewCancelToken,
    *,
    start_offset: int = 0,
    max_lines: int | None = None,
) -> PreviewIndexScan | Text | PreviewCancelled:
    offsets: list[int] = []
    try:
        with path.open("rb") as file:
            file.seek(start_offset)
            while max_lines is None or len(offsets) < max_lines:
                if cancel_token.cancelled:
                    return PreviewCancelled()
                offset = file.tell()
                line = file.readline(PREVIEW_MAX_LINE_BYTES + 1)
                if line == b"":
                    return PreviewIndexScan(offsets, file.tell(), True)
                if b"\0" in line:
                    return PreviewIndexScan(
                        offsets,
                        file.tell(),
                        True,
                        "Binary data found after the indexed prefix. Preview stopped.",
                    )
                offsets.append(offset)
                if len(line) > PREVIEW_MAX_LINE_BYTES and not drain_line(
                    file,
                    cancel_token,
                ):
                    return PreviewCancelled()
            return PreviewIndexScan(offsets, file.tell(), False)
    except OSError as exc:
        return Text(f"Unable to read {path}: {exc}", style="red")


def preview_index_status_message(
    *,
    file_size: int,
    indexed_lines: int,
    continue_indexing: bool,
    complete: bool,
) -> str | None:
    if complete:
        return None
    size = format_byte_size(file_size)
    if continue_indexing:
        return (
            f"Showing first {indexed_lines} lines of {size}; "
            "indexing the rest in background."
        )
    return (
        f"Showing first {indexed_lines} lines of {size}; "
        "full indexing is skipped for large files."
    )


def read_preview_line(document: PreviewDocument, index: int) -> str:
    offset = document.line_offset_at(index)
    if offset is None:
        return document.status_message or ""

    try:
        with document.path.open("rb") as file:
            file.seek(offset)
            raw_line = file.readline(PREVIEW_MAX_LINE_BYTES + 1)
    except OSError as exc:
        return f"Unable to read line: {exc}"

    truncated = len(raw_line) > PREVIEW_MAX_LINE_BYTES
    if truncated:
        raw_line = raw_line[:PREVIEW_MAX_LINE_BYTES]
    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
    if len(line) > PREVIEW_MAX_COLUMNS:
        line = f"{line[:PREVIEW_MAX_COLUMNS]} ..."
    if truncated:
        line = f"{line} ..."
    return line


def drain_line(file: object, cancel_token: PreviewCancelToken) -> bool:
    while True:
        if cancel_token.cancelled:
            return False
        chunk = file.readline(PREVIEW_MAX_LINE_BYTES)
        if chunk == b"" or chunk.endswith(b"\n"):
            return True


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TUI client for reviewing svn status")
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="working copy path to inspect",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    SvnTui(Path(args.target)).run()


if __name__ == "__main__":
    main()
