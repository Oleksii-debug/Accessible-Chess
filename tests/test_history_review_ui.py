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
    assert len(api.sans) == 4
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

    start = api.go_to_move("start")
    assert start["ok"]
    assert start["reviewCursor"] == 0
    assert start["moves"] == "No moves yet"

    white_two = api.go_to_move("2w")
    assert white_two["ok"]
    assert white_two["reviewCursor"] == 3
    assert "N f 3" in white_two["lastMove"]

    black_two = api.go_to_move("2...")
    assert black_two["ok"]
    assert black_two["reviewCursor"] == 4

    bare_two = api.go_to_move("2")
    assert bare_two["ok"]
    assert bare_two["reviewCursor"] == 4

    end = api.go_to_move("end")
    assert end["ok"]
    assert end["reviewCursor"] == 4


def test_review_does_not_act_like_undo():
    api = AccessibleChessAPI("uk")
    _play_opening(api)
    api.review_previous()

    blocked = api.make_move("Bb5")
    assert not blocked["ok"]
    assert len(api.sans) == 4

    api.go_to_move("end")
    undo = api.undo()
    assert undo["ok"]
    assert len(api.sans) == 3
    redo = api.redo()
    assert redo["ok"]
    assert len(api.sans) == 4


def test_invalid_jump_preserves_current_review_state():
    api = AccessibleChessAPI("uk")
    _play_opening(api)
    before_fen = api.board.fen()
    before_cursor = api.review_cursor

    invalid = api.go_to_move("99")
    assert not invalid["ok"]
    assert api.review_cursor == before_cursor
    assert api.board.fen() == before_fen


def test_history_ui_is_semantic_and_keyboard_discoverable():
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    required = (
        '<h2 id="h-history">',
        'id="history-input" type="text"',
        'id="history-prev" type="button"',
        'id="history-next" type="button"',
        'id="history-go" type="button"',
        "Ctrl+G",
        "Shift+A",
        "Shift+D",
        "focusHistoryJump()",
        "apiAction('review_previous')",
        "apiAction('review_next')",
    )
    for marker in required:
        assert marker in html

    history_pos = html.index('id="history-input"')
    board_app_pos = html.index('id="board-application"')
    assert history_pos < board_app_pos
