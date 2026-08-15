from __future__ import annotations

import json
from pathlib import Path

import pytest

from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


def test_move_entry_alias_remap_is_authoritative_and_persists(tmp_path: Path) -> None:
    profile = tmp_path / "keymap.json"
    api = KeymapAwareAccessibleChessAPI(keymap_path=profile)

    assert api.make_move("e4")["ok"] is True
    assert len(api.sans) == 1
    assert api.make_move("u")["ok"] is True
    assert len(api.sans) == 0

    changed = api.keymap_save("move.undo", "z")
    assert changed["ok"] is True
    assert profile.exists()

    assert api.make_move("e4")["ok"] is True
    assert len(api.sans) == 1
    assert api.make_move("z")["ok"] is True
    assert len(api.sans) == 0

    # The old alias is no longer a hidden shortcut. It is parsed as chess input
    # and must not mutate history when invalid.
    assert api.make_move("e4")["ok"] is True
    before = list(api.sans)
    old = api.make_move("u")
    assert old["ok"] is False
    assert api.sans == before

    restarted = KeymapAwareAccessibleChessAPI(keymap_path=profile)
    resolved = restarted.keymap_resolve_alias("move_entry", "z")
    assert resolved is not None
    assert resolved["actionId"] == "move.undo"
    assert restarted.keymap_resolve_alias("move_entry", "u") is None


def test_central_alias_registry_controls_empty_board_command(tmp_path: Path) -> None:
    api = KeymapAwareAccessibleChessAPI(keymap_path=tmp_path / "keymap.json")

    result = api.make_move("e")

    assert result["ok"] is True
    assert api.board.board.count("K") == 0
    assert api.board.board.count("k") == 0


def test_keymap_bridge_exposes_preview_save_reset_and_export(tmp_path: Path) -> None:
    api = KeymapAwareAccessibleChessAPI(keymap_path=tmp_path / "keymap.json")

    conflict = api.keymap_preview("history.next", "Shift+A")
    assert conflict["status"] == "error"
    assert conflict["canSave"] is False

    clean = api.keymap_preview("history.next", "Ctrl+Shift+J")
    assert clean["status"] == "ok"
    assert clean["canSave"] is True

    saved = api.keymap_save("history.next", "Ctrl+Shift+J")
    assert saved["ok"] is True
    resolved = api.keymap_resolve_binding("history", "Ctrl+Shift+J")
    assert resolved is not None
    assert resolved["actionId"] == "history.next"

    exported = json.loads(api.keymap_export_profile())
    assert exported["bindings"]["history.next"] == "Ctrl+Shift+J"

    reset = api.keymap_reset_action("history.next")
    assert reset["ok"] is True
    restored = api.keymap_resolve_binding("history", "Shift+D")
    assert restored is not None
    assert restored["actionId"] == "history.next"


def test_malformed_persisted_profile_has_recovery_path(tmp_path: Path) -> None:
    profile = tmp_path / "keymap.json"
    profile.write_text("{not valid json", encoding="utf-8")

    api = KeymapAwareAccessibleChessAPI(keymap_path=profile)
    snapshot = api.keymap_snapshot()

    assert snapshot["recoveryMessage"]
    assert api.keymap_resolve_binding("history", "Shift+D")["actionId"] == "history.next"

    result = api.keymap_reset_all()
    assert result["ok"] is True
    json.loads(profile.read_text(encoding="utf-8"))
    assert api.keymap_snapshot()["recoveryMessage"] is None
