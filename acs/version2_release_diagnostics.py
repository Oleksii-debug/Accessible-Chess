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
_REQUIRED_STARTER_BOOKLETS = frozenset(
    f"starter-booklet-{index:02d}" for index in range(1, 25)
)


def packaged_starter_materials_ready(value: Any) -> bool:
    """Return whether the semantic snapshot proves the packaged W3 starter set."""

    if not isinstance(value, dict):
        return False
    if value.get("current_id") != "starter-course":
        return False

    booklet_count = value.get("booklet_count")
    if type(booklet_count) is not int or booklet_count < len(_REQUIRED_STARTER_BOOKLETS):
        return False

    items = value.get("items")
    if not isinstance(items, (tuple, list)):
        return False

    material_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            return False
        material_id = item.get("material_id")
        if not isinstance(material_id, str) or not material_id:
            return False
        material_ids.append(material_id)

    # A duplicated semantic item must not satisfy a projected count.  The count
    # is required to agree with the distinct booklet inventory, and the canonical
    # first 24 booklet identities must all be present.
    if len(set(material_ids)) != len(material_ids):
        return False
    if material_ids.count("starter-course") != 1:
        return False
    booklet_ids = {
        material_id
        for material_id in material_ids
        if material_id.startswith("starter-booklet-")
    }
    if booklet_count != len(booklet_ids):
        return False
    return _REQUIRED_STARTER_BOOKLETS.issubset(booklet_ids)


def packaged_w2_library_ready(value: Any) -> bool:
    """Return whether Library state proves packaged W2 discovery/use controls.

    This predicate deliberately consumes only projected browser-safe state. The
    physical release diagnostic decides whether W2 evidence is required by first
    observing the package-local ``release-content/w2-starter`` directory. Once
    that directory exists, malformed/missing metadata, misleading accessible
    labels, or any missing user action must fail closed instead of allowing
    package qualification to pass on bytes that the application cannot discover
    or describe truthfully to a screen-reader user.
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
    if type(starter_games) is not int or starter_games < 200:
        return False
    if type(stress_games) is not int or stress_games <= starter_games:
        return False

    actions = value.get("actions")
    if not isinstance(actions, (tuple, list)):
        return False
    action_map: dict[str, dict[str, Any]] = {}
    for item in actions:
        if not isinstance(item, dict) or item.get("enabled") is not True:
            continue
        action = item.get("action")
        if not isinstance(action, str) or not action:
            continue
        if action in action_map:
            return False
        action_map[action] = item
    if not _PACKAGED_W2_ACTIONS.issubset(action_map):
        return False

    expected_counts = {
        "library.open_packaged_starter_pgn": starter_games,
        "library.open_packaged_stress_pgn": stress_games,
        "library.import_packaged_sample_library": starter_games,
    }
    for action, expected_count in expected_counts.items():
        label = action_map[action].get("label")
        if not isinstance(label, str) or not label.strip():
            return False
        if str(expected_count) not in label:
            return False
    return True


__all__ = ["packaged_starter_materials_ready", "packaged_w2_library_ready"]
