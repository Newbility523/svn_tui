from __future__ import annotations

from pathlib import Path


def relative_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def repo_relative_path(path_text: str, target_repo_path: str) -> str:
    normalized_root = target_repo_path.rstrip("/")
    if not normalized_root or normalized_root == path_text:
        return path_text.lstrip("/") or "."
    prefix = f"{normalized_root}/"
    if path_text.startswith(prefix):
        relative = path_text[len(prefix) :]
        return relative or "."
    return path_text.lstrip("/") or "."
