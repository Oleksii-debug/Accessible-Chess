from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from acs.chesscore import Board
from acs.history import PositionSnapshot
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
        self.assertEqual([item["ply"] for item in items], [0, 1, 2, 3, 4])
        self.assertEqual(sum(bool(item["selected"]) for item in items), 1)
        self.assertTrue(items[-1]["selected"])
        self.assertTrue(items[-1]["live"])
        self.assertEqual(items[0]["label"], "Початкова позиція.")
        self.assertTrue(items[1]["label"].startswith("1."))
        self.assertTrue(items[2]["label"].startswith("1..."))
        self.assertTrue(items[3]["label"].startswith("2."))

        live_board = api.board
        live_fen = live_board.fen()
        reviewed = api.go_to_move("1w")
        self.assertTrue(reviewed["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), live_fen)

        selected = [item for item in reviewed["historyItems"] if item["selected"]]
        self.assertEqual([item["ply"] for item in selected], [1])
        self.assertFalse(selected[0]["live"])
        self.assertFalse(reviewed["historyItems"][0]["selected"])
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

    def test_history_list_includes_initial_position_as_canonical_ply_zero(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4", "e5")

        start = api.go_to_move("start")
        self.assertTrue(start["ok"])
        items = start["historyItems"]
        self.assertEqual([item["ply"] for item in items], [0, 1, 2])
        self.assertTrue(items[0]["selected"])
        self.assertFalse(items[0]["live"])
        self.assertTrue(items[-1]["live"])
        self.assertEqual(items[0]["label"], "Initial position.")

    def test_history_projection_fails_closed_when_metadata_outgrows_live_line(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4", "e5")
        api.sans.append("Nf3")
        api.move_sides.append("w")

        self.assertEqual(api._history_items(), [])

    def test_live_line_projection_rejects_cycle_instead_of_hanging(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4")
        live = api.live_history_node
        cycle_parent = live + 1000

        class CyclicHistory:
            @staticmethod
            def tree_nodes():
                return [
                    SimpleNamespace(node_id=live, parent_id=cycle_parent),
                    SimpleNamespace(node_id=cycle_parent, parent_id=live),
                ]

        with self.assertRaisesRegex(RuntimeError, "cyclic live review history"):
            api._live_line_nodes(CyclicHistory())

    def test_live_line_projection_rejects_duplicate_node_ids(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4")
        live = api.live_history_node

        class DuplicateHistory:
            @staticmethod
            def tree_nodes():
                return [
                    SimpleNamespace(node_id=live, parent_id=None),
                    SimpleNamespace(node_id=live, parent_id=None),
                ]

        with self.assertRaisesRegex(RuntimeError, "duplicate review history node"):
            api._live_line_nodes(DuplicateHistory())

    def test_live_line_projection_rejects_missing_parent(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4")
        live = api.live_history_node

        class MissingParentHistory:
            @staticmethod
            def tree_nodes():
                return [
                    SimpleNamespace(node_id=live, parent_id=live + 1000),
                ]

        with self.assertRaisesRegex(RuntimeError, "live review history node is missing"):
            api._live_line_nodes(MissingParentHistory())

    def test_committed_review_and_live_end_are_distinct_semantic_states(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4", "e5", "Nf3")
        reviewed = api.go_to_move("1")
        self.assertTrue(reviewed["ok"])

        items = reviewed["historyItems"]
        self.assertTrue(items[1]["selected"])
        self.assertFalse(items[1]["live"])
        self.assertFalse(items[0]["selected"])
        self.assertFalse(items[-1]["selected"])
        self.assertTrue(items[-1]["live"])

    def _append_detached_branch(self, api: AccessibleChessAPI) -> tuple[int, int]:
        branch_board = Board()
        first_san = branch_board.push_text("d4")
        first = PositionSnapshot(branch_board.fen(), san=first_san, side="w")
        second_san = branch_board.push_text("d5")
        second = PositionSnapshot(branch_board.fen(), san=second_san, side="b")
        branch = api.review_history.append_branch(0, (first, second))
        self.assertEqual(branch.created_count, 2)
        return branch.node_ids

    def test_history_previous_recovers_from_detached_gametree_branch(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4", "e5", "Nf3")
        live_fen = api.board.fen()
        branch_first, branch_second = self._append_detached_branch(api)

        selected = api.review_history.select_node(branch_second)
        self.assertEqual(selected.node_id, branch_second)
        self.assertNotIn(branch_first, api._live_line_nodes())

        result = api.review_previous()
        self.assertFalse(result["ok"])
        self.assertTrue(result["atHistoryEnd"])
        self.assertEqual(result["fen"], live_fen)
        self.assertEqual(api.review_history.cursor_node_id, api.live_history_node)
        self.assertTrue(result["historyItems"][-1]["selected"])
        self.assertTrue(result["historyItems"][-1]["live"])

    def test_history_direct_selection_rejects_detached_gametree_branch(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4", "e5", "Nf3")
        live_fen = api.board.fen()
        branch_first, _ = self._append_detached_branch(api)

        result = api._select_review_node(branch_first)
        self.assertFalse(result["ok"])
        self.assertTrue(result["atHistoryEnd"])
        self.assertEqual(result["fen"], live_fen)
        self.assertEqual(api.review_history.cursor_node_id, api.live_history_node)

    def test_history_direct_selection_rejects_non_integer_node_ids(self) -> None:
        api = AccessibleChessAPI("en")
        play(api, "e4")

        for invalid in (True, 1.0, "1", None):
            with self.subTest(invalid=invalid):
                result = api._select_review_node(invalid)
                self.assertFalse(result["ok"])
                self.assertTrue(result["atHistoryEnd"])

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
            "aria-current",
            "current review position",
            "live current position",
            "const sequenceOk=valid.length>0&&plies.every((ply,i)=>ply===i)",
            "const committedOk=committed.length===1",
            "const liveOk=live.length===1",
            "ply>=0",
            "History positions",
            "typeof item.ply==='number'",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

        self.assertIn(
            "Стрілки вгору і вниз вибирають позицію. Enter відкриває вибрану позицію.",
            html,
        )


if __name__ == "__main__":
    unittest.main()
