from __future__ import annotations

import unittest

from acs.book_index import BookIndex
from acs.bookdocument import BookDocument, Heading, Paragraph
from acs.bookreader import BookReader


class BookDocumentIngressPassiveCurrentTests(unittest.TestCase):
    @staticmethod
    def _canonical_document() -> BookDocument:
        return BookDocument(
            "Passive ingress",
            blocks=[
                Heading(
                    text="Chapter",
                    level=1,
                    block_id="chapter",
                    source_anchor="chapter:1",
                ),
                Paragraph(
                    text="Readable paragraph",
                    block_id="paragraph",
                    source_anchor="chapter:1:p1",
                ),
            ],
        )

    def test_reader_and_index_reject_document_subclass_before_attribute_hook(self) -> None:
        class HostileBookDocument(BookDocument):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {
                    "as_dict",
                    "blocks",
                    "warnings",
                    "title",
                }:
                    type(self).touched = True
                    raise AssertionError(
                        f"BookDocument subclass attribute hook must not execute: {name}"
                    )
                return super().__getattribute__(name)

        hostile = HostileBookDocument(
            "Hostile",
            blocks=[
                Heading(
                    text="Chapter",
                    level=1,
                    block_id="chapter",
                    source_anchor="chapter:1",
                )
            ],
        )
        HostileBookDocument.armed = True

        for factory in (BookReader, BookIndex):
            HostileBookDocument.touched = False
            with self.subTest(factory=factory.__name__):
                with self.assertRaisesRegex(
                    TypeError,
                    "^document must be a BookDocument$",
                ):
                    factory(hostile)
                self.assertFalse(HostileBookDocument.touched)

    def test_reader_and_index_reject_overridden_as_dict_before_method_lookup(self) -> None:
        class HostileBookDocument(BookDocument):
            armed = False
            touched = False

            def as_dict(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile as_dict must not execute")
                return super().as_dict()

        hostile = HostileBookDocument(
            "Hostile method",
            blocks=[
                Paragraph(
                    text="Paragraph",
                    block_id="paragraph",
                    source_anchor="p1",
                )
            ],
        )
        HostileBookDocument.armed = True

        for factory in (BookReader, BookIndex):
            HostileBookDocument.touched = False
            with self.subTest(factory=factory.__name__):
                with self.assertRaises(TypeError):
                    factory(hostile)
                self.assertFalse(HostileBookDocument.touched)

    def test_restore_snapshot_rejects_document_subclass_before_snapshot_hooks(self) -> None:
        class HostileBookDocument(BookDocument):
            pass

        class HostileSnapshot(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("snapshot must not be read for rejected document")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("snapshot must not be iterated for rejected document")

        document = HostileBookDocument("Rejected restore document")
        snapshot = HostileSnapshot()

        with self.assertRaisesRegex(TypeError, "^document must be a BookDocument$"):
            BookReader.restore_snapshot(document, snapshot)

        self.assertFalse(HostileSnapshot.touched)

    def test_exact_canonical_document_keeps_reader_and_index_semantics(self) -> None:
        document = self._canonical_document()

        reader = BookReader(document)
        index = BookIndex(document)

        location = reader.location()
        self.assertEqual(location.index, 0)
        self.assertEqual(location.kind, "Heading")
        self.assertEqual(location.block_id, "chapter")

        self.assertEqual(len(index.entries), 2)
        self.assertEqual(index.entries[0].target.block_id, "chapter")
        self.assertEqual(index.entries[1].target.block_id, "paragraph")

    def test_reader_keeps_live_revision_binding_for_exact_document(self) -> None:
        document = self._canonical_document()
        reader = BookReader(document)

        document.blocks[1].text = "Changed after indexing"

        with self.assertRaisesRegex(
            RuntimeError,
            "changed after BookReader creation",
        ):
            reader.location()


if __name__ == "__main__":
    unittest.main()
