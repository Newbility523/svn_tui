from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
