from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "language": "uk",
    "notation": "uk_literal",
    "sounds": True,
    "volume": 80,
    "tick_policy": "my_turn",
    "tick_last_seconds": 0,
    "engine_path": "",
}

_ALLOWED_LANGUAGE = {"uk", "en"}
_ALLOWED_NOTATION = {"san", "uk_literal", "en_literal"}
_ALLOWED_TICK_POLICY = {"off", "my_turn", "both"}


class SettingsError(ValueError):
    pass


def _validated_value(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting: {key}")
    if key == "language":
        if value not in _ALLOWED_LANGUAGE:
            raise SettingsError("language must be 'uk' or 'en'")
        return value
    if key == "notation":
        if value not in _ALLOWED_NOTATION:
            raise SettingsError("notation must be san, uk_literal, or en_literal")
        return value
    if key == "sounds":
        if not isinstance(value, bool):
            raise SettingsError("sounds must be boolean")
        return value
    if key == "volume":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise SettingsError("volume must be an integer in 0..100")
        return value
    if key == "tick_policy":
        if value not in _ALLOWED_TICK_POLICY:
            raise SettingsError("tick_policy must be off, my_turn, or both")
        return value
    if key == "tick_last_seconds":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3600:
            raise SettingsError("tick_last_seconds must be an integer in 0..3600")
        return value
    if key == "engine_path":
        if not isinstance(value, str):
            raise SettingsError("engine_path must be a string")
        return value
    return value


def _migrate(raw: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    warnings: list[str] = []
    # A missing schema key is the only legacy-v0 representation.  Do not let
    # JSON booleans, floats or numeric strings masquerade as schema integers:
    # accepting them can reinterpret a corrupted profile as a valid migration.
    if "schema_version" not in raw:
        version = 0
    else:
        version_value = raw["schema_version"]
        if isinstance(version_value, bool) or not isinstance(version_value, int):
            raise SettingsError("invalid settings schema_version")
        version = version_value

    if version > SCHEMA_VERSION:
        raise SettingsError(
            f"settings schema {version} is newer than supported schema {SCHEMA_VERSION}"
        )

    if version < 0:
        raise SettingsError("invalid settings schema_version")

    if version == 0:
        values = {key: raw[key] for key in DEFAULTS if key in raw}
        raw = {"schema_version": 1, "values": values}
        warnings.append("migrated unversioned settings to schema 1")
        version = 1

    if version == 1:
        values = raw.get("values", {})
        if not isinstance(values, Mapping):
            raise SettingsError("settings values must be an object")
        raw = {"schema_version": 2, "values": dict(values)}
        warnings.append("migrated settings schema 1 to schema 2")
        version = 2

    if version != SCHEMA_VERSION:
        raise SettingsError(f"unsupported settings schema {version}")

    values = raw.get("values", {})
    if not isinstance(values, Mapping):
        raise SettingsError("settings values must be an object")
    return dict(values), tuple(warnings)


class Settings:
    """Versioned, recovery-safe application settings.

    Preserves the legacy get/set/data API while adding explicit schema
    migration, validation, atomic writes and import/export support.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.warning: str | None = None
        self.load()

    def load(self) -> None:
        self.data = dict(DEFAULTS)
        self.warning = None
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise SettingsError("settings file must contain a JSON object")
            values, migration_warnings = _migrate(raw)
            for key, value in values.items():
                if key not in DEFAULTS:
                    continue
                self.data[key] = _validated_value(key, value)
            if migration_warnings:
                self.warning = "; ".join(migration_warnings)
        except Exception as exc:
            self.data = dict(DEFAULTS)
            self.warning = f"settings recovery: {exc}"

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        validated = _validated_value(key, value)
        self.data[key] = validated
        self.save()

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self.data = dict(DEFAULTS)
        else:
            if key not in DEFAULTS:
                raise KeyError(f"unknown setting: {key}")
            self.data[key] = DEFAULTS[key]
        self.save()

    def to_profile(self) -> dict[str, Any]:
        values = {key: self.data[key] for key in DEFAULTS}
        return {"schema_version": SCHEMA_VERSION, "values": values}

    def export_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_profile(), ensure_ascii=False, indent=indent, sort_keys=True)

    def import_json(self, text: str, *, persist: bool = True) -> tuple[str, ...]:
        raw = json.loads(text)
        if not isinstance(raw, Mapping):
            raise SettingsError("settings profile must be a JSON object")
        values, warnings = _migrate(raw)
        candidate = dict(DEFAULTS)
        for key, value in values.items():
            if key in DEFAULTS:
                candidate[key] = _validated_value(key, value)
        self.data = candidate
        self.warning = "; ".join(warnings) if warnings else None
        if persist:
            self.save()
        return warnings

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(self.export_json() + "\n", encoding="utf-8")
        tmp.replace(self.path)
