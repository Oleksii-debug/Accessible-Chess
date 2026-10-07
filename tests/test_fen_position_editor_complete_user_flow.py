import unittest
from pathlib import Path

from acs.input_limits import MAX_FEN_CHARS, MAX_SQUARE_TEXT_CHARS
from acs.position_editor import PositionState, PositionValidationError
from acs.webapp import AccessibleChessAPI


class FenPositionEditorCompleteUserFlowTests(unittest.TestCase):
    def test_direct_position_metadata_normalization_is_bounded_and_canonical(self):
        position = PositionState.from_fen(
            "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"
        )
        changed = position.with_en_passant(" D6 ")
        self.assertEqual(changed.en_passant, "d6")

        with self.assertRaisesRegex(PositionValidationError, "too long"):
            position.with_en_passant(" " * (MAX_SQUARE_TEXT_CHARS + 1))
        with self.assertRaisesRegex(PositionValidationError, "too long"):
            position.with_castling("K" * 257)

        with self.assertRaisesRegex(PositionValidationError, "too long"):
            PositionState(
                position.pieces,
                turn="w",
                castling="K" * 257,
                en_passant="-",
            )

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

    def test_root_editor_mutations_are_blocked_while_reviewing_history(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.make_move("e4")["ok"])
        live_fen = api.board.fen()
        live_tree = api.review_history.export_tree()
        self.assertTrue(api.review_previous()["ok"])
        self.assertFalse(api.get_state()["atHistoryEnd"])

        operations = (
            api.clear_board,
            lambda: api.set_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1"),
            lambda: api.set_position_text("W: K e1 B: K e8", "w"),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                result = operation()
                self.assertFalse(result["ok"])
                self.assertIn("Return to the end of history", result["announcement"])
                self.assertEqual(api.board.fen(), live_fen)
                self.assertEqual(api.review_history.export_tree(), live_tree)

    def test_side_to_move_action_clears_stale_en_passant_and_preserves_position(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(
            api.set_fen("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2")["ok"]
        )
        before_pieces = api.board.fen().split()[0]

        changed = api.set_turn("b")

        self.assertTrue(changed["ok"])
        fields = api.board.fen().split()
        self.assertEqual(fields[0], before_pieces)
        self.assertEqual(fields[1:], ["b", "-", "-", "0", "2"])
        self.assertTrue(api.get_state()["positionComplete"])

    def test_move_entry_side_command_uses_same_en_passant_safe_transition(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(
            api.set_fen("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2")["ok"]
        )

        changed = api.make_move("b")

        self.assertTrue(changed["ok"])
        self.assertEqual(
            api.board.fen(),
            "4k3/8/8/3pP3/8/8/8/4K3 b - - 0 2",
        )
        self.assertTrue(api.get_state()["positionComplete"])

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
            (
                "w",
                "-",
                "-",
                "1" * (MAX_FEN_CHARS // 2),
                "1" * (MAX_FEN_CHARS // 2),
            ),
        )
        for args in cases:
            with self.subTest(args=(len(args[0]), len(args[1]), len(args[2]), len(args[3]), len(args[4]))):
                self.assertFalse(api.edit_position_metadata(*args)["ok"])
                self.assertEqual(api.board.fen(), before)

    def test_editor_state_with_adjacent_kings_blocks_gameplay(self):
        api = AccessibleChessAPI(lang="en")
        self.assertTrue(api.clear_board()["ok"])
        self.assertTrue(api.edit_position_piece("e1", "K")["ok"])
        self.assertTrue(api.edit_position_piece("e2", "k")["ok"])
        before = api.board.fen()

        self.assertFalse(api.get_state()["positionComplete"])
        self.assertFalse(api.validate_position_editor()["ok"])

        moved = api.make_move("Ke2")
        self.assertFalse(moved["ok"])
        self.assertIn("Invalid position", moved["announcement"])
        self.assertEqual(api.board.fen(), before)

        selected = api.click_square("e1")
        self.assertFalse(selected["ok"])
        self.assertIn("Invalid position", selected["announcement"])
        self.assertEqual(api.board.fen(), before)

    def test_editor_state_with_inconsistent_en_passant_blocks_gameplay(self):
        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()

        edited = api.edit_position_metadata("w", "KQkq", "e6", "0", "1")
        self.assertTrue(edited["ok"])
        invalid_fen = api.board.fen()
        self.assertNotEqual(invalid_fen, before)
        self.assertFalse(api.get_state()["positionComplete"])
        self.assertFalse(api.validate_position_editor()["ok"])

        moved = api.make_move("e4")
        self.assertFalse(moved["ok"])
        self.assertIn("Invalid position", moved["announcement"])
        self.assertEqual(api.board.fen(), invalid_fen)

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

    def test_rejected_fen_and_metadata_inputs_remain_available_for_keyboard_correction(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("function captureRejectedEditorInput(name)", html)
        self.assertIn("function restoreRejectedEditorInput(name,snapshot)", html)
        self.assertIn("if(r&&!r.ok)restoreRejectedEditorInput(name,rejectedEditorInput)", html)
        self.assertIn("if(name==='set_fen')return{fen:el('fen-input').value}", html)
        self.assertIn("if(name==='edit_position_metadata')return{turn:el('position-turn').value", html)

    def test_editor_feedback_is_visible_and_plain_enter_is_keyboard_first(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("positionEditorActionNames=new Set", html)
        self.assertIn("setPositionEditorActionStatus(name,r&&r.announcement?r.announcement:'')", html)
        self.assertIn("el('position-square').addEventListener('keydown'", html)
        self.assertIn("el('position-piece-apply').click()", html)
        self.assertIn("el('position-metadata-apply').click()", html)

    def test_history_review_disables_live_mutation_controls_in_webview(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("const historyEndMutationIds=[...positionEditorMutationIds,'move-input','move-submit','fen-input','fen-load','undo','redo','white-turn','black-turn']", html)
        self.assertIn("historyEndMutationIds.forEach(id=>{const n=el(id);if(n)n.disabled=locked})", html)

    def test_board_render_restores_keyboard_focus_after_api_state_updates(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("restoreBoardFocus=grid.contains(document.activeElement)", html)
        self.assertIn("if(restoreBoardFocus){const next=grid.querySelectorAll('[role=gridcell]')[boardIndex];if(next)next.focus()}", html)

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

    def test_editor_feedback_is_persistent_and_plain_enter_is_keyboard_first(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("positionEditorActionNames=new Set", html)
        self.assertIn(
            "setPositionEditorActionStatus(name,r&&r.announcement?r.announcement:'')",
            html,
        )
        self.assertIn("el('position-square').addEventListener('keydown'", html)
        self.assertIn("el('position-piece-apply').click()", html)
        self.assertIn("el('position-metadata-apply').click()", html)

if __name__ == "__main__":
    unittest.main()
