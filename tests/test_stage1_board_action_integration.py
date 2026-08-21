from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.keybindings import ActionRegistry, BindingContext
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.ui_keymap_adapter import build_web_keymap


class Stage1BoardActionIntegrationTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Stage1ReleaseAccessibleChessAPI(keymap_path=Path(temp.name) / "keymap.json")

    def test_registry_board_information_actions_are_live_and_non_mutating(self):
        api = self.make_api()
        api.new_game()
        before = (api.board.fen(), tuple(api.sans), api.review_history.node_count)

        current = api.dispatch_action("board.current", "e2")
        legal = api.dispatch_action("board.legal_moves", "e2")
        surroundings = api.dispatch_action("board.surroundings", "e2")
        material = api.dispatch_action("board.material", "e2")

        self.assertTrue(current["ok"])
        self.assertEqual(current["focusSquare"], "e2")
        self.assertIn("e 2", current["announcement"])
        self.assertIn("пішак", current["announcement"])
        self.assertTrue(legal["ok"])
        self.assertIn("e 3", legal["announcement"])
        self.assertIn("e 4", legal["announcement"])
        self.assertTrue(surroundings["ok"])
        self.assertEqual(surroundings["focusSquare"], "e2")
        self.assertTrue(material["ok"])
        self.assertIn("39", material["announcement"])
        self.assertEqual((api.board.fen(), tuple(api.sans), api.review_history.node_count), before)

    def test_material_is_central_discoverable_unbound_and_remappable(self):
        registry = ActionRegistry()
        definition = registry.definition("board.material")
        self.assertEqual(definition.context, BindingContext.BOARD)
        self.assertIsNone(registry.get_binding("board.material"))
        self.assertIsNone(definition.default_binding)

        projected = {item["id"]: item for item in build_web_keymap(registry)} if False else None
        snapshot = build_web_keymap(registry)
        row = next(item for item in snapshot["actions"] if item["id"] == "board.material")
        self.assertEqual(row["labelUk"], "Матеріальний баланс")
        self.assertEqual(row["labelEn"], "Material balance")
        self.assertIsNone(row["binding"])

        registry.set_binding("board.material", "Ctrl+Shift+M")
        resolved = registry.resolve_binding(BindingContext.BOARD, "Ctrl+Shift+M")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.action_id, "board.material")

        api = self.make_api()
        saved = api.keymap_save("board.material", "Ctrl+Shift+M")
        self.assertTrue(saved["ok"])
        live = api.keymap_resolve_binding("board", "Ctrl+Shift+M")
        self.assertEqual(live["actionId"], "board.material")

    def test_current_square_query_covers_all_64_squares_without_mutation(self):
        api = self.make_api()
        api.new_game()
        before = (api.board.fen(), tuple(api.sans), api.review_history.node_count)
        visited = set()
        for rank in "12345678":
            for file_name in "abcdefgh":
                square = file_name + rank
                result = api.dispatch_action("board.current", square)
                self.assertTrue(result["ok"], square)
                self.assertEqual(result["focusSquare"], square)
                visited.add(result["focusSquare"])
        self.assertEqual(len(visited), 64)
        self.assertEqual((api.board.fen(), tuple(api.sans), api.review_history.node_count), before)

    def test_attackers_defenders_captures_and_piece_cycle_use_displayed_board(self):
        api = self.make_api()
        loaded = api.set_fen("7k/8/8/3p1p2/4P3/2N5/8/K7 w - - 0 1")
        self.assertTrue(loaded["ok"])

        captures = api.dispatch_action("board.captures", "e4")
        attackers = api.dispatch_action("board.attackers", "e4")
        defenders = api.dispatch_action("board.defenders", "e4")
        next_knight = api.dispatch_action("board.next_knight", "a1")
        previous_knight = api.dispatch_action("board.previous_knight", "h8")

        self.assertTrue(captures["ok"])
        self.assertIn("d 5", captures["announcement"])
        self.assertIn("f 5", captures["announcement"])
        self.assertIn("d 5", attackers["announcement"])
        self.assertIn("f 5", attackers["announcement"])
        self.assertIn("c 3", defenders["announcement"])
        self.assertEqual(next_knight["focusSquare"], "c3")
        self.assertEqual(previous_knight["focusSquare"], "c3")

    def test_edge_and_empty_square_controller_queries_do_not_wrap(self):
        api = self.make_api()
        self.assertTrue(api.set_fen("7k/8/8/8/8/8/1r6/K7 w - - 0 1")["ok"])
        edge = api.dispatch_action("board.attackers", "a2")
        surroundings = api.dispatch_action("board.surroundings", "a1")
        self.assertTrue(edge["ok"])
        self.assertIn("b 2", edge["announcement"])
        self.assertNotIn("h 2", edge["announcement"])
        self.assertTrue(surroundings["ok"])
        self.assertIn("a 2", surroundings["announcement"])
        self.assertIn("b 1", surroundings["announcement"])
        self.assertIn("b 2", surroundings["announcement"])
        self.assertNotIn("h 1", surroundings["announcement"])

    def test_material_balance_tracks_capture_and_undo(self):
        api = self.make_api()
        for move in ("e4", "d5", "exd5"):
            self.assertTrue(api.make_move(move)["ok"])
        after_capture = api.dispatch_action("board.material", "d5")
        self.assertTrue(after_capture["ok"])
        self.assertIn("39 до 38", after_capture["announcement"])
        self.assertIn("+1", after_capture["announcement"])
        self.assertTrue(api.undo()["ok"])
        restored = api.dispatch_action("board.material", "e4")
        self.assertIn("39 до 39", restored["announcement"])

    def test_last_move_and_last_capture_follow_review_history(self):
        api = self.make_api()
        for move in ("e4", "d5", "exd5"):
            result = api.make_move(move)
            self.assertTrue(result["ok"], result.get("announcement"))

        last = api.dispatch_action("board.last_move", "d5")
        captured = api.dispatch_action("board.last_captured", "d5")
        self.assertTrue(last["ok"])
        self.assertIn("d 5", last["announcement"])
        self.assertTrue(captured["ok"])
        self.assertIn("чорний пішак", captured["announcement"])

        self.assertTrue(api.review_previous()["ok"])
        previous_last = api.dispatch_action("board.last_move", "d5")
        self.assertIn("d 5", previous_last["announcement"])
        previous_capture = api.dispatch_action("board.last_captured", "d5")
        self.assertFalse(previous_capture["ok"])

    def test_piece_cycle_wraps_on_start_position(self):
        api = self.make_api()
        api.new_game()
        next_knight = api.dispatch_action("board.next_knight", "b1")
        previous_knight = api.dispatch_action("board.previous_knight", "b1")
        self.assertEqual(next_knight["focusSquare"], "g1")
        self.assertEqual(previous_knight["focusSquare"], "g1")

    def test_clock_actions_fail_concisely_when_no_engine_game_is_configured(self):
        api = self.make_api()
        mine = api.dispatch_action("board.my_clock", "e2")
        opponent = api.dispatch_action("board.opponent_clock", "e2")
        self.assertFalse(mine["ok"])
        self.assertFalse(opponent["ok"])
        self.assertNotIn("Traceback", mine["announcement"])
        self.assertNotIn("Exception", opponent["announcement"])

    def test_square_dependent_action_requires_real_board_focus_square(self):
        api = self.make_api()
        before = api.board.fen()
        result = api.dispatch_action("board.legal_moves")
        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)

    def test_release_web_bridge_routes_board_actions_with_current_square_and_live_help(self):
        root = Path(__file__).resolve().parents[1]
        bridge = (root / "web" / "stage1_board_actions.js").read_text(encoding="utf-8")
        release = (root / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")
        for marker in (
            "currentBoardSquare()",
            "apiAction('dispatch_action', id, origin || null)",
            "board.legal_moves",
            "board.captures",
            "board.attackers",
            "board.defenders",
            "board.material",
            "board.next_knight",
            "board.previous_knight",
            "liveHelpBoardActions",
            "jumpBoardFocus(target)",
        ):
            self.assertIn(marker, bridge)
        self.assertIn("stage1_board_actions.js", release)
        self.assertIn("window.evaluate_js(board_bridge_source)", release)


if __name__ == "__main__":
    unittest.main()
