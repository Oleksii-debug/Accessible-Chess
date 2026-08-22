from __future__ import annotations

import json
from pathlib import Path

from acs.keybindings import ActionRegistry, BindingContext


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web" / "index.html"
KEYMAP = ROOT / "web" / "keybindings.json"


def _actions() -> dict[str, dict[str, object]]:
    payload = json.loads(KEYMAP.read_text(encoding="utf-8"))
    return {item["id"]: item for item in payload["actions"]}


def test_rank_and_file_navigation_are_exposed_as_remappable_actions() -> None:
    actions = _actions()
    registry = ActionRegistry()

    for number in range(1, 9):
        rank = actions[f"board.rank_{number}"]
        assert rank["context"] == "board"
        assert rank["registryContext"] == "board"
        assert rank["binding"] == str(number)
        assert rank["defaultBinding"] == str(number)
        rank_resolution = registry.resolve_binding(BindingContext.BOARD, str(number))
        assert rank_resolution is not None
        assert rank_resolution.action_id == f"board.rank_{number}"

        file_action = actions[f"board.file_{number}"]
        assert file_action["context"] == "board"
        assert file_action["registryContext"] == "board"
        assert file_action["binding"] == f"Shift+{number}"
        assert file_action["defaultBinding"] == f"Shift+{number}"
        file_resolution = registry.resolve_binding(BindingContext.BOARD, f"Shift+{number}")
        assert file_resolution is not None
        assert file_resolution.action_id == f"board.file_{number}"


def test_board_dispatch_uses_action_ids_instead_of_hardcoded_digit_shortcuts() -> None:
    html = INDEX.read_text(encoding="utf-8")
    board_handler = html.split("async function onBoardKey(e)", 1)[1].split(
        "async function loadState()", 1
    )[0]

    assert "id.match(/^board\\.rank_([1-8])$/)" in html
    assert "id.match(/^board\\.file_([1-8])$/)" in html
    assert "await resolveBinding(eventChord(e),'board','board')" in board_handler
    assert "executeAction(a.actionId)" in board_handler

    # Regression guard: rank/file navigation must not bypass the keymap by
    # intercepting literal 1..8 / Shift+1..8 before Action Registry dispatch.
    assert "if(/^[1-8]$/.test(key)&&!e.shiftKey)" not in html
    assert "if(/^[1-8]$/.test(key)&&e.shiftKey)" not in html


def test_help_is_generated_from_live_rank_and_file_bindings() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert "line('board.rank_1')" in html
    assert "line('board.file_1')" in html
