import tempfile
import unittest
from pathlib import Path

from acs.webapp import AccessibleChessAPI
from acs.webapp_keymap_core import KeymapAwareAccessibleChessAPI


class FenEditorTurnSemanticsTests(unittest.TestCase):
    def test_manual_turn_edit_clears_stale_en_passant(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(api.board.fen().split()[3], "e3")

        changed = api.set_turn("w")

        self.assertTrue(changed["ok"])
        fields = api.board.fen().split()
        self.assertEqual(fields[1], "w")
        self.assertEqual(fields[3], "-")
        self.assertEqual(api.sans, [])
        self.assertEqual(api.get_state()["reviewCursor"], 0)
        self.assertTrue(api.get_state()["positionComplete"])

    def test_explicit_same_side_turn_edit_also_clears_en_passant_provenance(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(api.board.fen().split()[3], "e3")

        changed = api.set_turn("b")

        self.assertTrue(changed["ok"])
        fields = api.board.fen().split()
        self.assertEqual(fields[1], "b")
        self.assertEqual(fields[3], "-")
        self.assertEqual(api.sans, [])

    def test_move_entry_turn_command_uses_same_safe_editor_transition(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertEqual(api.board.fen().split()[3], "e3")

        changed = api.make_move("w")

        self.assertTrue(changed["ok"])
        fields = api.board.fen().split()
        self.assertEqual(fields[1], "w")
        self.assertEqual(fields[3], "-")
        self.assertEqual(api.sans, [])

    def test_v2_keymap_api_preserves_safe_turn_transition_and_reanchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = KeymapAwareAccessibleChessAPI(
                lang="en",
                keymap_path=Path(tmp) / "keymap.json",
            )
            self.assertTrue(api.make_move("e4")["ok"])
            self.assertEqual(api.board.fen().split()[3], "e3")

            changed = api.set_turn("w")

            self.assertTrue(changed["ok"])
            self.assertEqual(api.board.fen().split()[1], "w")
            self.assertEqual(api.board.fen().split()[3], "-")
            self.assertEqual(api.sans, [])
            self.assertEqual(
                api._analysis_origin_node_id,
                api.review_history.cursor_node_id,
            )

    def test_turn_edit_is_atomic_while_reviewing_history(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.make_move("e5")["ok"])
        self.assertTrue(api.review_previous()["ok"])
        before = api.board.fen()

        result = api.set_turn("w")

        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)


if __name__ == "__main__":
    unittest.main()
