from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile

from acs.format_factory_cli import run_offline_private_factory


BOOK = b"# Chapter one\n\nAccessible chess text.\n\n# Chapter two\n\nMore reading.\n"


class FactoryOfflineCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.source = self.dir / "book.md"
        self.source.write_bytes(BOOK)
        self.out = self.dir / "private"
        self.out.mkdir()

    def call(self, *extra: str) -> tuple[int, str, str]:
        stdout, stderr = StringIO(), StringIO()
        arguments = [
            "--source", str(self.source.absolute()),
            "--output-dir", str(self.out.absolute()),
            "--language", "en",
            "--format", "html",
            *extra,
        ]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = run_offline_private_factory(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_private_success_writes_manifest_and_verified_html(self) -> None:
        code, text, error = self.call()
        self.assertEqual(code, 0, error)
        self.assertIn("PARTIAL PREVIEW", text)
        names = sorted(path.name for path in self.out.iterdir())
        self.assertEqual(len(names), 2)
        html = next(self.out.glob("*.html"))
        manifest_file = next(self.out.glob("*.manifest.json"))
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertFalse(manifest["public_release_approved"])
        self.assertEqual(manifest["status"], "PARTIAL_PREVIEW_ONLY")
        self.assertEqual(manifest["outputs"][0]["sha256"], sha256(html.read_bytes()).hexdigest())
        self.assertIn(b"Accessible chess text", html.read_bytes())

    def test_path_replacement_between_stat_and_open_is_refused(self) -> None:
        """A changed pathname must not silently import replacement book bytes."""
        replacement = self.dir / "replacement.md"
        replacement.write_bytes(b"# Different book\n\nPrivate content.\n")
        original_open = os.open
        source_path = self.source

        def replace_before_open(path, flags, *args, **kwargs):
            if Path(path) == source_path:
                os.replace(replacement, source_path)
            return original_open(path, flags, *args, **kwargs)

        with mock.patch("acs.format_factory_cli.os.open", side_effect=replace_before_open):
            code, _, error = self.call()
        self.assertEqual(code, 2)
        self.assertFalse(list(self.out.iterdir()))
        self.assertNotIn("Private content", error)
        self.assertNotIn(str(source_path), error)

    def test_repeat_does_not_overwrite_or_delete_existing_results(self) -> None:
        self.assertEqual(self.call()[0], 0)
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        self.assertEqual(self.call()[0], 2)
        self.assertEqual({p.name: p.read_bytes() for p in self.out.iterdir()}, before)

    def test_unqualified_input_refused_without_creation(self) -> None:
        self.source.write_bytes(b"%PDF-1.7\nunqualified")
        code, text, error = self.call()
        self.assertEqual(code, 2)
        self.assertFalse(list(self.out.iterdir()))
        self.assertNotIn(str(self.source), error)

    def test_select_only_explicit_chapter_and_keep_private(self) -> None:
        code, _, error = self.call(
            "--scope", "chapters", "--ranges", "2", "--chapter-heading-level", "1"
        )
        self.assertEqual(code, 0, error)
        data = next(self.out.glob("*.html")).read_text()
        self.assertIn("More reading.", data)
        self.assertNotIn("Accessible chess text.", data)

    def test_invalid_scope_fails_without_partial_files(self) -> None:
        code, _, _ = self.call("--scope", "chapters", "--ranges", "999", "--chapter-heading-level", "1")
        self.assertEqual(code, 2)
        self.assertFalse(list(self.out.iterdir()))

    def test_epub3_and_docx_bundle_is_source_verified_and_private(self) -> None:
        code, _, error = self.call(
            "--format", "epub3", "--format", "docx",
            "--modified-utc", "2026-10-10T00:00:00Z"
        )
        self.assertEqual(code, 0, error)
        with ZipFile(next(self.out.glob("*.epub"))) as zf:
            self.assertEqual(zf.read("mimetype"), b"application/epub+zip")
        with ZipFile(next(self.out.glob("*.docx"))) as zf:
            self.assertIn(b"Accessible chess text", zf.read("word/document.xml"))
        manifest = json.loads(next(self.out.glob("*.manifest.json")).read_text())
        self.assertEqual(len(manifest["outputs"]), 3)
        self.assertEqual({x["format"] for x in manifest["outputs"]}, {"html", "epub3", "docx"})

    def test_missing_package_timestamp_fails_closed(self) -> None:
        code, _, _ = self.call("--format", "docx")
        self.assertEqual(code, 2)
        self.assertFalse(list(self.out.iterdir()))


if __name__ == "__main__":
    unittest.main()
