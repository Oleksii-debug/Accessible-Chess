import json

from acs.keybindings import ActionRegistry
from acs.ui_keymap_service import KeymapService


def test_service_persists_shortcut_and_alias(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path)

    assert service.save("history.go_to_move", "Alt+J")["ok"] is True
    assert service.save("move.undo", "z")["ok"] is True

    reloaded = KeymapService(path)
    snap = reloaded.snapshot()
    by_id = {item["id"]: item for item in snap["actions"]}
    assert by_id["history.go_to_move"]["binding"] == "Alt+J"
    assert by_id["move.undo"]["alias"] == "z"


def test_service_rejects_same_context_duplicate_without_overwrite(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path)

    result = service.save("history.previous", "Shift+D")
    assert result["ok"] is False
    assert any(c["kind"] == "duplicate" for c in result["conflicts"])

    reloaded = KeymapService(path)
    by_id = {item["id"]: item for item in reloaded.snapshot()["actions"]}
    assert by_id["history.previous"]["binding"] == "Shift+A"
    assert by_id["history.next"]["binding"] == "Shift+D"


def test_service_requires_explicit_confirmation_for_reserved_warning(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path)

    blocked = service.save("history.go_to_move", "Ctrl+L")
    assert blocked["ok"] is False
    assert any(c["severity"] == "warning" for c in blocked["conflicts"])

    accepted = service.save("history.go_to_move", "Ctrl+L", allow_warnings=True)
    assert accepted["ok"] is True
    assert ActionRegistry.load(path)[0].get_binding("history.go_to_move") == "Ctrl+L"


def test_preview_bridge_is_non_mutating_and_blocks_exact_conflict(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path, lang="uk")

    before = service.snapshot()
    preview = service.preview("history.next", "Shift+A")
    after = service.snapshot()

    assert preview["actionId"] == "history.next"
    assert preview["value"] == "Shift+A"
    assert preview["valueKind"] == "shortcut"
    assert preview["status"] == "error"
    assert preview["canSave"] is False
    assert preview["requiresConfirmation"] is False
    assert preview["message"].startswith("Конфлікт: ")
    assert any(c["kind"] == "duplicate" and c["severity"] == "error" for c in preview["conflicts"])
    assert before == after
    assert not path.exists()


def test_preview_bridge_exposes_confirmable_reserved_warning(tmp_path):
    service = KeymapService(tmp_path / "keymap.json", lang="en")

    preview = service.preview("history.go_to_move", "Ctrl+L")

    assert preview["status"] == "warning"
    assert preview["canSave"] is True
    assert preview["requiresConfirmation"] is True
    assert preview["message"].startswith("Warning: ")
    assert any(c["kind"] == "webview_reserved" and c["severity"] == "warning" for c in preview["conflicts"])
    assert service.snapshot()["actions"][2]["binding"] == "Ctrl+G"


def test_preview_bridge_reports_clean_alias_without_persisting(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path)

    preview = service.preview("move.black_to_move", "z")

    assert preview == {
        "actionId": "move.black_to_move",
        "value": "z",
        "valueKind": "alias",
        "canSave": True,
        "requiresConfirmation": False,
        "status": "ok",
        "message": "Конфліктів немає.",
        "conflicts": [],
    }
    assert service.editor.registry.get_alias("move.black_to_move") == "b"
    assert not path.exists()


def test_capture_shortcut_builds_normalized_chord_and_previews_warning(tmp_path):
    service = KeymapService(tmp_path / "keymap.json", lang="en")

    result = service.capture_shortcut(
        "history.go_to_move",
        "l",
        ctrl=True,
    )

    assert result["captured"] is True
    assert result["reason"] == "captured"
    assert result["binding"] == "Ctrl+L"
    assert result["value"] == "Ctrl+L"
    assert result["status"] == "warning"
    assert result["canSave"] is True
    assert result["requiresConfirmation"] is True
    assert any(item["kind"] == "webview_reserved" for item in result["conflicts"])
    assert service.editor.registry.get_binding("history.go_to_move") == "Ctrl+G"


def test_capture_shortcut_preserves_literal_space_from_keyboard_event(tmp_path):
    service = KeymapService(tmp_path / "keymap.json", lang="en")

    result = service.capture_shortcut("board.current", " ", ctrl=True)

    assert result["captured"] is True
    assert result["reason"] == "captured"
    assert result["binding"] == "Ctrl+Space"
    assert result["value"] == "Ctrl+Space"
    assert result["status"] == "ok"
    assert result["canSave"] is True
    assert service.editor.registry.get_binding("board.current") == "O"


def test_capture_shortcut_normalizes_legacy_spacebar_key_name(tmp_path):
    service = KeymapService(tmp_path / "keymap.json", lang="uk")

    result = service.capture_shortcut("board.current", "Spacebar", alt=True, shift=True)

    assert result["captured"] is True
    assert result["binding"] == "Alt+Shift+Space"
    assert result["status"] == "ok"
    assert result["canSave"] is True


def test_capture_shortcut_preserves_tab_navigation_and_escape_cancel(tmp_path):
    service = KeymapService(tmp_path / "keymap.json", lang="uk")

    tab = service.capture_shortcut("history.go_to_move", "Tab")
    escape = service.capture_shortcut("history.go_to_move", "Escape")

    assert tab["captured"] is False
    assert tab["reason"] == "navigation"
    assert tab["canSave"] is False
    assert "Tab" in tab["message"]
    assert escape["captured"] is False
    assert escape["reason"] == "cancelled"
    assert escape["canSave"] is False
    assert "скасовано" in escape["message"]


def test_capture_shortcut_rejects_modifier_only_event(tmp_path):
    service = KeymapService(tmp_path / "keymap.json", lang="en")

    result = service.capture_shortcut(
        "history.go_to_move",
        "Shift",
        shift=True,
    )

    assert result["captured"] is False
    assert result["reason"] == "incomplete"
    assert result["status"] == "pending"
    assert result["canSave"] is False
    assert "non-modifier" in result["message"]


def test_live_binding_resolution_tracks_remap_immediately(tmp_path):
    service = KeymapService(tmp_path / "keymap.json")

    initial = service.resolve_binding("history", "Ctrl+G")
    assert initial == {
        "actionId": "history.go_to_move",
        "context": "history",
        "binding": "Ctrl+G",
        "alias": None,
    }

    assert service.save("history.go_to_move", "Alt+J")["ok"] is True
    assert service.resolve_binding("history", "Ctrl+G") is None
    assert service.resolve_binding("history", "alt+j")["actionId"] == "history.go_to_move"


def test_live_alias_resolution_tracks_remap_without_touching_chess_syntax(tmp_path):
    service = KeymapService(tmp_path / "keymap.json")

    assert service.resolve_alias("move_entry", "u")["actionId"] == "move.undo"
    assert service.save("move.undo", "z")["ok"] is True
    assert service.resolve_alias("move_entry", "u") is None
    resolved = service.resolve_alias("move_entry", "Z")
    assert resolved["actionId"] == "move.undo"
    assert resolved["alias"] == "z"
    assert service.resolve_alias("position_editor", "W:") is None
    assert service.resolve_alias("position_editor", "B:") is None


def test_live_binding_resolution_preserves_global_context_fallback(tmp_path):
    service = KeymapService(tmp_path / "keymap.json")

    resolved = service.resolve_binding("board", "Ctrl+Z")

    assert resolved["actionId"] == "edit.undo"
    assert resolved["context"] == "global"
    assert resolved["binding"] == "Ctrl+Z"


def test_reset_context_preserves_other_contexts(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path)
    assert service.save("history.go_to_move", "Alt+J")["ok"] is True
    assert service.save("board.current", "F6")["ok"] is True

    result = service.reset_context("history")
    assert result["ok"] is True

    registry, error = ActionRegistry.load(path)
    assert error is None
    assert registry.get_binding("history.go_to_move") == "Ctrl+G"
    assert registry.get_binding("board.current") == "F6"


def test_import_is_atomic_on_conflict(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path)
    assert service.save("history.go_to_move", "Alt+J")["ok"] is True
    before = path.read_text(encoding="utf-8")

    payload = json.loads(service.export_profile())
    payload["bindings"]["history.previous"] = "Shift+D"
    result = service.import_profile(json.dumps(payload))

    assert result["ok"] is False
    assert path.read_text(encoding="utf-8") == before


def test_malformed_saved_profile_recovers_to_defaults(tmp_path):
    path = tmp_path / "keymap.json"
    path.write_text("{not json", encoding="utf-8")

    service = KeymapService(path)
    snap = service.snapshot()
    by_id = {item["id"]: item for item in snap["actions"]}

    assert snap["recoveryMessage"]
    assert by_id["history.go_to_move"]["binding"] == "Ctrl+G"
    assert service.reset_all()["ok"] is True
    assert KeymapService(path).snapshot()["recoveryMessage"] is None


def test_search_returns_semantic_rows(tmp_path):
    service = KeymapService(tmp_path / "keymap.json", lang="uk")
    rows = service.search("атак", "board")

    assert len(rows) == 1
    assert rows[0]["action_id"] == "board.attackers"
    assert rows[0]["value"] == "A"
    assert rows[0]["context"] == "board"
