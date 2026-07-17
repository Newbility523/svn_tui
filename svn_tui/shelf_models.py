from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ShelfVersionKind = Literal["checkpoint", "shelve"]


@dataclass(frozen=True)
class WorkingCopyIdentity:
    wc_root: Path
    repo_uuid: str
    repo_root_url: str
    target_relative_path: str
    base_revision: str


@dataclass(frozen=True)
class Shelf:
    name: str
    path: Path
    created_at: str
    updated_at: str
    working_copy_fingerprint: str
    next_version: int
    version_count: int
    latest_version: int | None
    latest_kind: ShelfVersionKind | None


@dataclass(frozen=True)
class ShelfVersion:
    shelf_name: str
    number: int
    kind: ShelfVersionKind
    created_at: str
    note: str
    working_copy_root: Path
    repo_uuid: str
    repo_root_url: str
    target_relative_path: str
    base_revision: str
    paths: tuple[str, ...]
    status_summary: dict[str, str]
    path_revisions: dict[str, str]
    patch_path: Path
    metadata_path: Path

    @property
    def label(self) -> str:
        return f"v{self.number:03d}"
