import unittest
from pathlib import Path

from acs.webapp import AccessibleChessAPI


class FenEditorTurnAndVisibleStatusTests(unittest.TestCase):
    def test_manual_turn_edit_clears_stale_en_passant_through_editor_authority(self):
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

    def test_turn_edit_is_atomic_while_reviewing_history(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.make_move("e5")["ok"])
        self.assertTrue(api.review_previous()["ok"])
        before = api.board.fen()

        result = api.set_turn("w")

        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)

    def test_position_editor_action_feedback_has_a_visible_copyable_surface(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'id="position-editor-status" class="block" aria-live="off"',
            html,
        )
        self.assertIn("const positionEditorActions=new Set([", html)
        self.assertIn("'validate_position_editor'", html)
        self.assertIn("'edit_position_piece'", html)
        self.assertIn("'edit_position_metadata'", html)
        self.assertIn(
            "setPositionEditorActionStatus(name,r&&r.announcement)",
            html,
        )
        self.assertIn(
            "setPositionEditorActionStatus(name,message)",
            html,
        )


if __name__ == "__main__":
    unittest.main()
