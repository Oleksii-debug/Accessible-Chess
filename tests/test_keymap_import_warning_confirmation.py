import json

from acs.keybindings import ActionRegistry
from acs.ui_keymap_service import KeymapService


def _profile_with_reserved_shortcut(service: KeymapService) -> str:
    payload = json.loads(service.export_profile())
    payload["bindings"]["history.go_to_move"] = "Ctrl+L"
    return json.dumps(payload)


def test_risky_profile_import_requires_confirmation_and_is_atomic(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path, lang="en")
    assert service.save("board.current", "F6")["ok"] is True
    before = path.read_text(encoding="utf-8")

    result = service.import_profile(_profile_with_reserved_shortcut(service))

    assert result["ok"] is False
    assert result["requiresConfirmation"] is True
    assert result["message"].startswith("Import requires confirmation. ")
    assert any(item["severity"] == "warning" for item in result["conflicts"])
    assert any(item["kind"] == "webview_reserved" for item in result["conflicts"])
    assert path.read_text(encoding="utf-8") == before
    assert service.editor.registry.get_binding("history.go_to_move") == "Ctrl+G"
    assert service.editor.registry.get_binding("board.current") == "F6"


def test_risky_profile_import_applies_only_after_explicit_confirmation(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path, lang="uk")
    profile = _profile_with_reserved_shortcut(service)

    blocked = service.import_profile(profile)
    accepted = service.import_profile(profile, allow_warnings=True)

    assert blocked["ok"] is False
    assert blocked["requiresConfirmation"] is True
    assert "потребує підтвердження" in blocked["message"]
    assert accepted["ok"] is True
    assert accepted["requiresConfirmation"] is False

    registry, recovery = ActionRegistry.load(path)
    assert recovery is None
    assert registry.get_binding("history.go_to_move") == "Ctrl+L"


def test_profile_with_blocking_conflict_cannot_be_forced(tmp_path):
    path = tmp_path / "keymap.json"
    service = KeymapService(path)
    payload = json.loads(service.export_profile())
    payload["bindings"]["history.previous"] = "Shift+D"
    profile = json.dumps(payload)

    result = service.import_profile(profile, allow_warnings=True)

    assert result["ok"] is False
    assert result["requiresConfirmation"] is False
    assert any(item["severity"] == "error" for item in result["conflicts"])
    assert not path.exists()
