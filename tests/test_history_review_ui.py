from pathlib import Path
import unittest

from acs.webapp import AccessibleChessAPI


def _play_opening(api: AccessibleChessAPI) -> None:
    for move in ("e4", "e5", "Nf3", "Nc6"):
        result = api.make_move(move)
        assert result["ok"], result["announcement"]


class HistoryReviewUiIntegrationTests(unittest.TestCase):
    def test_review_navigation_is_non_destructive_and_reversible(self):
        api = AccessibleChessAPI("uk")
        _play_opening(api)
        live_board = api.board
        end_fen = api.board.fen()
        end_sans = list(api.sans)
        undo_len = len(api.board.undo_stack)
        redo_len = len(api.board.redo_stack)

        previous = api.review_previous()
        self.assertTrue(previous["ok"])
        self.assertEqual(previous["reviewCursor"], 3)
        self.assertEqual(api.sans, end_sans)
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), end_fen)
        self.assertEqual(len(api.board.undo_stack), undo_len)
        self.assertEqual(len(api.board.redo_stack), redo_len)
        self.assertNotEqual(previous["fen"], end_fen)
        self.assertNotIn("N c 6", previous["moves"])

        forward = api.review_next()
        self.assertTrue(forward["ok"])
        self.assertEqual(forward["reviewCursor"], 4)
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), end_fen)
        self.assertEqual(api.sans, end_sans)
        self.assertIn("N c 6", forward["moves"])

    def test_review_end_then_undo_redo_restores_exact_live_position_and_history(self):
        api = AccessibleChessAPI("en")
        _play_opening(api)
        live_board = api.board
        end_fen = api.board.fen()
        end_sans = list(api.sans)

        self.assertTrue(api.review_previous()["ok"])
        self.assertTrue(api.review_previous()["ok"])
        self.assertTrue(api.go_to_move("end")["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), end_fen)

        undone = api.undo()
        self.assertTrue(undone["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(len(api.sans), len(end_sans) - 1)
        self.assertNotEqual(api.board.fen(), end_fen)

        redone = api.redo()
        self.assertTrue(redone["ok"])
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), end_fen)
        self.assertEqual(api.sans, end_sans)
        self.assertTrue(redone["atHistoryEnd"])

    def test_direct_history_jump_supports_locked_forms(self):
        api = AccessibleChessAPI("en")
        _play_opening(api)
        live_fen = api.board.fen()
        self.assertEqual(api.go_to_move("start")["reviewCursor"], 0)
        self.assertEqual(api.board.fen(), live_fen)
        white_two = api.go_to_move("2w")
        self.assertTrue(white_two["ok"])
        self.assertEqual(white_two["reviewCursor"], 3)
        self.assertIn("N f 3", white_two["lastMove"])
        self.assertEqual(api.go_to_move("2...")["reviewCursor"], 4)
        self.assertEqual(api.go_to_move("2")["reviewCursor"], 4)
        self.assertEqual(api.go_to_move("end")["reviewCursor"], 4)
        self.assertEqual(api.board.fen(), live_fen)

    def test_invalid_jump_preserves_current_review_state_and_live_board(self):
        api = AccessibleChessAPI("uk")
        _play_opening(api)
        live_board = api.board
        live_fen = api.board.fen()
        api.review_previous()
        before_display_fen, before_cursor = api.get_state()["fen"], api.review_cursor
        invalid = api.go_to_move("99")
        self.assertFalse(invalid["ok"])
        self.assertEqual(api.review_cursor, before_cursor)
        self.assertEqual(api.get_state()["fen"], before_display_fen)
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), live_fen)

    def test_undo_then_new_move_creates_live_variation_without_reusing_redo_branch(self):
        api = AccessibleChessAPI("en")
        _play_opening(api)
        old_end = api.board.fen()
        self.assertTrue(api.undo()["ok"])
        self.assertTrue(api.make_move("d6")["ok"])
        self.assertNotEqual(api.board.fen(), old_end)
        self.assertFalse(api.redo_meta)
        self.assertTrue(api.get_state()["atHistoryEnd"])
        self.assertTrue(api.review_previous()["ok"])
        self.assertTrue(api.review_next()["ok"])
        self.assertEqual(api.get_state()["fen"], api.board.fen())

    def test_history_ui_is_semantic_but_does_not_break_locked_h2_order(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<h3 id="h-history">', html)
        self.assertNotIn('<h2 id="h-history">', html)
        for marker in (
            'id="history-input" type="text"',
            'id="history-prev" type="button"',
            'id="history-next" type="button"',
            'id="history-go" type="button"',
            "focusHistoryJump()",
            "apiAction('review_previous')",
            "apiAction('review_next')",
        ):
            self.assertIn(marker, html)
        headings = [
            'h-game-info', 'h-moves', 'h-white', 'h-black', 'h-status',
            'h-last', 'h-input', 'h-engine', 'h-board', 'h-actions',
        ]
        positions = [html.index(f'<h2 id="{heading}"') for heading in headings]
        self.assertEqual(positions, sorted(positions))

    def test_history_shortcuts_come_from_central_keymap_not_hardcoded_handler(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        keymap = (root / "web" / "keybindings.json").read_text(encoding="utf-8")
        compact = keymap.replace(" ", "").replace("\n", "")
        self.assertIn('"id":"history.previous"', compact)
        self.assertIn('"binding":"Shift+A"', compact)
        self.assertIn('"id":"history.next"', compact)
        self.assertIn('"binding":"Shift+D"', compact)
        self.assertIn('"id":"history.go_to_move"', compact)
        self.assertIn('"binding":"Ctrl+G"', compact)
        self.assertNotIn('"id":"history.goto"', compact)
        self.assertIn("resolveBinding(chord,'history','document')", html)
        self.assertIn("typeof a.keymap_resolve_binding==='function'", html)
        self.assertNotIn("actionByChord(eventChord(e),'document')", html)


if __name__ == "__main__":
    unittest.main()
