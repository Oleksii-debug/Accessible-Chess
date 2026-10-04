from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.chesscore import Board
from acs.input_limits import MAX_CHESS_MOVE_TEXT_CHARS
from acs.move_entry import MAX_MOVE_ENTRY_CHARS
from acs.position_editor import MAX_COORDINATE_POSITION_CHARS


class CanonicalMoveTextBudgetCurrentTests(unittest.TestCase):
    @staticmethod
    def _snapshot(board: Board):
        return (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

    def test_move_entry_and_core_share_the_same_effective_product_budget(self) -> None:
        self.assertEqual(MAX_CHESS_MOVE_TEXT_CHARS, 4096)
        self.assertEqual(
            MAX_MOVE_ENTRY_CHARS,
            min(MAX_COORDINATE_POSITION_CHARS, MAX_CHESS_MOVE_TEXT_CHARS),
        )

    def test_oversized_move_fails_before_normalization_or_legal_move_generation(self) -> None:
        board = Board()

        with (
            patch("acs.chesscore.MAX_CHESS_MOVE_TEXT_CHARS", 3),
            patch.object(
                board,
                "legal_moves",
                side_effect=AssertionError("oversized move must not generate legal moves"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Текст ходу занадто довгий"):
                board.parse_move(" e4 ")

    def test_oversized_push_text_is_atomic_with_existing_undo_redo_state(self) -> None:
        board = Board()
        board.push_text("e4")
        board.push_text("e5")
        board.undo()
        before = self._snapshot(board)

        with patch("acs.chesscore.MAX_CHESS_MOVE_TEXT_CHARS", 3):
            with self.assertRaisesRegex(ValueError, "Текст ходу занадто довгий"):
                board.push_text("    ")

        self.assertEqual(self._snapshot(board), before)

    def test_text_subclass_is_rejected_before_length_or_strip_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("move text subclass len must not execute")

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("move text subclass strip must not execute")

        board = Board()
        with self.assertRaisesRegex(ValueError, "Хід має бути текстом"):
            board.parse_move(HostileText("e4"))

        self.assertFalse(HostileText.touched)

    def test_exact_budget_can_normalize_to_valid_san(self) -> None:
        board = Board()
        with patch("acs.chesscore.MAX_CHESS_MOVE_TEXT_CHARS", 4):
            move = board.parse_move(" e4 ")

        self.assertEqual(board.san(move), "e4")

    def test_one_character_over_budget_rejects_even_when_trimmed_move_would_be_valid(self) -> None:
        board = Board()
        with patch("acs.chesscore.MAX_CHESS_MOVE_TEXT_CHARS", 4):
            with self.assertRaisesRegex(ValueError, "Текст ходу занадто довгий"):
                board.parse_move("  e4 ")

    def test_supported_move_input_forms_remain_unchanged(self) -> None:
        board = Board()
        self.assertEqual(board.push_text("e4"), "e4")
        self.assertEqual(board.push_text("e7e5"), "e5")
        self.assertEqual(board.push_text("Nf3"), "Nf3")

        null_board = Board()
        self.assertEqual(null_board.push_text("--"), "--")

    def test_promotion_and_castling_inputs_remain_supported(self) -> None:
        promotion = Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        self.assertEqual(promotion.push_text("a7a8q"), "a8=Q+")

        castle = Board("4k2r/8/8/8/8/8/8/4K2R w Kk - 0 1")
        self.assertEqual(castle.push_text("0-0"), "O-O")


if __name__ == "__main__":
    unittest.main()
