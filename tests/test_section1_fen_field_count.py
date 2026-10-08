from __future__ import annotations

import unittest

from acs.chesscore import Board


class Section1FenFieldCountTests(unittest.TestCase):
    def test_canonical_six_field_fen_is_unchanged(self) -> None:
        fen = Board.START
        self.assertEqual(Board(fen).fen(), fen)

    def test_explicit_legacy_four_field_fen_still_normalizes_counters(self) -> None:
        legacy = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        self.assertEqual(Board(legacy).fen(), Board.START)

    def test_five_field_fen_is_rejected_instead_of_inventing_fullmove(self) -> None:
        malformed = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 17"
        with self.assertRaisesRegex(ValueError, "4 або 6 полів"):
            Board(malformed)

    def test_five_field_rejection_is_atomic_for_live_board_and_history(self) -> None:
        board = Board()
        board.push_text("e4")
        before = (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

        malformed = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 17"
        with self.assertRaisesRegex(ValueError, "4 або 6 полів"):
            board.set_fen(malformed)

        self.assertEqual(
            (
                board.fen(),
                tuple(board.undo_stack),
                tuple(board.redo_stack),
                board.last_move,
            ),
            before,
        )


if __name__ == "__main__":
    unittest.main()
