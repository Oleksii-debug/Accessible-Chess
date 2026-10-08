from __future__ import annotations

import unittest

from acs.chesscore import Board


class Section1FenEnPassantHalfmoveTests(unittest.TestCase):
    @staticmethod
    def _snapshot(board: Board):
        return (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

    def test_en_passant_target_requires_zero_halfmove_for_both_sides(self) -> None:
        board = Board()
        board.push_text("e4")
        board.push_text("e5")
        board.undo()
        before = self._snapshot(board)

        malformed = (
            # Black's preceding e7-e5 double push is represented correctly,
            # but a pawn move must reset the halfmove clock.
            "7k/8/8/4p3/8/8/8/K7 w - e6 1 2",
            # Same invariant after White's preceding e2-e4 double push.
            "7k/8/8/8/4P3/8/8/K7 b - e3 9 1",
        )
        for fen in malformed:
            with self.subTest(fen=fen):
                with self.assertRaisesRegex(ValueError, "halfmove.*0"):
                    board.set_fen(fen)
                self.assertEqual(self._snapshot(board), before)

    def test_zero_halfmove_en_passant_provenance_remains_accepted(self) -> None:
        cases = (
            "7k/8/8/4p3/8/8/8/K7 w - e6 0 2",
            "7k/8/8/8/4P3/8/8/K7 b - e3 0 1",
        )
        for fen in cases:
            with self.subTest(fen=fen):
                self.assertEqual(Board(fen).fen(), fen)

    def test_positive_halfmove_without_en_passant_remains_valid(self) -> None:
        fen = "7k/8/8/8/8/8/8/K7 w - - 17 23"
        self.assertEqual(Board(fen).fen(), fen)


if __name__ == "__main__":
    unittest.main()
