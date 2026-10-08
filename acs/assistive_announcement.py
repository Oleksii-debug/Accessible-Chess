from __future__ import annotations

"""Bounded assistive-announcement policy for media and agent events.

Adapted from Oleksii-debug/Autosport@bd1f603b769606027af409fa9a7e1385d774c4cf
src/autosport/accessibility_announcements.py
(blob 21621bca6fbe29d0999b3a1286bf2f164f414808).

The policy classifies and deduplicates events only. It does not claim NVDA
speech; the Windows emitter and human NVDA verification remain separate gates.
"""

from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Final, Mapping


class AnnouncementPriority(str, Enum):
    SILENT = "SILENT"
    POLITE = "POLITE"
    ASSERTIVE = "ASSERTIVE"


class AnnouncementKind(str, Enum):
    MEDIA_CLOCK_TICK = "MEDIA_CLOCK_TICK"
    MEDIA_BUFFERING_TICK = "MEDIA_BUFFERING_TICK"
    AGENT_PROGRESS_TICK = "AGENT_PROGRESS_TICK"

    MEDIA_MOVE = "MEDIA_MOVE"
    MEDIA_POSITION_RESTORED = "MEDIA_POSITION_RESTORED"
    MEDIA_PLAYBACK_CHANGED = "MEDIA_PLAYBACK_CHANGED"
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_RESPONSE = "AGENT_RESPONSE"
    AGENT_STOPPED = "AGENT_STOPPED"
    OPERATION_COMPLETED = "OPERATION_COMPLETED"

    MEDIA_AMBIGUOUS = "MEDIA_AMBIGUOUS"
    MEDIA_RESYNC_REQUIRED = "MEDIA_RESYNC_REQUIRED"
    AGENT_AUTHORITY_BLOCKED = "AGENT_AUTHORITY_BLOCKED"
    CRITICAL_ERROR = "CRITICAL_ERROR"


_PRIORITY_BY_KIND: Final[Mapping[AnnouncementKind, AnnouncementPriority]] = MappingProxyType({
    AnnouncementKind.MEDIA_CLOCK_TICK: AnnouncementPriority.SILENT,
    AnnouncementKind.MEDIA_BUFFERING_TICK: AnnouncementPriority.SILENT,
    AnnouncementKind.AGENT_PROGRESS_TICK: AnnouncementPriority.SILENT,
    AnnouncementKind.MEDIA_MOVE: AnnouncementPriority.POLITE,
    AnnouncementKind.MEDIA_POSITION_RESTORED: AnnouncementPriority.POLITE,
    AnnouncementKind.MEDIA_PLAYBACK_CHANGED: AnnouncementPriority.POLITE,
    AnnouncementKind.AGENT_STARTED: AnnouncementPriority.POLITE,
    AnnouncementKind.AGENT_RESPONSE: AnnouncementPriority.POLITE,
    AnnouncementKind.AGENT_STOPPED: AnnouncementPriority.POLITE,
    AnnouncementKind.OPERATION_COMPLETED: AnnouncementPriority.POLITE,
    AnnouncementKind.MEDIA_AMBIGUOUS: AnnouncementPriority.ASSERTIVE,
    AnnouncementKind.MEDIA_RESYNC_REQUIRED: AnnouncementPriority.ASSERTIVE,
    AnnouncementKind.AGENT_AUTHORITY_BLOCKED: AnnouncementPriority.ASSERTIVE,
    AnnouncementKind.CRITICAL_ERROR: AnnouncementPriority.ASSERTIVE,
})
if set(_PRIORITY_BY_KIND) != set(AnnouncementKind):
    raise RuntimeError("announcement policy must classify every kind")

_ACTIVITY_ID_PREFIX = "accessible-chess:announcement:v1:"


def _trimmed(name: str, value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class AnnouncementEvent:
    kind: AnnouncementKind
    text: str
    state_token: str
    episode_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not AnnouncementKind:
            raise TypeError("kind must be AnnouncementKind")
        _trimmed("text", self.text)
        _trimmed("state_token", self.state_token)
        priority = _PRIORITY_BY_KIND[self.kind]
        if priority is AnnouncementPriority.ASSERTIVE:
            if self.episode_id is None:
                raise ValueError("assertive event requires episode_id")
            _trimmed("episode_id", self.episode_id)
        elif self.episode_id is not None:
            raise ValueError("episode_id is only valid for assertive events")


@dataclass(frozen=True, slots=True)
class AnnouncementDecision:
    emit: bool
    priority: AnnouncementPriority
    text: str | None
    reason: str
    activity_id: str | None
    move_focus: bool = False

    def __post_init__(self) -> None:
        if type(self.emit) is not bool or type(self.move_focus) is not bool:
            raise TypeError("decision flags must be boolean")
        if self.move_focus:
            raise ValueError("announcement policy must never request focus movement")
        _trimmed("reason", self.reason)
        if self.emit:
            if self.priority is AnnouncementPriority.SILENT:
                raise ValueError("emitted decision cannot be SILENT")
            _trimmed("text", self.text)
            _validate_activity_id(self.activity_id, self.priority)
        else:
            if self.priority is not AnnouncementPriority.SILENT:
                raise ValueError("suppressed decision must be SILENT")
            if self.text is not None or self.activity_id is not None:
                raise ValueError("suppressed decision must not contain speech data")


class AnnouncementGate:
    __slots__ = ("_max_history", "_history")

    def __init__(self, *, max_history: int = 256) -> None:
        if type(max_history) is not int or max_history <= 0:
            raise ValueError("max_history must be positive")
        self._max_history = max_history
        self._history: OrderedDict[tuple[str, ...], None] = OrderedDict()

    @property
    def history_size(self) -> int:
        return len(self._history)

    def decide(self, event: AnnouncementEvent) -> AnnouncementDecision:
        if type(event) is not AnnouncementEvent:
            raise TypeError("event must be AnnouncementEvent")
        priority = _PRIORITY_BY_KIND[event.kind]
        if priority is AnnouncementPriority.SILENT:
            return _suppressed("HIGH_FREQUENCY_CHURN")

        if priority is AnnouncementPriority.ASSERTIVE:
            assert event.episode_id is not None
            key = ("ASSERTIVE", event.episode_id)
            duplicate_reason = "DUPLICATE_CRITICAL_EPISODE"
        else:
            key = ("POLITE", event.state_token)
            duplicate_reason = "DUPLICATE_STATE_TRANSITION"

        if key in self._history:
            self._history.move_to_end(key)
            return _suppressed(duplicate_reason)

        self._history[key] = None
        while len(self._history) > self._max_history:
            self._history.popitem(last=False)

        return AnnouncementDecision(
            emit=True,
            priority=priority,
            text=event.text,
            reason="EMIT",
            activity_id=_activity_id_for_key(key),
            move_focus=False,
        )


def priority_for_kind(kind: AnnouncementKind) -> AnnouncementPriority:
    if type(kind) is not AnnouncementKind:
        raise TypeError("kind must be AnnouncementKind")
    return _PRIORITY_BY_KIND[kind]


def _activity_id_for_key(key: tuple[str, str]) -> str:
    identity_kind, identity = key
    payload = identity_kind.encode("ascii") + b"\0" + identity.encode("utf-8")
    digest = sha256(payload).hexdigest()
    return f"{_ACTIVITY_ID_PREFIX}{identity_kind.lower()}:sha256:{digest}"


def _validate_activity_id(value: object, priority: AnnouncementPriority) -> str:
    result = _trimmed("activity_id", value)
    if not result.isascii() or not result.startswith(_ACTIVITY_ID_PREFIX):
        raise ValueError("activity_id must be a product-issued ASCII identity")
    suffix = result[len(_ACTIVITY_ID_PREFIX):]
    try:
        identity_kind, algorithm, digest = suffix.split(":", 2)
    except ValueError as exc:
        raise ValueError("invalid activity_id format") from exc
    if identity_kind != priority.value.lower() or algorithm != "sha256":
        raise ValueError("invalid activity_id format")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("invalid activity_id digest")
    return result


def _suppressed(reason: str) -> AnnouncementDecision:
    return AnnouncementDecision(
        emit=False,
        priority=AnnouncementPriority.SILENT,
        text=None,
        reason=reason,
        activity_id=None,
        move_focus=False,
    )
