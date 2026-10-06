from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.keybindings import ActionRegistry, BindingContext
from acs.webapp import AccessibleChessAPI
from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


def play(api, *moves: str) -> None:
    for move in moves:
        result = api.make_move(move)
        assert result["ok"], result["announcement"]


class HistoryReviewCompleteUserFlowTests(unittest.TestCase):
    def test_history_items_cover_live_line_and_follow_committed_review_cursor(self) -> None:
        api = AccessibleChessAPI("uk")
        play(api, "e4", "e5", "Nf3", "Nc6")

        state = api.get_state()
        items = state["historyItems"]
        self.assertEqual([item["ply"] for item in items], [1, 2, 3, 4])
        self.assertEqual(sum(bool(item["selected"]) for item in items), 1)
        self.assertTrue(items[-1]["selected"])
        self.assertTrue(items[-1]["live"])
        self.assertTrue(items[0]["label"].startswith("1."))
        self.assertTrue(items[1]["label"].startswith("1..."))
        self.assertTrue(items[2]["label"].startswith("2."))

        live_board = api.board
        live_fen = live_board.fen()
        reviewed = api.go_to_move("1w")
        self.assertTrue(reviewed["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), live_fen)

        selected = [item for item in reviewed["historyItems"] if item["selected"]]
        self.assertEqual([item["ply"] for item in selected], [1])
        self.assertFalse(selected[0]["live"])
        self.assertEqual(reviewed["reviewCursor"], 1)

    def test_review_board_queries_and_analysis_target_use_historical_position(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(
                "en",
                keymap_path=Path(td) / "keymap.json",
            )
            play(api, "e4", "d5", "exd5")
            live_fen = api.board.fen()

            live_material = api.dispatch_action("board.material")
            self.assertTrue(live_material["ok"])
            live_last = api.dispatch_action("board.last_move")
            self.assertTrue(live_last["ok"])

            reviewed = api.go_to_move("1...")
            self.assertTrue(reviewed["ok"])
            self.assertNotEqual(reviewed["fen"], live_fen)
            self.assertEqual(api.board.fen(), live_fen)

            read_fen = api.dispatch_action("board.read_fen")
            self.assertTrue(read_fen["ok"])
            self.assertEqual(read_fen["fen"], reviewed["fen"])

            review_material = api.dispatch_action("board.material")
            self.assertTrue(review_material["ok"])
            self.assertNotEqual(
                review_material["announcement"],
                live_material["announcement"],
            )

            review_last = api.dispatch_action("board.last_move")
            self.assertTrue(review_last["ok"])
            self.assertNotEqual(
                review_last["announcement"],
                live_last["announcement"],
            )

            state = api.get_state()
            self.assertEqual(state["fen"], reviewed["fen"])
            self.assertEqual(state["analysis"]["fen"], reviewed["fen"])
            self.assertFalse(state["atHistoryEnd"])
            self.assertEqual(api.board.fen(), live_fen)

    def test_undo_redo_defaults_are_global_and_review_does_not_reinterpret_them(self) -> None:
        registry = ActionRegistry()
        self.assertEqual(
            registry.resolve_binding(BindingContext.GLOBAL, "Ctrl+Z").action_id,
            "edit.undo",
        )
        self.assertEqual(
            registry.resolve_binding(
                BindingContext.GLOBAL,
                "Ctrl+Shift+Z",
            ).action_id,
            "edit.redo",
        )

        api = AccessibleChessAPI("en")
        play(api, "e4", "e5")
        live_fen = api.board.fen()
        self.assertTrue(api.review_previous()["ok"])

        undo = api.undo()
        redo = api.redo()
        self.assertFalse(undo["ok"])
        self.assertFalse(redo["ok"])
        self.assertEqual(api.board.fen(), live_fen)
        self.assertFalse(api.get_state()["atHistoryEnd"])

    def test_history_list_is_keyboard_select_then_enter_commit(self) -> None:
        html = (
            Path(__file__).resolve().parents[1] / "web" / "index.html"
        ).read_text(encoding="utf-8")

        for marker in (
            'id="history-list" role="listbox"',
            'id="history-list-help"',
            "function onHistoryListKey(e)",
            "e.key==='ArrowUp'",
            "e.key==='ArrowDown'",
            "e.key==='Home'",
            "e.key==='End'",
            "e.key==='Enter'",
            "apiAction('go_to_move',String(ply))",
            "setHistoryBrowsePly(Number(options[next].dataset.ply),true)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

        self.assertIn(
            "Стрілки вгору і вниз вибирають хід. Enter відкриває позицію після вибраного ходу.",
            html,
        )


if __name__ == "__main__":
    unittest.main()
