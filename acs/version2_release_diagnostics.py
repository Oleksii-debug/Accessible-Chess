from __future__ import annotations

"""Pure fail-closed predicates used by the final-product release diagnostic.

These helpers validate already-projected semantic state only. They do not own
starter content, chess rules, persistence, UI state, or release composition.
Keeping the predicates pure lets CI prove both positive packaged paths and
negative malformed/missing-state cases without replacing the real launcher.
"""

from typing import Any


_PACKAGED_W2_ACTIONS = frozenset(
    {
        "library.open_packaged_starter_pgn",
        "library.open_packaged_stress_pgn",
        "library.import_packaged_sample_library",
    }
)


def packaged_starter_materials_ready(value: Any) -> bool:
    """Return whether the semantic snapshot proves the packaged W3 starter set."""

    if not isinstance(value, dict):
        return False
    if value.get("current_id") != "starter-course":
        return False

    booklet_count = value.get("booklet_count")
    if not isinstance(booklet_count, int) or booklet_count < 24:
        return False

    items = value.get("items")
    if not isinstance(items, (tuple, list)) or len(items) < 25:
        return False

    return any(
        isinstance(item, dict) and item.get("material_id") == "starter-course"
        for item in items
    )


def packaged_w2_library_ready(value: Any) -> bool:
    """Return whether Library state proves packaged W2 discovery/use controls.

    This predicate deliberately consumes only projected browser-safe state. The
    physical release diagnostic decides whether W2 evidence is required by first
    observing the package-local ``release-content/w2-starter`` directory. Once
    that directory exists, malformed/missing metadata or any missing user action
    must fail closed instead of allowing package qualification to pass on bytes
    that the application cannot discover or use.
    """

    if not isinstance(value, dict):
        return False
    starter = value.get("packaged_starter_content")
    if not isinstance(starter, dict):
        return False
    if starter.get("available") is not True:
        return False
    if starter.get("network_required") is not False:
        return False
    if starter.get("prebuilt_library") is not True:
        return False

    starter_games = starter.get("starter_games")
    stress_games = starter.get("stress_games")
    if not isinstance(starter_games, int) or starter_games < 200:
        return False
    if not isinstance(stress_games, int) or stress_games <= starter_games:
        return False

    actions = value.get("actions")
    if not isinstance(actions, (tuple, list)):
        return False
    action_ids = {
        item.get("action")
        for item in actions
        if isinstance(item, dict) and item.get("enabled") is True
    }
    return _PACKAGED_W2_ACTIONS.issubset(action_ids)


__all__ = ["packaged_starter_materials_ready", "packaged_w2_library_ready"]
