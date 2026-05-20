from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len, get_character_cell_size, set_cell_size
from rich.text import Text

from svn_tui.config import (
    CHECK_COLUMN_WIDTH,
    DEFAULT_THEME,
    EXTENSION_COLUMN_WIDTH,
    LOG_ACTION_WIDTH,
    LOG_AUTHOR_WIDTH,
    LOG_DATE_WIDTH,
    LOG_KIND_WIDTH,
    LOG_REVISION_WIDTH,
    PATH_COLUMN_MIN_WIDTH,
    PATH_SCROLL_SEPARATOR,
    SIZE_COLUMN_WIDTH,
    STATUS_COLUMN_WIDTH,
    StatusTheme,
)
from svn_tui.models import SvnLogEntry, SvnLogPathEntry, SvnStatusEntry
from svn_tui.utils.formatting import format_byte_size


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
        gap = max(1, width - display_width(left) - display_width(right))
    text = Text(left, style="dim")
    text.append(" " * gap)
    text.append(right_count, style="dim")
    text.append(" ")
    text.append(jump_hint, style="bold")
    return text


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
    row.append(fit_cell(entry.raw_status, STATUS_COLUMN_WIDTH), style=status_style(entry, theme))
    row.append(" ")
    row.append(
        fit_path_label(str(shown_path), path_width, is_highlighted, path_scroll_offset),
        style=file_type_style(entry.path, theme),
    )
    row.append(" ")
    row.append(fit_cell(file_extension(entry.path), EXTENSION_COLUMN_WIDTH), style="cyan")
    row.append(" ")
    row.append(f"{file_size_label(entry.path):>{SIZE_COLUMN_WIDTH}}", style="dim")
    if is_in_visual_range:
        row.stylize("reverse")
    return row


def format_log_row(entry: SvnLogEntry, row_width: int = 0) -> Text:
    summary_width = log_summary_width(row_width)
    row = Text()
    row.append(fit_cell(entry.revision, LOG_REVISION_WIDTH), style="bold cyan")
    row.append(" ")
    row.append(fit_cell(entry.author, LOG_AUTHOR_WIDTH), style="green")
    row.append(" ")
    row.append(fit_cell(entry.date, LOG_DATE_WIDTH), style="dim")
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
    if display_width(path_text) <= width:
        return fit_cell(path_text, width)
    if is_highlighted:
        return scroll_path_label(path_text, width, scroll_offset)
    return middle_truncate(path_text, width)


def middle_truncate(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if display_width(value) <= width:
        return fit_cell(value, width)
    marker = "..."
    marker_width = display_width(marker)
    if width <= marker_width:
        return fit_cell(value, width)
    remaining = width - marker_width
    head_width = (remaining + 1) // 2
    tail_width = remaining - head_width
    return fit_cell(
        take_cells_start(value, head_width)
        + marker
        + take_cells_end(value, tail_width),
        width,
    )


def end_truncate(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if display_width(value) <= width:
        return fit_cell(value, width)
    marker = "..."
    marker_width = display_width(marker)
    if width <= marker_width:
        return fit_cell(value, width)
    return fit_cell(take_cells_start(value, width - marker_width) + marker, width)


def scroll_path_label(path_text: str, width: int, scroll_offset: int) -> str:
    if width <= 0:
        return ""
    cycle = path_text + PATH_SCROLL_SEPARATOR
    cycle_width = display_width(cycle)
    if cycle_width == 0:
        return " " * width
    offset = scroll_offset % cycle_width
    visible = take_cells_start(drop_cells_start(cycle + cycle, offset), width)
    return fit_cell(visible, width)


def display_width(value: str) -> int:
    return cell_len(value)


def fit_cell(value: str, width: int) -> str:
    if width <= 0:
        return ""
    return set_cell_size(value, width)


def take_cells_start(value: str, width: int) -> str:
    if width <= 0:
        return ""
    result: list[str] = []
    used = 0
    for character in value:
        size = get_character_cell_size(character)
        if used + size > width:
            break
        result.append(character)
        used += size
    return "".join(result)


def take_cells_end(value: str, width: int) -> str:
    if width <= 0:
        return ""
    result: list[str] = []
    used = 0
    for character in reversed(value):
        size = get_character_cell_size(character)
        if used + size > width:
            break
        result.append(character)
        used += size
    return "".join(reversed(result))


def drop_cells_start(value: str, width: int) -> str:
    if width <= 0:
        return value
    skipped = 0
    for index, character in enumerate(value):
        size = get_character_cell_size(character)
        if skipped + size > width:
            return value[index + 1 :]
        skipped += size
        if skipped == width:
            return value[index + 1 :]
    return ""


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
        ("z", "Open actions for the current entry"),
        ("Z", "Open actions for checked entries or the current directory"),
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
