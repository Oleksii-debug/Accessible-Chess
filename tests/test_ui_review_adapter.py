import unittest

from acs.history import ReviewHistory
from acs.ui_review_adapter import ReviewPresentationAdapter


START = "start-fen"
FEN1 = "fen-after-e4"
FEN2 = "fen-after-e5"
FEN3 = "fen-after-nf3"


def _history() -> ReviewHistory:
    history = ReviewHistory(START)
    history.append(FEN1, san="e4", side="w", last_move="e4")
    history.append(FEN2, san="e5", side="b", last_move="e5")
    history.append(FEN3, san="Nf3", side="w", last_move="Nf3")
    return history


class ReviewPresentationAdapterIntegrationTests(unittest.TestCase):
    def test_adapter_moves_only_review_cursor_and_returns_fen_projection(self):
        history = _history()
        live_game_guard = {"fen": FEN3, "undo_depth": 3, "redo_depth": 0}
        adapter = ReviewPresentationAdapter(history, language="en")
        previous = adapter.previous()
        self.assertTrue(previous.ok)
        self.assertEqual(previous.view.fen, FEN2)
        self.assertEqual(previous.view.ply, 2)
        self.assertFalse(previous.view.at_end)
        self.assertEqual(live_game_guard, {"fen": FEN3, "undo_depth": 3, "redo_depth": 0})
        end = adapter.jump("end")
        self.assertTrue(end.ok)
        self.assertEqual(end.view.fen, FEN3)
        self.assertTrue(end.view.at_end)
        self.assertEqual(live_game_guard["undo_depth"], 3)

    def test_adapter_supports_locked_jump_forms_and_stable_node_ids(self):
        adapter = ReviewPresentationAdapter(_history(), language="uk")
        start = adapter.jump("start")
        self.assertTrue(start.ok)
        self.assertEqual((start.view.ply, start.view.node_id), (0, 0))
        white_two = adapter.jump("2w")
        self.assertTrue(white_two.ok)
        self.assertEqual(white_two.view.ply, 3)
        self.assertEqual(white_two.view.node_id, 3)
        self.assertEqual(white_two.view.last_move, "Nf3")
        black_one = adapter.jump("1...")
        self.assertTrue(black_one.ok)
        self.assertEqual(black_one.view.ply, 2)
        self.assertEqual(black_one.view.node_id, 2)

    def test_adapter_preserves_cursor_on_invalid_jump_and_reports_accessibly(self):
        history = _history()
        adapter = ReviewPresentationAdapter(history, language="uk")
        before = adapter.current()
        result = adapter.jump("99")
        self.assertFalse(result.ok)
        self.assertEqual(result.view.node_id, before.node_id)
        self.assertEqual(result.view.fen, before.fen)
        self.assertIn("Не вдалося", result.announcement)

    def test_adapter_reports_start_and_end_boundaries_without_mutation(self):
        history = _history()
        adapter = ReviewPresentationAdapter(history, language="en")
        at_end = adapter.next()
        self.assertFalse(at_end.ok)
        self.assertTrue(at_end.view.at_end)
        self.assertEqual(at_end.announcement, "Already at the end of history.")
        adapter.jump("start")
        at_start = adapter.previous()
        self.assertFalse(at_start.ok)
        self.assertTrue(at_start.view.at_start)
        self.assertEqual(at_start.announcement, "Already at the initial position.")

    def test_reviewhistory_tree_exchange_roundtrip_preserves_branch_identity(self):
        history = _history()
        history.jump("1w")
        variation = history.append("fen-after-c5", san="c5", side="b", last_move="c5")
        tree = history.export_tree()
        restored = ReviewHistory.from_tree(tree)
        self.assertEqual(restored.cursor_node_id, variation.node_id)
        self.assertEqual(restored.export_tree(), tree)
        self.assertEqual([snapshot.san for snapshot in restored.active_line()], [None, "e4", "c5"])


if __name__ == "__main__":
    unittest.main()
