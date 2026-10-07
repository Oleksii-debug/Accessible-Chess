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

    def test_explicit_white_to_move_en_passant_rejects_fullmove_one_atomically(self) -> None:
        board = Board()
        board.push_text("e4")
        board.push_text("e5")
        board.undo()
        before = self._snapshot(board)

        malformed = "7k/8/8/4p3/8/8/8/K7 w - e6 0 1"
        with self.assertRaisesRegex(ValueError, "fullmove.*2"):
            board.set_fen(malformed)

        self.assertEqual(self._snapshot(board), before)

    def test_explicit_consistent_en_passant_fullmove_values_remain_accepted(self) -> None:
        cases = (
            "7k/8/8/4p3/8/8/8/K7 w - e6 0 2",
            "7k/8/8/4p3/8/8/8/K7 w - e6 0 17",
            "7k/8/8/8/4P3/8/8/K7 b - e3 0 1",
            "7k/8/8/8/4P3/8/8/K7 b - e3 0 17",
        )
        for fen in cases:
            with self.subTest(fen=fen):
                self.assertEqual(Board(fen).fen(), fen)

    def test_four_field_en_passant_defaults_to_minimum_consistent_fullmove(self) -> None:
        cases = (
            (
                "7k/8/8/4p3/8/8/8/K7 w - e6",
                "7k/8/8/4p3/8/8/8/K7 w - e6 0 2",
            ),
            (
                "7k/8/8/8/4P3/8/8/K7 b - e3",
                "7k/8/8/8/4P3/8/8/K7 b - e3 0 1",
            ),
        )
        for abbreviated, canonical in cases:
            with self.subTest(fen=abbreviated):
                board = Board(abbreviated)
                self.assertEqual(board.fen(), canonical)
                self.assertEqual(Board(board.fen()).fen(), canonical)

    def test_ordinary_four_field_and_six_field_defaults_are_unchanged(self) -> None:
        four = "7k/8/8/8/8/8/8/K7 w - -"
        self.assertEqual(Board(four).fen(), four + " 0 1")

        six = "7k/8/8/8/8/8/8/K7 w - - 0 1"
        self.assertEqual(Board(six).fen(), six)


if __name__ == "__main__":
    unittest.main()
