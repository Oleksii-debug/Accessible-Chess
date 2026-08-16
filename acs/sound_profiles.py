from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Mapping


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
)

OPTIONAL_CLASSROOM_SOUND_EVENTS = (
    "classroom.join",
    "classroom.leave",
    "classroom.hand_raise",
    "classroom.permission",
    "lesson.position_deployed",
)

_ALLOWED_AUDIO_SUFFIXES = {".wav", ".ogg", ".mp3"}


@dataclass(frozen=True)
class SoundEventPreference:
    enabled: bool = True
    volume_percent: int = 100
    sound_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.volume_percent, bool) or not 0 <= int(self.volume_percent) <= 100:
            raise ValueError("sound event volume_percent must be in 0..100")
        object.__setattr__(self, "volume_percent", int(self.volume_percent))
        if self.sound_id is not None:
            sound_id = str(self.sound_id).strip().lower()
            if not sound_id:
                raise ValueError("sound_id cannot be blank")
            object.__setattr__(self, "sound_id", sound_id)


@dataclass(frozen=True)
class SoundPackManifest:
    pack_id: str
    version: str
    title: str
    license_id: str
    files: Mapping[str, str]
    author: str = ""

    def __post_init__(self) -> None:
        pack_id = _stable_id(self.pack_id)
        version = str(self.version).strip()
        title = str(self.title).strip()
        license_id = str(self.license_id).strip()
        if not version or not title or not license_id:
            raise ValueError("sound pack version, title and license_id are required")
        files: dict[str, str] = {}
        for sound_id, value in dict(self.files).items():
            key = _stable_id(sound_id, allow_dot=True)
            path = _safe_audio_path(value)
            if key in files:
                raise ValueError(f"duplicate sound id: {key}")
            files[key] = path
        missing = [event for event in CORE_SOUND_EVENTS if event not in files]
        if missing:
            raise ValueError(f"sound pack is missing core events: {', '.join(missing)}")
        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "license_id", license_id)
        object.__setattr__(self, "author", str(self.author).strip())
        object.__setattr__(self, "files", files)


@dataclass(frozen=True)
class SoundProfile:
    pack_id: str = "classic"
    master_enabled: bool = True
    master_volume_percent: int = 80
    events: Mapping[str, SoundEventPreference] = field(default_factory=dict)

    def __post_init__(self) -> None:
        pack_id = _stable_id(self.pack_id)
        if isinstance(self.master_volume_percent, bool) or not 0 <= int(self.master_volume_percent) <= 100:
            raise ValueError("master_volume_percent must be in 0..100")
        normalized: dict[str, SoundEventPreference] = {}
        for event_id, preference in dict(self.events).items():
            key = _stable_id(event_id, allow_dot=True)
            if not isinstance(preference, SoundEventPreference):
                raise TypeError("events must contain SoundEventPreference values")
            normalized[key] = preference
        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "master_volume_percent", int(self.master_volume_percent))
        object.__setattr__(self, "events", normalized)

    def preference_for(self, event_id: str) -> SoundEventPreference:
        event_id = _stable_id(event_id, allow_dot=True)
        return self.events.get(event_id, SoundEventPreference())

    def effective_volume(self, event_id: str) -> int:
        pref = self.preference_for(event_id)
        if not self.master_enabled or not pref.enabled:
            return 0
        return round(self.master_volume_percent * pref.volume_percent / 100)


def _stable_id(value: object, *, allow_dot: bool = False) -> str:
    text = str(value).strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-" + ("." if allow_dot else "")
    if not text or any(ch not in allowed for ch in text):
        raise ValueError("id must use lowercase ascii letters, digits, dot, dash or underscore")
    return text


def _safe_audio_path(value: object) -> str:
    text = str(value).strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError("sound file path must stay below pack root")
    if path.suffix.lower() not in _ALLOWED_AUDIO_SUFFIXES:
        raise ValueError("unsupported sound asset type")
    return path.as_posix()
