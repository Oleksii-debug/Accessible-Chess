from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from acs.webapp_keymap import KeymapAwareAccessibleChessAPI, _asset_root


HTML = (_asset_root() / "web" / "index.html").read_text(encoding="utf-8")


class Issue22ReleaseContractTests(unittest.TestCase):
    def test_issue22_forbidden_user_facing_strings_are_absent(self):
        forbidden = (
            "Семантичний документ Edge/WebView2",
            "Команди історії налаштовуються",
            "Перенесення MultiPV",
            "migration is still in progress",
            "ValueError:",
        )
        for text in forbidden:
            self.assertNotIn(text, HTML)

    def test_passive_no_conflict_state_is_not_a_live_announcement(self):
        self.assertNotIn("Конфліктів немає", HTML)
        self.assertNotIn("No conflicts.", HTML)
        self.assertEqual(HTML.count('aria-live="polite"'), 1)
        self.assertIn('id="live" role="status" aria-live="polite"', HTML)

    def test_move_entry_enter_contract_clears_only_on_success_and_refocuses(self):
        self.assertIn("const r=await apiAction('make_move',v)", HTML)
        self.assertIn("if(r&&r.ok){input.value='';input.focus()}", HTML)
        self.assertIn("else{input.focus();input.select()}", HTML)
        self.assertIn("el('move-input').addEventListener('keydown'", HTML)
        self.assertIn("if(e.key==='Enter')", HTML)

    def test_real_move_entry_e4_changes_core_state(self):
        with TemporaryDirectory() as temp:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(temp) / "keymap.json")
            before = api.get_state()
            result = api.make_move("e4")
            after = api.get_state()
            self.assertTrue(result["ok"])
            self.assertNotEqual(before["fen"], after["fen"])
            self.assertEqual(api.board.turn, "b")
            self.assertEqual(len(api.sans), 1)

    def test_copy_and_selection_are_not_hijacked(self):
        self.assertIn("String(e.key).toLowerCase()==='c'", HTML)
        self.assertIn("selection&&selection.toString()", HTML)
        self.assertIn("['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)", HTML)

    def test_normal_controls_do_not_carry_verbose_descriptions(self):
        for control in ("move-input", "history-input", "position-input", "board-launcher", "board-application"):
            start = HTML.index(f'id="{control}"')
            self.assertNotIn("aria-describedby", HTML[start:start + 250])

    def test_release_composition_uses_native_menu_real_sound_and_stockfish(self):
        source = (_asset_root() / "acs" / "release_app.py").read_text(encoding="utf-8")
        self.assertIn("install_windows_native_menu", source)
        self.assertNotIn("make_keymap_menu", source)
        self.assertIn("WindowsSoundPlaybackAdapter", source)
        self.assertIn("GameSoundRuntime", source)
        self.assertIn("StockfishRuntime", source)
        self.assertIn('"Accessible Chess"', source)


if __name__ == "__main__":
    unittest.main()
