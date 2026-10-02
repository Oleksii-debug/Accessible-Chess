from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


LONG_GAME = (
    "e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6",
    "O-O", "Be7", "Re1", "b5", "Bb3", "d6", "c3", "O-O",
    "h3", "Nb8", "d4", "Nbd7", "c4", "c6", "cxb5", "axb5",
)


class Stage1SaturationHistoryStressTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Stage1ReleaseAccessibleChessAPI(keymap_path=Path(temp.name) / "keymap.json")

    def play_long_game(self, api):
        for ply, move in enumerate(LONG_GAME, start=1):
            result = api.make_move(move)
            self.assertTrue(result["ok"], f"ply {ply} {move}: {result.get('announcement')}")
        self.assertEqual(len(api.sans), len(LONG_GAME))
        self.assertEqual(api.review_history.node_count, len(LONG_GAME) + 1)

    def test_24_ply_game_repeated_undo_redo_restores_exact_state(self):
        api = self.make_api()
        self.play_long_game(api)
        final = (api.board.fen(), tuple(api.sans), tuple(api.move_sides), api.live_history_node)
        for cycle in range(12):
            undone = api.undo()
            self.assertTrue(undone["ok"], f"undo cycle {cycle}")
            self.assertEqual(len(api.sans), len(LONG_GAME) - 1)
            redone = api.redo()
            self.assertTrue(redone["ok"], f"redo cycle {cycle}")
            self.assertEqual(
                (api.board.fen(), tuple(api.sans), tuple(api.move_sides), api.live_history_node),
                final,
            )

    def test_long_review_walk_is_non_destructive_and_returns_exact_live_node(self):
        api = self.make_api()
        self.play_long_game(api)
        live_fen = api.board.fen()
        live_node = api.live_history_node
        for _ in range(15):
            result = api.review_previous()
            self.assertTrue(result["ok"])
            self.assertEqual(api.board.fen(), live_fen)
        reviewed = api.get_state()
        self.assertFalse(reviewed["atHistoryEnd"])
        self.assertEqual(api.board.fen(), live_fen)
        returned = api.go_to_move("end")
        self.assertTrue(returned["ok"])
        self.assertEqual(returned["fen"], live_fen)
        self.assertEqual(api.review_history.cursor_node_id, live_node)
        self.assertEqual(api.board.fen(), live_fen)

    def test_invalid_fen_and_editor_attempts_preserve_long_game_state(self):
        api = self.make_api()
        self.play_long_game(api)
        baseline = (
            api.board.fen(), tuple(api.sans), tuple(api.move_sides),
            api.review_history.cursor_node_id, api.live_history_node,
            api.get_state()["lastMove"],
        )
        invalid_fens = (
            "not a fen",
            "8/8/8/8/8/8/8/8 w - - 0 1",
            "8/8/8/8/8/8/4K3/4k3 w - - 0 1",
            "4k3/8/8/8/8/8/4P3/4K3 w KQ - 0 1",
        )
        for fen in invalid_fens:
            with self.subTest(fen=fen):
                result = api.set_fen(fen)
                self.assertFalse(result["ok"])
                self.assertEqual(
                    (
                        api.board.fen(), tuple(api.sans), tuple(api.move_sides),
                        api.review_history.cursor_node_id, api.live_history_node,
                        api.get_state()["lastMove"],
                    ),
                    baseline,
                )

        for text in ("broken position", "W: K e1 K e2 B: K e8", "W: K e1 P a8 B: K e8"):
            with self.subTest(text=text):
                result = api.set_position_text(text, "w")
                self.assertFalse(result["ok"])
                self.assertEqual(
                    (
                        api.board.fen(), tuple(api.sans), tuple(api.move_sides),
                        api.review_history.cursor_node_id, api.live_history_node,
                        api.get_state()["lastMove"],
                    ),
                    baseline,
                )

    def test_new_move_after_undo_creates_new_live_line_without_redo_reuse(self):
        api = self.make_api()
        for move in LONG_GAME[:10]:
            self.assertTrue(api.make_move(move)["ok"])
        old_final_fen = api.board.fen()
        self.assertTrue(api.undo()["ok"])
        node_count_before = api.review_history.node_count
        replacement = api.make_move("d5")
        self.assertTrue(replacement["ok"], replacement.get("announcement"))
        self.assertNotEqual(api.board.fen(), old_final_fen)
        self.assertEqual(len(api.redo_meta), 0)
        self.assertGreater(api.review_history.node_count, node_count_before)
        redo = api.redo()
        self.assertFalse(redo["ok"])


if __name__ == "__main__":
    unittest.main()
