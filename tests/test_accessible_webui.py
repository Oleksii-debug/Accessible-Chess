import json
import unittest
from pathlib import Path

from acs.webapp import AccessibleChessAPI


class AccessibleWebUiTests(unittest.TestCase):
    def setUp(self):
        self.api = AccessibleChessAPI("uk")
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "web" / "index.html").read_text(encoding="utf-8")
        self.pgn_js = (self.root / "web" / "full_product_pgn.js").read_text(encoding="utf-8")

    def test_board_has_64_cells(self):
        self.assertEqual(len(self.api.get_state()["board"]), 64)

    def test_empty_and_occupied_square_speech(self):
        self.assertEqual(self.api.square_label("e4"), "e 4")
        self.assertEqual(self.api.square_label("e2"), "e 2, білий пішак")

    def test_move_entry_and_board_move_share_same_core(self):
        r = self.api.make_move("e4")
        self.assertTrue(r["ok"])
        self.assertIn("e 4", r["lastMove"])
        self.api.undo()
        self.api.activate_square("e2")
        r = self.api.activate_square("e4")
        self.assertTrue(r["ok"])
        self.assertIn("e 4", r["lastMove"])

    def test_text_position_editor_round_trip(self):
        text = "W: K g1 Q d1 R a1 R f1 B c4 N f3 P e4 B: K g8 Q d8 N f6"
        r = self.api.set_position_text(text, "b")
        self.assertTrue(r["ok"])
        self.assertEqual(self.api.board.turn, "b")

    def test_locked_first_ten_h2_order_is_exact(self):
        ids = [
            "h-game-info", "h-moves", "h-white", "h-black", "h-status",
            "h-last", "h-input", "h-engine", "h-board", "h-actions",
        ]
        positions = [self.html.index(f'<h2 id="{x}"') for x in ids]
        self.assertEqual(positions, sorted(positions))
        first_settings = self.html.index('<h2 id="h-settings"')
        self.assertTrue(all(p < first_settings for p in positions))
        self.assertIn('<h3 id="h-history">', self.html)
        self.assertNotIn('<h2 id="h-history">', self.html)

    def test_semantic_html_contract(self):
        for heading in [
            "Інформація про гру", "Список ходів", "Білі фігури", "Чорні фігури",
            "Стан гри / позиції", "Останній хід", "Введення ходу", "Аналіз Stockfish",
            "Дошка", "Дії", "Налаштування",
        ]:
            self.assertIn(f">{heading}<", self.html)
        for marker in (
            '<main id="main-content">',
            'id="move-input" type="text"', 'id="position-input"',
            'id="position-load" type="button"', 'id="empty-board" type="button"',
            'id="board-launcher" type="button"',
            'role="application" aria-label="Шахова дошка"',
            'role="grid" aria-label="64 поля шахової дошки" aria-rowcount="8" aria-colcount="8"',
            "node.setAttribute('aria-rowindex'", "node.setAttribute('aria-colindex'",
        ):
            self.assertIn(marker, self.html)
        self.assertNotIn("<canvas", self.html.lower())

    def test_human_nvda_main_document_is_clean(self):
        forbidden = (
            "Семантичний документ Edge/WebView2",
            "Команди історії налаштовуються",
            "У режимі огляду NVDA",
            "Приклади: e4",
            "W:/B:",
            "Усі команди Accessible Chess налаштовуються",
            "Перенесення MultiPV",
            "migration is still in progress",
            "ValueError:",
        )
        for text in forbidden:
            with self.subTest(text=text):
                self.assertNotIn(text, self.html)
        for control in ("move-input", "history-input", "position-input", "board-launcher", "board-application"):
            fragment = self.html[self.html.index(f'id="{control}"'):self.html.index(f'id="{control}"') + 250]
            self.assertNotIn("aria-describedby", fragment)

    def test_help_dialog_focus_target_is_programmatically_focusable(self):
        self.assertIn(
            '<h2 id="help-title" tabindex="-1">Довідка</h2>',
            self.html,
        )
        self.assertIn(
            '<div id="help" class="block" aria-live="off"></div>',
            self.html,
        )
        self.assertIn(
            "el('open-help').addEventListener('click',()=>{el('help-dialog').showModal();el('help-title').focus()})",
            self.html,
        )
        self.assertIn(
            "el('help-dialog').addEventListener('close',()=>el('open-help').focus())",
            self.html,
        )

    def test_keymap_dialog_restores_opener_focus_after_close(self):
        self.assertIn(
            "el('open-keymap').addEventListener('click',()=>{el('keymap-dialog').showModal();el('key-search').focus()})",
            self.html,
        )
        self.assertIn(
            "el('keymap-dialog').addEventListener('close',()=>{stopCapture(false);el('open-keymap').focus()})",
            self.html,
        )

    def test_engine_game_dialog_start_and_cancel_focus_are_atomic(self):
        self.assertIn(
            "let engineGameStartInFlight=false,engineGameReturnFocusOnClose=false;",
            self.html,
        )
        self.assertIn(
            "if(engineGameStartInFlight)return;const button=el('engine-game-start'),cancel=el('engine-game-cancel')",
            self.html,
        )
        self.assertIn(
            "engineGameStartInFlight=true;button.disabled=true;if(cancel)cancel.disabled=true",
            self.html,
        )
        self.assertIn(
            "engineGameReturnFocusOnClose=false;el('engine-game-dialog').close();el('move-input').focus()",
            self.html,
        )
        self.assertIn(
            "finally{engineGameStartInFlight=false;button.disabled=false;if(cancel)cancel.disabled=false}",
            self.html,
        )
        self.assertIn(
            "el('engine-game-dialog').addEventListener('cancel',e=>{if(engineGameStartInFlight)e.preventDefault()})",
            self.html,
        )
        self.assertIn(
            "el('engine-game-dialog').addEventListener('close',()=>{const restore=engineGameReturnFocusOnClose;engineGameReturnFocusOnClose=false;if(restore)el('engine-play-open').focus()})",
            self.html,
        )

    def test_one_live_region_only_and_no_no_conflict_spam(self):
        self.assertEqual(self.html.count('aria-live="polite"'), 1)
        self.assertIn('id="live" role="status" aria-live="polite"', self.html)
        self.assertIn(
            '<dialog id="keymap-dialog" aria-labelledby="h-keyboard" aria-describedby="key-recovery-status">',
            self.html,
        )
        self.assertIn('<div id="key-recovery-status" class="block" hidden></div>', self.html)
        self.assertNotIn('id="key-recovery-status" class="block" role="status"', self.html)
        self.assertNotIn('status.setAttribute(\'role\',\'status\')', self.html)
        self.assertNotIn("Конфліктів немає", self.html)
        self.assertNotIn("No conflicts.", self.html)

    def test_move_submit_uses_canonical_remappable_action_and_preserves_input_contract(self):
        self.assertIn("const r=await apiAction('make_move',v)", self.html)
        self.assertIn("if(r&&r.ok){input.value='';input.focus()}", self.html)
        self.assertIn("else{input.focus();input.select()}", self.html)
        self.assertIn("el('move-input').addEventListener('keydown'", self.html)
        self.assertIn("candidate=keymapActionForEvent(e,'move_entry')", self.html)
        self.assertIn("if(candidate!=='move.submit')return", self.html)
        self.assertIn("e.preventDefault();e.stopPropagation()", self.html)
        self.assertIn("resolveBinding(chord,'move_entry','move-entry')", self.html)
        self.assertIn("if(a&&a.actionId===candidate)executeAction(a.actionId)", self.html)

    def test_copy_and_selection_are_not_hijacked(self):
        self.assertIn("String(e.key).toLowerCase()==='c'", self.html)
        self.assertIn("selection&&selection.toString()", self.html)
        self.assertIn("['INPUT','TEXTAREA','SELECT'].includes(node.tagName)", self.html)
        self.assertIn("function editableShortcutTarget(node)", self.html)

    def test_analysis_hotkeys_claim_sync_then_validate_canonical_action(self):
        self.assertIn("function projectedOwnedAction(e,contexts)", self.html)
        self.assertIn("function claimOwnedKey(e){e.preventDefault();e.stopPropagation()}", self.html)
        self.assertIn("if(editable){const projectedHelp=projectedOwnedAction(e,['global'])", self.html)
        self.assertIn("if(!e.altKey)return", self.html)
        self.assertIn("const projectedAnalysis=projectedOwnedAction(e,['analysis'])", self.html)
        self.assertIn("claimOwnedKey(e);const analysis=await resolveBinding(chord,'analysis','analysis')", self.html)
        self.assertIn("analysis.actionId===projectedAnalysis", self.html)
        self.assertIn("analysis.context==='analysis'||String(analysis.actionId||'').startsWith('analysis.')", self.html)
        self.assertIn("const projectedAction=projectedOwnedAction(e,['analysis','global','history','document'])", self.html)
        self.assertIn("let a=await resolveBinding(chord,'analysis','analysis')", self.html)
        self.assertIn("if(!a)a=await resolveBinding(chord,'history','document')", self.html)
        self.assertIn("if(!a)a=await resolveBinding(chord,'document','document')", self.html)

    def test_board_dispatch_uses_canonical_board_analysis_global_precedence(self):
        board_start = self.html.index("async function onBoardKey(e)")
        board_end = self.html.index("function focusHistoryJump(", board_start)
        board = self.html[board_start:board_end]
        self.assertIn("for(const context of ['board','analysis','global'])", board)
        self.assertIn("const projected=keymapActionForEvent(e,context)", board)
        self.assertIn("if(projected===null)return", board)
        self.assertIn("if(projected){candidate=projected;break}", board)
        self.assertIn("if(!candidate)return", board)
        self.assertIn("e.preventDefault();e.stopPropagation()", board)
        self.assertIn("const a=await resolveBinding(chord,'board','board')", board)
        self.assertIn("if(a&&a.actionId===candidate)executeAction(a.actionId)", board)
        self.assertLess(
            board.index("e.preventDefault();e.stopPropagation()"),
            board.index("await resolveBinding(chord,'board','board')"),
        )

        modifier_guard = (
            'if (event.altKey || event.ctrlKey || event.shiftKey || event.metaKey) return;'
        )
        self.assertIn(modifier_guard, self.pgn_js)
        self.assertLess(
            self.pgn_js.index(modifier_guard),
            self.pgn_js.index('if (event.key === "ArrowUp")'),
        )

    def test_keymap_editor_is_out_of_main_flow_and_passive_validation_is_silent(self):
        self.assertIn('<dialog id="keymap-dialog"', self.html)
        self.assertIn('id="open-keymap" type="button"', self.html)
        self.assertIn('id="key-list" class="binding-list"', self.html)
        self.assertIn("typeof a.keymap_snapshot==='function'", self.html)
        self.assertIn("typeof a.keymap_preview==='function'", self.html)
        self.assertIn("typeof a.keymap_save==='function'", self.html)
        self.assertNotIn("updatePreview(item,inp,status);", self.html)

    def test_language_and_central_keymap_contracts_remain(self):
        self.assertIn('id="language-select"', self.html)
        self.assertIn("el('language-select').addEventListener('change'", self.html)
        self.assertIn("apiAction('set_language',e.target.value)", self.html)
        self.assertIn("function applyUiLanguage(lang)", self.html)
        self.assertNotIn("localStorage.setItem", self.html)
        self.assertNotIn("localStorage.getItem", self.html)
        data = json.loads((self.root / "web" / "keybindings.json").read_text(encoding="utf-8"))
        by_id = {x["id"]: x for x in data["actions"]}
        self.assertEqual(by_id["history.previous"]["binding"], "Shift+A")
        self.assertEqual(by_id["history.next"]["binding"], "Shift+D")
        self.assertEqual(by_id["history.go_to_move"]["binding"], "Ctrl+G")

    def test_live_region_contract_avoids_background_speech_spam(self):
        self.assertIn('role="status" aria-live="polite" aria-atomic="true" aria-relevant="text"', self.html)
        self.assertIn('id="game-info" class="block" aria-live="off"', self.html)
        self.assertIn('id="moves" class="block" aria-live="off"', self.html)
        self.assertIn('id="engine-status" class="block" aria-live="off"', self.html)
        self.assertIn("rememberedAnnouncementEvents.has(eventKey)", self.html)
        self.assertIn("rememberedAnnouncementEventOrder.length>256", self.html)
        self.assertIn("recentAnnouncements=recentAnnouncements.filter(item=>now-item.at<500)", self.html)
        self.assertIn("recentAnnouncements.some(item=>item.message===message)", self.html)


if __name__ == "__main__":
    unittest.main()
