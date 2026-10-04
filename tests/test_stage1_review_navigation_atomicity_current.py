import unittest
from unittest.mock import patch

from acs.webapp import AccessibleChessAPI


class Stage1ReviewNavigationAtomicityTests(unittest.TestCase):
    def _snapshot(self, api: AccessibleChessAPI) -> dict[str, object]:
        return {
            "board": api.board,
            "board_fen": api.board.fen(),
            "review_history": api.review_history,
            "review_tree": api.review_history.export_tree(),
            "review_adapter": api.review_adapter,
            "cursor": api.review_history.cursor_node_id,
            "live_node": api.live_history_node,
            "selected_source": api.selected_source,
            "sans": list(api.sans),
            "move_sides": list(api.move_sides),
            "redo_meta": list(api.redo_meta),
        }

    def _assert_unchanged(
        self,
        api: AccessibleChessAPI,
        before: dict[str, object],
    ) -> None:
        self.assertIs(api.board, before["board"])
        self.assertEqual(api.board.fen(), before["board_fen"])
        self.assertIs(api.review_history, before["review_history"])
        self.assertEqual(api.review_history.export_tree(), before["review_tree"])
        self.assertIs(api.review_adapter, before["review_adapter"])
        self.assertEqual(api.review_history.cursor_node_id, before["cursor"])
        self.assertEqual(api.live_history_node, before["live_node"])
        self.assertEqual(api.selected_source, before["selected_source"])
        self.assertEqual(api.sans, before["sans"])
        self.assertEqual(api.move_sides, before["move_sides"])
        self.assertEqual(api.redo_meta, before["redo_meta"])

    def _install_malformed_live_tail(self, api: AccessibleChessAPI) -> tuple[int, int]:
        self.assertTrue(api.make_move("e4")["ok"])
        valid_node = api.live_history_node
        malformed = api.review_history.append(
            "not-a-fen",
            san="e5",
            side="b",
            last_move="e5",
        )
        api.live_history_node = malformed.node_id
        api.review_history.select_node(valid_node)
        return valid_node, malformed.node_id

    def test_review_next_malformed_live_tail_fails_without_moving_cursor(self):
        api = AccessibleChessAPI(lang="uk")
        valid_node, malformed_node = self._install_malformed_live_tail(api)
        self.assertNotEqual(valid_node, malformed_node)
        before = self._snapshot(api)

        result = api.review_next()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Не вдалося підготувати вибрану позицію історії.",
        )
        self.assertNotIn("FEN", result["announcement"])
        self._assert_unchanged(api, before)

    def test_go_to_move_malformed_live_tail_fails_without_publishing_candidate(self):
        api = AccessibleChessAPI(lang="en")
        self._install_malformed_live_tail(api)
        before = self._snapshot(api)

        result = api.go_to_move("1b")

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not prepare the selected history position.",
        )
        self.assertNotIn("fen", result["announcement"].lower())
        self._assert_unchanged(api, before)

    def test_review_presenter_construction_failure_preserves_exact_cursor(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.make_move("e5")["ok"])
        before = self._snapshot(api)

        with patch(
            "acs.webapp.ReviewPresentationAdapter",
            side_effect=RuntimeError("private review presenter detail"),
        ):
            result = api.review_previous()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not prepare the selected history position.",
        )
        self.assertNotIn("private review presenter detail", result["announcement"])
        self._assert_unchanged(api, before)

    def test_review_history_clone_failure_preserves_exact_cursor(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        before = self._snapshot(api)

        with patch(
            "acs.webapp.ReviewHistory.from_tree",
            side_effect=RuntimeError("private review clone detail"),
        ):
            result = api.go_to_move("0")

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Не вдалося підготувати вибрану позицію історії.",
        )
        self.assertNotIn("private review clone detail", result["announcement"])
        self._assert_unchanged(api, before)

    def test_live_node_fen_mismatch_is_rejected_before_publication(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        e4_node = api.live_history_node
        self.assertTrue(api.make_move("e5")["ok"])
        e5_node = api.live_history_node
        self.assertNotEqual(e4_node, e5_node)

        # Simulate a corrupted restored live-node pointer. The visible cursor is
        # still on the valid e5 position, so the failure path itself is renderable.
        api.live_history_node = e4_node
        before = self._snapshot(api)

        result = api.go_to_move("end")

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not prepare the selected history position.",
        )
        self._assert_unchanged(api, before)

    def test_missing_live_node_pointer_is_contained_before_lineage_navigation(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        api.live_history_node = 999_999
        before = self._snapshot(api)

        result = api.go_to_move("0")

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Could not prepare the selected history position.",
        )
        self._assert_unchanged(api, before)

    def test_successful_review_navigation_never_replaces_live_board(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.make_move("e5")["ok"])
        live_board = api.board
        live_fen = api.board.fen()
        live_node = api.live_history_node

        selected = api.activate_square("g1")
        self.assertTrue(selected["ok"])
        self.assertEqual(selected["selectedSquare"], "g1")

        previous = api.review_previous()
        self.assertTrue(previous["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), live_fen)
        self.assertIsNone(api.selected_source)
        self.assertEqual(api.review_history.cursor_node_id, live_node - 1)

        next_result = api.review_next()
        self.assertTrue(next_result["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), live_fen)
        self.assertEqual(api.review_history.cursor_node_id, live_node)
        self.assertEqual(api.review_adapter.current().fen, live_fen)

        start = api.go_to_move("0")
        self.assertTrue(start["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), live_fen)
        self.assertEqual(api.review_history.cursor_node_id, 0)

        end = api.go_to_move("end")
        self.assertTrue(end["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), live_fen)
        self.assertEqual(api.review_history.cursor_node_id, live_node)
        self.assertEqual(api.review_adapter.current().fen, live_fen)


if __name__ == "__main__":
    unittest.main()
