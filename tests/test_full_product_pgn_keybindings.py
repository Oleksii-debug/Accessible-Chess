from __future__ import annotations

import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.keybindings import ActionRegistry, BindingContext


def _action_for(registry: ActionRegistry, binding: str) -> str | None:
    resolved = registry.resolve_binding(BindingContext.DOCUMENT, binding)
    return None if resolved is None else resolved.action_id


class FullProductPgnKeybindingTests(unittest.TestCase):
    def test_pgn_tree_navigation_defaults_are_registered_and_context_local(self) -> None:
        registry = build_full_product_action_registry()

        self.assertEqual("pgn.previous_item", _action_for(registry, "Up"))
        self.assertEqual("pgn.next_item", _action_for(registry, "Down"))
        self.assertEqual("pgn.parent_variation", _action_for(registry, "Left"))
        self.assertEqual(
            "board.cursor_up",
            registry.resolve_binding(BindingContext.BOARD, "Up").action_id,
        )

    def test_remap_replaces_old_binding_and_survives_profile_roundtrip(self) -> None:
        registry = build_full_product_action_registry()
        registry.set_binding("pgn.next_item", "J")

        self.assertIsNone(_action_for(registry, "Down"))
        self.assertEqual("pgn.next_item", _action_for(registry, "J"))

        restored = ActionRegistry.import_json(
            registry.export_json(),
            registry.definitions(),
        )
        self.assertIsNone(_action_for(restored, "Down"))
        self.assertEqual("pgn.next_item", _action_for(restored, "J"))


if __name__ == "__main__":
    unittest.main()
