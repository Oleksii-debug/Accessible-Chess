import unittest
from pathlib import Path

from acs.input_limits import MAX_FEN_CHARS, MAX_SQUARE_TEXT_CHARS
from acs.webapp import AccessibleChessAPI


class FenPositionEditorCompleteUserFlowTests(unittest.TestCase):
    def test_keyboard_editor_builds_complete_position_without_fen_typing(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.clear_board()["ok"])

        for square, piece in (
            ("a1", "K"),
            ("h8", "k"),
            ("a2", "R"),
            ("e5", "p"),
        ):
            with self.subTest(square=square, piece=piece):
                self.assertTrue(api.edit_position_piece(square, piece)["ok"])

        metadata = api.edit_position_metadata("w", "-", "e6", "0", "2")
        self.assertTrue(metadata["ok"])
        self.assertEqual(
            api.board.fen(),
            "7k/8/8/4p3/8/8/R7/K7 w - e6 0 2",
        )

        checked = api.validate_position_editor()
        self.assertTrue(checked["ok"])
        state = api.get_state()
        self.assertEqual(state["positionEditor"]["turn"], "w")
        self.assertEqual(state["positionEditor"]["castling"], "-")
        self.assertEqual(state["positionEditor"]["enPassant"], "e6")
        self.assertEqual(state["positionEditor"]["halfmove"], 0)
        self.assertEqual(state["positionEditor"]["fullmove"], 2)
        self.assertTrue(state["positionEditor"]["editable"])

    def test_piece_can_be_replaced_and_removed_by_square(self):
        api = AccessibleChessAPI(lang="en")
        api.clear_board()
        self.assertTrue(api.edit_position_piece("e1", "K")["ok"])
        self.assertTrue(api.edit_position_piece("e8", "k")["ok"])
        self.assertTrue(api.edit_position_piece("d4", "Q")["ok"])
        self.assertIn("Q", api.board.fen().split()[0])

        removed = api.edit_position_piece("d4", "-")
        self.assertTrue(removed["ok"])
        self.assertNotIn("Q", api.board.fen().split()[0])

    def test_metadata_update_is_atomic_on_invalid_values(self):
        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()

        invalid = (
            ("w", "KK", "-", "0", "1"),
            ("w", "-", "e3", "0", "1"),
            ("w", "-", "-", "-1", "1"),
            ("w", "-", "-", "0", "0"),
            ("x", "-", "-", "0", "1"),
        )
        for args in invalid:
            with self.subTest(args=args):
                result = api.edit_position_metadata(*args)
                self.assertFalse(result["ok"])
                self.assertEqual(api.board.fen(), before)

    def test_editor_rejects_mutation_while_reviewing_history(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.make_move("e5")["ok"])
        self.assertTrue(api.review_previous()["ok"])
        before = api.board.fen()

        result = api.edit_position_piece("a3", "N")
        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertFalse(api.get_state()["positionEditor"]["editable"])

    def test_validation_reports_incomplete_position_without_mutating_it(self):
        api = AccessibleChessAPI(lang="en")
        api.clear_board()
        before = api.board.fen()
        result = api.validate_position_editor()
        self.assertFalse(result["ok"])
        self.assertIn("not yet playable", result["announcement"])
        self.assertEqual(api.board.fen(), before)

    def test_direct_piece_editor_bounds_untrusted_text_before_normalization(self):
        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()

        too_long_square = " " * (MAX_SQUARE_TEXT_CHARS + 1)
        self.assertFalse(api.edit_position_piece(too_long_square, "Q")["ok"])
        self.assertEqual(api.board.fen(), before)

        self.assertFalse(api.edit_position_piece("e4", "Q" * 2)["ok"])
        self.assertEqual(api.board.fen(), before)

    def test_direct_metadata_editor_bounds_untrusted_text_atomically(self):
        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()
        cases = (
            ("ww", "-", "-", "0", "1"),
            ("w", "K" * (MAX_FEN_CHARS + 1), "-", "0", "1"),
            ("w", "-", " " * (MAX_SQUARE_TEXT_CHARS + 1), "0", "1"),
            ("w", "-", "-", "1" * (MAX_FEN_CHARS + 1), "1"),
            ("w", "-", "-", "0", "1" * (MAX_FEN_CHARS + 1)),
        )
        for args in cases:
            with self.subTest(args=(len(args[0]), len(args[1]), len(args[2]), len(args[3]), len(args[4]))):
                self.assertFalse(api.edit_position_metadata(*args)["ok"])
                self.assertEqual(api.board.fen(), before)

    def test_accessible_html_exposes_all_position_editor_controls(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        for marker in (
            'id="position-square"',
            'id="position-piece"',
            'id="position-piece-apply"',
            'id="position-castling"',
            'id="position-ep"',
            'id="position-halfmove"',
            'id="position-fullmove"',
            'id="position-metadata-apply"',
            'id="position-validate"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
