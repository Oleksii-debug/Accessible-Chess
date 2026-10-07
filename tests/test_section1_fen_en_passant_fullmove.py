from __future__ import annotations

import unittest

from acs.chesscore import Board


class Section1FenEnPassantFullmoveTests(unittest.TestCase):
    @staticmethod
    def _snapshot(board: Board):
        return (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

    def test_white_to_move_en_passant_requires_fullmove_at_least_two_atomically(self) -> None:
        board = Board()
        board.push_text("e4")
        board.push_text("e5")
        board.undo()
        before = self._snapshot(board)

        malformed = "7k/8/8/3p4/8/8/8/K7 w - d6 0 1"
        with self.assertRaisesRegex(ValueError, "fullmove.*2"):
            board.set_fen(malformed)

        self.assertEqual(self._snapshot(board), before)

    def test_white_to_move_en_passant_accepts_fullmove_two_or_later(self) -> None:
        cases = (
            "7k/8/8/3p4/8/8/8/K7 w - d6 0 2",
            "7k/8/8/3p4/8/8/8/K7 w - d6 0 37",
        )
        for fen in cases:
            with self.subTest(fen=fen):
                self.assertEqual(Board(fen).fen(), fen)

    def test_legacy_four_field_white_to_move_en_passant_remains_supported(self) -> None:
        source = "7k/8/8/3p4/8/8/8/K7 w - d6"
        self.assertEqual(Board(source).fen(), source + " 0 1")

    def test_black_to_move_en_passant_still_allows_fullmove_one(self) -> None:
        fen = "7k/8/8/8/4P3/8/8/K7 b - e3 0 1"
        self.assertEqual(Board(fen).fen(), fen)

    def test_non_en_passant_white_to_move_fullmove_one_remains_valid(self) -> None:
        fen = "7k/8/8/8/8/8/8/K7 w - - 0 1"
        self.assertEqual(Board(fen).fen(), fen)


if __name__ == "__main__":
    unittest.main()
