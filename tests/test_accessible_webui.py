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
            'class="skip-link" href="#main-content"', '<main id="main-content">',
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

    def test_one_live_region_only_and_no_no_conflict_spam(self):
        self.assertEqual(self.html.count('aria-live="polite"'), 1)
        self.assertIn('id="live" role="status" aria-live="polite"', self.html)
        self.assertNotIn('status.setAttribute(\'role\',\'status\')', self.html)
        self.assertNotIn("Конфліктів немає", self.html)
        self.assertNotIn("No conflicts.", self.html)

    def test_move_enter_success_clears_and_refocuses_input(self):
        self.assertIn("const r=await apiAction('make_move',v)", self.html)
        self.assertIn("if(r&&r.ok){input.value='';input.focus()}", self.html)
        self.assertIn("else{input.focus();input.select()}", self.html)
        marker = "el('move-input').addEventListener('keydown'"
        start = self.html.index(marker)
        end = self.html.index("el('fen-load')", start)
        handler = self.html[start:end]
        legacy_enter = "if(e.key==='Enter')" in handler and "submitMove()" in handler
        direct_registry = (
            "resolveBinding(eventChord(e),'move_entry','move-entry')" in handler
            and "a.actionId==='move.submit'" in handler
            and "executeAction(a.actionId)" in handler
        )
        cached_registry = (
            "keymapActionForEvent(e,'move_entry')" in handler
            and "resolveBinding(chord,'move_entry','move-entry')" in handler
            and "a&&a.actionId===candidate" in handler
            and "executeAction(a.actionId)" in handler
        )
        self.assertTrue(legacy_enter or direct_registry or cached_registry, handler)
        self.assertIn("e.preventDefault()", handler)
        if direct_registry or cached_registry:
            self.assertIn("'move.submit':()=>submitMove()", self.html)
            self.assertNotIn("if(e.key==='Enter')", handler)

    def test_copy_and_selection_are_not_hijacked(self):
        self.assertIn("String(e.key).toLowerCase()==='c'", self.html)
        self.assertIn("selection&&selection.toString()", self.html)
        self.assertIn("['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)", self.html)

    def test_analysis_hotkeys_remain_available_in_editable_controls(self):
        self.assertIn("function editableShortcutTarget(node)", self.html)
        self.assertIn("if(editable&&!e.altKey)return", self.html)
        self.assertIn("let a=await resolveBinding(chord,'analysis','analysis')", self.html)
        self.assertIn(
            "if(editable&&a&&a.context!=='analysis'&&!String(a.actionId||'').startsWith('analysis.'))a=null",
            self.html,
        )
        self.assertIn("if(!editable&&!a)a=await resolveBinding(chord,'history','document')", self.html)
        self.assertIn("if(!editable&&!a)a=await resolveBinding(chord,'document','document')", self.html)
        self.assertIn("e.stopPropagation();executeAction(a.actionId)", self.html)

    def test_modified_board_and_pgn_tree_chords_reach_central_keymap(self):
        board_start = self.html.index("async function onBoardKey(e)")
        board_end = self.html.index("function enterBoard(", board_start)
        board = self.html[board_start:board_end]
        self.assertIn(
            "modified=e.altKey||e.ctrlKey||e.shiftKey||e.metaKey",
            board,
        )
        self.assertIn(
            "if(modified){const mapped=await resolveBinding(eventChord(e),'board','board')",
            board,
        )
        self.assertLess(
            board.index("if(modified){const mapped=await resolveBinding"),
            board.index("if(!modified&&key==='Escape')"),
        )
        self.assertIn("if(!modified&&key==='ArrowUp')", board)
        self.assertIn("if(!modified&&key==='ArrowDown')", board)
        self.assertIn("e.stopPropagation();executeAction(mapped.actionId)", board)

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
