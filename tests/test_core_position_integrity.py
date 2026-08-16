from __future__ import annotations

import unittest

from acs.chesscore import Board, Move, parse_sq


class CorePositionIntegrityTests(unittest.TestCase):
    """Regression coverage for editor/FEN positions at the legality boundary."""

    def test_valid_double_push_ep_fen_survives_normal_stage1_flow(self) -> None:
        board = Board()
        start = board.fen()
        self.assertEqual("e4", board.push_text("e4"))
        e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        self.assertEqual(e4, board.fen())
        self.assertEqual(e4, Board(e4).fen())
        self.assertEqual("e4", board.undo())
        self.assertEqual(start, board.fen())
        self.assertEqual("e4", board.redo())
        self.assertEqual(e4, board.fen())

    def test_en_passant_requires_real_double_push_state_and_is_reversible(self) -> None:
        initial = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"
        board = Board(initial)
        move = board.parse_move("exd6")
        self.assertTrue(move.en_passant)
        self.assertEqual("exd6", board.push(move))
        after = "4k3/8/3P4/8/8/8/8/4K3 b - - 0 2"
        self.assertEqual(after, board.fen())
        self.assertEqual("exd6", board.undo())
        self.assertEqual(initial, board.fen())
        self.assertEqual("exd6", board.redo())
        self.assertEqual(after, board.fen())

    def test_malformed_ep_editor_fens_are_atomic_against_live_history(self) -> None:
        board = Board()
        board.push_text("e4")
        board.push_text("e5")
        board.undo()
        snapshot = (
            board.fen(),
            board.turn,
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )
        malformed = (
            # Correct target rank/turn but no white pawn on e4.
            "4k3/8/8/8/8/8/8/4K3 b - e3 0 1",
            # Target is occupied, so it cannot be an en-passant landing square.
            "4k3/8/8/8/4P3/4N3/8/4K3 b - e3 0 1",
            # Pawn is on e4, but its double-push origin e2 is still occupied.
            "4k3/8/8/8/4P3/8/4P3/4K3 b - e3 0 1",
            # White-to-move form requires the black pawn behind d6.
            "4k3/8/8/4P3/8/8/8/4K3 w - d6 0 2",
        )
        for fen in malformed:
            with self.subTest(fen=fen):
                with self.assertRaises(ValueError):
                    board.set_fen(fen, clear_history=False)
                self.assertEqual(
                    (
                        board.fen(),
                        board.turn,
                        tuple(board.undo_stack),
                        tuple(board.redo_stack),
                        board.last_move,
                    ),
                    snapshot,
                )

    def test_move_generation_never_captures_enemy_king(self) -> None:
        board = Board("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
        e2 = parse_sq("e2")
        e8 = parse_sq("e8")
        self.assertFalse(any(m.frm == e2 and m.to == e8 for m in board.pseudo_moves()))
        self.assertFalse(any(m.frm == e2 and m.to == e8 for m in board.legal_moves()))

        snapshot = (board.fen(), tuple(board.undo_stack), tuple(board.redo_stack), board.last_move)
        with self.assertRaises(ValueError):
            board.push_text("e2e8")
        self.assertEqual(
            (board.fen(), tuple(board.undo_stack), tuple(board.redo_stack), board.last_move),
            snapshot,
        )

        # Defense in depth: even a fabricated internal Move cannot remove a king.
        with self.assertRaises(ValueError):
            board._apply(Move(e2, e8))
        self.assertEqual(
            (board.fen(), tuple(board.undo_stack), tuple(board.redo_stack), board.last_move),
            snapshot,
        )


if __name__ == "__main__":
    unittest.main()
