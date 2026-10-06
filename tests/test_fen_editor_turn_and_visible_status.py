import unittest

from acs.webapp import AccessibleChessAPI


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
