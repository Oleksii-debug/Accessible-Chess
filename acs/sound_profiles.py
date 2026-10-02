from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Mapping


SOUND_PROFILE_SCHEMA_VERSION = 1
SOUND_PACK_MANIFEST_SCHEMA_VERSION = 1

CORE_SOUND_EVENTS = (
    "start",
    "move",
    "capture",
    "check",
    "castle",
    "promotion",
    "illegal",
    "end",
    "tick",
    "low_time",
)

OPTIONAL_CLASSROOM_SOUND_EVENTS = (
    "classroom.join",
    "classroom.leave",
    "classroom.hand_raise",
    "classroom.permission",
    "lesson.position_deployed",
    "chat.message",
    "file.transfer_complete",
)

_ALLOWED_AUDIO_SUFFIXES = {".wav", ".ogg", ".mp3"}
_WINDOWS_FORBIDDEN_PATH_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_BASENAMES = frozenset({"con", "prn", "aux", "nul", "conin$", "conout$"})
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9a-z]+(?:[.-][0-9a-z]+)*))?$")


@dataclass(frozen=True)
class SoundEventPreference:
    enabled: bool = True
    volume_percent: int = 100
    sound_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("sound event enabled must be boolean")
        if isinstance(self.volume_percent, bool) or not isinstance(self.volume_percent, int):
            raise TypeError("sound event volume_percent must be an integer")
        if not 0 <= self.volume_percent <= 100:
            raise ValueError("sound event volume_percent must be in 0..100")
        if self.sound_id is not None:
            sound_id = _stable_id(self.sound_id, allow_dot=True)
            object.__setattr__(self, "sound_id", sound_id)

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
        expected = {"enabled", "volume_percent", "sound_id"}
        if set(raw) != expected:
            raise ValueError("sound event preference fields are invalid")
        enabled = raw["enabled"]
        if type(enabled) is not bool:
            raise TypeError("sound event enabled must be boolean")
        sound_id = raw["sound_id"]
        if sound_id is not None and type(sound_id) is not str:
            raise TypeError("sound_id must be a string or null")
        return cls(
            enabled=enabled,
            volume_percent=raw["volume_percent"],
            sound_id=sound_id,
        )


@dataclass(frozen=True)
class SoundPackManifest:
    pack_id: str
    version: str
    title: str
    license_id: str
    files: Mapping[str, str]
    author: str = ""
    provenance: str = ""

    def __post_init__(self) -> None:
        pack_id = _stable_id(self.pack_id, allow_dot=True)
        for name in ("version", "title", "license_id", "author", "provenance"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"sound pack {name} must be text")
        version = _stable_version(self.version)
        title = self.title.strip()
        license_id = self.license_id.strip()
        author = self.author.strip()
        provenance = self.provenance.strip()
        if not version or not title or not license_id or not author or not provenance:
            raise ValueError(
                "sound pack version, title, author, license_id and provenance are required"
            )
        if not isinstance(self.files, Mapping):
            raise TypeError("sound pack files must be a mapping")
        files: dict[str, str] = {}
        path_spellings: dict[str, str] = {}
        for sound_id, value in self.files.items():
            key = _stable_id(sound_id, allow_dot=True)
            path = _safe_audio_path(value)
            if key in files:
                raise ValueError(f"duplicate sound id: {key}")
            folded = path.casefold()
            previous = path_spellings.get(folded)
            if previous is not None and previous != path:
                raise ValueError("sound pack contains Windows case-colliding asset paths")
            path_spellings[folded] = path
            files[key] = path
        missing = [event for event in CORE_SOUND_EVENTS if event not in files]
        if missing:
            raise ValueError(f"sound pack is missing core events: {', '.join(missing)}")
        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "license_id", license_id)
        object.__setattr__(self, "author", author)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "files", files)

    def sound_path(self, sound_id: str) -> str:
        key = _stable_id(sound_id, allow_dot=True)
        try:
            return self.files[key]
        except KeyError as exc:
            raise KeyError(f"unknown sound id for pack {self.pack_id}: {key}") from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": SOUND_PACK_MANIFEST_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "version": self.version,
            "title": self.title,
            "license_id": self.license_id,
            "files": dict(sorted(self.files.items())),
            "author": self.author,
            "provenance": self.provenance,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SoundPackManifest":
        if not isinstance(raw, Mapping) or any(type(key) is not str for key in raw):
            raise TypeError("sound pack manifest must be an object with text keys")
        expected = {
            "schema_version",
            "pack_id",
            "version",
            "title",
            "license_id",
            "files",
            "author",
            "provenance",
        }
        if set(raw) != expected:
            raise ValueError("sound pack manifest fields are invalid")
        schema = raw["schema_version"]
        if type(schema) is not int or schema != SOUND_PACK_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported sound pack manifest schema: {schema}")
        files_raw = raw["files"]
        if not isinstance(files_raw, Mapping) or any(
            type(key) is not str or type(value) is not str
            for key, value in files_raw.items()
        ):
            raise TypeError("sound pack manifest files must map text ids to text paths")
        return cls(
            pack_id=raw["pack_id"],  # type: ignore[arg-type]
            version=raw["version"],  # type: ignore[arg-type]
            title=raw["title"],  # type: ignore[arg-type]
            license_id=raw["license_id"],  # type: ignore[arg-type]
            files=dict(files_raw),
            author=raw["author"],  # type: ignore[arg-type]
            provenance=raw["provenance"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class SoundProfile:
    pack_id: str = "classic"
    master_enabled: bool = True
    master_volume_percent: int = 80
    events: Mapping[str, SoundEventPreference] = field(default_factory=dict)

    def __post_init__(self) -> None:
        pack_id = _stable_id(self.pack_id, allow_dot=True)
        if not isinstance(self.master_enabled, bool):
            raise TypeError("master_enabled must be boolean")
        if isinstance(self.master_volume_percent, bool) or not isinstance(self.master_volume_percent, int):
            raise TypeError("master_volume_percent must be an integer")
        if not 0 <= self.master_volume_percent <= 100:
            raise ValueError("master_volume_percent must be in 0..100")
        if not isinstance(self.events, Mapping):
            raise TypeError("events must be a mapping")
        normalized: dict[str, SoundEventPreference] = {}
        for event_id, preference in self.events.items():
            key = _stable_id(event_id, allow_dot=True)
            if not isinstance(preference, SoundEventPreference):
                raise TypeError("events must contain SoundEventPreference values")
            normalized[key] = preference
        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "events", normalized)

    def preference_for(self, event_id: str) -> SoundEventPreference:
        event_id = _stable_id(event_id, allow_dot=True)
        return self.events.get(event_id, SoundEventPreference())

    def effective_volume(self, event_id: str) -> int:
        pref = self.preference_for(event_id)
        if not self.master_enabled or not pref.enabled:
            return 0
        return round(self.master_volume_percent * pref.volume_percent / 100)

    def selected_sound_id(self, event_id: str) -> str:
        event_id = _stable_id(event_id, allow_dot=True)
        return self.preference_for(event_id).sound_id or event_id

    def with_pack(self, pack_id: str) -> "SoundProfile":
        """Retarget without carrying pack-relative asset ids across packs."""

        target = _stable_id(pack_id, allow_dot=True)
        if target == self.pack_id:
            return self
        events = {
            event_id: SoundEventPreference(
                enabled=preference.enabled,
                volume_percent=preference.volume_percent,
                sound_id=None,
            )
            for event_id, preference in self.events.items()
        }
        return SoundProfile(
            pack_id=target,
            master_enabled=self.master_enabled,
            master_volume_percent=self.master_volume_percent,
            events=events,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": SOUND_PROFILE_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "master_enabled": self.master_enabled,
            "master_volume_percent": self.master_volume_percent,
            "events": {
                event_id: preference.to_mapping()
                for event_id, preference in self.events.items()
            },
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SoundProfile":
        if not isinstance(raw, Mapping) or any(type(key) is not str for key in raw):
            raise TypeError("sound profile must be an object with text keys")
        schema_version = raw.get("schema_version")
        if schema_version is None:
            if not raw or not set(raw) <= {"sounds", "volume"}:
                raise ValueError("legacy sound profile fields are invalid")
            enabled = raw.get("sounds", True)
            if type(enabled) is not bool:
                raise TypeError("legacy sounds setting must be boolean")
            return cls(
                pack_id="classic",
                master_enabled=enabled,
                master_volume_percent=raw.get("volume", 80),
            )
        if type(schema_version) is not int or schema_version != SOUND_PROFILE_SCHEMA_VERSION:
            raise ValueError(f"unsupported sound profile schema: {schema_version}")
        expected = {
            "schema_version",
            "pack_id",
            "master_enabled",
            "master_volume_percent",
            "events",
        }
        if set(raw) != expected:
            raise ValueError("sound profile fields are invalid")
        enabled = raw["master_enabled"]
        if type(enabled) is not bool:
            raise TypeError("master_enabled must be boolean")
        events_raw = raw["events"]
        if not isinstance(events_raw, Mapping):
            raise TypeError("sound profile events must be an object")
        events: dict[str, SoundEventPreference] = {}
        for event_id, preference in events_raw.items():
            if type(event_id) is not str:
                raise TypeError("sound profile event ids must be text")
            events[event_id] = SoundEventPreference.from_mapping(preference)
        return cls(
            pack_id=raw["pack_id"],
            master_enabled=enabled,
            master_volume_percent=raw["master_volume_percent"],
            events=events,
        )


def _stable_id(value: object, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError("id must be text")
    text = value.strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-" + ("." if allow_dot else "")
    if not text or any(ch not in allowed for ch in text):
        raise ValueError("id must use lowercase ascii letters, digits, dot, dash or underscore")
    return text


def _stable_version(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("sound pack version must be text")
    text = value.strip().lower()
    if not _VERSION_RE.fullmatch(text):
        raise ValueError("sound pack version must be canonical semantic version text")
    return text


def _windows_reserved_path_component(part: str) -> bool:
    """Reject Win32 device aliases even when an extension is present."""

    basename = part.split(".", 1)[0].rstrip(" ").casefold()
    if basename in _WINDOWS_RESERVED_BASENAMES:
        return True
    return bool(
        len(basename) == 4
        and basename[:3] in {"com", "lpt"}
        and basename[3] in "123456789"
    )


def _safe_audio_path(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("sound file path must be text")
    text = value.strip().replace("\\", "/")
    if not text or "\x00" in text:
        raise ValueError("sound file path must stay below pack root")
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or any(part in {"", "."} for part in posix.parts)
    ):
        raise ValueError("sound file path must stay below pack root")
    for part in posix.parts:
        if part.endswith((" ", ".")):
            raise ValueError("sound file path is not stable on Windows")
        if (
            any(ch in _WINDOWS_FORBIDDEN_PATH_CHARS or ord(ch) < 32 for ch in part)
            or _windows_reserved_path_component(part)
        ):
            raise ValueError("sound file path is not valid on Windows")
    if posix.suffix.lower() not in _ALLOWED_AUDIO_SUFFIXES:
        raise ValueError("unsupported sound asset type")
    return posix.as_posix()
