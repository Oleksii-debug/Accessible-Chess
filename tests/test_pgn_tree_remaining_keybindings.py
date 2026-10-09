from __future__ import annotations

import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.keybindings import ActionRegistry, BindingContext


class PgnTreeRemainingKeybindingsTests(unittest.TestCase):
    def _action_for(self, registry: ActionRegistry, binding: str) -> str | None:
        resolved = registry.resolve_binding(BindingContext.PGN_TREE, binding)
        return None if resolved is None else resolved.action_id

    def test_remaining_tree_navigation_defaults_are_central_actions(self) -> None:
        registry = build_full_product_action_registry()
        self.assertEqual("pgn.first_child", self._action_for(registry, "Right"))
        self.assertEqual("pgn.first_item", self._action_for(registry, "Home"))
        self.assertEqual("pgn.last_item", self._action_for(registry, "End"))

    def test_remaining_tree_navigation_remaps_replace_defaults_and_roundtrip(self) -> None:
        registry = build_full_product_action_registry()
        replacements = {
            "pgn.first_child": ("Right", "J"),
            "pgn.first_item": ("Home", "Ctrl+Home"),
            "pgn.last_item": ("End", "Ctrl+End"),
        }
        for action_id, (old_binding, new_binding) in replacements.items():
            registry.set_binding(action_id, new_binding)
            self.assertIsNone(self._action_for(registry, old_binding))
            self.assertEqual(action_id, self._action_for(registry, new_binding))

        restored = ActionRegistry.import_json(
            registry.export_json(),
            registry.definitions(),
        )
        for action_id, (old_binding, new_binding) in replacements.items():
            self.assertIsNone(self._action_for(restored, old_binding))
            self.assertEqual(action_id, self._action_for(restored, new_binding))


if __name__ == "__main__":
    unittest.main()
