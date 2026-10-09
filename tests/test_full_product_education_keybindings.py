from __future__ import annotations

import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.keybindings import ActionRegistry, BindingContext
from acs.version2_final_product_profile import build_final_product_action_registry
from acs.ui_keymap_adapter import build_web_keymap


def _action_for(registry: ActionRegistry, binding: str) -> str | None:
    resolved = registry.resolve_binding(BindingContext.EDUCATION_LIST, binding)
    return None if resolved is None else resolved.action_id


class FullProductEducationKeybindingTests(unittest.TestCase):
    def test_actual_final_classes_surface_has_projected_education_keyboard_actions(self) -> None:
        registry = build_final_product_action_registry()
        projected = {row["id"]: row for row in build_web_keymap(registry)["actions"]}
        for action_id, key in (
            ("education.previous_item", "Up"),
            ("education.next_item", "Down"),
            ("education.open_selected", "Enter"),
        ):
            with self.subTest(action=action_id):
                self.assertEqual(_action_for(registry, key), action_id)
                self.assertEqual(projected[action_id]["registryContext"], "education_list")

    def test_education_list_defaults_are_registered_and_context_local(self) -> None:
        registry = build_full_product_action_registry()

        self.assertEqual("education.previous_item", _action_for(registry, "Up"))
        self.assertEqual("education.next_item", _action_for(registry, "Down"))
        self.assertEqual("education.open_selected", _action_for(registry, "Enter"))
        self.assertEqual(
            "board.cursor_up",
            registry.resolve_binding(BindingContext.BOARD, "Up").action_id,
        )
        self.assertEqual(
            "library.next_result",
            registry.resolve_binding(BindingContext.LIBRARY_RESULTS, "Down").action_id,
        )
        self.assertIsNone(registry.resolve_binding(BindingContext.DOCUMENT, "Down"))

    def test_remap_replaces_old_binding_and_survives_profile_roundtrip(self) -> None:
        registry = build_full_product_action_registry()
        registry.set_binding("education.next_item", "J")
        registry.set_binding("education.open_selected", "O")

        self.assertIsNone(_action_for(registry, "Down"))
        self.assertIsNone(_action_for(registry, "Enter"))
        self.assertEqual("education.next_item", _action_for(registry, "J"))
        self.assertEqual("education.open_selected", _action_for(registry, "O"))

        restored = ActionRegistry.import_json(
            registry.export_json(),
            registry.definitions(),
        )
        self.assertIsNone(_action_for(restored, "Down"))
        self.assertIsNone(_action_for(restored, "Enter"))
        self.assertEqual("education.next_item", _action_for(restored, "J"))
        self.assertEqual("education.open_selected", _action_for(restored, "O"))


if __name__ == "__main__":
    unittest.main()
