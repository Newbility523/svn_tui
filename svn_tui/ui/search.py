from __future__ import annotations

from pathlib import Path

from textual.widgets import ListView

from svn_tui.ui.formatters import file_extension, file_size_label
from svn_tui.ui.widgets import LogEntryRow, LogPathRow, StatusRow
from svn_tui.utils.paths import relative_path


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
