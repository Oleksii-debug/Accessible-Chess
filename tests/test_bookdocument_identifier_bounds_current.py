from __future__ import annotations

import unittest
from unittest.mock import patch

from acs import book_index
from acs.bookdocument import (
    MAX_BOOK_BLOCK_ID_CHARS,
    MAX_BOOK_SOURCE_ANCHOR_CHARS,
    BookDocument,
    BookDocumentError,
    Heading,
    Paragraph,
)


class BookDocumentIdentifierBoundsCurrentTests(unittest.TestCase):
    def test_identifier_caps_exactly_fit_durable_target_key_contract(self) -> None:
        self.assertEqual(
            MAX_BOOK_BLOCK_ID_CHARS + len("block:"),
            book_index._MAX_BOOK_TARGET_KEY_CHARS,
        )
        self.assertEqual(
            MAX_BOOK_SOURCE_ANCHOR_CHARS + len("source:"),
            book_index._MAX_BOOK_TARGET_KEY_CHARS,
        )

    def test_block_id_and_source_anchor_accept_exact_bounds_and_reject_one_over(self) -> None:
        with (
            patch("acs.bookdocument.MAX_BOOK_BLOCK_ID_CHARS", 4),
            patch("acs.bookdocument.MAX_BOOK_SOURCE_ANCHOR_CHARS", 3),
        ):
            accepted = Heading(
                text="Heading",
                block_id="abcd",
                source_anchor="xyz",
            )
            self.assertEqual(accepted.block_id, "abcd")
            self.assertEqual(accepted.source_anchor, "xyz")

            with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
                Heading(text="Heading", block_id="abcde")
            with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
                Heading(text="Heading", source_anchor="wxyz")

    def test_identifier_subclass_is_rejected_before_length_or_strip_hooks(self) -> None:
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

    def test_identifier_normalization_stays_inside_raw_bound(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_BLOCK_ID_CHARS", 3):
            heading = Heading(text="Heading", block_id=" a ")

        self.assertEqual(heading.block_id, "a")

    def test_from_dict_enforces_identifier_bound_before_indexing(self) -> None:
        payload = {
            "title": "Book",
            "blocks": [
                {
                    "kind": "Paragraph",
                    "text": "Readable",
                    "source_anchor": "abcd",
                }
            ],
        }

        with patch("acs.bookdocument.MAX_BOOK_SOURCE_ANCHOR_CHARS", 3):
            with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
                BookDocument.from_dict(payload)

    def test_export_revalidates_mutated_identifier_bound(self) -> None:
        paragraph = Paragraph(text="Readable", block_id="ok")
        document = BookDocument("Book", blocks=[paragraph])
        paragraph.block_id = "oversize"

        with patch("acs.bookdocument.MAX_BOOK_BLOCK_ID_CHARS", 4):
            with self.assertRaisesRegex(BookDocumentError, "identifier limit"):
                document.as_dict()


if __name__ == "__main__":
    unittest.main()
