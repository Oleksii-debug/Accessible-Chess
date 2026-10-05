from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web" / "index.html"
KEYBINDINGS = ROOT / "web" / "keybindings.json"


def _render_help_source() -> str:
    source = INDEX.read_text(encoding="utf-8")
    match = re.search(
        r"function renderHelp\(\)\{.*?\}\nfunction projectedOwnedAction",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, "main Help renderer must remain discoverable"
    return match.group(0)


def test_main_help_is_derived_from_the_live_keymap_instead_of_an_action_allowlist() -> None:
    source = _render_help_source()

    # Help must follow the authoritative live snapshot wholesale.  A literal
    # action-ID allowlist silently makes newly added/remapped commands invisible
    # to a keyboard/screen-reader user even though they are valid actions.
    assert "keymap.map" in source
    assert "x.binding||x.alias" in source
    assert "keymap.find" not in source
    assert "line('history.previous')" not in source


def test_default_catalog_contains_bound_actions_that_the_old_help_omitted() -> None:
    payload = json.loads(KEYBINDINGS.read_text(encoding="utf-8"))
    actions = {item["id"]: item for item in payload["actions"]}

    # These are representative user-visible commands that were valid and bound
    # but absent from the old hardcoded Help list.  Keeping them here prevents a
    # regression back to the incomplete allowlist while allowing future actions
    # to appear automatically without updating this test.
    for action_id in (
        "board.last_move",
        "board.legal_moves",
        "board.attackers",
        "move.undo",
        "move.redo",
    ):
        action = actions[action_id]
        assert action["binding"] or action["alias"]
