from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock

from rich.syntax import Syntax

from svn_tui.config import (
    PREVIEW_BACKGROUND_INDEX_MAX_BYTES,
    PREVIEW_FULL_INDEX_MAX_BYTES,
    PREVIEW_INITIAL_INDEX_LINES,
    PREVIEW_MAX_COLUMNS,
    PREVIEW_MAX_LINE_BYTES,
)
from svn_tui.models import SvnStatusEntry
from svn_tui.utils.formatting import format_byte_size


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


@dataclass(frozen=True)
class PreviewMessage:
    message: str
    style: str = "dim"



def build_preview_document(
    entry: SvnStatusEntry,
    cancel_token: PreviewCancelToken,
) -> PreviewDocument | PreviewMessage | PreviewCancelled:
    path = entry.path
    if path.is_dir():
        return PreviewMessage(f"{path} is a directory.")
    if not path.exists():
        return PreviewMessage(f"{path} does not exist in the working copy.", "yellow")

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        return PreviewMessage(f"Unable to read {path}: {exc}", "red")

    max_lines = (
        None
        if file_size <= PREVIEW_FULL_INDEX_MAX_BYTES
        else PREVIEW_INITIAL_INDEX_LINES
    )
    scan = scan_preview_offsets(path, cancel_token, max_lines=max_lines)
    if isinstance(scan, PreviewCancelled):
        return scan
    if isinstance(scan, PreviewMessage):
        return scan
    if scan.status_message is not None:
        return PreviewMessage(
            f"{path} looks like a binary file. Preview is unavailable.",
            "yellow",
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
    if isinstance(scan, PreviewMessage):
        document.apply_index_result(
            [],
            document.next_offset,
            True,
            f"Preview indexing stopped: {scan.message}",
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
) -> PreviewIndexScan | PreviewMessage | PreviewCancelled:
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
        return PreviewMessage(f"Unable to read {path}: {exc}", "red")


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
