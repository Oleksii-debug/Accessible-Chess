from __future__ import annotations

import json
import re
import unittest
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
    if match is None:
        raise AssertionError("main Help renderer must remain discoverable")
    return match.group(0)


class DynamicKeymapHelpContractTests(unittest.TestCase):
    def test_main_help_is_derived_from_the_live_keymap_instead_of_an_action_allowlist(self) -> None:
        source = _render_help_source()

        # Help must follow the authoritative live snapshot wholesale. A literal
        # action-ID allowlist silently makes newly added/remapped commands invisible
        # to a keyboard/screen-reader user even though they are valid actions.
        self.assertIn("keymap.map", source)
        self.assertIn("x.binding||x.alias", source)
        self.assertNotIn("keymap.find", source)
        self.assertNotIn("line('history.previous')", source)

    def test_default_catalog_contains_bound_actions_that_the_old_help_omitted(self) -> None:
        payload = json.loads(KEYBINDINGS.read_text(encoding="utf-8"))
        actions = {item["id"]: item for item in payload["actions"]}

        # These are representative user-visible commands that were valid and bound
        # but absent from the old hardcoded Help list. Keeping them here prevents a
        # regression back to the incomplete allowlist while allowing future actions
        # to appear automatically without updating this test.
        for action_id in (
            "board.last_move",
            "board.legal_moves",
            "board.attackers",
            "move.undo",
            "move.redo",
        ):
            with self.subTest(action_id=action_id):
                action = actions[action_id]
                self.assertTrue(action["binding"] or action["alias"])


if __name__ == "__main__":
    unittest.main()
