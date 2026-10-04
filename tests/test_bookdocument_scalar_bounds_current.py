from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.bookdocument import (
    BookDocument,
    BookDocumentError,
    Game,
    Heading,
    ListBlock,
    Paragraph,
    Position,
)


FEN = "8/8/8/8/8/8/4P3/4K2k w - - 0 1"


class BookDocumentScalarBoundsCurrentTests(unittest.TestCase):
    def test_text_bound_precedes_whitespace_scan(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TEXT_CHARS", 4):
            with self.assertRaisesRegex(BookDocumentError, "supported bound"):
                Paragraph(text="     ")
            self.assertEqual(Paragraph(text="text").text, "text")

    def test_identifier_bound_matches_semantic_target_budget(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_IDENTIFIER_CHARS", 4):
            with self.assertRaises(BookDocumentError):
                Heading(text="H", block_id="abcde")
            accepted = Heading(text="H", block_id="abcd", source_anchor="wxyz")
            self.assertEqual(accepted.block_id, "abcd")
            self.assertEqual(accepted.source_anchor, "wxyz")

    def test_fen_bound_precedes_split_and_canonical_board_parse(self) -> None:
        with patch("acs.bookdocument.MAX_FEN_CHARS", len(FEN)):
            self.assertEqual(Position(fen=FEN).fen, FEN)
            with self.assertRaisesRegex(BookDocumentError, "supported bound"):
                Position(fen=FEN + "0")

    def test_list_item_count_and_aggregate_text_are_bounded_atomically(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_LIST_ITEMS", 2):
            with self.assertRaisesRegex(BookDocumentError, "bounded"):
                ListBlock(items=["a", "b", "c"])

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TEXT_CHARS", 4):
            with self.assertRaisesRegex(BookDocumentError, "text bound"):
                ListBlock(items=["aa", "aaa"])
            accepted = ListBlock(items=["aa", "aa"])
            self.assertEqual(accepted.items, ["aa", "aa"])

    def test_game_pgn_and_warning_aggregate_use_canonical_text_budget(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TEXT_CHARS", 4):
            with self.assertRaisesRegex(BookDocumentError, "supported bound"):
                Game(pgn="1. e4")

            with self.assertRaisesRegex(BookDocumentError, "warnings"):
                BookDocument(title="Book", warnings=["aa", "aaa"])

            accepted = BookDocument(title="Book", warnings=["aa", "aa"])
            self.assertEqual(accepted.warnings, ["aa", "aa"])

    def test_export_revalidates_mutated_scalar_bounds(self) -> None:
        paragraph = Paragraph(text="ok")
        document = BookDocument(title="Book", blocks=[paragraph])
        paragraph.text = "oversize"

        with patch("acs.bookdocument.MAX_BOOK_DOCUMENT_TEXT_CHARS", 4):
            with self.assertRaises(BookDocumentError):
                document.as_dict()


if __name__ == "__main__":
    unittest.main()
