from __future__ import annotations

"""Pure fail-closed predicates used by the final-product release diagnostic.

These helpers validate already-projected semantic state only. They do not own
starter content, chess rules, persistence, UI state, or release composition.
Keeping the predicate pure lets CI prove both the positive packaged path and
negative malformed/missing-state cases without replacing the real launcher.
"""

from typing import Any


def packaged_starter_materials_ready(value: Any) -> bool:
    """Return whether the semantic snapshot proves the packaged starter set.

    The final product must expose the canonical starter course plus at least the
    accepted 24-booklet volume. Malformed or partially projected state fails
    closed so a launcher diagnostic cannot report PASS on an empty package.
    """

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


__all__ = ["packaged_starter_materials_ready"]
