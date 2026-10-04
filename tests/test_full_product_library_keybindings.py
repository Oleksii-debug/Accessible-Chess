from __future__ import annotations

import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.keybindings import ActionRegistry, BindingContext


def _action_for(registry: ActionRegistry, binding: str) -> str | None:
    resolved = registry.resolve_binding(BindingContext.LIBRARY_RESULTS, binding)
    return None if resolved is None else resolved.action_id


class FullProductLibraryKeybindingTests(unittest.TestCase):
    def test_result_navigation_defaults_are_registered_in_widget_context(self) -> None:
        registry = build_full_product_action_registry()

        self.assertEqual("library.previous_result", _action_for(registry, "Up"))
        self.assertEqual("library.next_result", _action_for(registry, "Down"))
        self.assertEqual("library.open_game", _action_for(registry, "Enter"))
        self.assertEqual(
            "board.cursor_down",
            registry.resolve_binding(BindingContext.BOARD, "Down").action_id,
        )
        self.assertIsNone(registry.resolve_binding(BindingContext.DATABASE, "Down"))
        self.assertIsNone(registry.resolve_binding(BindingContext.DATABASE, "Enter"))

    def test_result_navigation_remap_replaces_old_key_and_roundtrips(self) -> None:
        registry = build_full_product_action_registry()
        registry.set_binding("library.next_result", "J")
        registry.set_binding("library.open_game", "Ctrl+Enter")

        self.assertIsNone(_action_for(registry, "Down"))
        self.assertIsNone(_action_for(registry, "Enter"))
        self.assertEqual("library.next_result", _action_for(registry, "J"))
        self.assertEqual("library.open_game", _action_for(registry, "Ctrl+Enter"))

        restored = ActionRegistry.import_json(
            registry.export_json(),
            registry.definitions(),
        )
        self.assertIsNone(_action_for(restored, "Down"))
        self.assertIsNone(_action_for(restored, "Enter"))
        self.assertEqual("library.next_result", _action_for(restored, "J"))
        self.assertEqual("library.open_game", _action_for(restored, "Ctrl+Enter"))


if __name__ == "__main__":
    unittest.main()
