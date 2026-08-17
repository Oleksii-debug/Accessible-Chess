from __future__ import annotations

import unittest
from pathlib import Path

from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI, complete_user_flow_diagnostic


class Stage1PackagedFocusOriginContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.bootstrap = (self.root / "web" / "stage1_release_bootstrap.js").read_text(encoding="utf-8")
        self.html = (self.root / "web" / "index.html").read_text(encoding="utf-8")

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

    def test_packaged_move_edit_preserves_initial_dom_uia_identity_and_label(self) -> None:
        text = self.bootstrap
        self.assertIn('<label for="move-input">Хід</label>', self.html)
        self.assertIn('<input id="move-input" type="text"', self.html)
        self.assertIn("const input = oldInput;", text)
        self.assertNotIn("const input = oldInput.cloneNode(true)", text)
        self.assertIn("const button = oldButton.cloneNode(true)", text)
        # The release upgrade moves the existing edit node into the form. This
        # keeps WebView2/UIA provider identity stable while replacing only the
        # legacy button listener.
        self.assertIn("form.appendChild(input)", text)
        self.assertIn("row.replaceWith(form)", text)

    def test_release_enter_capture_replaces_only_legacy_enter_dispatch(self) -> None:
        text = self.bootstrap
        self.assertIn("input.addEventListener('keydown', event =>", text)
        self.assertIn("if (event.key !== 'Enter') return", text)
        self.assertIn("event.stopImmediatePropagation()", text)
        self.assertIn("form.requestSubmit(button)", text)
        self.assertIn("}, true);", text)
        # Copy/select shortcuts are not intercepted by this release handler.
        self.assertNotIn("event.key === 'c'", text)
        self.assertNotIn("event.key === 'a'", text)

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
        self.assertIn("settleBoardFocusAfterInvoke(boardSquare)", text)

    def test_uia_invoke_has_a_settled_focus_phase_after_submit_handler_returns(self) -> None:
        text = self.bootstrap
        self.assertIn("function settleBoardFocusAfterInvoke(square)", text)
        self.assertIn("function restoreBoardSquare(square, generation)", text)
        self.assertIn("focusState.restoreGeneration", text)
        self.assertIn("restoreBoardSquare(square, generation);", text)
        self.assertIn("setTimeout(() => restoreBoardSquare(square, generation), 0)", text)
        self.assertIn("target.focus({preventScroll: true})", text)
        self.assertIn("rememberBoardFocus(target)", text)
        self.assertNotIn("requestAnimationFrame(() => document.activeElement", text)

    def test_move_edit_focus_cancels_a_pending_deferred_board_restore(self) -> None:
        text = self.bootstrap
        start = text.index("function rememberMoveInputFocus()")
        end = text.index("function restoreBoardSquare", start)
        move_focus_body = text[start:end]
        self.assertIn("focusState.context = 'move'", move_focus_body)
        self.assertIn("focusState.boardSquare = ''", move_focus_body)
        self.assertIn("focusState.boardNode = null", move_focus_body)
        self.assertIn("focusState.restoreGeneration += 1", move_focus_body)

    def test_uia_invoke_can_preserve_last_semantic_board_square_without_global_keyboard_hijack(self) -> None:
        text = self.bootstrap
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
        self.assertIn("settleBoardFocusAfterInvoke", text)

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
