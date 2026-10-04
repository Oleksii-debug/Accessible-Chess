from __future__ import annotations

import unittest

from acs.book_index import BookIndex
from acs.bookdocument import (
    MAX_BOOK_BLOCK_ID_CHARS,
    MAX_BOOK_SOURCE_ANCHOR_CHARS,
    BookDocument,
    BookDocumentError,
    Heading,
    Paragraph,
)


class BookDocumentIdentityBoundsCurrentTests(unittest.TestCase):
    def test_exact_identifier_bounds_fit_durable_target_keys(self) -> None:
        by_block = BookDocument(
            title="Block id",
            blocks=[
                Heading(
                    text="Heading",
                    block_id="b" * MAX_BOOK_BLOCK_ID_CHARS,
                )
            ],
        )
        block_target = BookIndex(by_block).entries[0].target.key
        self.assertEqual(len(block_target), 4096)
        self.assertTrue(block_target.startswith("block:"))

        by_source = BookDocument(
            title="Source anchor",
            blocks=[
                Paragraph(
                    text="Paragraph",
                    source_anchor="s" * MAX_BOOK_SOURCE_ANCHOR_CHARS,
                )
            ],
        )
        source_target = BookIndex(by_source).entries[0].target.key
        self.assertEqual(len(source_target), 4096)
        self.assertTrue(source_target.startswith("source:"))

    def test_one_character_identifier_overflow_fails_at_model_boundary(self) -> None:
        with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
            Heading(
                text="Heading",
                block_id="b" * (MAX_BOOK_BLOCK_ID_CHARS + 1),
            )
        with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
            Paragraph(
                text="Paragraph",
                source_anchor="s" * (MAX_BOOK_SOURCE_ANCHOR_CHARS + 1),
            )

    def test_identifier_subclass_is_rejected_before_hooks(self) -> None:
        class HostileIdentifier(str):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("identifier subclass len must not execute")

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("identifier subclass strip must not execute")

        with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
            Heading(text="Heading", block_id=HostileIdentifier("safe"))
        self.assertFalse(HostileIdentifier.touched)

    def test_mutated_identifier_is_revalidated_before_export(self) -> None:
        heading = Heading(text="Heading", block_id="stable")
        document = BookDocument(title="Book", blocks=[heading])
        heading.block_id = "b" * (MAX_BOOK_BLOCK_ID_CHARS + 1)

        with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
            document.as_dict()

    def test_from_dict_uses_the_same_identifier_boundary(self) -> None:
        with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
            BookDocument.from_dict(
                {
                    "schema_version": 1,
                    "title": "Book",
                    "blocks": [
                        {
                            "kind": "Heading",
                            "text": "Heading",
                            "level": 1,
                            "block_id": "b" * (MAX_BOOK_BLOCK_ID_CHARS + 1),
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
