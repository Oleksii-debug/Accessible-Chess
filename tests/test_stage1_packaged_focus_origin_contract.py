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

    def test_complete_board_contract_has_64_unique_semantic_square_tokens(self) -> None:
        api = Stage1ReleaseAccessibleChessAPI()
        state = api.new_game()
        board = state.get("board") or []
        squares = [str(cell.get("square") or "") for cell in board]
        expected = {f"{file}{rank}" for file in "abcdefgh" for rank in "12345678"}
        self.assertEqual(len(board), 64)
        self.assertEqual(len(set(squares)), 64)
        self.assertEqual(set(squares), expected)

    def test_packaged_move_edit_never_leaves_its_initial_dom_parent_or_identity(self) -> None:
        text = self.bootstrap
        self.assertIn('<label for="move-input">Хід</label>', self.html)
        self.assertIn('<input id="move-input" type="text"', self.html)
        self.assertIn("function installMoveEntryIdentity()", text)
        self.assertIn("input.addEventListener('focusin', rememberMoveInputFocus)", text)
        self.assertIn("stage1MoveIdentityReady", text)
        self.assertNotIn("oldInput.cloneNode", text)
        self.assertNotIn("form.appendChild(input)", text)
        self.assertNotIn("row.replaceWith", text)
        self.assertNotIn("document.createElement('form')", text)
        # The original document owns Enter and button dispatch for the same
        # persistent Edit node; the release bootstrap only observes focus.
        self.assertIn("el('move-submit').addEventListener('click',submitMove)", self.html)
        self.assertIn("el('move-input').addEventListener('keydown'", self.html)

    def test_packaged_move_edit_has_explicit_short_uia_name_independent_of_label_projection(self) -> None:
        text = self.bootstrap
        self.assertIn("function moveEntryLabels()", text)
        self.assertIn("function stabilizeMoveEntryUiaSemantics()", text)
        self.assertIn("input.setAttribute('aria-label', labels.input)", text)
        self.assertIn("button.setAttribute('aria-label', labels.submit)", text)
        self.assertIn("data-stage1-uia-role", text)
        self.assertIn("stage1MoveUiaSemanticsReady", text)
        self.assertIn("? {input: 'Move', submit: 'Make move'}", text)
        self.assertIn(": {input: 'Хід', submit: 'Зробити хід'}", text)
        # Keep the normal concise HTML label too; aria-describedby must not be
        # used to inject tutorial prose when the Edit receives focus.
        self.assertIn('<label for="move-input">Хід</label>', self.html)
        move_markup = self.html.split('<input id="move-input"', 1)[1].split('>', 1)[0]
        self.assertNotIn("aria-describedby", move_markup)

    def test_packaged_move_uia_semantics_are_ready_before_release_ready_marker_and_follow_language(self) -> None:
        text = self.bootstrap
        install = text.index("installMoveEntryIdentity();")
        ready = text.index("if (api()) markReady();")
        self.assertLess(install, ready)
        mark_ready = text[text.index("async function markReady()"):text.index("installMoveFocusPolicy();")]
        self.assertIn("stabilizeMoveEntryUiaSemantics();", mark_ready)
        self.assertIn("document.body.dataset.stage1AppReady = 'true'", mark_ready)
        self.assertLess(
            mark_ready.index("stabilizeMoveEntryUiaSemantics();"),
            mark_ready.index("stage1AppReady = 'true'"),
        )
        self.assertIn("function refreshReleaseLanguageSemantics()", text)
        self.assertIn("stabilizeMoveEntryUiaSemantics();", text[text.index("function refreshReleaseLanguageSemantics()"):])
        self.assertIn("new MutationObserver(refreshReleaseLanguageSemantics)", text)

    def test_packaged_board_uia_names_contain_compact_coordinate_without_automation_id_dependency(self) -> None:
        text = self.bootstrap
        self.assertIn("function stableBoardAccessibleName(cell)", text)
        self.assertIn("function stabilizeBoardUiaSemantics(grid = byId('board-grid'))", text)
        self.assertIn("/^[a-h][1-8]$/", text)
        self.assertIn("cell.setAttribute('aria-label', stableBoardAccessibleName(cell))", text)
        self.assertIn("cell.setAttribute('data-accessible-square', square)", text)
        self.assertIn("stage1BoardUiaSemanticsReady", text)
        self.assertIn("queueMicrotask(() => stabilizeBoardUiaSemantics(grid))", text)

    def test_board_origin_is_semantic_state_not_active_element_only(self) -> None:
        text = self.bootstrap
        self.assertIn("const focusState = window.__accessibleChessStage1FocusState", text)
        self.assertIn("function rememberBoardFocus(cell)", text)
        self.assertIn("focusState.context = 'board'", text)
        self.assertIn("focusState.boardSquare = cell.dataset.square || ''", text)
        self.assertIn("function rememberMoveInputFocus()", text)
        self.assertIn("focusState.context = 'move'", text)
        self.assertIn("focusState.context === 'board' ? focusState.boardSquare : ''", text)
        self.assertIn("const result = await baseSubmit.apply(this, args)", text)
        self.assertIn("settleBoardFocusAfterInvoke(boardSquare)", text)

    def test_uia_invoke_has_bounded_settled_focus_convergence(self) -> None:
        text = self.bootstrap
        self.assertIn("function settleBoardFocusAfterInvoke(square)", text)
        self.assertIn("function restoreBoardSquare(square, generation)", text)
        self.assertIn("focusState.restoreGeneration", text)
        self.assertIn("setTimeout(() => restoreBoardSquare(square, generation), 0)", text)
        self.assertIn("setTimeout(() => restoreBoardSquare(square, generation), 50)", text)
        self.assertIn("target.focus({preventScroll: true})", text)
        self.assertIn("rememberBoardFocus(target)", text)

    def test_move_edit_focus_cancels_pending_board_restore(self) -> None:
        text = self.bootstrap
        start = text.index("function rememberMoveInputFocus()")
        end = text.index("function restoreBoardSquare", start)
        body = text[start:end]
        self.assertIn("focusState.context = 'move'", body)
        self.assertIn("focusState.boardSquare = ''", body)
        self.assertIn("focusState.boardNode = null", body)
        self.assertIn("focusState.restoreGeneration += 1", body)

    def test_copy_selection_and_document_shortcuts_are_not_newly_hijacked(self) -> None:
        text = self.bootstrap
        self.assertNotIn("document.addEventListener('keydown'", text)
        self.assertNotIn("window.addEventListener('keydown'", text)
        self.assertNotIn("event.key === 'c'", text)
        self.assertNotIn("event.key === 'a'", text)

    def test_rerender_recovery_and_submit_recovery_share_same_board_context(self) -> None:
        text = self.bootstrap
        self.assertIn("if (!focusState.boardNode || board.hidden) return", text)
        self.assertIn("node === focusState.boardNode", text)
        self.assertIn("focusState.boardSquare ? byId('sq-' + focusState.boardSquare) : null", text)
        self.assertIn("observer.observe(grid, {childList: true})", text)
        self.assertIn("stabilizeBoardUiaSemantics(grid)", text)
        self.assertIn("settleBoardFocusAfterInvoke", text)

    def test_normal_move_entry_remains_authoritative_in_original_document(self) -> None:
        self.assertIn("async function submitMove()", self.html)
        self.assertIn("if(r&&r.ok){input.value='';input.focus()}else{input.focus();input.select()}", self.html)
        self.assertIn("el('move-submit').addEventListener('click',submitMove)", self.html)
        self.assertIn("if(e.key==='Enter'){e.preventDefault();submitMove()}", self.html)
        self.assertIn("input.addEventListener('focusin', rememberMoveInputFocus)", self.bootstrap)


if __name__ == "__main__":
    unittest.main()
