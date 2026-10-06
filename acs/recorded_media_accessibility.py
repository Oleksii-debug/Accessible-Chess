from __future__ import annotations

"""Accessible presentation contract for recorded chess media.

This module is deliberately presentation-only. It consumes already-qualified
Media Core / recorded-sync snapshots and exposes only safe primitive data to a
WebView. It never creates or interprets chess references, moves, PGN, FEN, UCI,
or GameTree state. Commands are intent-only: the existing application host owns
their execution.
"""

from dataclasses import dataclass
from .media_preprocess import PreprocessCheckpoint, PreprocessStatus
from .recorded_media_sync import (
    AccessibleRecordedSyncEvent,
    RecordedPlaybackResolution,
    RecordedSyncSnapshot,
)


_SUPPORTED_LANGUAGES = frozenset({"en", "uk"})
_QUALIFICATIONS = frozenset(
    {"confirmed", "candidate", "ambiguous", "unlinked", "unavailable"}
)
_FOCUS_TARGETS = frozenset(
    {
        "recorded-media-play-toggle",
        "recorded-media-seek",
        "recorded-media-restore",
        "recorded-media-cancel",
        "recorded-media-status",
    }
)
_ACTIONS = frozenset({"play", "pause", "seek", "restore", "cancel"})
_MAX_TEXT = 4096
_MAX_PROGRESS = 100_000_000


class RecordedMediaAccessibilityError(ValueError):
    """Fail-closed error at the recorded-media UI boundary."""


def _language(value: object) -> str:
    if type(value) is not str or len(value) > 16 or "\x00" in value:
        raise RecordedMediaAccessibilityError("unsupported recorded-media language")
    selected = value.strip().lower()
    if selected not in _SUPPORTED_LANGUAGES:
        raise RecordedMediaAccessibilityError("unsupported recorded-media language")
    return selected


def _text(value: object, name: str, *, limit: int = _MAX_TEXT) -> str:
    if type(value) is not str or not value or len(value) > limit:
        raise RecordedMediaAccessibilityError(f"invalid {name}")
    if "\x00" in value or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise RecordedMediaAccessibilityError(f"unsafe {name}")
    return value


def _nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RecordedMediaAccessibilityError(f"invalid {name}")
    return value


def _optional_nonnegative_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, name)


def _format_time(position_ms: int) -> str:
    value = _nonnegative_int(position_ms, "media position")
    total_seconds = value // 1000
    seconds = total_seconds % 60
    minutes = (total_seconds // 60) % 60
    hours = total_seconds // 3600
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


_LABELS = {
    "en": {
        "play": "Play recorded media",
        "pause": "Pause recorded media",
        "seek": "Recorded media position",
        "restore": "Restore synchronized chess position",
        "cancel": "Cancel media preprocessing",
        "heading": "Recorded chess media",
        "region": "Recorded chess media player",
        "back": "Back 10 seconds",
        "forward": "Forward 10 seconds",
        "status_unavailable": "Recorded media synchronization is unavailable.",
        "status_confirmed": "A confirmed chess position is synchronized with the current media time.",
        "status_candidate": "The current media position has an unconfirmed chess candidate. Chess restore is disabled.",
        "status_ambiguous": "The current media position is ambiguous. Chess restore is disabled.",
        "status_unlinked": "No confirmed chess position is synchronized with the current media time.",
        "preprocess_running": "Media preprocessing is running.",
        "preprocess_canceled": "Media preprocessing was canceled.",
        "preprocess_complete": "Media preprocessing is complete.",
        "preprocess_unavailable": "Media preprocessing status is unavailable.",
        "progress": "Preprocessing progress",
        "ready": "Recorded media is ready.",
    },
    "uk": {
        "play": "Відтворювати записане медіа",
        "pause": "Призупинити записане медіа",
        "seek": "Позиція записаного медіа",
        "restore": "Відновити синхронізовану шахову позицію",
        "cancel": "Скасувати попередню обробку медіа",
        "heading": "Записане шахове медіа",
        "region": "Програвач записаного шахового медіа",
        "back": "Назад на 10 секунд",
        "forward": "Вперед на 10 секунд",
        "status_unavailable": "Синхронізація записаного медіа недоступна.",
        "status_confirmed": "Підтверджена шахова позиція синхронізована з поточним часом медіа.",
        "status_candidate": "Для поточного часу медіа є непідтверджений шаховий кандидат. Відновлення шахів вимкнено.",
        "status_ambiguous": "Поточна позиція медіа неоднозначна. Відновлення шахової позиції вимкнено.",
        "status_unlinked": "Для поточного часу медіа немає підтвердженої шахової позиції.",
        "preprocess_running": "Попередня обробка медіа триває.",
        "preprocess_canceled": "Попередню обробку медіа скасовано.",
        "preprocess_complete": "Попередню обробку медіа завершено.",
        "preprocess_unavailable": "Стан попередньої обробки медіа недоступний.",
        "progress": "Прогрес попередньої обробки",
        "ready": "Записане медіа готове.",
    },
}


def _qualification(
    playback: RecordedPlaybackResolution | None,
    snapshot: RecordedSyncSnapshot | None,
    position_ms: int | None,
) -> str:
    resolution = playback.resolution if playback is not None else None
    if resolution is None and snapshot is not None and position_ms is not None:
        resolution = snapshot.timeline.resolve_at_or_before(position_ms)
    if resolution is None:
        return "unavailable"
    if resolution.ambiguous:
        return "ambiguous"
    if resolution.chess_ref is not None:
        return "confirmed"
    if resolution.anchor_timestamp_ms is None:
        return "unlinked"
    return "candidate"


def _sync_status(qualification: str, language: str) -> str:
    labels = _LABELS[language]
    return {
        "confirmed": labels["status_confirmed"],
        "candidate": labels["status_candidate"],
        "ambiguous": labels["status_ambiguous"],
        "unlinked": labels["status_unlinked"],
        "unavailable": labels["status_unavailable"],
    }[qualification]


def _event_text(event: AccessibleRecordedSyncEvent | None) -> str:
    if event is None:
        return ""
    if type(event) is not AccessibleRecordedSyncEvent:
        raise RecordedMediaAccessibilityError("invalid recorded-media event")
    visible = _text(event.visible_text, "visible event text")
    announcement = _text(event.announcement_text, "announcement event text")
    if visible != announcement:
        raise RecordedMediaAccessibilityError(
            "recorded-media event text is not announcement-equivalent"
        )
    return visible


_PLAYBACK_STATES = frozenset(
    {"unstarted", "playing", "paused", "buffering", "ended"}
)


def _validate_clock_values(
    *,
    position_ms: object,
    duration_ms: object,
    playback_state: object,
    revision: object,
) -> tuple[int | None, int | None, str, int | None]:
    position = _optional_nonnegative_int(position_ms, "media position")
    duration = _optional_nonnegative_int(duration_ms, "media duration")
    if duration is not None and position is not None and position > duration:
        raise RecordedMediaAccessibilityError("media position exceeds duration")
    if type(playback_state) is not str or playback_state not in _PLAYBACK_STATES:
        raise RecordedMediaAccessibilityError("invalid media playback state")
    safe_revision = None
    if revision is not None:
        safe_revision = _nonnegative_int(revision, "media clock revision")
    return position, duration, playback_state, safe_revision


def _validate_sync_snapshot(snapshot: RecordedSyncSnapshot | None) -> RecordedSyncSnapshot | None:
    if snapshot is None:
        return None
    if type(snapshot) is not RecordedSyncSnapshot:
        raise RecordedMediaAccessibilityError("invalid recorded synchronization snapshot")
    if snapshot.source.source_id != snapshot.timeline.source_id:
        raise RecordedMediaAccessibilityError("recorded synchronization source mismatch")
    if snapshot.session.media_cursor.source_id != snapshot.source.source_id:
        raise RecordedMediaAccessibilityError("recorded synchronization cursor mismatch")
    return snapshot


def _validate_progress(
    checkpoint: PreprocessCheckpoint | None,
) -> tuple[str, int, int, bool]:
    if checkpoint is None:
        return "unavailable", 0, 0, False
    if type(checkpoint) is not PreprocessCheckpoint:
        raise RecordedMediaAccessibilityError("invalid preprocess checkpoint")
    completed = _nonnegative_int(checkpoint.next_index, "preprocess completed")
    total = _nonnegative_int(checkpoint.total, "preprocess total")
    if total > _MAX_PROGRESS or completed > total:
        raise RecordedMediaAccessibilityError("invalid preprocess progress")
    if type(checkpoint.status) is not PreprocessStatus:
        raise RecordedMediaAccessibilityError("invalid preprocess status")
    return (
        checkpoint.status.value,
        completed,
        total,
        checkpoint.status is PreprocessStatus.RUNNING,
    )


@dataclass(frozen=True, slots=True)
class RecordedMediaPlayerCommand:
    """Intent-only command safe to pass from browser code to the host."""

    action: str
    position_ms: int | None = None

    def __post_init__(self) -> None:
        if type(self.action) is not str or self.action not in _ACTIONS:
            raise RecordedMediaAccessibilityError("unsupported recorded-media action")
        if self.action == "seek":
            if self.position_ms is None:
                raise RecordedMediaAccessibilityError("seek requires a position")
            position = _nonnegative_int(self.position_ms, "seek position")
            object.__setattr__(self, "position_ms", position)
        elif self.position_ms is not None:
            raise RecordedMediaAccessibilityError(
                "non-seek recorded-media commands cannot carry a position"
            )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"action": self.action}
        if self.action == "seek":
            payload["positionMs"] = self.position_ms
        return payload


@dataclass(frozen=True, slots=True)
class RecordedMediaPlayerState:
    """Browser-safe, selectable, copyable recorded-media player state."""

    ok: bool
    revision: int | None
    position_ms: int | None
    duration_ms: int | None
    position_text: str
    region_label: str
    heading: str
    seek_label: str
    back_label: str
    forward_label: str
    restore_label: str
    cancel_label: str
    progress_label: str
    playback_state: str
    qualification: str
    status_text: str
    restore_enabled: bool
    play_action: str
    play_label: str
    seek_enabled: bool
    cancel_enabled: bool
    preprocess_status: str
    preprocess_completed: int
    preprocess_total: int
    progress_text: str
    announcement: str
    focus_target: str

    def __post_init__(self) -> None:
        if type(self.ok) is not bool:
            raise RecordedMediaAccessibilityError("invalid player ok flag")
        if self.revision is not None:
            _nonnegative_int(self.revision, "player revision")
        _optional_nonnegative_int(self.position_ms, "player position")
        _optional_nonnegative_int(self.duration_ms, "player duration")
        _text(self.position_text, "position text", limit=64)
        for name, value in ((
            "region label", self.region_label),
            ("heading", self.heading),
            ("seek label", self.seek_label),
            ("back label", self.back_label),
            ("forward label", self.forward_label),
            ("restore label", self.restore_label),
            ("cancel label", self.cancel_label),
            ("progress label", self.progress_label),
        ):
            _text(value, name, limit=256)
        _text(self.status_text, "status text")
        _text(self.announcement, "announcement text")
        if self.playback_state not in _PLAYBACK_STATES:
            raise RecordedMediaAccessibilityError("invalid playback state")
        if self.qualification not in _QUALIFICATIONS:
            raise RecordedMediaAccessibilityError("invalid synchronization qualification")
        if type(self.restore_enabled) is not bool:
            raise RecordedMediaAccessibilityError("invalid restore flag")
        if self.play_action not in {"play", "pause"}:
            raise RecordedMediaAccessibilityError("invalid play action")
        _text(self.play_label, "play label", limit=256)
        if type(self.seek_enabled) is not bool or type(self.cancel_enabled) is not bool:
            raise RecordedMediaAccessibilityError("invalid player action flags")
        if self.preprocess_status not in {
            "running",
            "canceled",
            "complete",
            "unavailable",
        }:
            raise RecordedMediaAccessibilityError("invalid preprocess status")
        _nonnegative_int(self.preprocess_completed, "preprocess completed")
        _nonnegative_int(self.preprocess_total, "preprocess total")
        if self.preprocess_completed > self.preprocess_total:
            raise RecordedMediaAccessibilityError("preprocess progress exceeds total")
        _text(self.progress_text, "progress text", limit=256)
        if self.focus_target not in _FOCUS_TARGETS:
            raise RecordedMediaAccessibilityError("invalid player focus target")
        if self.duration_ms is not None and self.position_ms is not None:
            if self.position_ms > self.duration_ms:
                raise RecordedMediaAccessibilityError("player position exceeds duration")
        if self.restore_enabled and self.qualification != "confirmed":
            raise RecordedMediaAccessibilityError(
                "restore cannot be enabled without a confirmed position"
            )

    def to_dict(self) -> dict[str, object]:
        """Return only primitive browser data; opaque domain identities never cross."""
        return {
            "ok": self.ok,
            "revision": self.revision,
            "positionMs": self.position_ms,
            "durationMs": self.duration_ms,
            "positionText": self.position_text,
            "regionLabel": self.region_label,
            "heading": self.heading,
            "seekLabel": self.seek_label,
            "backLabel": self.back_label,
            "forwardLabel": self.forward_label,
            "restoreLabel": self.restore_label,
            "cancelLabel": self.cancel_label,
            "progressLabel": self.progress_label,
            "playbackState": self.playback_state,
            "qualification": self.qualification,
            "statusText": self.status_text,
            "restoreEnabled": self.restore_enabled,
            "playAction": self.play_action,
            "playLabel": self.play_label,
            "seekEnabled": self.seek_enabled,
            "cancelEnabled": self.cancel_enabled,
            "preprocessStatus": self.preprocess_status,
            "preprocessCompleted": self.preprocess_completed,
            "preprocessTotal": self.preprocess_total,
            "progressText": self.progress_text,
            "announcement": self.announcement,
            "focusTarget": self.focus_target,
        }


class RecordedMediaAccessibilityBridge:
    """Presentation adapter over existing recorded-media contracts."""

    def __init__(self, *, language: str = "uk") -> None:
        self._language = _language(language)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        self._language = _language(language)

    def snapshot(
        self,
        *,
        position_ms: int | None = None,
        duration_ms: int | None = None,
        playback_state: str = "unstarted",
        revision: int | None = None,
        playback: RecordedPlaybackResolution | None = None,
        sync_snapshot: RecordedSyncSnapshot | None = None,
        preprocess: PreprocessCheckpoint | None = None,
        event: AccessibleRecordedSyncEvent | None = None,
    ) -> dict[str, object]:
        try:
            position, duration, playback_state, safe_revision = _validate_clock_values(
                position_ms=position_ms,
                duration_ms=duration_ms,
                playback_state=playback_state,
                revision=revision,
            )
            if playback is not None and type(playback) is not RecordedPlaybackResolution:
                raise RecordedMediaAccessibilityError(
                    "invalid recorded playback resolution"
                )
            safe_sync = _validate_sync_snapshot(sync_snapshot)
            if playback is not None:
                playback_position = _nonnegative_int(
                    playback.session.media_cursor.position_ms,
                    "recorded playback position",
                )
                if position is None or playback_position != position:
                    raise RecordedMediaAccessibilityError(
                        "recorded playback position disagrees with the current media clock"
                    )
            if playback is not None and safe_sync is not None:
                if playback.session.media_cursor.source_id != safe_sync.source.source_id:
                    raise RecordedMediaAccessibilityError(
                        "recorded playback and synchronization snapshots use different sources"
                    )
            qualification = _qualification(playback, safe_sync, position)
            preprocess_status, completed, total, cancel_enabled = _validate_progress(
                preprocess
            )
            if preprocess is not None and safe_sync is not None:
                if (
                    preprocess.source_id != safe_sync.source.source_id
                    or preprocess.source_revision != safe_sync.source_revision
                ):
                    raise RecordedMediaAccessibilityError(
                        "preprocess checkpoint belongs to a different recorded source revision"
                    )
            labels = _LABELS[self._language]
            restored_event = _event_text(event)
            if playback is not None:
                event_text = _event_text(playback.event)
                if restored_event and restored_event != event_text:
                    raise RecordedMediaAccessibilityError(
                        "playback/event mismatch"
                    )
                restored_event = event_text
            if qualification == "confirmed" and playback is not None:
                focus_target = "recorded-media-restore"
            elif preprocess_status == "running":
                focus_target = "recorded-media-cancel"
            elif position is not None:
                focus_target = "recorded-media-seek"
            else:
                focus_target = "recorded-media-status"

            if playback_state == "playing":
                play_action = "pause"
                play_label = labels["pause"]
            else:
                play_action = "play"
                play_label = labels["play"]

            progress_text = {
                "running": f"{labels['progress']}: {completed} of {total}.",
                "canceled": f"{labels['preprocess_canceled']} {labels['progress']}: {completed} of {total}.",
                "complete": f"{labels['preprocess_complete']} {labels['progress']}: {completed} of {total}.",
                "unavailable": labels["preprocess_unavailable"],
            }[preprocess_status]

            if position is None:
                position_text = "—"
            else:
                position_text = _format_time(position)

            status_text = _sync_status(qualification, self._language)
            if position is not None:
                status_text = f"{status_text} {position_text}."
            if restored_event:
                announcement = restored_event
            else:
                announcement = labels["ready"] if position is not None else status_text

            state = RecordedMediaPlayerState(
                ok=qualification != "unavailable" or position is not None,
                revision=safe_revision,
                position_ms=position,
                duration_ms=duration,
                position_text=position_text,
                region_label=labels["region"],
                heading=labels["heading"],
                seek_label=labels["seek"],
                back_label=labels["back"],
                forward_label=labels["forward"],
                restore_label=labels["restore"],
                cancel_label=labels["cancel"],
                progress_label=labels["progress"],
                playback_state=playback_state,
                qualification=qualification,
                status_text=status_text,
                restore_enabled=qualification == "confirmed",
                play_action=play_action,
                play_label=play_label,
                seek_enabled=position is not None and duration is not None and duration > 0,
                cancel_enabled=cancel_enabled,
                preprocess_status=preprocess_status,
                preprocess_completed=completed,
                preprocess_total=total,
                progress_text=progress_text,
                announcement=announcement,
                focus_target=focus_target,
            )
            return state.to_dict()
        except RecordedMediaAccessibilityError:
            raise
        except Exception:
            raise RecordedMediaAccessibilityError(
                "recorded-media presentation state could not be read safely"
            ) from None

    def error_state(self, *, position_ms: int | None = None) -> dict[str, object]:
        position = None if position_ms is None else _nonnegative_int(position_ms, "position")
        labels = _LABELS[self._language]
        state = RecordedMediaPlayerState(
            ok=False,
            revision=None,
            position_ms=position,
            duration_ms=None,
            position_text="—" if position is None else _format_time(position),
            region_label=labels["region"],
            heading=labels["heading"],
            seek_label=labels["seek"],
            back_label=labels["back"],
            forward_label=labels["forward"],
            restore_label=labels["restore"],
            cancel_label=labels["cancel"],
            progress_label=labels["progress"],
            playback_state="unstarted",
            qualification="unavailable",
            status_text=labels["status_unavailable"],
            restore_enabled=False,
            play_action="play",
            play_label=labels["play"],
            seek_enabled=False,
            cancel_enabled=False,
            preprocess_status="unavailable",
            preprocess_completed=0,
            preprocess_total=0,
            progress_text=labels["preprocess_unavailable"],
            announcement=labels["status_unavailable"],
            focus_target="recorded-media-status",
        )
        return state.to_dict()

    @staticmethod
    def command(
        action: str,
        *,
        position_ms: int | None = None,
    ) -> dict[str, object]:
        return RecordedMediaPlayerCommand(action, position_ms).to_dict()


__all__ = [
    "RecordedMediaAccessibilityBridge",
    "RecordedMediaAccessibilityError",
    "RecordedMediaPlayerCommand",
    "RecordedMediaPlayerState",
]
