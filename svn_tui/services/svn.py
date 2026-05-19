from __future__ import annotations

import asyncio
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from svn_tui.config import LOG_ENTRY_LIMIT
from svn_tui.models import SvnLogEntry, SvnLogPathEntry, SvnStatusEntry


async def run_command_text(args: list[str]) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode,
            args,
            output=stdout_text,
            stderr=stderr_text,
        )
    return stdout_text


def build_svn_commit_args(message: str, paths: list[Path]) -> list[str]:
    return ["svn", "commit", "-m", message, "--", *(str(path) for path in paths)]


class SvnClient:
    def __init__(self, target: Path) -> None:
        self.target = target.expanduser().resolve()
        self.display_root = self.target if self.target.is_dir() else self.target.parent
        self.root = self.display_root
        self.root_loaded = False
        self.repo_root_url = ""
        self.target_url = ""
        self.target_repo_path = ""
        self.repo_info_loaded = False

    async def ensure_working_copy_root(self) -> None:
        if self.root_loaded:
            return
        probe = self.target if self.target.is_dir() else self.target.parent
        stdout = await run_command_text(
            ["svn", "info", "--show-item", "wc-root", str(probe)]
        )
        self.root = Path(stdout.strip()).resolve()
        self.root_loaded = True

    async def status(self) -> list[SvnStatusEntry]:
        await self.ensure_working_copy_root()
        stdout = await run_command_text(["svn", "st", str(self.target)])
        entries: list[SvnStatusEntry] = []
        for line in stdout.splitlines():
            entry = parse_svn_status_line(line, self.root)
            if entry is not None:
                entries.append(entry)
        return entries

    async def commit(self, message: str, paths: list[Path]) -> str:
        return await run_command_text(build_svn_commit_args(message, paths))

    async def ensure_repository_metadata(self) -> None:
        if self.repo_info_loaded:
            return
        probe = self.target if self.target.is_dir() else self.target.parent
        repo_root_url = await run_command_text(
            ["svn", "info", "--show-item", "repos-root-url", str(probe)]
        )
        target_url = await run_command_text(["svn", "info", "--show-item", "url", str(probe)])
        self.repo_root_url = repo_root_url.strip().rstrip("/")
        self.target_url = target_url.strip()
        if self.repo_root_url and self.target_url.startswith(self.repo_root_url):
            suffix = self.target_url[len(self.repo_root_url) :].strip("/")
            self.target_repo_path = f"/{suffix}" if suffix else "/"
        else:
            self.target_repo_path = ""
        self.repo_info_loaded = True

    async def recent_logs(self, limit: int = LOG_ENTRY_LIMIT) -> list[SvnLogEntry]:
        await self.ensure_repository_metadata()
        stdout = await run_command_text(
            ["svn", "log", "--xml", "-v", "-l", str(limit), self.target_url]
        )
        return parse_svn_log_xml(stdout)

    async def diff_for_log_path(
        self,
        revision: str,
        path_entry: SvnLogPathEntry,
    ) -> str:
        await self.ensure_repository_metadata()
        url = self.repo_path_to_url(path_entry.path)
        revision_number = int(revision) if revision.isdigit() else None
        candidates: list[str] = []
        if revision_number is not None and path_entry.action == "D" and revision_number > 0:
            candidates.append(f"{url}@{revision_number - 1}")
        if revision_number is not None:
            candidates.append(f"{url}@{revision_number}")
        candidates.append(url)

        error: subprocess.CalledProcessError | None = None
        for candidate in dedupe_strings(candidates):
            try:
                return await run_command_text(["svn", "diff", "-c", revision, candidate])
            except subprocess.CalledProcessError as exc:
                error = exc
        if error is not None:
            raise error
        return ""

    def repo_path_to_url(self, repo_path: str) -> str:
        if repo_path.startswith("/") and self.repo_root_url:
            return f"{self.repo_root_url}{repo_path}"
        return repo_path

    def open_blame(self, entry: SvnStatusEntry) -> str | None:
        if entry.text_status in {"?", "I"}:
            return "Blame is unavailable for unversioned or ignored files."
        if entry.path.is_dir():
            return "Blame is unavailable for directories."
        if not entry.path.exists():
            return "Blame is unavailable because the file does not exist locally."

        blame = subprocess.run(
            ["svn", "blame", "--", str(entry.path)],
            check=False,
            capture_output=True,
        )
        if blame.returncode != 0:
            message = blame.stderr.decode("utf-8", errors="replace").strip()
            return message or "svn blame failed."

        suffix = entry.path.suffix
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f"svn-blame-{entry.path.stem}-",
            suffix=suffix,
            delete=False,
        ) as blame_file:
            blame_path = Path(blame_file.name)
            blame_file.write(blame.stdout)

        try:
            subprocess.run(["nvim", "-R", str(blame_path)])
        finally:
            blame_path.unlink(missing_ok=True)

        return None

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


def parse_svn_log_xml(xml_text: str) -> list[SvnLogEntry]:
    root = ET.fromstring(xml_text)
    entries: list[SvnLogEntry] = []
    for element in root.findall("logentry"):
        revision = element.attrib.get("revision", "")
        author = (element.findtext("author") or "").strip() or "-"
        date = format_log_date(element.findtext("date") or "")
        message = (element.findtext("msg") or "").strip()
        changed_paths: list[SvnLogPathEntry] = []
        for path_element in element.findall("./paths/path"):
            action = path_element.attrib.get("action", "?")
            node_kind = path_element.attrib.get("kind", "")
            path_text = (path_element.text or "").strip()
            if path_text:
                changed_paths.append(
                    SvnLogPathEntry(
                        action=action,
                        node_kind=node_kind,
                        path=path_text,
                    )
                )
        entries.append(
            SvnLogEntry(
                revision=revision,
                author=author,
                date=date,
                message=message,
                changed_paths=changed_paths,
            )
        )
    return entries


def format_log_date(value: str) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value.replace("T", " ")[:16]
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
