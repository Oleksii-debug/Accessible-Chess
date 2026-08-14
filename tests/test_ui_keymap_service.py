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
