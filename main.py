from __future__ import annotations

import argparse
import asyncio
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rich.segment import Segment
from rich.syntax import Syntax
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static


PREVIEW_ENABLED = True
PREVIEW_DEBOUNCE_SECONDS = 0.2
PREVIEW_EXTRA_LINES = 2
PREVIEW_FALLBACK_LINES = 40
PREVIEW_MAX_COLUMNS = 240
PREVIEW_MAX_LINE_BYTES = 8_192
CHECK_COLUMN_WIDTH = 6
EXTENSION_COLUMN_WIDTH = 10
SIZE_COLUMN_WIDTH = 8


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
class PreviewDocument:
    path: Path
    line_offsets: list[int]
    lexer: str

    @property
    def line_count(self) -> int:
        return len(self.line_offsets)


class SvnClient:
    def __init__(self, target: Path) -> None:
        self.target = target.expanduser().resolve()
        self.display_root = self.target if self.target.is_dir() else self.target.parent
        self.root = self._find_working_copy_root()

    def status(self) -> list[SvnStatusEntry]:
        result = subprocess.run(
            ["svn", "st", str(self.target)],
            check=True,
            capture_output=True,
            text=True,
        )
        entries: list[SvnStatusEntry] = []
        for line in result.stdout.splitlines():
            entry = parse_svn_status_line(line, self.root)
            if entry is not None:
                entries.append(entry)
        return entries

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

    def _find_working_copy_root(self) -> Path:
        probe = self.target if self.target.is_dir() else self.target.parent
        result = subprocess.run(
            ["svn", "info", "--show-item", "wc-root", str(probe)],
            check=True,
            capture_output=True,
            text=True,
        )
        return Path(result.stdout.strip()).resolve()


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

    def compose(self) -> ComposeResult:
        yield self.label

    def on_mount(self) -> None:
        self.refresh_label()

    def toggle_selected(self) -> None:
        self.selected_for_commit = not self.selected_for_commit
        self.refresh_label()

    def refresh_label(self) -> None:
        marker = (
            self.theme.selected_marker
            if self.selected_for_commit
            else self.theme.unselected_marker
        )
        shown_path = relative_path(self.entry.path, self.root)
        self.label.update(format_status_row(self.entry, shown_path, marker, self.theme))


class PreviewView(ScrollView):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.document: PreviewDocument | None = None
        self.message: Text | None = Text("No changed file selected.", style="dim")
        self.line_cache: dict[int, Strip] = {}

    def set_message(self, message: Text) -> None:
        self.document = None
        self.message = message
        self.line_cache.clear()
        self.virtual_size = Size(1, 1)
        self.scroll_to(x=0, y=0, animate=False, immediate=True)
        self.refresh(layout=True)

    def set_document(self, document: PreviewDocument) -> None:
        self.document = document
        self.message = None
        self.line_cache.clear()
        height = max(1, document.line_count)
        self.virtual_size = Size(PREVIEW_MAX_COLUMNS + 16, height)
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
        return strip.crop_pad(
            width,
            int(self.scroll_x),
            int(self.scroll_x) + width,
            self.visual_style.rich_style,
        )

    def render_document_line(self, y: int) -> Strip:
        assert self.document is not None
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
        options = self.app.console.options.update_width(max(1, self.size.width))
        lines = self.app.console.render_lines(renderable, options, pad=False)
        segments = lines[0] if lines else []
        normalized = [
            Segment(segment.text, segment.style or Style(), segment.control)
            for segment in segments
        ]
        return Strip(normalized)


class SvnTui(App[None]):
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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_status", "Refresh"),
        Binding("space", "toggle_entry", "Stage"),
        Binding("enter", "diff_entry", "Diff"),
        Binding("d", "diff_entry", "Diff"),
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
        self.detail = Static(id="details")
        self.preview = PreviewView(id="preview")
        self.status_theme = DEFAULT_THEME
        self.preview_task: asyncio.Task[None] | None = None
        self.preview_debounce_task: asyncio.Task[None] | None = None
        self.preview_request_id = 0
        self.preview_document: PreviewDocument | None = None
        self.waiting_for_second_g = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="content"):
            with Vertical(id="main"):
                yield self.status_header
                yield self.list_view
                yield self.detail
            with Vertical(id="side"):
                yield Static("Preview", id="preview-title")
                yield self.preview
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "svn-tui"
        self.sub_title = str(self.client.target)
        await self.load_status()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        row = event.item
        if isinstance(row, StatusRow):
            self.update_detail(row)
            self.schedule_preview(row.entry)

    def on_unmount(self) -> None:
        if self.preview_debounce_task is not None:
            self.preview_debounce_task.cancel()
        if self.preview_task is not None:
            self.preview_task.cancel()

    async def action_refresh_status(self) -> None:
        await self.load_status()

    def action_toggle_entry(self) -> None:
        self.waiting_for_second_g = False
        row = self.current_row()
        if row is None:
            return
        row.toggle_selected()
        self.update_detail(row)

    def action_diff_entry(self) -> None:
        self.waiting_for_second_g = False
        row = self.current_row()
        if row is None:
            return
        with self.suspend():
            self.client.open_diff(row.entry)

    def action_cursor_down(self) -> None:
        self.waiting_for_second_g = False
        self.list_view.action_cursor_down()

    def action_cursor_up(self) -> None:
        self.waiting_for_second_g = False
        self.list_view.action_cursor_up()

    def action_page_down(self) -> None:
        self.waiting_for_second_g = False
        self.list_view.action_page_down()

    def action_page_up(self) -> None:
        self.waiting_for_second_g = False
        self.list_view.action_page_up()

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

    def clear_pending_vim_prefix(self) -> None:
        self.waiting_for_second_g = False

    def move_to_top(self) -> None:
        if self.list_view.children:
            self.list_view.index = 0

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

    async def load_status(self) -> None:
        try:
            self.entries = self.client.status()
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

        await self.list_view.clear()
        if not self.entries:
            await self.list_view.append(ListItem(Label("Working copy is clean")))
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
            row = self.current_row()
            if row is not None:
                self.update_detail(row)
                self.schedule_preview(row.entry)

    def schedule_preview(self, entry: SvnStatusEntry) -> None:
        if not PREVIEW_ENABLED:
            self.preview.update(Text("Preview disabled.", style="dim"))
            return
        self.preview_request_id += 1
        request_id = self.preview_request_id
        if self.preview_debounce_task is not None:
            self.preview_debounce_task.cancel()
        if self.preview_task is not None:
            self.preview_task.cancel()
            self.preview_task = None
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
        try:
            document = await asyncio.to_thread(
                build_preview_document,
                entry,
            )
        except asyncio.CancelledError:
            return
        if request_id == self.preview_request_id:
            if isinstance(document, Text):
                self.preview_document = None
                self.preview.set_message(document)
                return
            self.preview_document = document
            self.preview.set_document(document)

    def update_detail(self, row: StatusRow | None = None) -> None:
        self.detail.update(self.format_detail(row))

    def format_detail(self, row: StatusRow | None = None) -> Text:
        selected = [
            row
            for row in self.list_view.children
            if isinstance(row, StatusRow) and row.selected_for_commit
        ]
        detail = Text()
        detail.append(f"Changed: {len(self.entries)}  ")
        detail.append(f"Commit list: {len(selected)}\n")
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

        detail.append(
            "Space: check/uncheck  Enter/d: nvim diff  j/k: move  "
            "gg/G: top/bottom  Ctrl-e/y/d/u: preview  Shift-left/right: preview x  r: refresh"
        )
        return detail


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


def relative_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def format_status_row(
    entry: SvnStatusEntry,
    shown_path: Path,
    marker: str,
    theme: StatusTheme,
) -> Text:
    row = Text()
    check = Text()
    check.append("[", style="dim")
    check.append(marker, style=theme.marker_style if marker.strip() else "dim")
    check.append("]", style="dim")
    check.append(" " * (CHECK_COLUMN_WIDTH - len(check.plain)))
    row.append_text(check)
    row.append(f"{entry.raw_status:<8}", style=status_style(entry, theme))
    row.append(" ")
    row.append(f"{file_extension(entry.path):<{EXTENSION_COLUMN_WIDTH}}", style="cyan")
    row.append(" ")
    row.append(f"{file_size_label(entry.path):>{SIZE_COLUMN_WIDTH}}", style="dim")
    row.append(" ")
    row.append(str(shown_path), style=file_type_style(entry.path, theme))
    return row


def format_status_header() -> Text:
    header = Text()
    header.append(f"{'Check':<{CHECK_COLUMN_WIDTH}}", style="bold")
    header.append(f"{'Status':<8}", style="bold")
    header.append(" ")
    header.append(f"{'Extension':<{EXTENSION_COLUMN_WIDTH}}", style="bold")
    header.append(" ")
    header.append(f"{'Size':>{SIZE_COLUMN_WIDTH}}", style="bold")
    header.append(" ")
    header.append("Path", style="bold")
    return header


def status_style(entry: SvnStatusEntry, theme: StatusTheme) -> str:
    status = first_status_char(entry)
    return theme.status_styles.get(status, theme.default_status_style)


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
    return suffix[1:]


def file_size_label(path: Path) -> str:
    if not path.is_file():
        return "-"
    try:
        size = path.stat().st_size
    except OSError:
        return "-"

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


def build_preview_document(entry: SvnStatusEntry) -> PreviewDocument | Text:
    path = entry.path
    if path.is_dir():
        return Text(f"{path} is a directory.", style="dim")
    if not path.exists():
        return Text(f"{path} does not exist in the working copy.", style="yellow")

    line_offsets: list[int] = []
    try:
        with path.open("rb") as file:
            while True:
                offset = file.tell()
                line = file.readline(PREVIEW_MAX_LINE_BYTES + 1)
                if line == b"":
                    break
                if b"\0" in line:
                    return Text(
                        f"{path} looks like a binary file. Preview is unavailable.",
                        style="yellow",
                    )
                line_offsets.append(offset)
                if len(line) > PREVIEW_MAX_LINE_BYTES:
                    drain_line(file)
    except OSError as exc:
        return Text(f"Unable to read {path}: {exc}", style="red")

    try:
        lexer = Syntax.guess_lexer(str(path), code="")
    except Exception:
        lexer = "text"

    return PreviewDocument(path=path, line_offsets=line_offsets, lexer=lexer)


def read_preview_line(document: PreviewDocument, index: int) -> str:
    with document.path.open("rb") as file:
        file.seek(document.line_offsets[index])
        raw_line = file.readline(PREVIEW_MAX_LINE_BYTES + 1)

    truncated = len(raw_line) > PREVIEW_MAX_LINE_BYTES
    if truncated:
        raw_line = raw_line[:PREVIEW_MAX_LINE_BYTES]
    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
    if len(line) > PREVIEW_MAX_COLUMNS:
        line = f"{line[:PREVIEW_MAX_COLUMNS]} ..."
    if truncated:
        line = f"{line} ..."
    return line


def drain_line(file: object) -> None:
    while True:
        chunk = file.readline(PREVIEW_MAX_LINE_BYTES)
        if chunk == b"" or chunk.endswith(b"\n"):
            return


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
