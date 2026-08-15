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
        end_fen = api.board.fen()
        end_sans = list(api.sans)
        previous = api.review_previous()
        self.assertTrue(previous["ok"])
        self.assertEqual(previous["reviewCursor"], 3)
        self.assertEqual(api.sans, end_sans)
        self.assertNotEqual(api.board.fen(), end_fen)
        self.assertNotIn("N c 6", previous["moves"])
        forward = api.review_next()
        self.assertTrue(forward["ok"])
        self.assertEqual(forward["reviewCursor"], 4)
        self.assertEqual(api.board.fen(), end_fen)
        self.assertEqual(api.sans, end_sans)
        self.assertIn("N c 6", forward["moves"])

    def test_direct_history_jump_supports_locked_forms(self):
        api = AccessibleChessAPI("en")
        _play_opening(api)
        self.assertEqual(api.go_to_move("start")["reviewCursor"], 0)
        white_two = api.go_to_move("2w")
        self.assertTrue(white_two["ok"])
        self.assertEqual(white_two["reviewCursor"], 3)
        self.assertIn("N f 3", white_two["lastMove"])
        self.assertEqual(api.go_to_move("2...")["reviewCursor"], 4)
        self.assertEqual(api.go_to_move("2")["reviewCursor"], 4)
        self.assertEqual(api.go_to_move("end")["reviewCursor"], 4)

    def test_invalid_jump_preserves_current_review_state(self):
        api = AccessibleChessAPI("uk")
        _play_opening(api)
        before_fen, before_cursor = api.board.fen(), api.review_cursor
        invalid = api.go_to_move("99")
        self.assertFalse(invalid["ok"])
        self.assertEqual(api.review_cursor, before_cursor)
        self.assertEqual(api.board.fen(), before_fen)

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
