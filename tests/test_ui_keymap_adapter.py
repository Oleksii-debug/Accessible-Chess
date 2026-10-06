from acs.full_product_actions import build_full_product_action_registry
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


def test_fen_user_actions_are_bilingual_and_remappable():
    rows = _by_id(build_web_keymap(build_full_product_action_registry()))
    expected = {
        "board.read_fen": ("Прочитати поточний FEN", "Read current FEN"),
        "position.read_fen": ("Прочитати поточний FEN", "Read current FEN"),
        "position.copy_fen": ("Скопіювати поточний FEN", "Copy current FEN"),
        "pgn.new_from_position": (
            "Створити PGN з поточної позиції",
            "Create PGN from current position",
        ),
    }
    for action_id, labels in expected.items():
        row = rows[action_id]
        assert (row["labelUk"], row["labelEn"]) == labels
        assert row["registryContext"] == "board"
        assert row["defaultBinding"] is None


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
        "file.new": "Ctrl+N",
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


def test_classroom_navigation_is_projected_as_one_remappable_context():
    rows = _by_id(build_web_keymap(build_full_product_action_registry()))
    expected = {
        "classroom.previous_item": "Up",
        "classroom.next_item": "Down",
        "classroom.first_item": "Home",
        "classroom.last_item": "End",
        "classroom.open_selected": "Enter",
    }
    for action_id, binding in expected.items():
        assert rows[action_id]["registryContext"] == "classroom_list"
        assert rows[action_id]["context"] == "classroom_list"
        assert rows[action_id]["binding"] == binding


def test_toolbar_roving_focus_is_projected_as_one_remappable_context():
    rows = _by_id(build_web_keymap(build_full_product_action_registry()))
    expected = {
        "toolbar.previous_control": "Left",
        "toolbar.next_control": "Right",
        "toolbar.first_control": "Home",
        "toolbar.last_control": "End",
    }
    for action_id, binding in expected.items():
        assert rows[action_id]["registryContext"] == "toolbar"
        assert rows[action_id]["context"] == "toolbar"
        assert rows[action_id]["binding"] == binding


def test_local_profile_save_is_projected_as_a_remappable_shortcut():
    row = _by_id(build_web_keymap(build_full_product_action_registry()))["profile.save_name"]
    assert row["registryContext"] == "profile_dialog"
    assert row["context"] == "profile_dialog"
    assert row["binding"] == "Enter"
