from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.book_epub_import import MAX_EPUB_TOTAL_UNCOMPRESSED_BYTES
from acs.bookdocument import (
    MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS,
    BookDocument,
    BookDocumentError,
    Paragraph,
)


class BookDocumentTotalTextBudgetCurrentTests(unittest.TestCase):
    def test_total_budget_covers_widest_supported_epub_envelope_with_headroom(self) -> None:
        self.assertGreaterEqual(
            MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS,
            2 * MAX_EPUB_TOTAL_UNCOMPRESSED_BYTES,
        )

    def test_exact_total_boundary_is_accepted(self) -> None:
        # title (1) + paragraph text (2) = 3. Structural block kind is not
        # semantic payload text and therefore does not consume the budget.
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 3):
            document = BookDocument("B", blocks=[Paragraph(text="ab")])
            self.assertEqual(document.as_dict()["blocks"][0]["text"], "ab")

    def test_one_character_over_total_boundary_fails_closed(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 3):
            with self.assertRaisesRegex(
                BookDocumentError,
                "text exceeds the canonical aggregate limit",
            ):
                BookDocument("B", blocks=[Paragraph(text="abc")])

    def test_metadata_warnings_and_identifiers_share_the_same_budget(self) -> None:
        # title (1) + author (1) + warning (1) + block id (2) + text (1) = 6.
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 6):
            document = BookDocument(
                "B",
                author="A",
                warnings=["w"],
                blocks=[Paragraph(text="x", block_id="id")],
            )
            self.assertEqual(document.author, "A")

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 5):
            with self.assertRaisesRegex(
                BookDocumentError,
                "text exceeds the canonical aggregate limit",
            ):
                BookDocument(
                    "B",
                    author="A",
                    warnings=["w"],
                    blocks=[Paragraph(text="x", block_id="id")],
                )

    def test_from_dict_stops_before_later_blocks_after_budget_overflow(self) -> None:
        payload = {
            "schema_version": 1,
            "title": "B",
            "blocks": [
                {"kind": "Paragraph", "text": "aa"},
                object(),
            ],
        }
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 2):
            with self.assertRaisesRegex(
                BookDocumentError,
                "text exceeds the canonical aggregate limit",
            ):
                BookDocument.from_dict(payload)

    def test_invalid_metadata_fails_before_block_materialization(self) -> None:
        class HostileText(str):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("metadata subclass length hook must not execute")

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("metadata subclass strip hook must not execute")

        payload = {
            "schema_version": 1,
            "title": HostileText("Book"),
            "blocks": [object()],
        }
        with self.assertRaisesRegex(BookDocumentError, "Book title"):
            BookDocument.from_dict(payload)
        self.assertFalse(HostileText.touched)

    def test_mutated_live_document_is_revalidated_before_export(self) -> None:
        paragraph = Paragraph(text="a")
        document = BookDocument("B", blocks=[paragraph])
        paragraph.text = "ab"

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 2):
            with self.assertRaisesRegex(
                BookDocumentError,
                "text exceeds the canonical aggregate limit",
            ):
                document.as_dict()

    def test_append_total_overflow_is_atomic(self) -> None:
        document = BookDocument("B", blocks=[Paragraph(text="a")])
        addition = Paragraph(text="bb")

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 3):
            with self.assertRaisesRegex(
                BookDocumentError,
                "text exceeds the canonical aggregate limit",
            ):
                document.append(addition)

        self.assertEqual(len(document.blocks), 1)
        self.assertEqual(document.blocks[0].text, "a")

    def test_extend_total_overflow_is_atomic(self) -> None:
        document = BookDocument("B")
        additions = [Paragraph(text="a"), Paragraph(text="bbb")]

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 4):
            with self.assertRaisesRegex(
                BookDocumentError,
                "text exceeds the canonical aggregate limit",
            ):
                document.extend(additions)

        self.assertEqual(document.blocks, [])

    def test_export_revalidation_accepts_exact_current_total(self) -> None:
        document = BookDocument(
            "B",
            source_name="S",
            warnings=["w"],
            blocks=[Paragraph(text="x")],
        )
        # title + source_name + warning + paragraph = 4.
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TOTAL_TEXT_CHARS", 4):
            payload = document.as_dict()
        self.assertEqual(payload["source_name"], "S")
        self.assertEqual(payload["warnings"], ["w"])


if __name__ == "__main__":
    unittest.main()
