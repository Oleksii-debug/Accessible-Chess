import unittest
from pathlib import Path

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

    def test_canonical_board_validity_blocks_gameplay_after_editor_changes(self):
        invalid_setups = (
            (
                "adjacent kings",
                (("e1", "K"), ("e2", "k")),
                None,
            ),
            (
                "pawn on first rank",
                (("a1", "K"), ("h8", "k"), ("b1", "P")),
                None,
            ),
            (
                "impossible en passant provenance",
                (("a1", "K"), ("h8", "k")),
                ("w", "-", "e6", "0", "1"),
            ),
        )

        for label, pieces, metadata in invalid_setups:
            with self.subTest(label=label):
                api = AccessibleChessAPI(lang="en")
                self.assertTrue(api.clear_board()["ok"])
                for square, piece in pieces:
                    self.assertTrue(api.edit_position_piece(square, piece)["ok"])
                if metadata is not None:
                    self.assertTrue(api.edit_position_metadata(*metadata)["ok"])

                before = api.board.fen()
                state = api.get_state()
                self.assertFalse(state["positionComplete"])
                self.assertIn("Complete and validate", state["gameStatus"])

                move_result = api.make_move("Ka2")
                self.assertFalse(move_result["ok"])
                self.assertEqual(api.board.fen(), before)

                square_result = api.activate_square("a1")
                self.assertFalse(square_result["ok"])
                self.assertEqual(api.board.fen(), before)
                self.assertIsNone(api.selected_source)

    def test_editor_api_rejects_oversized_input_without_publishing_state(self):
        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()

        self.assertFalse(api.edit_position_piece("a" * 300, "K")["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertFalse(api.edit_position_piece("a1", "K" * 2)["ok"])
        self.assertEqual(api.board.fen(), before)

        huge = "1" * 3000
        self.assertFalse(api.edit_position_metadata("w", "-", "-", huge, huge)["ok"])
        self.assertEqual(api.board.fen(), before)

        too_long = "9" * 5000
        self.assertFalse(api.edit_position_metadata("w", "-", "-", too_long, "1")["ok"])
        self.assertEqual(api.board.fen(), before)

    def test_editor_feedback_is_visible_and_plain_enter_is_keyboard_first(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("positionEditorActionNames=new Set", html)
        self.assertIn("setPositionEditorActionStatus(name,r&&r.announcement?r.announcement:'')", html)
        self.assertIn("el('position-square').addEventListener('keydown'", html)
        self.assertIn("el('position-piece-apply').click()", html)
        self.assertIn("el('position-metadata-apply').click()", html)

    def test_position_editor_lock_composes_history_and_analysis_reasons(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("positionEditorHistoryLocked||analysisMutationLocked", html)
        self.assertIn("setPositionEditorHistoryLock(pe.editable===false)", html)
        for control_id in (
            "position-square",
            "position-piece",
            "position-piece-apply",
            "position-turn",
            "position-castling",
            "position-ep",
            "position-halfmove",
            "position-fullmove",
            "position-metadata-apply",
            "position-validate",
            "position-input",
            "position-load",
            "empty-board",
        ):
            with self.subTest(control_id=control_id):
                self.assertIn(f"'{control_id}'", html)

    def test_valid_manual_editor_position_remains_playable(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.clear_board()["ok"])
        for square, piece in (
            ("a1", "K"),
            ("h8", "k"),
            ("a2", "R"),
            ("e5", "p"),
        ):
            self.assertTrue(api.edit_position_piece(square, piece)["ok"])
        self.assertTrue(api.edit_position_metadata("w", "-", "e6", "0", "2")["ok"])

        state = api.get_state()
        self.assertTrue(state["positionComplete"])
        self.assertTrue(api.validate_position_editor()["ok"])


if __name__ == "__main__":
    unittest.main()
