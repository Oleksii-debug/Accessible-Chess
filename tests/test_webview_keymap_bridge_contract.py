from __future__ import annotations

import json
from pathlib import Path

from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


def test_release_html_uses_python_keymap_bridge_as_authority() -> None:
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    for marker in (
        "keymap_snapshot",
        "keymap_preview",
        "keymap_capture_shortcut",
        "keymap_save",
        "keymap_reset_action",
        "keymap_reset_context",
        "keymap_reset_all",
        "keymap_export_profile",
        "keymap_import_profile",
        "keymap_resolve_binding",
        "await apiAction('make_move',v)",
    ):
        assert marker in html

    assert "localStorage.setItem" not in html
    assert "localStorage.getItem" not in html
    assert "function conflictsFor" not in html
    assert "const alias=keymap.find" not in html


def test_runtime_resolution_follows_persisted_remap_without_js_cache(tmp_path: Path) -> None:
    api = KeymapAwareAccessibleChessAPI(keymap_path=tmp_path / "keymap.json")

    assert api.keymap_resolve_binding("history", "Shift+D")["actionId"] == "history.next"
    changed = api.keymap_save("history.next", "Ctrl+Shift+J")
    assert changed["ok"] is True
    assert api.keymap_resolve_binding("history", "Shift+D") is None
    assert api.keymap_resolve_binding("history", "Ctrl+Shift+J")["actionId"] == "history.next"


def test_import_warning_requires_explicit_bridge_confirmation(tmp_path: Path) -> None:
    api = KeymapAwareAccessibleChessAPI(keymap_path=tmp_path / "keymap.json")
    exported = json.loads(api.keymap_export_profile())
    exported["bindings"]["history.next"] = "Ctrl+L"
    text = json.dumps(exported)

    before = api.keymap_resolve_binding("history", "Shift+D")
    first = api.keymap_import_profile(text, False)
    assert first["ok"] is False
    assert first["requiresConfirmation"] is True
    assert api.keymap_resolve_binding("history", "Shift+D") == before
    assert api.keymap_resolve_binding("history", "Ctrl+L") is None

    confirmed = api.keymap_import_profile(text, True)
    assert confirmed["ok"] is True
    assert api.keymap_resolve_binding("history", "Shift+D") is None
    assert api.keymap_resolve_binding("history", "Ctrl+L")["actionId"] == "history.next"


def test_move_alias_remap_is_resolved_only_by_release_api(tmp_path: Path) -> None:
    api = KeymapAwareAccessibleChessAPI(keymap_path=tmp_path / "keymap.json")
    assert api.keymap_save("move.undo", "z")["ok"] is True

    assert api.make_move("e4")["ok"] is True
    assert len(api.sans) == 1
    assert api.make_move("z")["ok"] is True
    assert len(api.sans) == 0
