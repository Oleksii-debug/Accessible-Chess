from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from acs.webapp_keymap import KeymapAwareAccessibleChessAPI, _asset_root


HTML = (_asset_root() / "web" / "index.html").read_text(encoding="utf-8")


def test_issue22_forbidden_user_facing_strings_are_absent():
    forbidden = (
        "Семантичний документ Edge/WebView2",
        "Команди історії налаштовуються",
        "Перенесення MultiPV",
        "migration is still in progress",
        "ValueError:",
    )
    for text in forbidden:
        assert text not in HTML


def test_passive_no_conflict_state_is_not_a_live_announcement():
    assert "Конфліктів немає" not in HTML
    assert "No conflicts." not in HTML
    assert HTML.count('aria-live="polite"') == 1
    assert 'id="live" role="status" aria-live="polite"' in HTML


def test_move_entry_enter_contract_clears_only_on_success_and_refocuses():
    assert "const r=await apiAction('make_move',v)" in HTML
    assert "if(r&&r.ok){input.value='';input.focus()}" in HTML
    assert "else{input.focus();input.select()}" in HTML
    assert "el('move-input').addEventListener('keydown'" in HTML
    assert "if(e.key==='Enter')" in HTML


def test_real_move_entry_e4_changes_core_state():
    with TemporaryDirectory() as temp:
        api = KeymapAwareAccessibleChessAPI(keymap_path=Path(temp) / "keymap.json")
        before = api.get_state()
        result = api.make_move("e4")
        after = api.get_state()
        assert result["ok"] is True
        assert before["fen"] != after["fen"]
        assert api.board.turn == "b"
        assert len(api.sans) == 1


def test_copy_and_selection_are_not_hijacked():
    assert "String(e.key).toLowerCase()==='c'" in HTML
    assert "selection&&selection.toString()" in HTML
    assert "['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)" in HTML


def test_normal_controls_do_not_carry_verbose_descriptions():
    for control in ("move-input", "history-input", "position-input", "board-launcher", "board-application"):
        start = HTML.index(f'id="{control}"')
        assert "aria-describedby" not in HTML[start:start + 250]


def test_release_composition_uses_native_menu_real_sound_and_stockfish():
    source = (_asset_root() / "acs" / "release_app.py").read_text(encoding="utf-8")
    assert "install_windows_native_menu" in source
    assert "make_keymap_menu" not in source
    assert "WindowsSoundPlaybackAdapter" in source
    assert "GameSoundRuntime" in source
    assert "StockfishRuntime" in source
    assert '"Accessible Chess"' in source
