import unittest
from unittest.mock import patch

from acs.webapp import AccessibleChessAPI


VALID_CUSTOM_FEN = "4k3/8/8/8/8/8/8/3QK3 b - - 0 1"


class Stage1FenHistoryAtomicityTests(unittest.TestCase):
    def _live_snapshot(self, api: AccessibleChessAPI) -> dict[str, object]:
        return {
            "board": api.board,
            "fen": api.board.fen(),
            "start_fen": api.start_fen,
            "sans": list(api.sans),
            "move_sides": list(api.move_sides),
            "redo_meta": list(api.redo_meta),
            "selected_source": api.selected_source,
            "review_history": api.review_history,
            "review_adapter": api.review_adapter,
            "live_history_node": api.live_history_node,
        }

    def _assert_snapshot_unchanged(
        self,
        api: AccessibleChessAPI,
        before: dict[str, object],
    ) -> None:
        self.assertIs(api.board, before["board"])
        self.assertEqual(api.board.fen(), before["fen"])
        self.assertEqual(api.start_fen, before["start_fen"])
        self.assertEqual(api.sans, before["sans"])
        self.assertEqual(api.move_sides, before["move_sides"])
        self.assertEqual(api.redo_meta, before["redo_meta"])
        self.assertEqual(api.selected_source, before["selected_source"])
        self.assertIs(api.review_history, before["review_history"])
        self.assertIs(api.review_adapter, before["review_adapter"])
        self.assertEqual(api.live_history_node, before["live_history_node"])

    def test_success_replaces_board_and_all_live_history_state(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.undo()["ok"])
        self.assertTrue(api.redo_meta)
        self.assertTrue(api.board.redo_stack)

        result = api.set_fen(VALID_CUSTOM_FEN)

        self.assertTrue(result["ok"])
        self.assertEqual(result["announcement"], "FEN завантажено.")
        self.assertEqual(api.board.fen(), VALID_CUSTOM_FEN)
        self.assertEqual(api.start_fen, VALID_CUSTOM_FEN)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.move_sides, [])
        self.assertEqual(api.redo_meta, [])
        self.assertIsNone(api.selected_source)
        self.assertEqual(api.board.undo_stack, [])
        self.assertEqual(api.board.redo_stack, [])
        self.assertIsNone(api.board.last_move)
        self.assertEqual(api.review_history.cursor_node_id, api.live_history_node)
        self.assertEqual(len(api.review_history.tree_nodes()), 1)
        self.assertEqual(api.review_adapter.current().fen, VALID_CUSTOM_FEN)
        self.assertEqual(api.review_adapter.current().ply, 0)

    def test_history_construction_failure_preserves_live_state_and_is_sanitized(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        before = self._live_snapshot(api)

        with patch(
            "acs.webapp.ReviewHistory",
            side_effect=RuntimeError("private history implementation detail"),
        ):
            result = api.set_fen(VALID_CUSTOM_FEN)

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Не вдалося підготувати історію FEN-позиції.",
        )
        self.assertNotIn("private history implementation detail", result["announcement"])
        self._assert_snapshot_unchanged(api, before)

    def test_presenter_construction_failure_preserves_live_state_and_is_sanitized(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        before = self._live_snapshot(api)

        with patch(
            "acs.webapp.ReviewPresentationAdapter",
            side_effect=RuntimeError("private presenter implementation detail"),
        ):
            result = api.set_fen(VALID_CUSTOM_FEN)

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not prepare history for the FEN position.",
        )
        self.assertNotIn("private presenter implementation detail", result["announcement"])
        self._assert_snapshot_unchanged(api, before)

    def test_invalid_fen_keeps_existing_live_game_and_history(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        before = self._live_snapshot(api)

        result = api.set_fen("8/8/8/8/8/8/8/8 w - - 0 1")

        self.assertFalse(result["ok"])
        self._assert_snapshot_unchanged(api, before)


if __name__ == "__main__":
    unittest.main()
