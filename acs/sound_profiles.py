from __future__ import annotations

"""Versioned, presentation-neutral sound profile and pack contracts.

Chess semantics remain owned by sound_events.SoundEvent. This module only
controls downstream playback preferences and safe pack metadata; it cannot add,
remove or reorder semantic chess events.
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Mapping

from .sound_events import SoundEvent


SOUND_PROFILE_SCHEMA_VERSION = 1
SOUND_PACK_MANIFEST_SCHEMA_VERSION = 1

CORE_SOUND_EVENTS = tuple(event.value for event in SoundEvent)
OPTIONAL_CLASSROOM_SOUND_EVENTS = (
    "classroom.join",
    "classroom.leave",
    "classroom.hand_raise",
    "classroom.permission",
    "lesson.position_deployed",
    "classroom.chat",
    "classroom.file_transfer_complete",
)
KNOWN_SOUND_EVENTS = CORE_SOUND_EVENTS + OPTIONAL_CLASSROOM_SOUND_EVENTS
_KNOWN_SOUND_EVENT_SET = frozenset(KNOWN_SOUND_EVENTS)
_ALLOWED_AUDIO_SUFFIXES = frozenset({".wav"})


def canonical_sound_id(value: object, *, label: str = "sound id") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    text = value.strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789._-"
    if not text or any(ch not in allowed for ch in text):
        raise ValueError(
            f"{label} must use lowercase ASCII letters, digits, dot, dash or underscore"
        )
    return text


def canonical_sound_event_id(value: object) -> str:
    event_id = canonical_sound_id(value, label="sound event id")
    if event_id not in _KNOWN_SOUND_EVENT_SET:
        raise ValueError(f"unknown sound event id: {event_id}")
    return event_id


def safe_sound_asset_path(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("sound asset path must be text")
    text = value.strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("sound asset path must stay below the pack root")
    if path.suffix.lower() not in _ALLOWED_AUDIO_SUFFIXES:
        raise ValueError("current Windows sound packs support WAV assets only")
    if any(not part or ":" in part for part in path.parts):
        raise ValueError("sound asset path is invalid")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class SoundEventPreference:
    enabled: bool = True
    volume_percent: int = 100
    sound_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("sound event enabled must be boolean")
        if type(self.volume_percent) is not int:
            raise TypeError("sound event volume_percent must be an integer")
        if not 0 <= self.volume_percent <= 100:
            raise ValueError("sound event volume_percent must be in 0..100")
        if self.sound_id is not None:
            object.__setattr__(
                self,
                "sound_id",
                canonical_sound_id(self.sound_id, label="sound id"),
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "volume_percent": self.volume_percent,
            "sound_id": self.sound_id,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SoundEventPreference":
        if not isinstance(raw, Mapping):
            raise TypeError("sound event preference must be an object")
        allowed = {"enabled", "volume_percent", "sound_id"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError("sound event preference contains unknown fields")
        enabled = raw.get("enabled", True)
        volume = raw.get("volume_percent", 100)
        sound_id = raw.get("sound_id")
        if type(enabled) is not bool:
            raise TypeError("sound event enabled must be boolean")
        if type(volume) is not int:
            raise TypeError("sound event volume_percent must be an integer")
        if sound_id is not None and not isinstance(sound_id, str):
            raise TypeError("sound_id must be text or null")
        return cls(enabled=enabled, volume_percent=volume, sound_id=sound_id)


@dataclass(frozen=True, slots=True)
class SoundPackManifest:
    pack_id: str
    version: str
    title: str
    license_id: str
    files: Mapping[str, str]
    author: str
    provenance: str

    def __post_init__(self) -> None:
        pack_id = canonical_sound_id(self.pack_id, label="sound pack id")
        for label, value in (
            ("version", self.version),
            ("title", self.title),
            ("license_id", self.license_id),
            ("author", self.author),
            ("provenance", self.provenance),
        ):
            if not isinstance(value, str):
                raise TypeError(f"sound pack {label} must be text")
            if not value.strip():
                raise ValueError(f"sound pack {label} is required")

        if not isinstance(self.files, Mapping):
            raise TypeError("sound pack files must be an object")
        normalized: dict[str, str] = {}
        for raw_id, raw_path in self.files.items():
            sound_id = canonical_sound_id(raw_id, label="sound id")
            if sound_id in normalized:
                raise ValueError(f"duplicate sound id: {sound_id}")
            normalized[sound_id] = safe_sound_asset_path(raw_path)
        missing = [event for event in CORE_SOUND_EVENTS if event not in normalized]
        if missing:
            raise ValueError(
                "sound pack is missing core events: " + ", ".join(missing)
            )

        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "license_id", self.license_id.strip())
        object.__setattr__(self, "author", self.author.strip())
        object.__setattr__(self, "provenance", self.provenance.strip())
        object.__setattr__(self, "files", MappingProxyType(normalized))

    def sound_path(self, sound_id: str) -> str:
        key = canonical_sound_id(sound_id, label="sound id")
        try:
            return self.files[key]
        except KeyError as exc:
            raise KeyError(
                f"sound pack {self.pack_id} does not define sound {key}"
            ) from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": SOUND_PACK_MANIFEST_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "version": self.version,
            "title": self.title,
            "license_id": self.license_id,
            "author": self.author,
            "provenance": self.provenance,
            "files": dict(self.files),
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SoundPackManifest":
        if not isinstance(raw, Mapping):
            raise TypeError("sound pack manifest must be an object")
        allowed = {
            "schema_version",
            "pack_id",
            "version",
            "title",
            "license_id",
            "author",
            "provenance",
            "files",
        }
        if set(raw) - allowed:
            raise ValueError("sound pack manifest contains unknown fields")
        schema = raw.get("schema_version")
        if type(schema) is not int or schema != SOUND_PACK_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported sound pack manifest schema")
        files = raw.get("files")
        if not isinstance(files, Mapping):
            raise TypeError("sound pack files must be an object")
        return cls(
            pack_id=raw.get("pack_id"),  # type: ignore[arg-type]
            version=raw.get("version"),  # type: ignore[arg-type]
            title=raw.get("title"),  # type: ignore[arg-type]
            license_id=raw.get("license_id"),  # type: ignore[arg-type]
            author=raw.get("author"),  # type: ignore[arg-type]
            provenance=raw.get("provenance"),  # type: ignore[arg-type]
            files=files,
        )


@dataclass(frozen=True, slots=True)
class SoundProfile:
    pack_id: str = "classic"
    master_enabled: bool = True
    master_volume_percent: int = 80
    events: Mapping[str, SoundEventPreference] = field(default_factory=dict)

    def __post_init__(self) -> None:
        pack_id = canonical_sound_id(self.pack_id, label="sound pack id")
        if type(self.master_enabled) is not bool:
            raise TypeError("master_enabled must be boolean")
        if type(self.master_volume_percent) is not int:
            raise TypeError("master_volume_percent must be an integer")
        if not 0 <= self.master_volume_percent <= 100:
            raise ValueError("master_volume_percent must be in 0..100")
        if not isinstance(self.events, Mapping):
            raise TypeError("events must be an object")

        normalized: dict[str, SoundEventPreference] = {}
        for raw_event, preference in self.events.items():
            event_id = canonical_sound_event_id(raw_event)
            if event_id in normalized:
                raise ValueError(f"duplicate sound event preference: {event_id}")
            if not isinstance(preference, SoundEventPreference):
                raise TypeError("events must contain SoundEventPreference values")
            normalized[event_id] = preference

        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "events", MappingProxyType(normalized))

    def preference_for(self, event_id: str) -> SoundEventPreference:
        key = canonical_sound_event_id(event_id)
        return self.events.get(key, SoundEventPreference())

    def effective_volume(self, event_id: str) -> int:
        preference = self.preference_for(event_id)
        if not self.master_enabled or not preference.enabled:
            return 0
        return round(
            self.master_volume_percent * preference.volume_percent / 100
        )

    def selected_sound_id(self, event_id: str) -> str:
        key = canonical_sound_event_id(event_id)
        return self.preference_for(key).sound_id or key

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": SOUND_PROFILE_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "master_enabled": self.master_enabled,
            "master_volume_percent": self.master_volume_percent,
            "events": {
                event_id: preference.to_mapping()
                for event_id, preference in sorted(self.events.items())
            },
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SoundProfile":
        if not isinstance(raw, Mapping):
            raise TypeError("sound profile must be an object")
        allowed = {
            "schema_version",
            "pack_id",
            "master_enabled",
            "master_volume_percent",
            "events",
        }
        if set(raw) - allowed:
            raise ValueError("sound profile contains unknown fields")
        schema = raw.get("schema_version")
        if type(schema) is not int or schema != SOUND_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported sound profile schema")
        pack_id = raw.get("pack_id", "classic")
        enabled = raw.get("master_enabled", True)
        volume = raw.get("master_volume_percent", 80)
        events_raw = raw.get("events", {})
        if not isinstance(pack_id, str):
            raise TypeError("sound pack id must be text")
        if type(enabled) is not bool:
            raise TypeError("master_enabled must be boolean")
        if type(volume) is not int:
            raise TypeError("master_volume_percent must be an integer")
        if not isinstance(events_raw, Mapping):
            raise TypeError("sound profile events must be an object")

        events: dict[str, SoundEventPreference] = {}
        for event_id, preference in events_raw.items():
            if not isinstance(event_id, str):
                raise TypeError("sound event id must be text")
            if not isinstance(preference, Mapping):
                raise TypeError("sound event preference must be an object")
            events[event_id] = SoundEventPreference.from_mapping(preference)
        return cls(
            pack_id=pack_id,
            master_enabled=enabled,
            master_volume_percent=volume,
            events=events,
        )

    @classmethod
    def from_legacy_settings(
        cls,
        settings: Mapping[str, object],
        *,
        pack_id: str = "classic",
    ) -> "SoundProfile":
        if not isinstance(settings, Mapping):
            raise TypeError("legacy sound settings must be an object")
        enabled = settings.get("sounds", True)
        volume = settings.get("volume", 80)
        if type(enabled) is not bool:
            raise TypeError("legacy sounds setting must be boolean")
        if type(volume) is not int:
            raise TypeError("legacy volume setting must be an integer")
        return cls(
            pack_id=pack_id,
            master_enabled=enabled,
            master_volume_percent=volume,
        )
