from __future__ import annotations

import unittest
from unittest.mock import patch

from acs import book_webview_projection
from acs.bookdocument import (
    MAX_BOOK_LIST_ITEMS,
    MAX_BOOK_LIST_TOTAL_CHARS,
    MAX_BOOK_PGN_CHARS,
    MAX_BOOK_TEXT_FIELD_CHARS,
    MAX_BOOK_WARNING_TOTAL_CHARS,
    BookDocumentError,
    Exercise,
    Game,
    ListBlock,
    Paragraph,
    Position,
    VariationTree,
)
from acs.pgn_roundtrip import MAX_PGN_TEXT_CHARS


FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


class BookDocumentScalarBoundsCurrentTests(unittest.TestCase):
    def test_canonical_visible_and_pgn_caps_match_product_authorities(self) -> None:
        self.assertEqual(
            MAX_BOOK_TEXT_FIELD_CHARS,
            book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS,
        )
        self.assertEqual(
            MAX_BOOK_LIST_TOTAL_CHARS,
            book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS,
        )
        self.assertEqual(
            MAX_BOOK_LIST_ITEMS,
            book_webview_projection._MAX_BOOK_LIST_ITEMS,
        )
        self.assertEqual(MAX_BOOK_PGN_CHARS, MAX_PGN_TEXT_CHARS)
        self.assertEqual(
            MAX_BOOK_WARNING_TOTAL_CHARS,
            book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS,
        )

    def test_warning_aggregate_rejects_before_whitespace_scan(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_WARNING_TOTAL_CHARS", 3):
            with self.assertRaisesRegex(
                BookDocumentError,
                "warning text exceeds the canonical aggregate limit",
            ):
                # If whitespace classification ran first this would report the
                # non-empty-string error instead of the aggregate resource bound.
                from acs.bookdocument import BookDocument

                BookDocument("Book", warnings=["    "])

    def test_warning_aggregate_exact_limit_is_accepted_and_exported(self) -> None:
        from acs.bookdocument import BookDocument

        with patch("acs.bookdocument.MAX_BOOK_WARNING_TOTAL_CHARS", 2):
            document = BookDocument("Book", warnings=["a", "b"])
            self.assertEqual(document.as_dict()["warnings"], ["a", "b"])

    def test_warning_subclass_is_rejected_before_length_or_strip_hooks(self) -> None:
        from acs.bookdocument import BookDocument

        class HostileWarning(str):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("warning length hook must not execute")

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("warning strip hook must not execute")

        with self.assertRaises(BookDocumentError):
            BookDocument("Book", warnings=[HostileWarning("warning")])

        self.assertFalse(HostileWarning.touched)

    def test_visible_text_size_rejects_before_whitespace_scan(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_TEXT_FIELD_CHARS", 3):
            with self.assertRaisesRegex(
                BookDocumentError,
                "canonical text field limit",
            ):
                Paragraph(text="    ")

    def test_fen_size_rejects_before_board_validation(self) -> None:
        with (
            patch("acs.bookdocument.MAX_FEN_CHARS", 8),
            patch(
                "acs.bookdocument.Board",
                side_effect=AssertionError("oversized FEN must not reach Board"),
            ),
        ):
            with self.assertRaisesRegex(
                BookDocumentError,
                "canonical FEN input limit",
            ):
                Position(fen=FEN)

    def test_game_pgn_size_rejects_before_empty_text_scan(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_PGN_CHARS", 3):
            with self.assertRaisesRegex(
                BookDocumentError,
                "canonical PGN text limit",
            ):
                Game(pgn="    ", game_id=1)

    def test_variation_and_exercise_use_pgn_specific_not_visible_text_cap(self) -> None:
        # Keep valid FEN/visible fields inside their own envelope while making
        # the PGN deliberately larger than the visible-text ceiling.
        pgn = "x" * (len(FEN) + 1)
        with (
            patch("acs.bookdocument.MAX_BOOK_TEXT_FIELD_CHARS", len(FEN)),
            patch("acs.bookdocument.MAX_BOOK_PGN_CHARS", len(pgn)),
        ):
            variation = VariationTree(root_fen=FEN, pgn=pgn, title="Tree")
            exercise = Exercise(
                fen=FEN,
                prompt="Mate",
                solution_pgn=pgn,
            )

        self.assertEqual(variation.pgn, pgn)
        self.assertEqual(exercise.solution_pgn, pgn)

    def test_list_item_count_rejects_before_item_hooks(self) -> None:
        class HostileText(str):
            armed = False
            touched = False

            def __len__(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("over-count list must not inspect items")
                return super().__len__()

            def strip(self, *args, **kwargs):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("over-count list must not inspect items")
                return super().strip(*args, **kwargs)

        first = HostileText("one")
        second = HostileText("two")
        HostileText.armed = True

        with patch("acs.bookdocument.MAX_BOOK_LIST_ITEMS", 1):
            with self.assertRaisesRegex(BookDocumentError, "at most 1 items"):
                ListBlock(items=[first, second])

        self.assertFalse(HostileText.touched)

    def test_list_aggregate_rejects_before_required_text_scan(self) -> None:
        with (
            patch("acs.bookdocument.MAX_BOOK_LIST_TOTAL_CHARS", 0),
            patch(
                "acs.bookdocument._required_text",
                side_effect=AssertionError("over-budget list must not strip item"),
            ),
        ):
            with self.assertRaisesRegex(
                BookDocumentError,
                "canonical aggregate limit",
            ):
                ListBlock(items=["x"])

    def test_exact_scalar_and_list_limits_are_accepted(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_TEXT_FIELD_CHARS", 3):
            paragraph = Paragraph(text="abc")

        with patch("acs.bookdocument.MAX_BOOK_PGN_CHARS", 3):
            game = Game(pgn="e4*", title="ok")

        with (
            patch("acs.bookdocument.MAX_BOOK_LIST_ITEMS", 2),
            patch("acs.bookdocument.MAX_BOOK_LIST_TOTAL_CHARS", 2),
        ):
            list_block = ListBlock(items=["a", "b"])

        with (
            patch("acs.bookdocument.MAX_BOOK_TEXT_FIELD_CHARS", len(FEN)),
            patch("acs.bookdocument.MAX_FEN_CHARS", len(FEN)),
        ):
            position = Position(fen=FEN)

        self.assertEqual(paragraph.text, "abc")
        self.assertEqual(game.pgn, "e4*")
        self.assertEqual(list_block.items, ["a", "b"])
        self.assertEqual(position.fen, FEN)

    def test_one_unit_over_each_scalar_limit_fails_closed(self) -> None:
        with patch("acs.bookdocument.MAX_BOOK_TEXT_FIELD_CHARS", 3):
            with self.assertRaises(BookDocumentError):
                Paragraph(text="abcd")

        with patch("acs.bookdocument.MAX_BOOK_PGN_CHARS", 3):
            with self.assertRaises(BookDocumentError):
                Game(pgn="e4 *")

        with patch("acs.bookdocument.MAX_BOOK_LIST_TOTAL_CHARS", 2):
            with self.assertRaises(BookDocumentError):
                ListBlock(items=["a", "bb"])


if __name__ == "__main__":
    unittest.main()
