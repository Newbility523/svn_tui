from __future__ import annotations

from collections import OrderedDict
from copy import copy

from rich.segment import Segment
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Label, ListItem

from svn_tui.config import (
    DEFAULT_THEME,
    PREVIEW_LINE_CACHE_SIZE,
    PREVIEW_RENDER_COLUMNS,
    StatusTheme,
)
from svn_tui.models import SvnLogEntry, SvnLogPathEntry, SvnStatusEntry
from svn_tui.services.preview import PreviewDocument, read_preview_line
from svn_tui.ui.formatters import (
    display_width,
    format_log_path_row,
    format_log_row,
    format_status_row,
    log_path_width,
    path_column_width,
)
from svn_tui.utils.paths import relative_path


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
        return display_width(str(shown_path)) > path_column_width(row_width)


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
        return display_width(self.shown_path) > log_path_width(row_width)


class OverlayMenuItem(ListItem):
    def __init__(
        self,
        option_id: str,
        label_text: str | Text,
        *,
        has_submenu: bool = False,
    ) -> None:
        super().__init__()
        self.option_id = option_id
        self.label_text = label_text
        self.has_submenu = has_submenu

    def compose(self) -> ComposeResult:
        label_text = self.label_text
        if self.has_submenu:
            if isinstance(label_text, Text):
                submenu_text = copy(label_text)
                submenu_text.append(">")
                yield Label(submenu_text)
                return
            yield Label(Text(f"{label_text:<20}>"))
            return
        yield Label(copy(label_text) if isinstance(label_text, Text) else Text(label_text))
