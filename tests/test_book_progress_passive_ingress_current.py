from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Heading
from acs.bookreader import BookReader


class BookProgressPassiveIngressCurrentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name) / "not-created-yet"
        self.store = BookProgressStore(self.root / "book-progress.json")

    @staticmethod
    def _document() -> BookDocument:
        return BookDocument(
            "Progress ingress",
            blocks=[Heading(text="Chapter", level=1, block_id="chapter")],
        )

    def test_save_rejects_reader_subclass_before_snapshot_or_storage_access(self) -> None:
        class HostileReader(BookReader):
            touched = False

            def snapshot(self):
                type(self).touched = True
                raise AssertionError("rejected BookReader subclass snapshot must not execute")

        reader = HostileReader(self._document())

        with self.assertRaisesRegex(TypeError, "^reader must be BookReader$"):
            self.store.save("book:hostile-reader", reader)

        self.assertFalse(HostileReader.touched)
        self.assertFalse(self.root.exists())

    def test_restore_boundaries_reject_document_subclass_before_storage_access(self) -> None:
        class HostileDocument(BookDocument):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {"as_dict", "blocks", "warnings", "title"}:
                    type(self).touched = True
                    raise AssertionError("rejected BookDocument subclass must remain passive")
                return super().__getattribute__(name)

        document = HostileDocument(
            "Hostile restore",
            blocks=[Heading(text="Chapter", level=1, block_id="chapter")],
        )
        HostileDocument.armed = True

        operations = (
            self.store.restore,
            self.store.restore_primary,
            self.store.validated_recovery_revisions,
            self.store.validated_backup_revision,
        )
        for operation in operations:
            HostileDocument.touched = False
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(TypeError, "^document must be BookDocument$"):
                    operation("book:hostile-document", document)
                self.assertFalse(HostileDocument.touched)
                self.assertFalse(self.root.exists())

    def test_exact_reader_and_document_keep_round_trip_semantics(self) -> None:
        document = self._document()
        reader = BookReader(document)
        saved = self.store.save("book:exact", reader)

        self.assertEqual(saved["current_target"], "block:chapter")
        restored = self.store.restore("book:exact", self._document())
        self.assertEqual(restored.location().block_id, "chapter")


if __name__ == "__main__":
    unittest.main()
