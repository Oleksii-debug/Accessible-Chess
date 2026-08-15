import json
import unittest
from pathlib import Path

from acs.webapp import AccessibleChessAPI


class AccessibleWebUiTests(unittest.TestCase):
    def setUp(self):
        self.api = AccessibleChessAPI("uk")
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "web" / "index.html").read_text(encoding="utf-8")

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

    def test_locked_core_single_letter_commands_remain_compatible_defaults(self):
        self.assertTrue(self.api.make_move("b")["ok"])
        self.assertEqual(self.api.board.turn, "b")
        self.assertTrue(self.api.make_move("w")["ok"])
        self.assertEqual(self.api.board.turn, "w")
        self.assertTrue(self.api.make_move("e")["ok"])
        self.assertTrue(self.api.engine_enabled)
        self.assertTrue(self.api.make_move("c")["ok"])
        self.assertFalse(self.api.get_state()["positionComplete"])
        self.assertTrue(self.api.make_move("s")["ok"])
        self.assertTrue(self.api.get_state()["positionComplete"])
        self.assertFalse(self.api.make_move("d")["ok"])
        self.assertFalse(self.api.make_move("x")["ok"])

    def test_text_position_editor_round_trip(self):
        text = "W: K g1 Q d1 R a1 R f1 B c4 N f3 P e4 B: K g8 Q d8 N f6"
        r = self.api.set_position_text(text, "b")
        self.assertTrue(r["ok"])
        self.assertEqual(self.api.board.turn, "b")
        self.assertEqual(self.api.square_label("g1"), "g 1, білий король")
        self.assertEqual(self.api.square_label("g8"), "g 8, чорний король")

    def test_clear_board_is_safe_in_accessible_state(self):
        r = self.api.clear_board()
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["board"]), 64)
        self.assertEqual(r["whitePieces"], "фігур немає")
        self.assertFalse(r["positionComplete"])

    def test_api_language_switch_changes_state_and_square_speech(self):
        r = self.api.set_language("en")
        self.assertTrue(r["ok"])
        self.assertEqual(self.api.square_label("e2"), "e 2, white pawn")
        self.assertEqual(r["gameStatus"], "White to move")

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
            'role="application" aria-label="Шахова дошка" aria-describedby="board-help"',
            'role="grid" aria-label="64 поля шахової дошки" aria-rowcount="8" aria-colcount="8"',
            "node.setAttribute('aria-rowindex'", "node.setAttribute('aria-colindex'",
        ):
            self.assertIn(marker, self.html)
        self.assertNotIn("<canvas", self.html.lower())

    def test_runtime_ua_en_language_contract(self):
        self.assertIn('id="language-select"', self.html)
        self.assertIn("el('language-select').addEventListener('change'", self.html)
        self.assertIn("apiAction('set_language',e.target.value)", self.html)
        self.assertIn("function applyUiLanguage(lang)", self.html)
        self.assertIn("document.documentElement.lang=lang==='en'?'en':'uk'", self.html)

    def test_board_coordinate_navigation_no_longer_steals_a_or_d(self):
        self.assertNotIn("/^[a-hA-H]$/.test(key)", self.html)
        self.assertIn("/^[1-8]$/.test(key)&&!e.shiftKey", self.html)
        self.assertIn("/^[1-8]$/.test(key)&&e.shiftKey", self.html)
        self.assertIn("actionByChord(eventChord(e),'board')", self.html)
        data = json.loads((self.root / "web" / "keybindings.json").read_text(encoding="utf-8"))
        by_id = {x["id"]: x for x in data["actions"]}
        self.assertEqual(by_id["board.attackers"]["binding"], "A")
        self.assertEqual(by_id["board.defenders"]["binding"], "D")

    def test_remappable_keybinding_editor_is_accessible_and_recoverable(self):
        for marker in (
            '<h3 id="h-keyboard">Клавіатура і команди</h3>',
            'id="key-search" type="search"', 'id="key-context"',
            'id="key-reset-context" type="button"', 'id="key-reset-all" type="button"',
            'id="key-export" type="button"', 'id="key-import" type="file"',
            'id="key-capture-help" class="sr-note"', 'id="key-list" class="binding-list"',
            "localStorage.setItem(storageKey()", "function conflictsFor(item,value)",
            "function renderHelp()", "function beginCapture(item,inp,status,button)",
            "function stopCapture(cancelled=false)", "captureButton.setAttribute('aria-pressed','false')",
            "if(e.key==='Escape')", "if(e.key==='Tab')return",
        ):
            self.assertIn(marker, self.html)
        self.assertIn("NVDA", self.html)
        self.assertIn("H/B/E/F", self.html)

    def test_shortcut_capture_does_not_claim_nvda_browse_keys(self):
        self.assertIn("Press new shortcut", self.html)
        self.assertIn("Натиснути нову комбінацію", self.html)
        self.assertIn("Escape скасовує захоплення", self.html)
        self.assertIn("NVDA browse keys H/B/E/F belong to NVDA", self.html)
        self.assertNotIn("H/B/E/F can be remapped", self.html)

    def test_context_reset_is_scoped_and_has_recovery_when_no_context_selected(self):
        self.assertIn("el('key-context').addEventListener('change',renderKeymap)", self.html)
        self.assertIn("el('key-reset-context').addEventListener('click'", self.html)
        self.assertIn("if(!ctx){announce(en?'Choose a context first.'", self.html)
        self.assertIn("(item.registryContext||item.context)===ctx", self.html)
        self.assertIn("keymap=keymapBase.actions.map", self.html)

    def test_keybinding_defaults_are_centralized_outside_main_html(self):
        compact = self.html.replace(" ", "").replace("\n", "")
        self.assertNotIn("Shift+A—", self.html)
        self.assertNotIn("Ctrl+G—", self.html)
        data = json.loads((self.root / "web" / "keybindings.json").read_text(encoding="utf-8"))
        by_id = {x["id"]: x for x in data["actions"]}
        self.assertEqual(by_id["history.previous"]["binding"], "Shift+A")
        self.assertEqual(by_id["history.next"]["binding"], "Shift+D")
        self.assertEqual(by_id["history.go_to_move"]["binding"], "Ctrl+G")
        self.assertEqual(by_id["move.black_to_move"]["alias"], "b")
        self.assertEqual(by_id["move.clear"]["alias"], "c")
        self.assertNotIn("history.goto", by_id)
        self.assertNotIn("game.undo", by_id)
        self.assertNotIn("move.engine", by_id)
        self.assertTrue(compact)

    def test_ui_dispatch_uses_stable_central_action_ids(self):
        for action_id in (
            "history.go_to_move", "edit.undo", "edit.redo",
            "move.white_to_move", "move.black_to_move", "move.empty",
            "board.last_captured", "board.best_move", "board.play_best",
        ):
            self.assertIn(action_id, self.html if action_id in {"history.go_to_move", "edit.undo", "edit.redo", "move.white_to_move", "move.black_to_move", "move.empty"} else (self.root / "web" / "keybindings.json").read_text(encoding="utf-8"))
        for legacy in ("history.goto", "game.undo", "game.redo", "move.white'", "move.black'", "move.engine"):
            self.assertNotIn(legacy, self.html)

    def test_live_region_contract_avoids_background_speech_spam(self):
        self.assertIn('role="status" aria-live="polite" aria-atomic="true" aria-relevant="text"', self.html)
        self.assertIn('id="game-info" class="block" aria-live="off"', self.html)
        self.assertIn('id="moves" class="block" aria-live="off"', self.html)
        self.assertIn('id="engine-status" class="block" aria-live="off"', self.html)
        self.assertIn("message===lastAnnouncement&&now-lastAnnouncementAt<500", self.html)
        self.assertIn("live.setAttribute('aria-busy','true')", self.html)
        self.assertIn("live.setAttribute('aria-busy','false')", self.html)


if __name__ == "__main__":
    unittest.main()
