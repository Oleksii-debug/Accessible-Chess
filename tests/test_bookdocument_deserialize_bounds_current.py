from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.bookdocument import (
    MAX_BOOK_DOCUMENT_BLOCKS,
    MAX_BOOK_DOCUMENT_WARNINGS,
    BookDocument,
    BookDocumentError,
    BookDocumentErrorCode,
    Paragraph,
    block_from_dict,
)
from acs.book_epub_import import MAX_EPUB_WARNINGS
from acs.book_html_import import MAX_HTML_BLOCKS, MAX_HTML_WARNINGS
from acs.book_text_import import MAX_TEXT_BLOCKS, MAX_TEXT_WARNINGS


class BookDocumentDeserializeBoundsCurrentTests(unittest.TestCase):
    def test_canonical_document_caps_cover_supported_importer_caps(self) -> None:
        self.assertGreaterEqual(MAX_BOOK_DOCUMENT_BLOCKS, MAX_TEXT_BLOCKS)
        self.assertGreaterEqual(MAX_BOOK_DOCUMENT_BLOCKS, MAX_HTML_BLOCKS)
        self.assertGreaterEqual(MAX_BOOK_DOCUMENT_WARNINGS, MAX_TEXT_WARNINGS)
        self.assertGreaterEqual(MAX_BOOK_DOCUMENT_WARNINGS, MAX_HTML_WARNINGS)
        self.assertGreaterEqual(MAX_BOOK_DOCUMENT_WARNINGS, MAX_EPUB_WARNINGS)

    def test_top_level_field_count_fails_before_key_materialization(self) -> None:
        class HostileKey(str):
            armed = False
            touched = False

            def __hash__(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("oversized document must not hash hostile key")
                return super().__hash__()

            def __eq__(self, other):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("oversized document must not compare hostile key")
                return super().__eq__(other)

        hostile = HostileKey("extra")
        payload = {"title": "Book", hostile: "value"}
        HostileKey.armed = True

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_FIELDS", 1):
            with self.assertRaises(BookDocumentError) as caught:
                BookDocument.from_dict(payload)

        self.assertEqual(caught.exception.code, BookDocumentErrorCode.UNKNOWN_FIELD)
        self.assertFalse(HostileKey.touched)

    def test_block_field_count_fails_before_key_iteration_or_hashing(self) -> None:
        class HostileKey(str):
            armed = False
            touched = False

            def __hash__(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("oversized block must not hash hostile key")
                return super().__hash__()

            def __eq__(self, other):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("oversized block must not compare hostile key")
                return super().__eq__(other)

        hostile = HostileKey("extra")
        payload = {"kind": "Paragraph", hostile: "value"}
        HostileKey.armed = True

        with patch("acs.bookdocument._MAX_BOOK_BLOCK_FIELDS", 1):
            with self.assertRaises(BookDocumentError) as caught:
                block_from_dict(payload)

        self.assertEqual(caught.exception.code, BookDocumentErrorCode.UNKNOWN_FIELD)
        self.assertFalse(HostileKey.touched)

    def test_from_dict_rejects_too_many_blocks_before_block_deserialization(self) -> None:
        class HostileBlock(dict):
            armed = False
            touched = False

            def __iter__(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("over-budget blocks must not be inspected")
                return super().__iter__()

            def get(self, *args, **kwargs):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("over-budget blocks must not be inspected")
                return super().get(*args, **kwargs)

        first = HostileBlock({"kind": "Paragraph", "text": "one"})
        second = HostileBlock({"kind": "Paragraph", "text": "two"})
        HostileBlock.armed = True

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_BLOCKS", 1):
            with self.assertRaises(BookDocumentError) as caught:
                BookDocument.from_dict(
                    {"title": "Book", "blocks": [first, second]}
                )

        self.assertEqual(caught.exception.code, BookDocumentErrorCode.INVALID_FIELD)
        self.assertFalse(HostileBlock.touched)

    def test_from_dict_rejects_too_many_warnings_before_text_hooks(self) -> None:
        class HostileWarning(str):
            armed = False
            touched = False

            def strip(self, *args, **kwargs):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("over-budget warnings must not be inspected")
                return super().strip(*args, **kwargs)

        first = HostileWarning("one")
        second = HostileWarning("two")
        HostileWarning.armed = True

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_WARNINGS", 1):
            with self.assertRaises(BookDocumentError) as caught:
                BookDocument.from_dict(
                    {"title": "Book", "warnings": [first, second]}
                )

        self.assertEqual(caught.exception.code, BookDocumentErrorCode.INVALID_FIELD)
        self.assertFalse(HostileWarning.touched)

    def test_constructor_rejects_over_budget_blocks_before_block_validation(self) -> None:
        first = Paragraph(text="one")
        second = Paragraph(text="two")

        with (
            patch("acs.bookdocument.MAX_BOOK_DOCUMENT_BLOCKS", 1),
            patch.object(
                Paragraph,
                "as_dict",
                side_effect=AssertionError("over-budget constructor must not inspect blocks"),
            ),
        ):
            with self.assertRaises(BookDocumentError):
                BookDocument("Book", blocks=[first, second])

    def test_export_validation_rejects_corrupted_over_budget_state_before_block_scan(self) -> None:
        book = BookDocument("Book", blocks=[Paragraph(text="one")])
        book.blocks.append(Paragraph(text="two"))

        with (
            patch("acs.bookdocument.MAX_BOOK_DOCUMENT_BLOCKS", 1),
            patch.object(
                Paragraph,
                "as_dict",
                side_effect=AssertionError("over-budget export must not inspect blocks"),
            ),
        ):
            with self.assertRaises(BookDocumentError):
                book.as_dict()

    def test_append_at_limit_is_atomic(self) -> None:
        book = BookDocument("Book")
        before = list(book.blocks)
        new_block = Paragraph(text="new")

        with (
            patch("acs.bookdocument.MAX_BOOK_DOCUMENT_BLOCKS", 0),
            patch.object(
                Paragraph,
                "as_dict",
                side_effect=AssertionError("overflow append must not validate rejected block"),
            ),
        ):
            with self.assertRaises(BookDocumentError):
                book.append(new_block)

        self.assertEqual(book.blocks, before)

    def test_extend_consumes_only_one_item_beyond_remaining_capacity_and_is_atomic(self) -> None:
        book = BookDocument("Book", blocks=[Paragraph(text="existing")])
        before = list(book.blocks)
        consumed: list[int] = []

        def additions():
            for index in range(3):
                consumed.append(index)
                if index == 2:
                    raise AssertionError("bounded extend must not request a third item")
                yield Paragraph(text=f"p{index}")

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_BLOCKS", 2):
            with self.assertRaises(BookDocumentError):
                book.extend(additions())

        self.assertEqual(consumed, [0, 1])
        self.assertEqual(book.blocks, before)

    def test_exact_patched_block_and_warning_limits_are_accepted(self) -> None:
        payload = {
            "title": "Book",
            "warnings": ["one", "two"],
            "blocks": [
                {"kind": "Paragraph", "text": "one"},
                {"kind": "Paragraph", "text": "two"},
            ],
        }

        with (
            patch("acs.bookdocument.MAX_BOOK_DOCUMENT_BLOCKS", 2),
            patch("acs.bookdocument.MAX_BOOK_DOCUMENT_WARNINGS", 2),
        ):
            document = BookDocument.from_dict(payload)
            exported = document.as_dict()

        self.assertEqual(len(exported["blocks"]), 2)
        self.assertEqual(exported["warnings"], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
