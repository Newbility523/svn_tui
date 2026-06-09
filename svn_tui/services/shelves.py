from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from svn_tui.models import SvnStatusEntry
from svn_tui.services.svn import SvnClient, relative_to_root

ShelfVersionKind = Literal["checkpoint", "shelve"]


@dataclass(frozen=True)
class ShelfWorkspace:
    fingerprint: str
    working_copy_root: Path
    repo_uuid: str
    repo_root_url: str
    target_relpath: str
    base_revision: str


@dataclass(frozen=True)
class ShelfVersion:
    shelf_name: str
    storage_id: str
    version: int
    kind: ShelfVersionKind
    created_at: str
    paths: tuple[Path, ...]
    statuses: tuple[str, ...]
    patch_path: Path
    meta_path: Path

    @property
    def label(self) -> str:
        return f"v{self.version:03d} {self.kind}"


@dataclass(frozen=True)
class Shelf:
    name: str
    storage_id: str
    path: Path
    versions: tuple[ShelfVersion, ...]

    @property
    def latest_version(self) -> ShelfVersion | None:
        return self.versions[0] if self.versions else None


class ShelfStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_shelf_root()

    def workspace_dir(self, workspace: ShelfWorkspace) -> Path:
        return self.root / workspace.fingerprint

    def list_shelves(self, workspace: ShelfWorkspace) -> list[Shelf]:
        directory = self.workspace_dir(workspace)
        if not directory.exists():
            return []
        shelves: list[Shelf] = []
        for shelf_dir in sorted(directory.iterdir()):
            if not shelf_dir.is_dir():
                continue
            shelf = self.read_shelf(shelf_dir)
            if shelf is not None:
                shelves.append(shelf)
        shelves.sort(key=shelf_sort_key, reverse=True)
        return shelves

    def read_shelf(self, shelf_dir: Path) -> Shelf | None:
        shelf_json = shelf_dir / "shelf.json"
        if not shelf_json.exists():
            return None
        try:
            data = read_json(shelf_json)
            name = str(data["name"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        versions = tuple(
            sorted(
                (
                    version
                    for version_dir in shelf_dir.iterdir()
                    if version_dir.is_dir()
                    for version in [self.read_version(shelf_dir.name, name, version_dir)]
                    if version is not None
                ),
                key=lambda version: version.version,
                reverse=True,
            )
        )
        return Shelf(
            name=name,
            storage_id=shelf_dir.name,
            path=shelf_dir,
            versions=versions,
        )

    def read_version(
        self,
        storage_id: str,
        shelf_name: str,
        version_dir: Path,
    ) -> ShelfVersion | None:
        meta_path = version_dir / "meta.json"
        patch_path = version_dir / "patch.diff"
        if not meta_path.exists() or not patch_path.exists():
            return None
        try:
            data = read_json(meta_path)
            version = int(data["version"])
            kind = str(data["kind"])
            if kind not in {"checkpoint", "shelve"}:
                return None
            paths = tuple(Path(path) for path in data.get("paths", []))
            statuses = tuple(str(status) for status in data.get("statuses", []))
            created_at = str(data["created_at"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return ShelfVersion(
            shelf_name=shelf_name,
            storage_id=storage_id,
            version=version,
            kind=kind,  # type: ignore[arg-type]
            created_at=created_at,
            paths=paths,
            statuses=statuses,
            patch_path=patch_path,
            meta_path=meta_path,
        )

    def create_version(
        self,
        workspace: ShelfWorkspace,
        shelf_name: str,
        kind: ShelfVersionKind,
        patch_text: str,
        entries: list[SvnStatusEntry],
    ) -> ShelfVersion:
        storage_id = shelf_storage_id(shelf_name)
        shelf_dir = self.workspace_dir(workspace) / storage_id
        shelf_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        self.write_shelf_json(shelf_dir, shelf_name, now)
        version = self.next_version_number(shelf_dir)
        version_dir = shelf_dir / f"v{version:03d}"
        version_dir.mkdir()
        patch_path = version_dir / "patch.diff"
        patch_path.write_text(patch_text, encoding="utf-8", newline="\n")
        relative_paths = [
            relative_to_root(entry.path, workspace.working_copy_root) for entry in entries
        ]
        meta = {
            "name": shelf_name,
            "storage_id": storage_id,
            "version": version,
            "kind": kind,
            "created_at": now,
            "working_copy_root": str(workspace.working_copy_root),
            "repo_uuid": workspace.repo_uuid,
            "repo_root_url": workspace.repo_root_url,
            "target_relpath": workspace.target_relpath,
            "base_revision": workspace.base_revision,
            "paths": [str(path) for path in relative_paths],
            "statuses": [entry.raw_status for entry in entries],
            "patch": "patch.diff",
        }
        meta_path = version_dir / "meta.json"
        write_json(meta_path, meta)
        return ShelfVersion(
            shelf_name=shelf_name,
            storage_id=storage_id,
            version=version,
            kind=kind,
            created_at=now,
            paths=tuple(relative_paths),
            statuses=tuple(entry.raw_status for entry in entries),
            patch_path=patch_path,
            meta_path=meta_path,
        )

    def write_shelf_json(self, shelf_dir: Path, shelf_name: str, now: str) -> None:
        shelf_json = shelf_dir / "shelf.json"
        if shelf_json.exists():
            data = read_json(shelf_json)
            data["updated_at"] = now
        else:
            data = {
                "name": shelf_name,
                "created_at": now,
                "updated_at": now,
            }
        write_json(shelf_json, data)

    def next_version_number(self, shelf_dir: Path) -> int:
        numbers: list[int] = []
        for path in shelf_dir.iterdir():
            if not path.is_dir():
                continue
            match = re.fullmatch(r"v(\d+)", path.name)
            if match:
                numbers.append(int(match.group(1)))
        return max(numbers, default=0) + 1

    def delete_version(self, version: ShelfVersion) -> None:
        shutil.rmtree(version.meta_path.parent)

    def delete_shelf(self, shelf: Shelf) -> None:
        shutil.rmtree(shelf.path)


async def build_shelf_workspace(client: SvnClient) -> ShelfWorkspace:
    await client.ensure_working_copy_root()
    await client.ensure_repository_metadata()
    base_revision = await client.working_revision()
    fingerprint = workspace_fingerprint(
        client.root,
        client.repo_uuid,
        client.repo_root_url,
        client.target_repo_path,
    )
    return ShelfWorkspace(
        fingerprint=fingerprint,
        working_copy_root=client.root,
        repo_uuid=client.repo_uuid,
        repo_root_url=client.repo_root_url,
        target_relpath=client.target_repo_path,
        base_revision=base_revision,
    )


def default_shelf_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "svn-tui" / "shelves"
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "svn-tui" / "shelves"
    return Path.home() / ".local" / "share" / "svn-tui" / "shelves"


def workspace_fingerprint(
    working_copy_root: Path,
    repo_uuid: str,
    repo_root_url: str,
    target_relpath: str,
) -> str:
    raw = "\n".join(
        [
            str(working_copy_root.resolve()),
            repo_uuid,
            repo_root_url,
            target_relpath,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def shelf_storage_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    slug = slug or "shelf"
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:40]}-{digest}"


def shelfable_entries(entries: list[SvnStatusEntry]) -> list[SvnStatusEntry]:
    return [
        entry
        for entry in entries
        if is_shelfable_entry(entry)
    ]


def is_shelfable_entry(entry: SvnStatusEntry) -> bool:
    if entry.path.exists() and entry.path.is_dir():
        return False
    if entry.path.exists() and looks_like_binary_file(entry.path):
        return False
    if entry.text_status in {"?", "I", "C"} or entry.prop_status == "C":
        return False
    return entry.text_status.strip() != "" or entry.prop_status.strip() != ""


def looks_like_binary_file(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\0" in sample


def shelf_sort_key(shelf: Shelf) -> str:
    latest = shelf.latest_version
    if latest is None:
        return ""
    return latest.created_at


def read_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object.")
    return data


def write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
