from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.input_limits import MAX_FEN_CHARS
from acs.position_editor import PositionState, PositionValidationError, standard_position
from acs.webapp import AccessibleChessAPI


def _oversized_fen() -> str:
    prefix = "8/8/8/8/8/8/8/K6k w - - 0 "
    return prefix + ("9" * (MAX_FEN_CHARS - len(prefix) + 1))


class FenInputBudgetCurrentTests(unittest.TestCase):
    def test_shared_budget_rejects_before_unbounded_fen_parsing(self) -> None:
        oversized = _oversized_fen()

        self.assertEqual(len(oversized), MAX_FEN_CHARS + 1)

        with self.assertRaisesRegex(ValueError, "FEN занадто довгий"):
            Board(oversized)
        with self.assertRaisesRegex(PositionValidationError, "FEN is too long"):
            PositionState.from_fen(oversized)

    def test_board_rejection_preserves_exact_live_state_and_history(self) -> None:
        board = Board()
        board.push_text("e4")
        before_fen = board.fen()
        before_undo = list(board.undo_stack)
        before_redo = list(board.redo_stack)
        before_last_move = board.last_move

        with self.assertRaisesRegex(ValueError, "FEN занадто довгий"):
            board.set_fen(_oversized_fen())

        self.assertEqual(board.fen(), before_fen)
        self.assertEqual(board.undo_stack, before_undo)
        self.assertEqual(board.redo_stack, before_redo)
        self.assertEqual(board.last_move, before_last_move)

    def test_position_editor_rejection_keeps_existing_immutable_position(self) -> None:
        position = standard_position()
        before = position.to_fen()

        with self.assertRaisesRegex(PositionValidationError, "FEN is too long"):
            PositionState.from_fen(_oversized_fen())

        self.assertEqual(position.to_fen(), before)

    def test_stage1_rejection_preserves_board_and_review_history(self) -> None:
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        board = api.board
        history = api.review_history
        adapter = api.review_adapter
        before_fen = api.board.fen()
        before_start = api.start_fen
        before_sans = list(api.sans)
        before_sides = list(api.move_sides)
        before_redo = list(api.redo_meta)
        before_cursor = api.live_history_node

        result = api.set_fen(_oversized_fen())

        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "FEN занадто довгий")
        self.assertIs(api.board, board)
        self.assertIs(api.review_history, history)
        self.assertIs(api.review_adapter, adapter)
        self.assertEqual(api.board.fen(), before_fen)
        self.assertEqual(api.start_fen, before_start)
        self.assertEqual(api.sans, before_sans)
        self.assertEqual(api.move_sides, before_sides)
        self.assertEqual(api.redo_meta, before_redo)
        self.assertEqual(api.live_history_node, before_cursor)

    def test_ordinary_exact_fen_semantics_remain_unchanged(self) -> None:
        fen = "8/8/8/8/8/8/8/K6k b - - 17 42"

        board = Board(fen)
        editor = PositionState.from_fen(fen)

        self.assertEqual(board.fen(), fen)
        self.assertEqual(editor.to_fen(), fen)


if __name__ == "__main__":
    unittest.main()
