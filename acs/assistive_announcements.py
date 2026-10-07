from __future__ import annotations

"""Bounded assistive-technology announcement policy for Agent/Media status.

Adapted from first-party donor:
Oleksii-debug/Autosport@main
src/autosport/accessibility_announcements.py
blob 21621bca6fbe29d0999b3a1286bf2f164f414808

This module classifies and deduplicates announcements only. It never moves
focus and does not claim that NVDA actually spoke a notification.
"""

from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256


class AnnouncementPriority(StrEnum):
    SILENT = "SILENT"
    POLITE = "POLITE"
    ASSERTIVE = "ASSERTIVE"


class ChessAnnouncementKind(StrEnum):
    MEDIA_PROGRESS = "MEDIA_PROGRESS"
    AGENT_PROGRESS = "AGENT_PROGRESS"
    MEDIA_POSITION_CHANGED = "MEDIA_POSITION_CHANGED"
    AGENT_OPERATION_COMPLETED = "AGENT_OPERATION_COMPLETED"
    STOP_REQUESTED = "STOP_REQUESTED"
    STOP_COMPLETED = "STOP_COMPLETED"
    MEDIA_AMBIGUOUS = "MEDIA_AMBIGUOUS"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CRITICAL_ERROR = "CRITICAL_ERROR"


_PRIORITY = {
    ChessAnnouncementKind.MEDIA_PROGRESS: AnnouncementPriority.SILENT,
    ChessAnnouncementKind.AGENT_PROGRESS: AnnouncementPriority.SILENT,
    ChessAnnouncementKind.MEDIA_POSITION_CHANGED: AnnouncementPriority.POLITE,
    ChessAnnouncementKind.AGENT_OPERATION_COMPLETED: AnnouncementPriority.POLITE,
    ChessAnnouncementKind.STOP_REQUESTED: AnnouncementPriority.POLITE,
    ChessAnnouncementKind.STOP_COMPLETED: AnnouncementPriority.POLITE,
    ChessAnnouncementKind.MEDIA_AMBIGUOUS: AnnouncementPriority.ASSERTIVE,
    ChessAnnouncementKind.RECOVERY_REQUIRED: AnnouncementPriority.ASSERTIVE,
    ChessAnnouncementKind.CRITICAL_ERROR: AnnouncementPriority.ASSERTIVE,
}
if set(_PRIORITY) != set(ChessAnnouncementKind):
    raise RuntimeError("every announcement kind must have exactly one priority")


@dataclass(frozen=True, slots=True)
class ChessAnnouncementEvent:
    kind: ChessAnnouncementKind
    text: str
    state_token: str
    episode_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ChessAnnouncementKind):
            raise TypeError("kind must be ChessAnnouncementKind")
        for label, value in (("text", self.text), ("state_token", self.state_token)):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{label} must be non-empty trimmed text")
        if _PRIORITY[self.kind] is AnnouncementPriority.ASSERTIVE:
            if not isinstance(self.episode_id, str) or not self.episode_id.strip():
                raise ValueError("assertive events require episode_id")
        elif self.episode_id is not None:
            raise ValueError("episode_id is valid only for assertive events")


@dataclass(frozen=True, slots=True)
class ChessAnnouncementDecision:
    emit: bool
    priority: AnnouncementPriority
    text: str | None
    reason: str
    activity_id: str | None = None
    move_focus: bool = False

    def __post_init__(self) -> None:
        if type(self.emit) is not bool or type(self.move_focus) is not bool:
            raise TypeError("emit and move_focus must be boolean")
        if self.move_focus:
            raise ValueError("announcement policy must never request focus movement")
        if not isinstance(self.priority, AnnouncementPriority):
            raise TypeError("priority must be AnnouncementPriority")
        if self.emit:
            if self.priority is AnnouncementPriority.SILENT:
                raise ValueError("emitted announcement cannot be SILENT")
            if not isinstance(self.text, str) or not self.text.strip():
                raise ValueError("emitted announcement requires text")
            if not isinstance(self.activity_id, str) or not self.activity_id:
                raise ValueError("emitted announcement requires activity_id")
        else:
            if self.priority is not AnnouncementPriority.SILENT:
                raise ValueError("suppressed announcement must be SILENT")
            if self.text is not None or self.activity_id is not None:
                raise ValueError("suppressed announcement must carry no text/activity_id")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must not be empty")


class ChessAnnouncementGate:
    def __init__(self, *, max_history: int = 128) -> None:
        if type(max_history) is not int or max_history <= 0:
            raise ValueError("max_history must be a positive integer")
        self._max_history = max_history
        self._history: OrderedDict[tuple[str, str], None] = OrderedDict()

    @property
    def history_size(self) -> int:
        return len(self._history)

    def decide(self, event: ChessAnnouncementEvent) -> ChessAnnouncementDecision:
        if type(event) is not ChessAnnouncementEvent:
            raise TypeError("event must be ChessAnnouncementEvent")
        priority = _PRIORITY[event.kind]
        if priority is AnnouncementPriority.SILENT:
            return ChessAnnouncementDecision(
                False, AnnouncementPriority.SILENT, None, "HIGH_FREQUENCY_CHURN"
            )

        if priority is AnnouncementPriority.ASSERTIVE:
            assert event.episode_id is not None
            key = ("ASSERTIVE", event.episode_id)
            duplicate_reason = "DUPLICATE_CRITICAL_EPISODE"
        else:
            key = ("POLITE", event.state_token)
            duplicate_reason = "DUPLICATE_STATE_TRANSITION"

        if key in self._history:
            self._history.move_to_end(key)
            return ChessAnnouncementDecision(
                False, AnnouncementPriority.SILENT, None, duplicate_reason
            )

        self._history[key] = None
        while len(self._history) > self._max_history:
            self._history.popitem(last=False)

        raw = (key[0] + "\0" + key[1]).encode("utf-8")
        activity = (
            "accessible-chess:announcement:v1:"
            + key[0].lower()
            + ":sha256:"
            + sha256(raw).hexdigest()
        )
        return ChessAnnouncementDecision(
            True,
            priority,
            event.text,
            "EMIT",
            activity_id=activity,
            move_focus=False,
        )


__all__ = [
    "AnnouncementPriority",
    "ChessAnnouncementDecision",
    "ChessAnnouncementEvent",
    "ChessAnnouncementGate",
    "ChessAnnouncementKind",
]
