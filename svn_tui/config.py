from __future__ import annotations

from dataclasses import dataclass


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
STATUS_ACTION_MENU_WIDTH = 32


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
