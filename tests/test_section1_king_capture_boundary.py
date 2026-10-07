from __future__ import annotations

import unittest

from acs.chesscore import Board, Move, parse_sq


class Section1KingCaptureBoundaryTests(unittest.TestCase):
    @staticmethod
    def _snapshot(board: Board):
        return (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

    def test_slider_attack_remains_check_but_never_becomes_king_capture_move(self) -> None:
        # Structurally representable but historically impossible: black is
        # already in check while it is White's turn.  The attack relation is
        # still meaningful for analysis/error handling, but legal move
        # generation must never publish a move that captures the black king.
        board = Board("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
        king_square = parse_sq("e8")
        before = self._snapshot(board)

        self.assertTrue(board.attacked(king_square, "w"))
        self.assertTrue(board.in_check("b"))
        self.assertFalse(any(move.to == king_square for move in board.legal_moves()))

        with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
            board.parse_move("Rxe8")
        self.assertEqual(self._snapshot(board), before)

        with self.assertRaisesRegex(ValueError, "Нелегальний координатний хід"):
            board.parse_move("e2e8")
        self.assertEqual(self._snapshot(board), before)

        with self.assertRaisesRegex(ValueError, "Нелегальний хід"):
            board.push(Move(parse_sq("e2"), king_square))
        self.assertEqual(self._snapshot(board), before)

    def test_knight_and_pawn_cannot_capture_opposing_king(self) -> None:
        cases = (
            (
                Board("8/8/8/5k2/8/4N3/8/4K3 w - - 0 1"),
                "e3",
                "f5",
            ),
            (
                Board("8/8/8/3k4/4P3/8/8/4K3 w - - 0 1"),
                "e4",
                "d5",
            ),
        )
        for board, source, king in cases:
            with self.subTest(source=source, king=king):
                source_square = parse_sq(source)
                king_square = parse_sq(king)
                before = self._snapshot(board)
                self.assertTrue(board.attacked(king_square, "w"))
                self.assertFalse(
                    any(
                        move.frm == source_square and move.to == king_square
                        for move in board.legal_moves()
                    )
                )
                self.assertEqual(self._snapshot(board), before)

    def test_normal_check_and_checkmate_san_paths_are_unchanged(self) -> None:
        board = Board()
        for token in ("f3", "e5", "g4"):
            board.push_text(token)

        mate = board.parse_move("Qh4#")
        self.assertEqual(board.san(mate), "Qh4#")
        self.assertEqual(board.push(mate), "Qh4#")
        self.assertEqual(board.legal_moves(), [])


if __name__ == "__main__":
    unittest.main()
