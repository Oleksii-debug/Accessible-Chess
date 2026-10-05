from __future__ import annotations

"""Provider-neutral media synchronization core.

This file implements the stable contracts approved in
MEDIA_INTELLIGENCE_AND_CHESS_AGENT_ARCHITECTURE.md. It is intentionally free of
YouTube/Lichess/vision/STT SDK dependencies.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class MediaPlaybackState(StrEnum):
    UNSTARTED = "unstarted"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ENDED = "ended"


class MediaEvidenceKind(StrEnum):
    STRUCTURED_MOVE = "structured_move"
    BOARD_PLACEMENT = "board_placement"
    STABLE_FRAME = "stable_frame"
    SPEECH_CONTEXT = "speech_context"
    KNOWN_GAME_CANDIDATE = "known_game_candidate"
    USER_CORRECTION = "user_correction"


class ReconciliationStatus(StrEnum):
    VERIFIED = "verified"
    INFERRED = "inferred"
    OBSERVED = "observed"
    AMBIGUOUS = "ambiguous"
    RESYNC_REQUIRED = "resync_required"
    NO_CHANGE = "no_change"


@dataclass(frozen=True, slots=True)
class MediaSession:
    session_id: str
    source_kind: str
    source_id: str
    state: MediaPlaybackState = MediaPlaybackState.UNSTARTED
    current_ms: int = 0
    playback_rate: float = 1.0
    revision: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("session_id", self.session_id),
            ("source_kind", self.source_kind),
            ("source_id", self.source_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must not be empty")
        if type(self.current_ms) is not int or self.current_ms < 0:
            raise ValueError("current_ms must be a non-negative integer")
        if isinstance(self.playback_rate, bool) or not isinstance(self.playback_rate, (int, float)):
            raise TypeError("playback_rate must be numeric")
        if self.playback_rate <= 0:
            raise ValueError("playback_rate must be positive")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("revision must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class MediaEvidence:
    evidence_id: str
    kind: MediaEvidenceKind
    start_ms: int
    end_ms: int
    source: str
    confidence: float
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, str) or not self.evidence_id.strip():
            raise ValueError("evidence_id must not be empty")
        if not isinstance(self.kind, MediaEvidenceKind):
            raise TypeError("kind must be MediaEvidenceKind")
        if type(self.start_ms) is not int or type(self.end_ms) is not int:
            raise TypeError("evidence timestamps must be integers")
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError("evidence timestamps are invalid")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must not be empty")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError("confidence must be numeric")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: ReconciliationStatus
    position_id: str | None = None
    move_id: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReconciliationStatus):
            raise TypeError("status must be ReconciliationStatus")
        if self.status in {ReconciliationStatus.VERIFIED, ReconciliationStatus.INFERRED}:
            if not isinstance(self.position_id, str) or not self.position_id.strip():
                raise ValueError("accepted reconciliation requires position_id")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must not be empty")


class ChessStateReconciler:
    """Reconcile noisy media candidates against canonical legal transitions.

    The caller provides canonical legal transition identities:
        move_id -> resulting_position_id

    This keeps the media layer independent from the concrete chess-core API while
    still making canonical legality the only acceptance authority.
    """

    def reconcile(
        self,
        *,
        current_position_id: str,
        legal_transitions: Mapping[str, str],
        observed_position_id: str | None = None,
        structured_move_id: str | None = None,
        observed_confidence: float = 0.0,
    ) -> ReconciliationResult:
        if not isinstance(current_position_id, str) or not current_position_id.strip():
            raise ValueError("current_position_id must not be empty")
        if not isinstance(legal_transitions, Mapping):
            raise TypeError("legal_transitions must be a mapping")
        canonical: dict[str, str] = {}
        for move_id, position_id in legal_transitions.items():
            if not isinstance(move_id, str) or not move_id.strip():
                raise ValueError("legal move identity must not be empty")
            if not isinstance(position_id, str) or not position_id.strip():
                raise ValueError("legal position identity must not be empty")
            canonical[move_id] = position_id
        if isinstance(observed_confidence, bool) or not isinstance(
            observed_confidence, (int, float)
        ):
            raise TypeError("observed_confidence must be numeric")
        if not 0.0 <= float(observed_confidence) <= 1.0:
            raise ValueError("observed_confidence must be between 0 and 1")

        if observed_position_id == current_position_id and structured_move_id is None:
            return ReconciliationResult(
                ReconciliationStatus.NO_CHANGE,
                position_id=current_position_id,
                reason="observed position matches current canonical position",
            )

        if structured_move_id is not None:
            target = canonical.get(structured_move_id)
            if target is None:
                return ReconciliationResult(
                    ReconciliationStatus.RESYNC_REQUIRED,
                    reason="structured move is not legal from current canonical position",
                )
            if observed_position_id is not None and observed_position_id != target:
                return ReconciliationResult(
                    ReconciliationStatus.AMBIGUOUS,
                    reason="structured move and observed board candidate disagree",
                )
            return ReconciliationResult(
                ReconciliationStatus.VERIFIED,
                position_id=target,
                move_id=structured_move_id,
                reason="structured move matches canonical legal transition",
            )

        if observed_position_id is None:
            return ReconciliationResult(
                ReconciliationStatus.OBSERVED,
                reason="no candidate position is available for canonical reconciliation",
            )

        candidates = [
            (move_id, position_id)
            for move_id, position_id in canonical.items()
            if position_id == observed_position_id
        ]
        if not candidates:
            return ReconciliationResult(
                ReconciliationStatus.RESYNC_REQUIRED,
                reason="observed board cannot be reached by one canonical legal transition",
            )
        if len(candidates) > 1:
            return ReconciliationResult(
                ReconciliationStatus.AMBIGUOUS,
                reason="multiple canonical legal transitions match observed board",
            )
        if observed_confidence < 0.85:
            return ReconciliationResult(
                ReconciliationStatus.OBSERVED,
                reason="board candidate is legal but confidence is below acceptance threshold",
            )
        move_id, position_id = candidates[0]
        return ReconciliationResult(
            ReconciliationStatus.INFERRED,
            position_id=position_id,
            move_id=move_id,
            reason="unique canonical legal transition explains stable board candidate",
        )


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    start_ms: int
    end_ms: int | None
    segment_id: str
    gametree_node_id: str
    position_id: str
    qualification: ReconciliationStatus

    def __post_init__(self) -> None:
        if type(self.start_ms) is not int or self.start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        if self.end_ms is not None and (type(self.end_ms) is not int or self.end_ms <= self.start_ms):
            raise ValueError("end_ms must be greater than start_ms")
        for label, value in (
            ("segment_id", self.segment_id),
            ("gametree_node_id", self.gametree_node_id),
            ("position_id", self.position_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must not be empty")
        if self.qualification not in {
            ReconciliationStatus.VERIFIED,
            ReconciliationStatus.INFERRED,
        }:
            raise ValueError("timeline entries require accepted reconciliation")


class MediaPositionTimeline:
    def __init__(self, entries: tuple[TimelineEntry, ...] = ()) -> None:
        ordered = tuple(sorted(entries, key=lambda item: item.start_ms))
        previous: TimelineEntry | None = None
        for entry in ordered:
            if previous is not None:
                if previous.end_ms is None or entry.start_ms < previous.end_ms:
                    raise ValueError("timeline entries must not overlap")
            previous = entry
        self._entries = ordered
        self._starts = tuple(item.start_ms for item in ordered)

    @property
    def entries(self) -> tuple[TimelineEntry, ...]:
        return self._entries

    def at(self, timestamp_ms: int) -> TimelineEntry | None:
        if type(timestamp_ms) is not int or timestamp_ms < 0:
            raise ValueError("timestamp_ms must be a non-negative integer")
        index = bisect_right(self._starts, timestamp_ms) - 1
        if index < 0:
            return None
        entry = self._entries[index]
        if entry.end_ms is not None and timestamp_ms >= entry.end_ms:
            return None
        return entry

    def previous(self, timestamp_ms: int) -> TimelineEntry | None:
        if type(timestamp_ms) is not int or timestamp_ms < 0:
            raise ValueError("timestamp_ms must be a non-negative integer")
        index = bisect_right(self._starts, timestamp_ms) - 1
        if index <= 0:
            return None
        return self._entries[index - 1]

    def next(self, timestamp_ms: int) -> TimelineEntry | None:
        if type(timestamp_ms) is not int or timestamp_ms < 0:
            raise ValueError("timestamp_ms must be a non-negative integer")
        index = bisect_right(self._starts, timestamp_ms)
        if index >= len(self._entries):
            return None
        return self._entries[index]


__all__ = [
    "ChessStateReconciler",
    "MediaEvidence",
    "MediaEvidenceKind",
    "MediaPlaybackState",
    "MediaPositionTimeline",
    "MediaSession",
    "ReconciliationResult",
    "ReconciliationStatus",
    "TimelineEntry",
]
