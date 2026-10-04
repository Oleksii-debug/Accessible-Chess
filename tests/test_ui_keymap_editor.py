import json

from acs.keybindings import ActionRegistry, BindingContext
from acs.ui_keymap_editor import KeymapEditorModel


def _row(model: KeymapEditorModel, action_id: str):
    return next(row for row in model.rows() if row.action_id == action_id)


def test_rows_are_searchable_localized_and_expose_context_and_defaults():
    model = KeymapEditorModel(lang="uk")
    row = _row(model, "history.go_to_move")
    assert row.label == "Перейти до ходу"
    assert row.context == "history"
    assert row.context_label == "Історія"
    assert row.value == "Ctrl+G"
    assert row.default_value == "Ctrl+G"
    assert row.value_kind == "shortcut"
    assert row.changed is False
    assert row.status == "ok"
    assert row.status_text == "Конфліктів немає."

    found = model.rows(query="перейти")
    assert [x.action_id for x in found] == ["history.go_to_move"]

    model.set_language("en")
    row_en = _row(model, "history.go_to_move")
    assert row_en.label == "Go to move"
    assert row_en.status_text == "No conflicts."


def test_board_context_can_be_filtered_without_visual_table_semantics():
    model = KeymapEditorModel()
    rows = model.rows(context=BindingContext.BOARD)
    assert rows
    assert all(row.context == "board" for row in rows)
    assert {row.action_id for row in rows} >= {"board.attackers", "board.defenders", "board.input"}


def test_preview_is_non_mutating_and_reports_exact_conflict_before_save():
    registry = ActionRegistry()
    model = KeymapEditorModel(registry)

    preview = model.preview("history.next", "Shift+A")

    assert preview.status == "error"
    assert preview.can_save is False
    assert preview.requires_confirmation is False
    assert preview.value_kind == "shortcut"
    assert any(item.kind == "duplicate" for item in preview.conflicts)
    assert "Конфлікт:" in preview.message
    assert registry.get_binding("history.next") == "Shift+D"


def test_preview_reports_reserved_shortcut_as_confirmable_warning():
    registry = ActionRegistry()
    model = KeymapEditorModel(registry, lang="en")

    webview = model.preview("history.go_to_move", "Ctrl+L")
    assert webview.status == "warning"
    assert webview.can_save is True
    assert webview.requires_confirmation is True
    assert any(item.kind == "webview_reserved" for item in webview.conflicts)
    assert webview.message.startswith("Warning: ")
    assert registry.get_binding("history.go_to_move") == "Ctrl+G"


def test_preview_reports_alias_collision_without_mutating_alias():
    registry = ActionRegistry()
    model = KeymapEditorModel(registry)

    preview = model.preview("move.clear", "u")

    assert preview.status == "error"
    assert preview.value_kind == "alias"
    assert preview.can_save is False
    assert any(item.kind == "alias_duplicate" for item in preview.conflicts)
    assert registry.get_alias("move.clear") == "c"


def test_preview_reports_clean_value_and_invalid_capture():
    model = KeymapEditorModel()

    clean = model.preview("board.attackers", "Ctrl+Shift+A")
    assert clean.status == "ok"
    assert clean.can_save is True
    assert clean.requires_confirmation is False
    assert clean.conflicts == ()

    invalid = model.preview("board.attackers", "Ctrl+Alt")
    assert invalid.status == "error"
    assert invalid.can_save is False
    assert "non-modifier" in invalid.message


def test_save_remaps_shortcut_through_registry_and_marks_changed():
    registry = ActionRegistry()
    model = KeymapEditorModel(registry)
    result = model.save("history.go_to_move", "Ctrl+Shift+G")
    assert result.ok
    assert registry.get_binding("history.go_to_move") == "Ctrl+Shift+G"
    row = _row(model, "history.go_to_move")
    assert row.value == "Ctrl+Shift+G"
    assert row.changed is True


def test_save_blocks_exact_same_context_conflict_without_silent_overwrite():
    registry = ActionRegistry()
    model = KeymapEditorModel(registry)
    result = model.save("history.next", "Shift+A")
    assert not result.ok
    assert any(item.kind == "duplicate" for item in result.conflicts)
    assert registry.get_binding("history.next") == "Shift+D"


def test_save_blocks_reserved_warning_by_default_but_can_accept_explicit_override():
    registry = ActionRegistry()
    model = KeymapEditorModel(registry)
    blocked = model.save("history.go_to_move", "Ctrl+L")
    assert not blocked.ok
    assert any(item.kind == "webview_reserved" for item in blocked.conflicts)
    assert registry.get_binding("history.go_to_move") == "Ctrl+G"

    accepted = model.save("history.go_to_move", "Ctrl+L", allow_warnings=True)
    assert accepted.ok
    assert registry.get_binding("history.go_to_move") == "Ctrl+L"


def test_alias_remap_uses_registry_and_duplicate_alias_is_rejected():
    registry = ActionRegistry()
    model = KeymapEditorModel(registry)
    ok = model.save("move.black_to_move", "z")
    assert ok.ok
    assert registry.get_alias("move.black_to_move") == "z"

    duplicate = model.save("move.clear", "z")
    assert not duplicate.ok
    assert any(item.kind == "alias_duplicate" for item in duplicate.conflicts)
    assert registry.get_alias("move.clear") == "c"


def test_reset_action_context_and_all_are_supported():
    registry = ActionRegistry()
    model = KeymapEditorModel(registry)
    assert model.save("board.attackers", "Ctrl+A").ok
    assert model.save("board.defenders", "Ctrl+D").ok
    model.reset_action("board.attackers")
    assert registry.get_binding("board.attackers") == "A"
    assert registry.get_binding("board.defenders") == "Ctrl+D"

    model.reset_context(BindingContext.BOARD)
    assert registry.get_binding("board.attackers") == "A"
    assert registry.get_binding("board.defenders") == "D"

    assert model.save("history.go_to_move", "Ctrl+Shift+G").ok
    model.reset_all()
    assert registry.get_binding("history.go_to_move") == "Ctrl+G"


def test_export_import_round_trip_preserves_remaps_and_rejects_invalid_profile():
    source = KeymapEditorModel()
    assert source.save("history.go_to_move", "Ctrl+Shift+G").ok
    assert source.save("move.black_to_move", "z").ok
    payload = source.export_profile()
    decoded = json.loads(payload)
    assert decoded["schema_version"] == 1

    target = KeymapEditorModel()
    result = target.import_profile(payload)
    assert result.ok
    assert target.registry.get_binding("history.go_to_move") == "Ctrl+Shift+G"
    assert target.registry.get_alias("move.black_to_move") == "z"

    bad = target.import_profile('{"schema_version":999,"bindings":{},"aliases":{}}')
    assert not bad.ok
    assert target.registry.get_binding("history.go_to_move") == "Ctrl+Shift+G"


def test_nvda_browse_commands_are_not_exposed_as_app_owned_rows():
    model = KeymapEditorModel()
    ids = {row.action_id for row in model.rows()}
    assert "nvda.heading" not in ids
    assert "nvda.button" not in ids
    assert "nvda.edit" not in ids
    assert "nvda.form" not in ids
