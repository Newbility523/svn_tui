from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from svn_tui.models import SvnStatusEntry
from svn_tui.services.shelves import (
    ShelfStore,
    ShelfWorkspace,
    shelf_storage_id,
    shelfable_entries,
    workspace_fingerprint,
)


class ShelfStorageTests(unittest.TestCase):
    def test_workspace_fingerprint_distinguishes_working_copy_roots(self) -> None:
        first = workspace_fingerprint(
            Path("one"),
            "uuid",
            "https://svn.example/repo",
            "/trunk/app",
        )
        second = workspace_fingerprint(
            Path("two"),
            "uuid",
            "https://svn.example/repo",
            "/trunk/app",
        )

        self.assertNotEqual(first, second)

    def test_shelf_storage_id_keeps_readable_slug_and_hash(self) -> None:
        storage_id = shelf_storage_id("fix login flow")

        self.assertTrue(storage_id.startswith("fix-login-flow-"))
        self.assertGreater(len(storage_id), len("fix-login-flow-"))

    def test_create_version_writes_patch_and_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = ShelfWorkspace(
                fingerprint="abc123",
                working_copy_root=root / "wc",
                repo_uuid="uuid",
                repo_root_url="https://svn.example/repo",
                target_relpath="/trunk/app",
                base_revision="42",
            )
            entry = SvnStatusEntry(
                workspace.working_copy_root / "src" / "app.py",
                "M",
                " ",
                "M",
            )
            store = ShelfStore(root / "shelves")

            version = store.create_version(
                workspace,
                "fix login flow",
                "checkpoint",
                "Index: src/app.py\n+hello\n",
                [entry],
            )
            shelves = store.list_shelves(workspace)

            self.assertEqual(version.version, 1)
            self.assertEqual(version.paths, (Path("src/app.py"),))
            self.assertEqual(version.patch_path.read_text(encoding="utf-8"), "Index: src/app.py\n+hello\n")
            self.assertEqual(len(shelves), 1)
            self.assertEqual(shelves[0].name, "fix login flow")
            self.assertEqual(shelves[0].versions[0].paths, (Path("src/app.py"),))

    def test_shelfable_entries_keep_versioned_files_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            versioned = root / "app.py"
            unversioned = root / "new.py"
            conflict = root / "conflict.py"
            directory_path = root / "src"
            versioned.write_text("hello", encoding="utf-8")
            unversioned.write_text("hello", encoding="utf-8")
            conflict.write_text("hello", encoding="utf-8")
            directory_path.mkdir()
            entries = [
                SvnStatusEntry(versioned, "M", " ", "M"),
                SvnStatusEntry(unversioned, "?", " ", "?"),
                SvnStatusEntry(conflict, "C", " ", "C"),
                SvnStatusEntry(directory_path, "M", " ", "M"),
            ]

            filtered = shelfable_entries(entries)

            self.assertEqual(filtered, [entries[0]])


if __name__ == "__main__":
    unittest.main()
