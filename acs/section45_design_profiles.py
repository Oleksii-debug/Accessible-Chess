"""Section 45: bounded, presentation-only design profile schema.

This module has no dependency on chess rules, GameTree, Settings or the network.
The same JSON envelope is consumed by Windows and Web; no private paths,
identifiers, student data or credentials may be exported.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

VERSION = 1
MAX_BYTES = 16384
MAX_PROFILES = 16
ALLOWED_THEMES = frozenset({"system", "light", "dark", "contrast"})
ALLOWED_BOARDS = frozenset({
    "classic", "high_contrast", "blue", "classic_wood",
    "modern_graphite", "tournament_blue", "light_minimal",
})
ALLOWED_PIECES = frozenset({"unicode", "letters", "rhosgfx"})
ALLOWED_COORDINATES = frozenset({"off", "edges", "every_square"})
ALLOWED_DENSITIES = frozenset({"comfortable", "compact"})
ALLOWED_LAYOUTS = frozenset({"auto", "single"})
_NAME_RE = re.compile(r"^[^\\/\x00-\x1f\x7f<>:\"|?*]{1,48}$")

DEFAULT_PREFERENCES = {
    "theme": "system",
    "board_theme": "classic",
    "piece_theme": "unicode",
    "font_percent": 100,
    "board_scale": 100,
    "density": "comfortable",
    "layout": "auto",
    "coordinates": "edges",
    "orientation": "white",
    "highlight": True,
    "animations": False,
    "sound": True,
}
PRESETS = {
    "Classic": dict(DEFAULT_PREFERENCES),
    "Tournament": {**DEFAULT_PREFERENCES, "board_theme": "tournament_blue", "density": "compact", "coordinates": "every_square"},
    "Coach": {**DEFAULT_PREFERENCES, "font_percent": 125, "board_scale": 125, "highlight": True},
    "Classroom Presentation": {**DEFAULT_PREFERENCES, "font_percent": 150, "board_scale": 150, "coordinates": "every_square"},
    "Low Vision": {**DEFAULT_PREFERENCES, "font_percent": 175, "board_scale": 175, "board_theme": "high_contrast"},
    "High Contrast": {**DEFAULT_PREFERENCES, "theme": "contrast", "board_theme": "high_contrast", "piece_theme": "letters", "font_percent": 125},
}
DEFAULT_STORE = {"version": VERSION, "selected": "Classic", "profiles": {}}


class DesignProfileError(ValueError):
    pass


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DesignProfileError("duplicate key in design profile")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise DesignProfileError("nonfinite design profile value")


def validate_preferences(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(DEFAULT_PREFERENCES):
        raise DesignProfileError("design preferences must have exactly the published keys")
    fields = {
        "theme": ALLOWED_THEMES,
        "board_theme": ALLOWED_BOARDS,
        "piece_theme": ALLOWED_PIECES,
        "density": ALLOWED_DENSITIES,
        "layout": ALLOWED_LAYOUTS,
        "coordinates": ALLOWED_COORDINATES,
        "orientation": frozenset({"white", "black"}),
    }
    for key, options in fields.items():
        if type(value[key]) is not str or value[key] not in options:
            raise DesignProfileError("invalid " + key)
    for key, allowed in (
        ("font_percent", frozenset({75, 100, 125, 150, 175, 200})),
        ("board_scale", frozenset({75, 100, 125, 150, 175, 200})),
    ):
        if type(value[key]) is not int or value[key] not in allowed:
            raise DesignProfileError("invalid " + key)
    for key in ("highlight", "animations", "sound"):
        if type(value[key]) is not bool:
            raise DesignProfileError("invalid " + key)
    return {key: value[key] for key in DEFAULT_PREFERENCES}


def _name(value: object) -> str:
    if type(value) is not str or not _NAME_RE.fullmatch(value) or value.strip() != value:
        raise DesignProfileError("unsafe or invalid profile name")
    if value in PRESETS or value in (".", "..") or value.casefold() in {
        name.casefold() for name in PRESETS
    }:
        raise DesignProfileError("built-in profile cannot be overwritten")
    return value


def validate_store(store: object) -> dict[str, Any]:
    if type(store) is not dict or set(store) != {"version", "selected", "profiles"}:
        raise DesignProfileError("invalid design store structure")
    if type(store["version"]) is not int or store["version"] != VERSION:
        raise DesignProfileError("unsupported design store version")
    raw = store["profiles"]
    if type(raw) is not dict or len(raw) > MAX_PROFILES:
        raise DesignProfileError("invalid custom profile collection")
    profiles: dict[str, dict[str, Any]] = {}
    seen = {name.casefold() for name in PRESETS}
    for name, value in raw.items():
        safe_name = _name(name)
        if safe_name.casefold() in seen:
            raise DesignProfileError("ambiguous profile name")
        seen.add(safe_name.casefold())
        profiles[safe_name] = validate_preferences(value)
    selected = store["selected"]
    if type(selected) is not str or selected not in PRESETS and selected not in profiles:
        raise DesignProfileError("selected profile does not exist")
    return {"version": VERSION, "selected": selected, "profiles": profiles}


def read_store(text: object) -> dict[str, Any]:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_BYTES:
        raise DesignProfileError("design profile payload exceeds limit")
    try:
        value = json.loads(
            text, object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise DesignProfileError("malformed design profile payload") from exc
    return validate_store(value)


def serialize_store(store: object) -> str:
    value = validate_store(store)
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise DesignProfileError("design profile payload exceeds limit")
    return encoded


def selected_preferences(store: Mapping[str, Any]) -> dict[str, Any]:
    valid = validate_store(dict(store))
    name = valid["selected"]
    return dict(PRESETS[name] if name in PRESETS else valid["profiles"][name])


def save_copy(store: object, name: str, preferences: object) -> dict[str, Any]:
    current = validate_store(store)
    safe_name = _name(name)
    if safe_name not in current["profiles"] and len(current["profiles"]) >= MAX_PROFILES:
        raise DesignProfileError("profile limit reached")
    current["profiles"][safe_name] = validate_preferences(preferences)
    current["selected"] = safe_name
    return validate_store(current)
