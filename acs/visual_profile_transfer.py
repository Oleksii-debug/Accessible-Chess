"""Section 45.5: explicit portable *visual-only* profile interchange.

The schema deliberately mirrors the already accepted visual_profile_json Settings
value. It does not duplicate Settings, create a new persistence authority, touch
chess state, or silently synchronize devices.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

FORMAT = "accessible-chess-visual-profile"
VERSION = 1
MAX_BYTES = 4096
FIELDS = {
    "profile": frozenset({"classic", "studio", "tournament", "low-vision", "minimal"}),
    "theme": frozenset({"system", "light", "dark", "contrast"}),
    "board_theme": frozenset({"wood", "graphite", "blue", "minimal", "high-contrast"}),
    "density": frozenset({"comfortable", "compact", "spacious"}),
}


class VisualProfileTransferError(ValueError):
    """Reject malformed, private, ambiguous or unsupported interchange data."""


def validate_preferences(value: object) -> dict[str, str]:
    if type(value) is not dict or set(value) != set(FIELDS):
        raise VisualProfileTransferError("invalid visual-profile fields")
    for field, allowed in FIELDS.items():
        if type(value[field]) is not str or value[field] not in allowed:
            raise VisualProfileTransferError("invalid " + field)
    return {field: value[field] for field in FIELDS}


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VisualProfileTransferError("duplicate visual-profile key")
        result[key] = value
    return result


def _no_constants(value: str) -> None:
    raise VisualProfileTransferError("nonfinite visual-profile value")


def encode_transfer(preferences: object) -> str:
    """Deterministic, limited, non-private JSON for *manual* copy/import."""
    valid = validate_preferences(preferences)
    payload = json.dumps(
        {"format": FORMAT, "version": VERSION, "preferences": valid},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) > MAX_BYTES:
        raise VisualProfileTransferError("visual-profile export too large")
    return payload


def decode_transfer(payload: object) -> dict[str, str]:
    if type(payload) is not str:
        raise VisualProfileTransferError("visual-profile import must be text")
    try:
        if len(payload.encode("utf-8")) > MAX_BYTES:
            raise VisualProfileTransferError("visual-profile import too large")
        value = json.loads(
            payload, object_pairs_hook=_no_duplicates, parse_constant=_no_constants,
        )
    except (UnicodeError, RecursionError, TypeError, ValueError) as exc:
        raise VisualProfileTransferError("invalid visual-profile JSON") from exc
    if type(value) is not dict or set(value) != {"format", "version", "preferences"}:
        raise VisualProfileTransferError("invalid visual-profile envelope")
    if value["format"] != FORMAT or type(value["version"]) is not int or value["version"] != VERSION:
        raise VisualProfileTransferError("unsupported visual-profile version")
    return validate_preferences(value["preferences"])


def revision_of_stored_text(text: object) -> str:
    """Optimistic client token; Settings retains the actual disk CAS authority."""
    if type(text) is not str:
        raise VisualProfileTransferError("unreadable existing visual profile")
    try:
        value = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constants)
        validate_preferences(value)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise VisualProfileTransferError("invalid existing visual profile") from exc
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
