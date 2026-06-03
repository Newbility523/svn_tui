from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from svn_tui.config import PREVIEW_MAX_COLUMNS
from svn_tui.models import SvnStatusEntry
from svn_tui.services.preview import (
    PreviewCancelToken,
    PreviewDocument,
    PreviewMessage,
    build_preview_document,
    read_preview_line,
)


class PreviewTests(unittest.TestCase):
    def test_missing_file_returns_message(self) -> None:
        entry = SvnStatusEntry(Path("missing.txt").resolve(), "M", " ", "M")

        preview = build_preview_document(entry, PreviewCancelToken())

        self.assertIsInstance(preview, PreviewMessage)
        assert isinstance(preview, PreviewMessage)
        self.assertIn("does not exist", preview.message)

    def test_binary_file_returns_message(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "binary.dat"
            path.write_bytes(b"hello\0world")
            entry = SvnStatusEntry(path, "M", " ", "M")

            preview = build_preview_document(entry, PreviewCancelToken())

        self.assertIsInstance(preview, PreviewMessage)
        assert isinstance(preview, PreviewMessage)
        self.assertIn("binary file", preview.message)

    def test_read_preview_line_truncates_long_display_lines(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "long.txt"
            path.write_text("x" * (PREVIEW_MAX_COLUMNS + 20), encoding="utf-8")
            entry = SvnStatusEntry(path, "M", " ", "M")

            preview = build_preview_document(entry, PreviewCancelToken())
            self.assertIsInstance(preview, PreviewDocument)
            assert isinstance(preview, PreviewDocument)
            line = read_preview_line(preview, 0)

        self.assertEqual(line, f"{'x' * PREVIEW_MAX_COLUMNS} ...")


if __name__ == "__main__":
    unittest.main()
