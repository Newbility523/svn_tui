from __future__ import annotations

import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from svn_tui.models import SvnStatusEntry
from svn_tui.services.shelves import (
    ShelfNameError,
    ShelfOperationError,
    ShelfOverwriteRequired,
    ShelfSelectionError,
    ShelfService,
    ShelfStore,
    validate_shelf_name,
    working_copy_fingerprint,
)
from svn_tui.shelf_models import WorkingCopyIdentity


PATCH = """Index: src/app.py
===================================================================
--- src/app.py\t(revision 5)
+++ src/app.py\t(working copy)
@@ -1 +1,2 @@
 base
+local
"""


def identity(root: Path) -> WorkingCopyIdentity:
    return WorkingCopyIdentity(
        wc_root=root.resolve(),
        repo_uuid="repo-uuid",
        repo_root_url="https://example.test/svn/project",
        target_relative_path="trunk",
        base_revision="5",
    )


class FakeSvnClient:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.identity = identity(root)
        self.reverted: list[list[Path]] = []
        self.applied: list[Path] = []
        self.current_status: list[SvnStatusEntry] = []
        self.fail_revert = False
        self.fail_patch = False
        self.diff_outputs = [PATCH]

    async def working_copy_identity(self) -> WorkingCopyIdentity:
        return self.identity

    def relative_working_copy_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    async def diff_paths(self, paths: list[Path]) -> str:
        self.diff_requested = paths
        return self.diff_outputs.pop(0) if len(self.diff_outputs) > 1 else self.diff_outputs[0]

    async def path_base_revisions(self, paths: list[Path]) -> dict[str, str]:
        return {self.relative_working_copy_path(path): "5" for path in paths}

    async def revert_paths(self, paths: list[Path]) -> str:
        self.reverted.append(paths)
        if self.fail_revert:
            raise subprocess.CalledProcessError(1, ["svn", "revert"], stderr="revert failed")
        return "Reverted paths"

    async def status_paths(self, paths: list[Path]) -> list[SvnStatusEntry]:
        self.status_requested = paths
        return self.current_status

    async def apply_patch(self, patch_path: Path) -> str:
        self.applied.append(patch_path)
        if self.fail_patch:
            raise subprocess.CalledProcessError(1, ["svn", "patch"], stderr="patch failed")
        return "U         src/app.py\n"


class ShelfStoreTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_isolates_working_copy_paths(self) -> None:
        first = identity(Path("first"))
        same = identity(Path("first"))
        second = identity(Path("second"))

        self.assertEqual(working_copy_fingerprint(first), working_copy_fingerprint(same))
        self.assertNotEqual(working_copy_fingerprint(first), working_copy_fingerprint(second))

    def test_shelf_name_rejects_unsafe_paths(self) -> None:
        for value in ("", "../other", "folder/name", ".hidden", "bad\0name"):
            with self.subTest(value=value), self.assertRaises(ShelfNameError):
                validate_shelf_name(value)

    def test_auto_name_collision_adds_numeric_suffix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixed = datetime(2026, 7, 16, 14, 30, 52, tzinfo=timezone.utc)
            store = ShelfStore(root / "data", now=lambda: fixed)
            wc_identity = identity(root / "wc")

            first = store.create_shelf_version(
                wc_identity,
                patch=PATCH,
                paths=["src/app.py"],
                status_summary={"src/app.py": "M"},
                path_revisions={"src/app.py": "5"},
            )
            second = store.create_shelf_version(
                wc_identity,
                patch=PATCH,
                paths=["src/app.py"],
                status_summary={"src/app.py": "M"},
                path_revisions={"src/app.py": "5"},
            )

            self.assertEqual(first.shelf_name, "shelf-20260716-143052")
            self.assertEqual(second.shelf_name, "shelf-20260716-143052-02")

    def test_versions_persist_with_patch_and_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ShelfStore(root / "data")
            wc_identity = identity(root / "wc")

            first = store.create_shelf_version(
                wc_identity,
                name="feature-a",
                patch=PATCH,
                paths=["src/app.py"],
                status_summary={"src/app.py": "M"},
                path_revisions={"src/app.py": "5"},
            )
            second = store.save_version(
                wc_identity,
                "feature-a",
                kind="shelve",
                note="ready to switch",
                patch=PATCH.replace("+local", "+second"),
                paths=["src/app.py"],
                status_summary={"src/app.py": "M"},
                path_revisions={"src/app.py": "5"},
            )

            shelves = store.list_shelves(wc_identity)
            versions = store.list_versions(wc_identity, "feature-a")

            self.assertEqual(first.label, "v001")
            self.assertEqual(second.label, "v002")
            self.assertEqual(second.kind, "shelve")
            self.assertEqual(second.note, "ready to switch")
            self.assertEqual(shelves[0].version_count, 2)
            self.assertEqual(shelves[0].latest_version, 2)
            self.assertEqual([version.number for version in versions], [1, 2])
            self.assertEqual(first.patch_path.read_text(encoding="utf-8"), PATCH)
            self.assertTrue((store.identity_root(wc_identity) / "identity.json").is_file())

    def test_export_and_delete_version_and_shelf(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ShelfStore(root / "data")
            wc_identity = identity(root / "wc")
            version = store.create_shelf_version(
                wc_identity,
                name="feature-a",
                patch=PATCH,
                paths=["src/app.py"],
                status_summary={"src/app.py": "M"},
                path_revisions={"src/app.py": "5"},
            )

            exported = store.export_patch(wc_identity, "feature-a", 1, root / "exports")
            self.assertEqual(exported.name, "feature-a-v001.diff")
            self.assertEqual(exported.read_text(encoding="utf-8"), PATCH)

            store.delete_version(wc_identity, "feature-a", version.number)
            self.assertEqual(store.list_versions(wc_identity, "feature-a"), [])
            store.delete_shelf(wc_identity, "feature-a")
            self.assertEqual(store.list_shelves(wc_identity), [])


class ShelfServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wc = self.root / "wc"
        (self.wc / "src").mkdir(parents=True)
        self.path = self.wc / "src" / "app.py"
        self.path.write_text("base\nlocal\n", encoding="utf-8")
        self.entry = SvnStatusEntry(self.path, "M", " ", "M")
        self.client = FakeSvnClient(self.wc)
        self.store = ShelfStore(self.root / "data")
        self.service = ShelfService(self.client, self.store)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    async def test_new_checkpoint_keeps_working_file(self) -> None:
        version = await self.service.new_shelf([self.entry], name="feature-a")

        self.assertEqual(version.kind, "checkpoint")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "base\nlocal\n")
        self.assertEqual(self.client.reverted, [])

    async def test_rejects_unversioned_and_binary_selection_before_diff(self) -> None:
        unversioned = SvnStatusEntry(self.path, "?", " ", "?")
        with self.assertRaises(ShelfSelectionError):
            await self.service.new_shelf([unversioned])

        self.path.write_bytes(b"text\0binary")
        with self.assertRaises(ShelfSelectionError):
            await self.service.new_shelf([self.entry])

    async def test_shelve_saves_before_revert_and_preserves_version_on_failure(self) -> None:
        await self.service.new_shelf([self.entry], name="feature-a")
        self.client.fail_revert = True

        with self.assertRaises(ShelfOperationError) as raised:
            await self.service.shelve_selected("feature-a", [self.entry])

        self.assertEqual(raised.exception.saved_version.label, "v002")
        self.assertTrue(raised.exception.saved_version.patch_path.is_file())
        self.assertEqual(len(self.client.reverted), 1)

    async def test_shelve_does_not_revert_when_working_copy_changes_after_save(self) -> None:
        await self.service.new_shelf([self.entry], name="feature-a")
        self.client.diff_outputs = [PATCH, PATCH + "\nexternal change\n"]

        with self.assertRaises(ShelfOperationError) as raised:
            await self.service.shelve_selected("feature-a", [self.entry])

        self.assertIn("working copy changed", str(raised.exception))
        self.assertEqual(self.client.reverted, [])
        self.assertEqual(len(await self.service.list_versions("feature-a")), 2)

    async def test_unshelve_refuses_overwrite_without_confirmation(self) -> None:
        version = await self.service.new_shelf([self.entry], name="feature-a")
        self.client.current_status = [self.entry]

        with self.assertRaises(ShelfOverwriteRequired):
            await self.service.unshelve(version)

        self.assertEqual(self.client.reverted, [])
        self.assertEqual(self.client.applied, [])

    async def test_unshelve_only_reverts_recorded_changed_paths_then_applies_patch(self) -> None:
        version = await self.service.new_shelf([self.entry], name="feature-a")
        self.client.current_status = [self.entry]

        output = await self.service.unshelve(version, allow_overwrite=True)

        self.assertEqual(self.client.status_requested, [self.path.resolve()])
        self.assertEqual(self.client.reverted, [[self.path]])
        self.assertEqual(self.client.applied, [version.patch_path])
        self.assertIn("src/app.py", output)

    async def test_unshelve_patch_failure_keeps_saved_patch(self) -> None:
        version = await self.service.new_shelf([self.entry], name="feature-a")
        self.client.fail_patch = True

        with self.assertRaises(ShelfOperationError) as raised:
            await self.service.unshelve(version)

        self.assertIn("saved patch was kept", str(raised.exception))
        self.assertTrue(version.patch_path.is_file())


if __name__ == "__main__":
    unittest.main()
