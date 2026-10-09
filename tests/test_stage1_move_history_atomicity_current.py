import unittest
from unittest.mock import patch

from acs.chesscore import Board
from acs.webapp import AccessibleChessAPI


class Stage1MoveHistoryAtomicityTests(unittest.TestCase):
    def _snapshot(self, api: AccessibleChessAPI) -> dict[str, object]:
        return {
            "board": api.board,
            "fen": api.board.fen(),
            "undo_stack": list(api.board.undo_stack),
            "redo_stack": list(api.board.redo_stack),
            "last_move": api.board.last_move,
            "start_fen": api.start_fen,
            "sans": list(api.sans),
            "move_sides": list(api.move_sides),
            "redo_meta": list(api.redo_meta),
            "selected_source": api.selected_source,
            "review_history": api.review_history,
            "review_tree": api.review_history.export_tree(),
            "review_adapter": api.review_adapter,
            "live_history_node": api.live_history_node,
        }

    def _assert_unchanged(
        self,
        api: AccessibleChessAPI,
        before: dict[str, object],
    ) -> None:
        self.assertIs(api.board, before["board"])
        self.assertEqual(api.board.fen(), before["fen"])
        self.assertEqual(api.board.undo_stack, before["undo_stack"])
        self.assertEqual(api.board.redo_stack, before["redo_stack"])
        self.assertEqual(api.board.last_move, before["last_move"])
        self.assertEqual(api.start_fen, before["start_fen"])
        self.assertEqual(api.sans, before["sans"])
        self.assertEqual(api.move_sides, before["move_sides"])
        self.assertEqual(api.redo_meta, before["redo_meta"])
        self.assertEqual(api.selected_source, before["selected_source"])
        self.assertIs(api.review_history, before["review_history"])
        self.assertEqual(api.review_history.export_tree(), before["review_tree"])
        self.assertIs(api.review_adapter, before["review_adapter"])
        self.assertEqual(api.live_history_node, before["live_history_node"])

    def _assert_live_alignment(self, api: AccessibleChessAPI) -> None:
        view = api.review_adapter.current()
        self.assertEqual(view.node_id, api.live_history_node)
        self.assertEqual(view.fen, api.board.fen())
        self.assertEqual(api.review_history.cursor_node_id, api.live_history_node)
        self.assertEqual(len(api.sans), len(api.move_sides))
        self.assertEqual(view.ply, len(api.sans))

    def test_move_history_clone_failure_after_candidate_move_keeps_live_state(self):
        api = AccessibleChessAPI(lang="uk")
        before = self._snapshot(api)

        with patch(
            "acs.webapp.ReviewHistory.from_tree",
            side_effect=RuntimeError("private cloned-history failure"),
        ):
            result = api.make_move("e4")

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Не вдалося синхронізувати дошку та історію ходів.",
        )
        self.assertNotIn("private cloned-history failure", result["announcement"])
        self._assert_unchanged(api, before)

    def test_move_presenter_failure_after_candidate_append_keeps_live_state(self):
        api = AccessibleChessAPI(lang="en")
        before = self._snapshot(api)

        with patch(
            "acs.webapp.ReviewPresentationAdapter",
            side_effect=RuntimeError("private move presenter failure"),
        ):
            result = api.make_move("e4")

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not synchronize the board and move history.",
        )
        self.assertNotIn("private move presenter failure", result["announcement"])
        self._assert_unchanged(api, before)

    def test_board_activation_commit_failure_preserves_selected_piece_and_game(self):
        api = AccessibleChessAPI(lang="en")
        selected = api.activate_square("e2")
        self.assertTrue(selected["ok"])
        self.assertEqual(selected["selectedSquare"], "e2")
        before = self._snapshot(api)

        with patch(
            "acs.webapp.ReviewPresentationAdapter",
            side_effect=RuntimeError("private board presenter failure"),
        ):
            result = api.activate_square("e4")

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not synchronize the board and move history.",
        )
        self.assertNotIn("private board presenter failure", result["announcement"])
        self._assert_unchanged(api, before)

    def test_undo_presenter_failure_keeps_committed_move_and_history(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        before = self._snapshot(api)

        with patch(
            "acs.webapp.ReviewPresentationAdapter",
            side_effect=RuntimeError("private undo presenter failure"),
        ):
            result = api.undo()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Не вдалося синхронізувати дошку та історію ходів.",
        )
        self.assertNotIn("private undo presenter failure", result["announcement"])
        self._assert_unchanged(api, before)

    def test_redo_presenter_failure_keeps_undone_state_and_redo_available(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.undo()["ok"])
        before = self._snapshot(api)

        with patch(
            "acs.webapp.ReviewPresentationAdapter",
            side_effect=RuntimeError("private redo presenter failure"),
        ):
            result = api.redo()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not synchronize the board and move history.",
        )
        self.assertNotIn("private redo presenter failure", result["announcement"])
        self._assert_unchanged(api, before)

    def test_redo_san_mismatch_fails_closed_without_clearing_live_redo(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.undo()["ok"])
        before = self._snapshot(api)

        with patch.object(Board, "redo", return_value="d4"):
            result = api.redo()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not synchronize the board and move history.",
        )
        self._assert_unchanged(api, before)

    def test_move_undo_redo_success_keeps_board_history_and_metadata_aligned(self):
        api = AccessibleChessAPI(lang="en")
        initial_fen = api.board.fen()

        played = api.make_move("e4")
        self.assertTrue(played["ok"])
        played_fen = api.board.fen()
        self.assertNotEqual(played_fen, initial_fen)
        self.assertEqual(api.sans, ["e4"])
        self.assertEqual(api.move_sides, ["w"])
        self.assertEqual(api.redo_meta, [])
        self._assert_live_alignment(api)

        undone = api.undo()
        self.assertTrue(undone["ok"])
        self.assertEqual(api.board.fen(), initial_fen)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.move_sides, [])
        self.assertEqual(api.redo_meta, [("e4", "w")])
        self._assert_live_alignment(api)

        redone = api.redo()
        self.assertTrue(redone["ok"])
        self.assertEqual(api.board.fen(), played_fen)
        self.assertEqual(api.sans, ["e4"])
        self.assertEqual(api.move_sides, ["w"])
        self.assertEqual(api.redo_meta, [])
        self._assert_live_alignment(api)


if __name__ == "__main__":
    unittest.main()
