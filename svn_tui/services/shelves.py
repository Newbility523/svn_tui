from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

from svn_tui.models import SvnStatusEntry
from svn_tui.services.svn import SvnClient
from svn_tui.shelf_models import (
    Shelf,
    ShelfVersion,
    ShelfVersionKind,
    WorkingCopyIdentity,
)


SHELF_SCHEMA_VERSION = 1
AUTO_SHELF_NAME_FORMAT = "shelf-%Y%m%d-%H%M%S"
BINARY_PROBE_BYTES = 64 * 1024
BINARY_PATCH_MARKER = "Cannot display: file marked as a binary type."


class ShelfError(RuntimeError):
    pass


class ShelfNameError(ShelfError):
    pass


class ShelfNotFoundError(ShelfError):
    pass


class ShelfSelectionError(ShelfError):
    def __init__(self, message: str, unsupported_paths: Sequence[Path] = ()) -> None:
        super().__init__(message)
        self.unsupported_paths = tuple(unsupported_paths)


class ShelfOperationError(ShelfError):
    def __init__(
        self,
        message: str,
        *,
        saved_version: ShelfVersion | None = None,
        output: str = "",
    ) -> None:
        super().__init__(message)
        self.saved_version = saved_version
        self.output = output


class ShelfOverwriteRequired(ShelfOperationError):
    def __init__(self, entries: Sequence[SvnStatusEntry]) -> None:
        super().__init__("Unshelve would overwrite local changes; confirmation is required.")
        self.entries = tuple(entries)


def default_shelf_data_root() -> Path:
    return user_data_path("svn-tui", appauthor=False) / "shelves"


def working_copy_fingerprint(identity: WorkingCopyIdentity) -> str:
    payload = {
        "wc_root": str(identity.wc_root.expanduser().resolve()),
        "repo_uuid": identity.repo_uuid,
        "repo_root_url": identity.repo_root_url.rstrip("/"),
        "target_relative_path": identity.target_relative_path.strip("/"),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:24]


def validate_shelf_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ShelfNameError("Shelf name cannot be empty.")
    if normalized in {".", ".."}:
        raise ShelfNameError("Shelf name cannot be '.' or '..'.")
    if len(normalized) > 80:
        raise ShelfNameError("Shelf name cannot be longer than 80 characters.")
    if any(character in normalized for character in ("/", "\\")):
        raise ShelfNameError("Shelf name cannot contain path separators.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ShelfNameError("Shelf name cannot contain control characters.")
    if normalized.startswith("."):
        raise ShelfNameError("Shelf name cannot start with '.'.")
    return normalized


def is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return b"\0" in file.read(BINARY_PROBE_BYTES)
    except OSError as exc:
        raise ShelfSelectionError(f"Unable to read selected file {path}: {exc}", [path]) from exc


class ShelfStore:
    def __init__(
        self,
        data_root: Path | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.data_root = (data_root or default_shelf_data_root()).expanduser().resolve()
        self._now = now or (lambda: datetime.now().astimezone())

    def identity_root(self, identity: WorkingCopyIdentity) -> Path:
        return self.data_root / working_copy_fingerprint(identity)

    def shelf_path(self, identity: WorkingCopyIdentity, shelf_name: str) -> Path:
        return self.identity_root(identity) / validate_shelf_name(shelf_name)

    def ensure_identity_root(self, identity: WorkingCopyIdentity) -> Path:
        root = self.identity_root(identity)
        root.mkdir(parents=True, exist_ok=True)
        self._atomic_write_json(root / "identity.json", self._identity_payload(identity))
        return root

    def generate_shelf_name(self, identity: WorkingCopyIdentity) -> str:
        base = self._now().strftime(AUTO_SHELF_NAME_FORMAT)
        candidate = base
        suffix = 2
        while self.shelf_path(identity, candidate).exists():
            candidate = f"{base}-{suffix:02d}"
            suffix += 1
        return candidate

    def create_shelf_version(
        self,
        identity: WorkingCopyIdentity,
        *,
        patch: str,
        paths: Sequence[str],
        status_summary: dict[str, str],
        path_revisions: dict[str, str],
        name: str | None = None,
        kind: ShelfVersionKind = "checkpoint",
        note: str = "",
    ) -> ShelfVersion:
        shelf_name = validate_shelf_name(name) if name and name.strip() else self.generate_shelf_name(identity)
        root = self.ensure_identity_root(identity)
        shelf_path = root / shelf_name
        if shelf_path.exists():
            raise ShelfNameError(f"Shelf already exists: {shelf_name}")
        self._validate_version_input(patch, paths, kind)
        timestamp = self._timestamp()
        temporary = Path(tempfile.mkdtemp(prefix=f".{shelf_name}.", dir=root))
        try:
            number = self._write_version_directory(
                temporary,
                identity,
                shelf_name=shelf_name,
                number=1,
                kind=kind,
                timestamp=timestamp,
                note=note,
                patch=patch,
                paths=paths,
                status_summary=status_summary,
                path_revisions=path_revisions,
            )
            self._atomic_write_json(
                temporary / "shelf.json",
                self._shelf_payload(
                    identity,
                    shelf_name,
                    created_at=timestamp,
                    updated_at=timestamp,
                    next_version=2,
                ),
            )
            os.replace(temporary, shelf_path)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return self.load_version(identity, shelf_name, number)

    def save_version(
        self,
        identity: WorkingCopyIdentity,
        shelf_name: str,
        *,
        patch: str,
        paths: Sequence[str],
        status_summary: dict[str, str],
        path_revisions: dict[str, str],
        kind: ShelfVersionKind,
        note: str = "",
    ) -> ShelfVersion:
        self._validate_version_input(patch, paths, kind)
        shelf = self.load_shelf(identity, shelf_name)
        timestamp = self._timestamp()
        number = self._next_version_number(shelf.path, shelf.next_version)
        self._write_version_directory(
            shelf.path,
            identity,
            shelf_name=shelf.name,
            number=number,
            kind=kind,
            timestamp=timestamp,
            note=note,
            patch=patch,
            paths=paths,
            status_summary=status_summary,
            path_revisions=path_revisions,
        )
        self._atomic_write_json(
            shelf.path / "shelf.json",
            self._shelf_payload(
                identity,
                shelf.name,
                created_at=shelf.created_at,
                updated_at=timestamp,
                next_version=number + 1,
            ),
        )
        return self.load_version(identity, shelf.name, number)

    def list_shelves(self, identity: WorkingCopyIdentity) -> list[Shelf]:
        root = self.identity_root(identity)
        if not root.exists():
            return []
        shelves: list[Shelf] = []
        for child in root.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            try:
                shelves.append(self.load_shelf(identity, child.name))
            except ShelfError:
                continue
        return sorted(shelves, key=lambda shelf: (shelf.updated_at, shelf.name), reverse=True)

    def load_shelf(self, identity: WorkingCopyIdentity, shelf_name: str) -> Shelf:
        path = self.shelf_path(identity, shelf_name)
        metadata_path = path / "shelf.json"
        if not metadata_path.is_file():
            raise ShelfNotFoundError(f"Shelf not found: {shelf_name}")
        payload = self._read_json(metadata_path)
        if payload.get("working_copy_fingerprint") != working_copy_fingerprint(identity):
            raise ShelfError(f"Shelf belongs to a different working copy: {shelf_name}")
        versions = self.list_versions(identity, shelf_name, _shelf_path=path)
        latest = versions[-1] if versions else None
        return Shelf(
            name=str(payload["name"]),
            path=path,
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            working_copy_fingerprint=str(payload["working_copy_fingerprint"]),
            next_version=int(payload.get("next_version", 1)),
            version_count=len(versions),
            latest_version=latest.number if latest else None,
            latest_kind=latest.kind if latest else None,
        )

    def list_versions(
        self,
        identity: WorkingCopyIdentity,
        shelf_name: str,
        *,
        _shelf_path: Path | None = None,
    ) -> list[ShelfVersion]:
        shelf_path = _shelf_path or self.shelf_path(identity, shelf_name)
        if not shelf_path.is_dir():
            raise ShelfNotFoundError(f"Shelf not found: {shelf_name}")
        versions: list[ShelfVersion] = []
        for child in shelf_path.iterdir():
            if not child.is_dir() or not child.name.startswith("v"):
                continue
            try:
                number = int(child.name[1:])
                versions.append(self.load_version(identity, shelf_name, number))
            except (ValueError, ShelfError):
                continue
        return sorted(versions, key=lambda version: version.number)

    def load_version(
        self,
        identity: WorkingCopyIdentity,
        shelf_name: str,
        number: int,
    ) -> int:
        shelf_path = self.shelf_path(identity, shelf_name)
        version_path = shelf_path / f"v{number:03d}"
        metadata_path = version_path / "meta.json"
        patch_path = version_path / "patch.diff"
        if not metadata_path.is_file() or not patch_path.is_file():
            raise ShelfNotFoundError(f"Shelf version not found: {shelf_name} v{number:03d}")
        payload = self._read_json(metadata_path)
        if payload.get("working_copy_fingerprint") != working_copy_fingerprint(identity):
            raise ShelfError("Shelf version belongs to a different working copy.")
        kind = str(payload["kind"])
        if kind not in {"checkpoint", "shelve"}:
            raise ShelfError(f"Unknown shelf version kind: {kind}")
        return ShelfVersion(
            shelf_name=str(payload["shelf_name"]),
            number=int(payload["number"]),
            kind=kind,  # type: ignore[arg-type]
            created_at=str(payload["created_at"]),
            note=str(payload.get("note", "")),
            working_copy_root=Path(str(payload["working_copy_root"])),
            repo_uuid=str(payload["repo_uuid"]),
            repo_root_url=str(payload["repo_root_url"]),
            target_relative_path=str(payload["target_relative_path"]),
            base_revision=str(payload["base_revision"]),
            paths=tuple(str(path) for path in payload.get("paths", [])),
            status_summary={str(key): str(value) for key, value in payload.get("status_summary", {}).items()},
            path_revisions={str(key): str(value) for key, value in payload.get("path_revisions", {}).items()},
            patch_path=patch_path,
            metadata_path=metadata_path,
        )

    def delete_version(self, identity: WorkingCopyIdentity, shelf_name: str, number: int) -> None:
        shelf = self.load_shelf(identity, shelf_name)
        version = self.load_version(identity, shelf_name, number)
        shutil.rmtree(version.metadata_path.parent)
        self._atomic_write_json(
            shelf.path / "shelf.json",
            self._shelf_payload(
                identity,
                shelf.name,
                created_at=shelf.created_at,
                updated_at=self._timestamp(),
                next_version=max(shelf.next_version, number + 1),
            ),
        )

    def delete_shelf(self, identity: WorkingCopyIdentity, shelf_name: str) -> None:
        shelf = self.load_shelf(identity, shelf_name)
        shutil.rmtree(shelf.path)

    def export_patch(
        self,
        identity: WorkingCopyIdentity,
        shelf_name: str,
        number: int,
        destination: Path,
    ) -> Path:
        version = self.load_version(identity, shelf_name, number)
        target = destination.expanduser().resolve()
        if (target.exists() and target.is_dir()) or (not target.exists() and not target.suffix):
            target = target / f"{shelf_name}-{version.label}.diff"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(version.patch_path, target)
        return target

    def _write_version_directory(
        self,
        shelf_path: Path,
        identity: WorkingCopyIdentity,
        *,
        shelf_name: str,
        number: int,
        kind: ShelfVersionKind,
        timestamp: str,
        note: str,
        patch: str,
        paths: Sequence[str],
        status_summary: dict[str, str],
        path_revisions: dict[str, str],
    ) -> ShelfVersion:
        final_path = shelf_path / f"v{number:03d}"
        if final_path.exists():
            raise ShelfError(f"Shelf version already exists: {shelf_name} v{number:03d}")
        temporary = Path(tempfile.mkdtemp(prefix=f".v{number:03d}.", dir=shelf_path))
        try:
            (temporary / "patch.diff").write_text(patch, encoding="utf-8", newline="")
            self._atomic_write_json(
                temporary / "meta.json",
                {
                    "schema_version": SHELF_SCHEMA_VERSION,
                    "shelf_name": shelf_name,
                    "number": number,
                    "kind": kind,
                    "created_at": timestamp,
                    "note": note.strip(),
                    "working_copy_fingerprint": working_copy_fingerprint(identity),
                    "working_copy_root": str(identity.wc_root),
                    "repo_uuid": identity.repo_uuid,
                    "repo_root_url": identity.repo_root_url,
                    "target_relative_path": identity.target_relative_path,
                    "base_revision": identity.base_revision,
                    "paths": list(paths),
                    "status_summary": status_summary,
                    "path_revisions": path_revisions,
                    "patch_file": "patch.diff",
                },
            )
            os.replace(temporary, final_path)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return number

    def _next_version_number(self, shelf_path: Path, configured: int) -> int:
        existing = [
            int(path.name[1:])
            for path in shelf_path.glob("v[0-9][0-9][0-9]*")
            if path.is_dir() and path.name[1:].isdigit()
        ]
        return max(configured, max(existing, default=0) + 1)

    @staticmethod
    def _validate_version_input(
        patch: str,
        paths: Sequence[str],
        kind: ShelfVersionKind,
    ) -> None:
        if kind not in {"checkpoint", "shelve"}:
            raise ShelfError(f"Unsupported shelf version kind: {kind}")
        if not paths:
            raise ShelfSelectionError("Select at least one modified text file.")
        if not patch.strip():
            raise ShelfSelectionError("Selected files do not contain a text diff.")
        if BINARY_PATCH_MARKER in patch:
            raise ShelfSelectionError("Binary files cannot be saved in the first Shelf version.")

    def _shelf_payload(
        self,
        identity: WorkingCopyIdentity,
        shelf_name: str,
        *,
        created_at: str,
        updated_at: str,
        next_version: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": SHELF_SCHEMA_VERSION,
            "name": shelf_name,
            "created_at": created_at,
            "updated_at": updated_at,
            "working_copy_fingerprint": working_copy_fingerprint(identity),
            "next_version": next_version,
        }

    @staticmethod
    def _identity_payload(identity: WorkingCopyIdentity) -> dict[str, Any]:
        return {
            "schema_version": SHELF_SCHEMA_VERSION,
            "working_copy_root": str(identity.wc_root),
            "repo_uuid": identity.repo_uuid,
            "repo_root_url": identity.repo_root_url,
            "target_relative_path": identity.target_relative_path,
            "working_copy_fingerprint": working_copy_fingerprint(identity),
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShelfError(f"Unable to read Shelf metadata {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ShelfError(f"Invalid Shelf metadata: {path}")
        return value

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _timestamp(self) -> str:
        return self._now().astimezone().isoformat(timespec="seconds")


class ShelfService:
    def __init__(self, client: SvnClient, store: ShelfStore | None = None) -> None:
        self.client = client
        self.store = store or ShelfStore()
        self.identity: WorkingCopyIdentity | None = None

    async def initialize(self) -> WorkingCopyIdentity:
        if self.identity is None:
            self.identity = await self.client.working_copy_identity()
        return self.identity

    async def list_shelves(self) -> list[Shelf]:
        return self.store.list_shelves(await self.initialize())

    async def list_versions(self, shelf_name: str) -> list[ShelfVersion]:
        return self.store.list_versions(await self.initialize(), shelf_name)

    async def delete_version(self, shelf_name: str, number: int) -> None:
        self.store.delete_version(await self.initialize(), shelf_name, number)

    async def delete_shelf(self, shelf_name: str) -> None:
        self.store.delete_shelf(await self.initialize(), shelf_name)

    async def export_patch(
        self,
        shelf_name: str,
        number: int,
        destination: Path,
    ) -> Path:
        return self.store.export_patch(
            await self.initialize(),
            shelf_name,
            number,
            destination,
        )

    async def new_shelf(
        self,
        entries: Sequence[SvnStatusEntry],
        *,
        name: str | None = None,
        note: str = "",
    ) -> ShelfVersion:
        prepared = await self._prepare_version(entries)
        return self.store.create_shelf_version(
            prepared.identity,
            name=name,
            kind="checkpoint",
            note=note,
            patch=prepared.patch,
            paths=prepared.paths,
            status_summary=prepared.status_summary,
            path_revisions=prepared.path_revisions,
        )

    async def save_checkpoint(
        self,
        shelf_name: str,
        entries: Sequence[SvnStatusEntry],
        *,
        note: str = "",
    ) -> ShelfVersion:
        prepared = await self._prepare_version(entries)
        return self.store.save_version(
            prepared.identity,
            shelf_name,
            kind="checkpoint",
            note=note,
            patch=prepared.patch,
            paths=prepared.paths,
            status_summary=prepared.status_summary,
            path_revisions=prepared.path_revisions,
        )

    async def shelve_selected(
        self,
        shelf_name: str,
        entries: Sequence[SvnStatusEntry],
        *,
        note: str = "",
    ) -> tuple[ShelfVersion, str]:
        prepared = await self._prepare_version(entries)
        version = self.store.save_version(
            prepared.identity,
            shelf_name,
            kind="shelve",
            note=note,
            patch=prepared.patch,
            paths=prepared.paths,
            status_summary=prepared.status_summary,
            path_revisions=prepared.path_revisions,
        )
        try:
            current_patch = await self.client.diff_paths(
                [entry.path for entry in prepared.entries]
            )
            if current_patch != prepared.patch:
                raise ShelfOperationError(
                    f"Saved {version.label}, but the working copy changed before revert; no paths were reverted.",
                    saved_version=version,
                )
            output = await self.client.revert_paths([entry.path for entry in prepared.entries])
        except ShelfOperationError:
            raise
        except (OSError, subprocess.CalledProcessError) as exc:
            output = command_exception_output(exc)
            raise ShelfOperationError(
                f"Saved {version.label}, but reverting selected paths failed.",
                saved_version=version,
                output=output,
            ) from exc
        return version, output

    async def unshelve_conflicts(self, version: ShelfVersion) -> list[SvnStatusEntry]:
        self._validate_version_identity(await self.initialize(), version)
        paths = self.version_paths(version)
        return await self.client.status_paths(paths)

    async def unshelve(
        self,
        version: ShelfVersion,
        *,
        allow_overwrite: bool = False,
    ) -> str:
        identity = await self.initialize()
        self._validate_version_identity(identity, version)
        paths = self.version_paths(version)
        current = await self.client.status_paths(paths)
        if current and not allow_overwrite:
            raise ShelfOverwriteRequired(current)
        output_parts: list[str] = []
        if current:
            output_parts.append(await self.client.revert_paths([entry.path for entry in current]))
        try:
            output_parts.append(await self.client.apply_patch(version.patch_path))
        except (OSError, subprocess.CalledProcessError) as exc:
            output = "\n".join(part for part in [*output_parts, command_exception_output(exc)] if part)
            raise ShelfOperationError(
                f"Unable to apply {version.shelf_name} {version.label}; the saved patch was kept.",
                saved_version=version,
                output=output,
            ) from exc
        return "\n".join(part for part in output_parts if part)

    def version_paths(self, version: ShelfVersion) -> list[Path]:
        root = version.working_copy_root.expanduser().resolve()
        paths: list[Path] = []
        for stored in version.paths:
            candidate = (root / stored).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise ShelfError(f"Shelf contains an unsafe path: {stored}") from exc
            paths.append(candidate)
        return paths

    async def _prepare_version(self, entries: Sequence[SvnStatusEntry]) -> PreparedShelfVersion:
        selected = self._validate_entries(entries)
        identity = await self.initialize()
        paths = [entry.path for entry in selected]
        relative_paths = tuple(self.client.relative_working_copy_path(path) for path in paths)
        patch = await self.client.diff_paths(paths)
        if BINARY_PATCH_MARKER in patch:
            raise ShelfSelectionError("Binary files cannot be saved in the first Shelf version.", paths)
        revisions = await self.client.path_base_revisions(paths)
        return PreparedShelfVersion(
            identity=identity,
            entries=tuple(selected),
            patch=patch,
            paths=relative_paths,
            status_summary={
                relative: entry.status_label
                for relative, entry in zip(relative_paths, selected, strict=True)
            },
            path_revisions=revisions,
        )

    @staticmethod
    def _validate_entries(entries: Sequence[SvnStatusEntry]) -> list[SvnStatusEntry]:
        unique: dict[Path, SvnStatusEntry] = {}
        for entry in entries:
            unique[entry.path.resolve()] = entry
        selected = list(unique.values())
        if not selected:
            raise ShelfSelectionError("Select at least one modified text file.")
        unsupported = [
            entry.path
            for entry in selected
            if entry.text_status != "M"
            or entry.prop_status == "C"
            or not entry.path.is_file()
            or entry.path.is_symlink()
            or is_probably_binary(entry.path)
        ]
        if unsupported:
            raise ShelfSelectionError(
                "The first Shelf version only supports versioned, modified text files.",
                unsupported,
            )
        return selected

    @staticmethod
    def _validate_version_identity(identity: WorkingCopyIdentity, version: ShelfVersion) -> None:
        if working_copy_fingerprint(identity) != working_copy_fingerprint(
            WorkingCopyIdentity(
                wc_root=version.working_copy_root,
                repo_uuid=version.repo_uuid,
                repo_root_url=version.repo_root_url,
                target_relative_path=version.target_relative_path,
                base_revision=version.base_revision,
            )
        ):
            raise ShelfError("Shelf version belongs to a different working copy.")


class PreparedShelfVersion:
    def __init__(
        self,
        *,
        identity: WorkingCopyIdentity,
        entries: tuple[SvnStatusEntry, ...],
        patch: str,
        paths: tuple[str, ...],
        status_summary: dict[str, str],
        path_revisions: dict[str, str],
    ) -> None:
        self.identity = identity
        self.entries = entries
        self.patch = patch
        self.paths = paths
        self.status_summary = status_summary
        self.path_revisions = path_revisions


def command_exception_output(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return "\n".join(
            part.strip()
            for part in (str(exc.output or ""), str(exc.stderr or ""))
            if part and str(part).strip()
        )
    return str(exc)


def open_directory(path: Path) -> None:
    target = str(path.expanduser().resolve())
    if sys.platform == "darwin":
        subprocess.run(["open", target], check=False)
    elif os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", target], check=False)
