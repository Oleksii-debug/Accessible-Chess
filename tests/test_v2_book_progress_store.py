from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.book_progress_store import (
    BOOK_PROGRESS_STORE_SCHEMA_VERSION,
    MAX_BOOK_KEY_CHARS,
    MAX_BOOK_SNAPSHOT_BYTES,
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
)
from acs.bookdocument import BookDocument, Diagram, Heading, Paragraph
from acs.bookreader import BookReader


WHITE_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


class BookProgressStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "state" / "book-progress.json"
        self.store = BookProgressStore(self.path)

    @staticmethod
    def original_document(*, source_name: str | None = None) -> BookDocument:
        return BookDocument(
            "Semantic book",
            source_name=source_name,
            blocks=[
                Heading(text="Chapter", level=1, block_id="chapter"),
                Paragraph(text="Introduction", block_id="intro"),
                Diagram(
                    fen=WHITE_FEN,
                    caption="Critical position",
                    alt_text="White king e2; black king h1.",
                    block_id="diagram",
                    source_anchor="chapter-1-diagram",
                ),
                Paragraph(text="After the position", block_id="after"),
            ],
        )

    @staticmethod
    def reordered_document() -> BookDocument:
        return BookDocument(
            "Semantic book revised",
            blocks=[
                Heading(text="Chapter", level=1, block_id="chapter"),
                Paragraph(text="Inserted", block_id="inserted"),
                Paragraph(text="After the position", block_id="after"),
                Diagram(
                    fen=WHITE_FEN,
                    caption="Critical position",
                    alt_text="White king e2; black king h1.",
                    block_id="diagram",
                    source_anchor="chapter-1-diagram",
                ),
                Paragraph(text="Introduction", block_id="intro"),
            ],
        )

    def test_close_reopen_restores_exact_location_and_named_bookmark(self) -> None:
        document = self.original_document()
        reader = BookReader(document)
        reader.go_to(2)
        reader.save_return_point("analysis-return")
        reader.go_to(3)

        saved = self.store.save("library:book-42", reader)
        self.assertEqual(saved["current_target"], "block:after")

        # Simulate application close: discard the original reader and build a
        # fresh BookDocument/BookReader from persisted state only.
        reopened = self.store.restore("library:book-42", self.original_document())
        self.assertEqual(reopened.location().block_id, "after")
        restored = reopened.restore_return_point("analysis-return")
        self.assertEqual(restored.block_id, "diagram")
        self.assertEqual(restored.position_fen, WHITE_FEN)

    def test_reopen_uses_semantic_identity_after_source_preserving_reorder(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(2)
        reader.save_return_point("board-return")
        reader.go_to(3)
        self.store.save("content:stable-id", reader)

        reopened = self.store.restore("content:stable-id", self.reordered_document())
        self.assertEqual(reopened.location().block_id, "after")
        self.assertEqual(reopened.location().index, 2)
        returned = reopened.restore_return_point("board-return")
        self.assertEqual(returned.block_id, "diagram")
        self.assertEqual(returned.index, 3)

    def test_source_path_is_not_persisted(self) -> None:
        private_source = r"C:\Users\Oleksii\Documents\private-book.epub"
        document = self.original_document(source_name=private_source)
        reader = BookReader(document)
        reader.go_to(2)
        self.store.save("source-sha256:012345", reader)

        persisted = self.path.read_text(encoding="utf-8")
        self.assertNotIn("Users", persisted)
        self.assertNotIn("Oleksii", persisted)
        self.assertNotIn("private-book.epub", persisted)
        self.assertNotIn(private_source, persisted)

    def test_multiple_books_are_isolated_and_removal_is_atomic(self) -> None:
        first = BookReader(self.original_document())
        first.go_to(1)
        second = BookReader(self.original_document())
        second.go_to(3)
        self.store.save("book:first", first)
        self.store.save("book:second", second)

        self.assertTrue(self.store.has("book:first"))
        self.assertTrue(self.store.has("book:second"))
        self.assertEqual(self.store.restore("book:first", self.original_document()).index, 1)
        self.assertEqual(self.store.restore("book:second", self.original_document()).index, 3)

        self.assertTrue(self.store.remove("book:first"))
        self.assertFalse(self.store.has("book:first"))
        self.assertTrue(self.store.has("book:second"))
        self.assertFalse(self.store.remove("book:first"))

    def test_missing_entry_does_not_fall_back_to_another_book(self) -> None:
        self.store.save("book:one", BookReader(self.original_document()))
        with self.assertRaisesRegex(LookupError, "No saved reading progress"):
            self.store.restore("book:two", self.original_document())

    def test_corrupt_store_fails_closed_and_save_does_not_overwrite_it(self) -> None:
        self.path.parent.mkdir(parents=True)
        original = b'{"schema_version":1,"entries":'
        self.path.write_bytes(original)

        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.save("book:one", BookReader(self.original_document()))
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(self.path.read_bytes(), original)

    def test_duplicate_json_object_keys_fail_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            '{"schema_version":1,"schema_version":1,"entries":{}}',
            encoding="utf-8",
        )
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)

    def test_unknown_or_future_store_schema_fails_closed(self) -> None:
        cases = [
            {"schema_version": 2, "entries": {}},
            {"schema_version": True, "entries": {}},
            {"schema_version": 1, "entries": {}, "future": 1},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(BookProgressStoreError):
                    self.store.has("book:one")

    def test_invalid_book_keys_fail_before_any_file_mutation(self) -> None:
        reader = BookReader(self.original_document())
        bad = ["", " book", "book ", "line\nbreak", "x" * (MAX_BOOK_KEY_CHARS + 1)]
        for key in bad:
            with self.subTest(key=key):
                with self.assertRaises(BookProgressStoreError):
                    self.store.save(key, reader)
        with self.assertRaises(BookProgressStoreError):
            self.store.save(123, reader)  # type: ignore[arg-type]
        self.assertFalse(self.path.exists())

    def test_snapshot_resource_limit_is_checked_before_restore(self) -> None:
        huge_target = "x" * (MAX_BOOK_SNAPSHOT_BYTES + 1)
        payload = {
            "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
            "entries": {
                "book:huge": {
                    "schema_version": 2,
                    "current_target": huge_target,
                    "return_points": {},
                    "fallback_digests": {},
                }
            },
        }
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:huge")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.RESOURCE_LIMIT)

    def test_failed_atomic_replace_preserves_previous_valid_snapshot(self) -> None:
        reader = BookReader(self.original_document())
        reader.go_to(1)
        self.store.save("book:atomic", reader)
        original_bytes = self.path.read_bytes()

        reader.go_to(3)
        with mock.patch("acs.book_progress_store.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.store.save("book:atomic", reader)
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(self.store.restore("book:atomic", self.original_document()).index, 1)

    @unittest.skipIf(os.name == "nt", "Windows symlink creation requires environment-specific privileges")
    def test_symlink_store_is_rejected(self) -> None:
        real = Path(self.tempdir.name) / "real.json"
        real.write_text('{"schema_version":1,"entries":{}}', encoding="utf-8")
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(real)
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.IO_FAILURE)

    def test_storage_errors_do_not_put_local_path_in_exception_message(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"not json")
        with self.assertRaises(BookProgressStoreError) as caught:
            self.store.has("book:one")
        message = str(caught.exception)
        self.assertNotIn(str(self.path), message)
        self.assertNotIn(self.tempdir.name, message)


if __name__ == "__main__":
    unittest.main()
