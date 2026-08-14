from acs.keybindings import ActionRegistry
from acs.ui_keymap_adapter import build_web_keymap


def _by_id(payload):
    return {item["id"]: item for item in payload["actions"]}


def test_ui_keymap_uses_exact_central_action_ids_and_defaults():
    registry = ActionRegistry()
    payload = build_web_keymap(registry)
    rows = _by_id(payload)
    expected = {d.action_id for d in registry.definitions() if not d.external}
    assert set(rows) == expected
    assert len(rows) == len(payload["actions"])
    for definition in registry.definitions():
        if definition.external:
            continue
        row = rows[definition.action_id]
        assert row["binding"] == registry.get_binding(definition.action_id)
        assert row["alias"] == registry.get_alias(definition.action_id)
        assert row["defaultBinding"] == definition.default_binding
        assert row["defaultAlias"] == definition.default_alias


def test_ui_keymap_has_no_legacy_parallel_action_ids():
    rows = _by_id(build_web_keymap())
    forbidden = {
        "history.goto", "game.undo", "game.redo", "board.lastCaptured",
        "board.lastMove", "board.myClock", "board.opponentClock",
        "board.legal", "board.best", "board.playBest", "move.white",
        "move.black", "move.engine",
    }
    assert forbidden.isdisjoint(rows)


def test_locked_board_and_history_defaults_are_projected_for_webview():
    rows = _by_id(build_web_keymap())
    expected = {
        "history.previous": "Shift+A",
        "history.next": "Shift+D",
        "history.go_to_move": "Ctrl+G",
        "board.current": "O",
        "board.last_captured": "C",
        "board.last_move": "L",
        "board.attackers": "A",
        "board.defenders": "D",
        "board.best_move": "G",
        "board.play_best": "Shift+G",
        "board.input": "I",
    }
    for action_id, binding in expected.items():
        assert rows[action_id]["binding"] == binding


def test_move_entry_aliases_are_projected_without_changing_parser_syntax():
    rows = _by_id(build_web_keymap())
    assert rows["move.white_to_move"]["alias"] == "w"
    assert rows["move.black_to_move"]["alias"] == "b"
    assert rows["move.clear"]["alias"] == "c"
    assert rows["move.standard"]["alias"] == "s"
    assert rows["move.empty"]["alias"] == "e"
    assert all("W:" not in (row["alias"] or "") for row in rows.values())
