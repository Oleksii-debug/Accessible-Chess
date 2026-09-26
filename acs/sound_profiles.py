from __future__ import annotations

"""Persistent sound-profile and pack metadata contracts.

This module is presentation/application policy only.  Semantic chess-event ordering
remains owned by :mod:`acs.sound_events`; sound profiles can silence, remap or scale
an already-produced event but never invent chess state or reorder events.
"""

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .sound_events import SoundEvent


SOUND_PROFILE_SCHEMA_VERSION = 1
SOUND_PACK_MANIFEST_SCHEMA_VERSION = 1

CORE_SOUND_EVENTS = tuple(event.value for event in SoundEvent) + ("low_time",)
OPTIONAL_CLASSROOM_SOUND_EVENTS = (
    "classroom.join",
    "classroom.leave",
    "classroom.hand_raise",
    "classroom.permission",
    "lesson.position_deployed",
    "classroom.chat",
    "classroom.file_complete",
)

_ALLOWED_AUDIO_SUFFIXES = {".wav", ".ogg", ".mp3"}
_HEX = frozenset("0123456789abcdef")


def _stable_id(value: object, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError("id must be text")
    text = value.strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-" + ("." if allow_dot else "")
    if not text or any(ch not in allowed for ch in text):
        raise ValueError(
            "id must use lowercase ascii letters, digits, dot, dash or underscore"
        )
    return text


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    text = value.strip()
    if not text:
        raise ValueError(f"{name} is required")
    if any(ord(ch) < 32 for ch in text):
        raise ValueError(f"{name} contains control characters")
    return text


def _safe_audio_path(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("sound file path must be text")
    text = value.strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError("sound file path must stay below pack root")
    if any(part in {"", "."} for part in path.parts):
        raise ValueError("sound file path contains an empty/current-directory part")
    if ":" in path.parts[0]:
        raise ValueError("sound file path must not contain a drive prefix")
    if path.suffix.lower() not in _ALLOWED_AUDIO_SUFFIXES:
        raise ValueError("unsupported sound asset type")
    return path.as_posix()


def _sha256(value: object, name: str = "sha256") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    digest = value.strip().lower()
    if len(digest) != 64 or any(ch not in _HEX for ch in digest):
        raise ValueError(f"{name} must be a 64-character lowercase hex digest")
    return digest


@dataclass(frozen=True)
class SoundEventPreference:
    enabled: bool = True
    volume_percent: int = 100
    sound_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("sound event enabled must be boolean")
        if isinstance(self.volume_percent, bool) or not isinstance(
            self.volume_percent, int
        ):
            raise TypeError("sound event volume_percent must be an integer")
        if not 0 <= self.volume_percent <= 100:
            raise ValueError("sound event volume_percent must be in 0..100")
        if self.sound_id is not None:
            object.__setattr__(
                self, "sound_id", _stable_id(self.sound_id, allow_dot=True)
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
        enabled = raw.get("enabled", True)
        if type(enabled) is not bool:
            raise TypeError("sound event enabled must be boolean")
        volume = raw.get("volume_percent", 100)
        if isinstance(volume, bool) or not isinstance(volume, int):
            raise TypeError("sound event volume_percent must be an integer")
        sound_id = raw.get("sound_id")
        if sound_id is not None and not isinstance(sound_id, str):
            raise TypeError("sound_id must be a string or null")
        return cls(enabled=enabled, volume_percent=volume, sound_id=sound_id)


@dataclass(frozen=True)
class SoundPackManifest:
    pack_id: str
    version: str
    title: str
    license_id: str
    files: Mapping[str, str]
    sha256: Mapping[str, str]
    author: str
    provenance: str
    schema_version: int = SOUND_PACK_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(
            self.schema_version, int
        ):
            raise TypeError("sound pack schema_version must be an integer")
        if self.schema_version != SOUND_PACK_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported sound pack manifest schema: {self.schema_version}"
            )
        object.__setattr__(self, "pack_id", _stable_id(self.pack_id, allow_dot=True))
        object.__setattr__(self, "version", _required_text(self.version, "version"))
        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(
            self, "license_id", _required_text(self.license_id, "license_id")
        )
        object.__setattr__(self, "author", _required_text(self.author, "author"))
        object.__setattr__(
            self, "provenance", _required_text(self.provenance, "provenance")
        )

        files: dict[str, str] = {}
        for sound_id, value in dict(self.files).items():
            key = _stable_id(sound_id, allow_dot=True)
            if key in files:
                raise ValueError(f"duplicate sound id: {key}")
            files[key] = _safe_audio_path(value)

        hashes: dict[str, str] = {}
        for sound_id, value in dict(self.sha256).items():
            key = _stable_id(sound_id, allow_dot=True)
            if key in hashes:
                raise ValueError(f"duplicate sound hash id: {key}")
            hashes[key] = _sha256(value, f"sha256[{key}]")

        missing = [event for event in CORE_SOUND_EVENTS if event not in files]
        if missing:
            raise ValueError(f"sound pack is missing core events: {', '.join(missing)}")
        if set(hashes) != set(files):
            missing_hashes = sorted(set(files) - set(hashes))
            extra_hashes = sorted(set(hashes) - set(files))
            raise ValueError(
                "sound pack hashes must match files exactly; "
                f"missing={missing_hashes!r} extra={extra_hashes!r}"
            )

        object.__setattr__(self, "files", files)
        object.__setattr__(self, "sha256", hashes)

    def sound_path(self, sound_id: str) -> str:
        key = _stable_id(sound_id, allow_dot=True)
        try:
            return self.files[key]
        except KeyError as exc:
            raise KeyError(
                f"unknown sound id for pack {self.pack_id}: {key}"
            ) from exc

    def sound_sha256(self, sound_id: str) -> str:
        key = _stable_id(sound_id, allow_dot=True)
        try:
            return self.sha256[key]
        except KeyError as exc:
            raise KeyError(
                f"unknown sound hash for pack {self.pack_id}: {key}"
            ) from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "version": self.version,
            "title": self.title,
            "author": self.author,
            "license_id": self.license_id,
            "provenance": self.provenance,
            "files": dict(self.files),
            "sha256": dict(self.sha256),
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SoundPackManifest":
        if not isinstance(raw, Mapping):
            raise TypeError("sound pack manifest must be an object")
        files = raw.get("files")
        hashes = raw.get("sha256")
        if not isinstance(files, Mapping):
            raise TypeError("sound pack files must be an object")
        if not isinstance(hashes, Mapping):
            raise TypeError("sound pack sha256 must be an object")
        schema = raw.get("schema_version", SOUND_PACK_MANIFEST_SCHEMA_VERSION)
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise TypeError("sound pack schema_version must be an integer")
        return cls(
            schema_version=schema,
            pack_id=raw.get("pack_id"),  # type: ignore[arg-type]
            version=raw.get("version"),  # type: ignore[arg-type]
            title=raw.get("title"),  # type: ignore[arg-type]
            author=raw.get("author"),  # type: ignore[arg-type]
            license_id=raw.get("license_id"),  # type: ignore[arg-type]
            provenance=raw.get("provenance"),  # type: ignore[arg-type]
            files={str(key): value for key, value in files.items()},  # type: ignore[dict-item]
            sha256={str(key): value for key, value in hashes.items()},  # type: ignore[dict-item]
        )


@dataclass(frozen=True)
class SoundPackCatalogEntry:
    """Provider-neutral remote catalogue metadata.

    Download/network implementations live behind another adapter.  This DTO contains
    no credentials and requires an HTTPS URL plus a pinned archive digest/size.
    """

    pack_id: str
    version: str
    title: str
    author: str
    license_id: str
    provenance: str
    download_url: str
    archive_sha256: str
    archive_size_bytes: int
    min_product_sound_api: int = 1
    max_product_sound_api: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "pack_id", _stable_id(self.pack_id, allow_dot=True))
        for name in ("version", "title", "author", "license_id", "provenance"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(
            self, "archive_sha256", _sha256(self.archive_sha256, "archive_sha256")
        )
        if isinstance(self.archive_size_bytes, bool) or not isinstance(
            self.archive_size_bytes, int
        ):
            raise TypeError("archive_size_bytes must be an integer")
        if self.archive_size_bytes <= 0:
            raise ValueError("archive_size_bytes must be positive")
        for name in ("min_product_sound_api", "max_product_sound_api"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.min_product_sound_api > self.max_product_sound_api:
            raise ValueError("sound API compatibility range is inverted")

        url = _required_text(self.download_url, "download_url")
        parts = urlsplit(url)
        if (
            parts.scheme.casefold() != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
        ):
            raise ValueError("download_url must be credential-free HTTPS without fragment")
        object.__setattr__(self, "download_url", url)


@dataclass(frozen=True)
class SoundProfile:
    pack_id: str = "classic"
    master_enabled: bool = True
    master_volume_percent: int = 80
    events: Mapping[str, SoundEventPreference] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pack_id", _stable_id(self.pack_id, allow_dot=True))
        if type(self.master_enabled) is not bool:
            raise TypeError("master_enabled must be boolean")
        if isinstance(self.master_volume_percent, bool) or not isinstance(
            self.master_volume_percent, int
        ):
            raise TypeError("master_volume_percent must be an integer")
        if not 0 <= self.master_volume_percent <= 100:
            raise ValueError("master_volume_percent must be in 0..100")

        normalized: dict[str, SoundEventPreference] = {}
        for event_id, preference in dict(self.events).items():
            key = _stable_id(event_id, allow_dot=True)
            if not isinstance(preference, SoundEventPreference):
                raise TypeError("events must contain SoundEventPreference values")
            normalized[key] = preference
        object.__setattr__(self, "events", normalized)

    def preference_for(self, event_id: str) -> SoundEventPreference:
        key = _stable_id(event_id, allow_dot=True)
        return self.events.get(key, SoundEventPreference())

    def effective_volume(self, event_id: str) -> int:
        pref = self.preference_for(event_id)
        if not self.master_enabled or not pref.enabled:
            return 0
        return round(self.master_volume_percent * pref.volume_percent / 100)

    def selected_sound_id(self, event_id: str) -> str:
        key = _stable_id(event_id, allow_dot=True)
        return self.preference_for(key).sound_id or key

    def with_pack(self, pack_id: str, *, clear_sound_ids: bool = False) -> "SoundProfile":
        events = self.events
        if clear_sound_ids:
            events = {
                event_id: replace(preference, sound_id=None)
                for event_id, preference in self.events.items()
            }
        return replace(
            self,
            pack_id=_stable_id(pack_id, allow_dot=True),
            events=events,
        )

    def with_event(
        self,
        event_id: str,
        preference: SoundEventPreference,
    ) -> "SoundProfile":
        key = _stable_id(event_id, allow_dot=True)
        if not isinstance(preference, SoundEventPreference):
            raise TypeError("preference must be SoundEventPreference")
        events = dict(self.events)
        events[key] = preference
        return replace(self, events=events)

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
        schema_version = raw.get("schema_version")
        if schema_version is None:
            enabled = raw.get("sounds", True)
            volume = raw.get("volume", 80)
            if type(enabled) is not bool:
                raise TypeError("legacy sounds setting must be boolean")
            if isinstance(volume, bool) or not isinstance(volume, int):
                raise TypeError("legacy volume setting must be an integer")
            return cls(
                pack_id="classic",
                master_enabled=enabled,
                master_volume_percent=volume,
            )
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise TypeError("sound profile schema_version must be an integer")
        if schema_version != SOUND_PROFILE_SCHEMA_VERSION:
            raise ValueError(f"unsupported sound profile schema: {schema_version}")

        enabled = raw.get("master_enabled", True)
        volume = raw.get("master_volume_percent", 80)
        pack_id = raw.get("pack_id", "classic")
        if type(enabled) is not bool:
            raise TypeError("master_enabled must be boolean")
        if isinstance(volume, bool) or not isinstance(volume, int):
            raise TypeError("master_volume_percent must be an integer")
        if not isinstance(pack_id, str):
            raise TypeError("pack_id must be text")
        events_raw = raw.get("events", {})
        if not isinstance(events_raw, Mapping):
            raise TypeError("sound profile events must be an object")
        events: dict[str, SoundEventPreference] = {}
        for event_id, preference in events_raw.items():
            if not isinstance(event_id, str):
                raise TypeError("sound profile event ids must be text")
            if not isinstance(preference, Mapping):
                raise TypeError("sound profile event preference must be an object")
            events[event_id] = SoundEventPreference.from_mapping(preference)
        return cls(
            pack_id=pack_id,
            master_enabled=enabled,
            master_volume_percent=volume,
            events=events,
        )


class SoundProfileStore:
    """Small atomic JSON store with explicit legacy migration and safe recovery."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.warning: str | None = None

    def load(self) -> SoundProfile:
        self.warning = None
        if not self.path.exists():
            return SoundProfile()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise TypeError("sound profile file must contain a JSON object")
            return SoundProfile.from_mapping(raw)
        except Exception as exc:
            self.warning = f"sound profile recovery: {exc}"
            return SoundProfile()

    def load_or_migrate(
        self,
        legacy_settings: Mapping[str, object] | None = None,
    ) -> SoundProfile:
        if self.path.exists():
            return self.load()
        profile = (
            SoundProfile.from_mapping(legacy_settings)
            if legacy_settings is not None
            else SoundProfile()
        )
        self.save(profile)
        self.warning = (
            "migrated legacy sound settings to sound profile"
            if legacy_settings is not None
            else None
        )
        return profile

    def save(self, profile: SoundProfile) -> None:
        if not isinstance(profile, SoundProfile):
            raise TypeError("profile must be SoundProfile")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        payload = json.dumps(
            profile.to_mapping(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


class SoundPreviewPlaybackPort(Protocol):
    def play_sound(
        self,
        *,
        pack_id: str,
        sound_id: str,
        volume: int,
        fallback_event: SoundEvent | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class SoundPreviewResult:
    event_id: str
    played: bool
    reason: str = ""


class SoundPreviewService:
    """Accessible preview seam: caller announces the returned deterministic result."""

    def __init__(
        self,
        profile_provider: Callable[[], SoundProfile],
        playback: SoundPreviewPlaybackPort,
    ) -> None:
        if not callable(profile_provider):
            raise TypeError("profile_provider must be callable")
        if isinstance(playback, type) or not callable(
            getattr(playback, "play_sound", None)
        ):
            raise TypeError("playback must expose play_sound")
        self._profile_provider = profile_provider
        self._playback = playback

    def preview(self, event_id: str) -> SoundPreviewResult:
        key = _stable_id(event_id, allow_dot=True)
        profile = self._profile_provider()
        if not isinstance(profile, SoundProfile):
            raise TypeError("profile_provider must return SoundProfile")
        volume = profile.effective_volume(key)
        if volume == 0:
            return SoundPreviewResult(key, False, "silenced")
        fallback = None
        try:
            fallback = SoundEvent(key)
        except ValueError:
            pass
        self._playback.play_sound(
            pack_id=profile.pack_id,
            sound_id=profile.selected_sound_id(key),
            volume=volume,
            fallback_event=fallback,
        )
        return SoundPreviewResult(key, True, "played")
