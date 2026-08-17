from __future__ import annotations

import unittest
from pathlib import Path

from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI, complete_user_flow_diagnostic


class Stage1PackagedFocusOriginContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.bootstrap = (self.root / "web" / "stage1_release_bootstrap.js").read_text(encoding="utf-8")

    def test_complete_stage1_user_flow_still_covers_canonical_state_history_fen_editor_and_sound_contract(self) -> None:
        api = Stage1ReleaseAccessibleChessAPI()
        result = complete_user_flow_diagnostic(api)
        self.assertTrue(result["ok"], result)
        checks = result["checks"]
        for name in (
            "startup",
            "initial_focus_semantics",
            "e4",
            "e4_board",
            "black_to_move",
            "invalid_move_atomic",
            "invalid_move_concise",
            "history_review",
            "history_return",
            "undo",
            "redo",
            "fen_error_concise",
            "fen_load",
            "editor_load",
            "editor_error_concise",
            "square_error_concise",
            "final_board_64",
            "no_raw_exception_text",
            "sound_settings_contract",
        ):
            self.assertTrue(checks[name], name)
        self.assertEqual(result["boardCells"], 64)

    def test_board_origin_is_semantic_state_not_active_element_only(self) -> None:
        text = self.bootstrap
        self.assertIn("const focusState = window.__accessibleChessStage1FocusState", text)
        self.assertIn("function rememberBoardFocus(cell)", text)
        self.assertIn("focusState.context = 'board'", text)
        self.assertIn("focusState.boardSquare = cell.dataset.square || ''", text)
        self.assertIn("function rememberMoveInputFocus()", text)
        self.assertIn("focusState.context = 'move'", text)
        self.assertIn("input.addEventListener('focusin', rememberMoveInputFocus)", text)
        self.assertIn("focusState.context === 'board' ? focusState.boardSquare : ''", text)
        self.assertIn("const result = await baseSubmit.apply(this, args)", text)
        self.assertIn("rememberBoardFocus(target)", text)

    def test_uia_invoke_can_preserve_last_semantic_board_square_without_global_keyboard_hijack(self) -> None:
        text = self.bootstrap
        # The submit button deliberately does not overwrite the semantic focus
        # context. UIA ValuePattern.SetValue + Invoke can therefore keep the
        # last actual board square as the origin even when activeElement is no
        # longer that gridcell by the time submitMove executes.
        self.assertNotIn("button.addEventListener('focusin'", text)
        self.assertNotIn("button.addEventListener('click'", text)
        self.assertIn("activeBoardSquare || (", text)
        self.assertIn("focusState.context === 'board'", text)
        self.assertNotIn("document.addEventListener('keydown'", text)
        self.assertNotIn("window.addEventListener('keydown'", text)

    def test_rerender_recovery_and_submit_recovery_share_the_same_board_context(self) -> None:
        text = self.bootstrap
        self.assertIn("if (!focusState.boardNode || board.hidden) return", text)
        self.assertIn("node === focusState.boardNode", text)
        self.assertIn("focusState.boardSquare ? byId('sq-' + focusState.boardSquare) : null", text)
        self.assertIn("target.focus({preventScroll: true})", text)
        self.assertIn("rememberBoardFocus(target)", text)
        self.assertIn("observer.observe(grid, {childList: true})", text)

    def test_normal_move_entry_remains_authoritative_after_user_focuses_edit(self) -> None:
        text = self.bootstrap
        self.assertIn("input.addEventListener('focusin', rememberMoveInputFocus)", text)
        self.assertIn("focusState.boardSquare = ''", text)
        self.assertIn("focusState.boardNode = null", text)
        self.assertIn("form.addEventListener('submit'", text)
        self.assertIn("event.preventDefault()", text)
        self.assertIn("await window.submitMove()", text)
        self.assertIn("form.dataset.submitting === 'true'", text)
        self.assertIn("form.setAttribute('aria-busy', 'true')", text)


if __name__ == "__main__":
    unittest.main()
