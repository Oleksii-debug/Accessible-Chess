from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.notation import NotationError, format_san


class Section1SanInternalWhitespaceTests(unittest.TestCase):
    @staticmethod
    def _snapshot(board: Board):
        return (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

    def test_internal_whitespace_is_not_silently_repaired_into_legal_san(self) -> None:
        for token in ("e 4", "N f3"):
            with self.subTest(token=token):
                with self.assertRaises(NotationError):
                    format_san(token, "san")

                board = Board()
                before = self._snapshot(board)
                with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
                    board.parse_move(token)
                self.assertEqual(self._snapshot(board), before)

                with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
                    board.push_text(token)
                self.assertEqual(self._snapshot(board), before)

    def test_outer_whitespace_remains_the_shared_bounded_input_convenience(self) -> None:
        board = Board()
        self.assertEqual(format_san("  e4  ", "san"), "e4")
        move = board.parse_move("  e4  ")
        self.assertEqual(board.san(move), "e4")
        self.assertEqual(board.push_text("  e4  "), "e4")


if __name__ == "__main__":
    unittest.main()
