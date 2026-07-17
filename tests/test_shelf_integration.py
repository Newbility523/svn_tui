from __future__ import annotations

import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from svn_tui.services.shelves import ShelfService, ShelfStore
from svn_tui.services.svn import SvnClient
from tools import svn_fixture


@unittest.skipUnless(
    shutil.which("svn") and shutil.which("svnadmin"),
    "svn and svnadmin are required for Shelf integration tests",
)
class ShelfIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_shelve_and_unshelve_real_working_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_root = root / "fixture"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = svn_fixture.main(
                    ["--root", str(fixture_root), "state", "shelf-ready"]
                )
            self.assertEqual(exit_code, 0)

            wc = fixture_root / "wc"
            client = SvnClient(wc)
            service = ShelfService(client, ShelfStore(root / "shelf-data"))
            entries = await client.status()
            selected = [
                entry
                for entry in entries
                if entry.path.name in {"app.py", "guide.md"}
            ]
            self.assertEqual(len(selected), 2)
            saved_contents = {
                entry.path: entry.path.read_text(encoding="utf-8")
                for entry in selected
            }

            checkpoint = await service.new_shelf(selected)
            self.assertEqual(checkpoint.kind, "checkpoint")
            self.assertEqual(checkpoint.paths, ("docs/guide.md", "src/app.py"))
            for path, content in saved_contents.items():
                self.assertEqual(path.read_text(encoding="utf-8"), content)

            shelved, revert_output = await service.shelve_selected(
                checkpoint.shelf_name,
                selected,
                note="switch tasks",
            )
            self.assertEqual(shelved.kind, "shelve")
            self.assertIn("Reverted", revert_output)
            self.assertEqual(await client.status_paths(list(saved_contents)), [])

            unrelated = wc / "README.txt"
            unrelated_original = unrelated.read_text(encoding="utf-8")
            unrelated.write_text(
                unrelated_original + "unrelated local change\n",
                encoding="utf-8",
            )
            selected[0].path.write_text("temporary overwrite\n", encoding="utf-8")
            conflicts = await service.unshelve_conflicts(checkpoint)
            self.assertEqual([entry.path for entry in conflicts], [selected[0].path])

            patch_output = await service.unshelve(checkpoint, allow_overwrite=True)
            self.assertIn("U", patch_output)
            for path, content in saved_contents.items():
                self.assertEqual(path.read_text(encoding="utf-8"), content)
            self.assertEqual(
                unrelated.read_text(encoding="utf-8"),
                unrelated_original + "unrelated local change\n",
            )
            self.assertEqual(
                [version.number for version in await service.list_versions(checkpoint.shelf_name)],
                [1, 2],
            )


if __name__ == "__main__":
    unittest.main()
