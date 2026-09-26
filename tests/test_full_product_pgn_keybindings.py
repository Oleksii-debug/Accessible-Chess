from __future__ import annotations

from acs.full_product_actions import build_full_product_action_registry
from acs.keybindings import ActionRegistry, BindingContext


def _action_for(registry: ActionRegistry, binding: str) -> str | None:
    resolved = registry.resolve_binding(BindingContext.DOCUMENT, binding)
    return None if resolved is None else resolved.action_id


def test_pgn_tree_navigation_defaults_are_registered_and_context_local() -> None:
    registry = build_full_product_action_registry()

    assert _action_for(registry, "Up") == "pgn.previous_item"
    assert _action_for(registry, "Down") == "pgn.next_item"
    assert _action_for(registry, "Left") == "pgn.parent_variation"
    assert registry.resolve_binding(BindingContext.BOARD, "Up").action_id == "board.cursor_up"


def test_pgn_tree_navigation_remap_replaces_old_binding_and_survives_profile_roundtrip() -> None:
    registry = build_full_product_action_registry()
    registry.set_binding("pgn.next_item", "J")

    assert _action_for(registry, "Down") is None
    assert _action_for(registry, "J") == "pgn.next_item"

    restored = ActionRegistry.import_json(registry.export_json(), registry.definitions())
    assert _action_for(restored, "Down") is None
    assert _action_for(restored, "J") == "pgn.next_item"
