from pathlib import Path

from acs.webapp import AccessibleChessAPI


def _play_opening(api: AccessibleChessAPI) -> None:
    for move in ("e4", "e5", "Nf3", "Nc6"):
        result = api.make_move(move)
        assert result["ok"], result["announcement"]


def test_review_navigation_is_non_destructive_and_reversible():
    api = AccessibleChessAPI("uk")
    _play_opening(api)
    live_board = api.board
    end_fen = api.board.fen()
    end_sans = list(api.sans)
    undo_len = len(api.board.undo_stack)
    redo_len = len(api.board.redo_stack)

    previous = api.review_previous()
    assert previous["ok"]
    assert previous["reviewCursor"] == 3
    assert api.sans == end_sans
    assert api.board is live_board
    assert api.board.fen() == end_fen
    assert len(api.board.undo_stack) == undo_len
    assert len(api.board.redo_stack) == redo_len
    assert previous["fen"] != end_fen
    assert "N c 6" not in previous["moves"]

    forward = api.review_next()
    assert forward["ok"]
    assert forward["reviewCursor"] == 4
    assert api.board is live_board
    assert api.board.fen() == end_fen
    assert api.sans == end_sans
    assert "N c 6" in forward["moves"]


def test_review_end_then_undo_redo_restores_exact_live_position_and_history():
    api = AccessibleChessAPI("en")
    _play_opening(api)
    live_board = api.board
    end_fen = api.board.fen()
    end_sans = list(api.sans)

    assert api.review_previous()["ok"]
    assert api.review_previous()["ok"]
    assert api.go_to_move("end")["ok"]
    assert api.board is live_board
    assert api.board.fen() == end_fen

    undone = api.undo()
    assert undone["ok"]
    assert api.board is live_board
    assert len(api.sans) == len(end_sans) - 1
    assert api.board.fen() != end_fen

    redone = api.redo()
    assert redone["ok"]
    assert api.board is live_board
    assert api.board.fen() == end_fen
    assert api.sans == end_sans
    assert redone["atHistoryEnd"] is True


def test_direct_history_jump_supports_locked_forms():
    api = AccessibleChessAPI("en")
    _play_opening(api)
    live_fen = api.board.fen()
    assert api.go_to_move("start")["reviewCursor"] == 0
    assert api.board.fen() == live_fen
    white_two = api.go_to_move("2w")
    assert white_two["ok"] and white_two["reviewCursor"] == 3
    assert "N f 3" in white_two["lastMove"]
    assert api.go_to_move("2...")["reviewCursor"] == 4
    assert api.go_to_move("2")["reviewCursor"] == 4
    assert api.go_to_move("end")["reviewCursor"] == 4
    assert api.board.fen() == live_fen


def test_invalid_jump_preserves_current_review_state_and_live_board():
    api = AccessibleChessAPI("uk")
    _play_opening(api)
    live_board = api.board
    live_fen = api.board.fen()
    api.review_previous()
    before_display_fen, before_cursor = api.get_state()["fen"], api.review_cursor
    invalid = api.go_to_move("99")
    assert not invalid["ok"]
    assert api.review_cursor == before_cursor
    assert api.get_state()["fen"] == before_display_fen
    assert api.board is live_board
    assert api.board.fen() == live_fen


def test_undo_then_new_move_creates_live_variation_without_reusing_redo_branch():
    api = AccessibleChessAPI("en")
    _play_opening(api)
    old_end = api.board.fen()
    assert api.undo()["ok"]
    assert api.make_move("d6")["ok"]
    assert api.board.fen() != old_end
    assert not api.redo_meta
    assert api.get_state()["atHistoryEnd"] is True
    assert api.review_previous()["ok"]
    assert api.review_next()["ok"]
    assert api.get_state()["fen"] == api.board.fen()


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
    compact = keymap.replace(" ", "").replace("\n", "")
    assert '"id":"history.previous"' in compact
    assert '"binding":"Shift+A"' in compact
    assert '"id":"history.next"' in compact
    assert '"binding":"Shift+D"' in compact
    assert '"id":"history.go_to_move"' in compact
    assert '"binding":"Ctrl+G"' in compact
    assert '"id":"history.goto"' not in compact
    assert "resolveBinding(chord,'history','document')" in html
    assert "typeof a.keymap_resolve_binding==='function'" in html
    assert "actionByChord(eventChord(e),'document')" not in html
