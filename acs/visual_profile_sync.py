"""Section 45.5: explicit portable visual preferences, never chess/user settings.

The same four-field design profile already drives the Windows WebView and Web DOM.
A transport document is deliberately separate from Settings.export_json(): it
cannot expose engine paths, credentials, library paths, or unrelated settings.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

KIND = "accessible-chess-visual-profile"
VERSION = 1
MAX_BYTES = 4096
CHOICES = {
    "profile": frozenset(("classic", "studio", "tournament", "low-vision", "minimal")),
    "theme": frozenset(("system", "light", "dark", "contrast")),
    "board_theme": frozenset(("wood", "graphite", "blue", "minimal", "high-contrast")),
    "density": frozenset(("comfortable", "compact", "spacious")),
}


class VisualProfileSyncError(ValueError):
    """Invalid, unexpected, or conflicted external visual preferences."""


def validate_profile(profile: object) -> dict[str, str]:
    if type(profile) is not dict or set(profile) != set(CHOICES):
        raise VisualProfileSyncError("visual profile fields are invalid")
    if any(type(profile[k]) is not str or profile[k] not in allowed
           for k, allowed in CHOICES.items()):
        raise VisualProfileSyncError("visual profile values are invalid")
    return {k: profile[k] for k in CHOICES}


def _canonical(profile: dict[str, str]) -> str:
    return json.dumps(profile, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def revision(profile: object) -> str:
    return hashlib.sha256(_canonical(validate_profile(profile)).encode("ascii")).hexdigest()


def export_document(profile: object) -> str:
    values = validate_profile(profile)
    return json.dumps(
        {"kind": KIND, "schema_version": VERSION, "profile": values,
         "revision": revision(values)},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VisualProfileSyncError("duplicate visual sync field")
        result[key] = value
    return result


def import_document(payload: object) -> dict[str, str]:
    if type(payload) is not str or len(payload) > MAX_BYTES:
        raise VisualProfileSyncError("visual sync document is too large or not text")
    try:
        raw = json.loads(
            payload,
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                VisualProfileSyncError("non-finite visual sync value")
            ),
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise VisualProfileSyncError("invalid visual sync JSON") from exc
    if type(raw) is not dict or set(raw) != {
        "kind", "schema_version", "profile", "revision"
    }:
        raise VisualProfileSyncError("unknown visual sync document fields")
    if raw["kind"] != KIND or type(raw["schema_version"]) is not int or raw["schema_version"] != VERSION:
        raise VisualProfileSyncError("unsupported visual sync schema")
    values = validate_profile(raw["profile"])
    if type(raw["revision"]) is not str or raw["revision"] != revision(values):
        raise VisualProfileSyncError("visual sync integrity mismatch")
    return values


def reconcile_import(
    document: object, current_profile: object, expected_local_revision: object,
) -> dict[str, str]:
    """Fail closed on a stale user preview. No automatic last-writer-wins."""
    current = validate_profile(current_profile)
    if type(expected_local_revision) is not str or expected_local_revision != revision(current):
        raise VisualProfileSyncError("visual sync conflict: local profile changed")
    return import_document(document)
