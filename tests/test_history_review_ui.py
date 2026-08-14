from pathlib import Path

from acs.webapp import AccessibleChessAPI


def _play_opening(api: AccessibleChessAPI) -> None:
    for move in ("e4", "e5", "Nf3", "Nc6"):
        result = api.make_move(move)
        assert result["ok"], result["announcement"]


def test_review_navigation_is_non_destructive_and_reversible():
    api = AccessibleChessAPI("uk")
    _play_opening(api)
    end_fen = api.board.fen()
    end_sans = list(api.sans)
    previous = api.review_previous()
    assert previous["ok"]
    assert previous["reviewCursor"] == 3
    assert api.sans == end_sans
    assert api.board.fen() != end_fen
    assert "Nc6" not in previous["moves"]
    forward = api.review_next()
    assert forward["ok"]
    assert forward["reviewCursor"] == 4
    assert api.board.fen() == end_fen
    assert api.sans == end_sans
    assert "Nc6" in forward["moves"]


def test_direct_history_jump_supports_locked_forms():
    api = AccessibleChessAPI("en")
    _play_opening(api)
    assert api.go_to_move("start")["reviewCursor"] == 0
    white_two = api.go_to_move("2w")
    assert white_two["ok"] and white_two["reviewCursor"] == 3
    assert "N f 3" in white_two["lastMove"]
    assert api.go_to_move("2...")["reviewCursor"] == 4
    assert api.go_to_move("2")["reviewCursor"] == 4
    assert api.go_to_move("end")["reviewCursor"] == 4


def test_invalid_jump_preserves_current_review_state():
    api = AccessibleChessAPI("uk")
    _play_opening(api)
    before_fen, before_cursor = api.board.fen(), api.review_cursor
    invalid = api.go_to_move("99")
    assert not invalid["ok"]
    assert api.review_cursor == before_cursor
    assert api.board.fen() == before_fen


def test_history_ui_is_semantic_but_does_not_break_locked_h2_order():
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    assert '<h3 id="h-history">' in html
    assert '<h2 id="h-history">' not in html
    for marker in (
        'id="history-input" type="text"',
        'id="history-prev" type="button"',
        'id="history-next" type="button"',
        'id="history-go" type="button"',
        "focusHistoryJump()",
        "apiAction('review_previous')",
        "apiAction('review_next')",
    ):
        assert marker in html
    headings = [
        'h-game-info', 'h-moves', 'h-white', 'h-black', 'h-status',
        'h-last', 'h-input', 'h-engine', 'h-board', 'h-actions',
    ]
    positions = [html.index(f'<h2 id="{heading}"') for heading in headings]
    assert positions == sorted(positions)


def test_history_shortcuts_come_from_central_keymap_not_hardcoded_handler():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    keymap = (root / "web" / "keybindings.json").read_text(encoding="utf-8")
    assert '"id":"history.previous"' in keymap.replace(" ", "").replace("\n", "")
    assert '"binding":"Shift+A"' in keymap.replace(" ", "").replace("\n", "")
    assert '"id":"history.next"' in keymap.replace(" ", "").replace("\n", "")
    assert '"binding":"Shift+D"' in keymap.replace(" ", "").replace("\n", "")
    assert '"id":"history.goto"' in keymap.replace(" ", "").replace("\n", "")
    assert '"binding":"Ctrl+G"' in keymap.replace(" ", "").replace("\n", "")
    assert "actionByChord(eventChord(e),'document')" in html
