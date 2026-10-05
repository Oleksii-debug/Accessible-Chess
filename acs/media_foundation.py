from __future__ import annotations

"""Canonical media synchronization core for Accessible Chess.

This module combines the media-state/evidence patterns from Oleksii's Nika-Core
with Accessible Chess' existing canonical chesscore.Board. Media evidence can
propose a transition; only chesscore legality can accept it.

Reuse provenance:
Oleksii-debug/Nika-Core@6df8b80b7a248f1559a0ff96f74efa2d2c47ad14
- src/nika_core/media/contracts.py
- src/nika_core/media/transcription.py
"""

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .chesscore import Board


class MediaContractError(ValueError):
    pass


class MediaSourceKind(str, Enum):
    LOCAL_FILE = "local_file"
    REMOTE_MEDIA = "remote_media"
    STRUCTURED_BROADCAST = "structured_broadcast"


class PlaybackState(str, Enum):
    UNSTARTED = "unstarted"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ENDED = "ended"


class EvidenceKind(str, Enum):
    STRUCTURED_MOVE = "structured_move"
    BOARD_POSITION = "board_position"
    SPEECH_CONTEXT = "speech_context"
    KNOWN_GAME_CANDIDATE = "known_game_candidate"
    USER_CORRECTION = "user_correction"


class ReconciliationState(str, Enum):
    VERIFIED = "verified"
    INFERRED = "inferred"
    OBSERVED = "observed"
    AMBIGUOUS = "ambiguous"
    RESYNC_REQUIRED = "resync_required"
    NO_CHANGE = "no_change"


def _text(value: object, name: str, *, max_length: int = 4096) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise MediaContractError(f"{name} must be non-empty trimmed text")
    if len(value) > max_length:
        raise MediaContractError(f"{name} exceeds maximum length")
    if any(ord(ch) < 32 for ch in value):
        raise MediaContractError(f"{name} contains control characters")
    return value


def _non_negative(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise MediaContractError(f"{name} must be a non-negative integer")
    return value


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MediaContractError("confidence must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")) or not 0.0 <= result <= 1.0:
        raise MediaContractError("confidence must be finite and between 0 and 1")
    return result


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "segment_id", _text(self.segment_id, "segment_id", max_length=200))
        start = _non_negative(self.start_ms, "start_ms")
        end = _non_negative(self.end_ms, "end_ms")
        if end < start:
            raise MediaContractError("segment end_ms must be >= start_ms")
        if type(self.text) is not str:
            raise MediaContractError("segment text must be text")
        if self.confidence is not None:
            object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True, slots=True)
class MediaEvidence:
    evidence_id: str
    kind: EvidenceKind
    source_id: str
    start_ms: int
    end_ms: int
    payload: Mapping[str, object] = field(default_factory=dict)
    confidence: float = 1.0
    authoritative: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _text(self.evidence_id, "evidence_id", max_length=200))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id", max_length=200))
        if not isinstance(self.kind, EvidenceKind):
            try:
                object.__setattr__(self, "kind", EvidenceKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise MediaContractError("unsupported evidence kind") from exc
        if _non_negative(self.end_ms, "end_ms") < _non_negative(self.start_ms, "start_ms"):
            raise MediaContractError("evidence end_ms must be >= start_ms")
        if not isinstance(self.payload, Mapping):
            raise MediaContractError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if type(self.authoritative) is not bool:
            raise MediaContractError("authoritative must be boolean")


@dataclass(frozen=True, slots=True)
class MediaSessionState:
    session_id: str
    source_id: str
    source_kind: MediaSourceKind
    position_ms: int = 0
    duration_ms: int | None = None
    playback_state: PlaybackState = PlaybackState.UNSTARTED
    playback_rate: float = 1.0
    revision: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _text(self.session_id, "session_id", max_length=200))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id", max_length=200))
        if not isinstance(self.source_kind, MediaSourceKind):
            object.__setattr__(self, "source_kind", MediaSourceKind(self.source_kind))
        position = _non_negative(self.position_ms, "position_ms")
        if self.duration_ms is not None:
            duration = _non_negative(self.duration_ms, "duration_ms")
            if position > duration:
                raise MediaContractError("position_ms exceeds duration_ms")
        if not isinstance(self.playback_state, PlaybackState):
            object.__setattr__(self, "playback_state", PlaybackState(self.playback_state))
        if isinstance(self.playback_rate, bool) or not isinstance(self.playback_rate, (int, float)):
            raise MediaContractError("playback_rate must be numeric")
        rate = float(self.playback_rate)
        if not 0.1 <= rate <= 8.0:
            raise MediaContractError("playback_rate must be between 0.1 and 8.0")
        object.__setattr__(self, "playback_rate", rate)
        _non_negative(self.revision, "revision")


class MediaClock:
    """Provider-published deterministic playback clock; no wall-time guessing."""

    def __init__(self, initial: MediaSessionState) -> None:
        if type(initial) is not MediaSessionState:
            raise TypeError("initial must be MediaSessionState")
        self._state = initial

    @property
    def state(self) -> MediaSessionState:
        return self._state

    def publish_position(self, position_ms: int) -> MediaSessionState:
        position = _non_negative(position_ms, "position_ms")
        if self._state.duration_ms is not None and position > self._state.duration_ms:
            raise MediaContractError("position_ms exceeds duration_ms")
        if position == self._state.position_ms:
            return self._state
        self._state = replace(self._state, position_ms=position, revision=self._state.revision + 1)
        return self._state

    def seek(self, position_ms: int) -> MediaSessionState:
        return self.publish_position(position_ms)

    def set_state(self, state: PlaybackState | str) -> MediaSessionState:
        wanted = state if isinstance(state, PlaybackState) else PlaybackState(state)
        if wanted is self._state.playback_state:
            return self._state
        self._state = replace(self._state, playback_state=wanted, revision=self._state.revision + 1)
        return self._state

    def set_rate(self, playback_rate: float) -> MediaSessionState:
        candidate = replace(self._state, playback_rate=playback_rate)
        if candidate.playback_rate == self._state.playback_rate:
            return self._state
        self._state = replace(candidate, revision=self._state.revision + 1)
        return self._state


@dataclass(frozen=True, slots=True)
class MediaPositionBinding:
    start_ms: int
    end_ms: int | None
    fen: str
    tree_path: tuple[int, ...] = ()
    state: ReconciliationState = ReconciliationState.VERIFIED
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        start = _non_negative(self.start_ms, "start_ms")
        if self.end_ms is not None and _non_negative(self.end_ms, "end_ms") <= start:
            raise MediaContractError("end_ms must be greater than start_ms")
        try:
            object.__setattr__(self, "fen", Board(self.fen).fen())
        except Exception as exc:
            raise MediaContractError("timeline FEN is invalid") from exc
        if type(self.tree_path) is not tuple or any(type(i) is not int or i < 0 for i in self.tree_path):
            raise MediaContractError("tree_path must contain non-negative integer indexes")
        if not isinstance(self.state, ReconciliationState):
            object.__setattr__(self, "state", ReconciliationState(self.state))
        if type(self.evidence_ids) is not tuple:
            raise MediaContractError("evidence_ids must be a tuple")


class MediaPositionTimeline:
    """Append-ordered timestamp to canonical FEN/GameTree mapping."""

    def __init__(self, bindings: tuple[MediaPositionBinding, ...] = ()) -> None:
        self._bindings: list[MediaPositionBinding] = []
        for binding in bindings:
            self.append(binding)

    @property
    def bindings(self) -> tuple[MediaPositionBinding, ...]:
        return tuple(self._bindings)

    def append(self, binding: MediaPositionBinding) -> None:
        if type(binding) is not MediaPositionBinding:
            raise TypeError("binding must be MediaPositionBinding")
        if self._bindings:
            previous = self._bindings[-1]
            if binding.start_ms < previous.start_ms:
                raise MediaContractError("timeline must be append-ordered")
            if previous.end_ms is not None and binding.start_ms < previous.end_ms:
                raise MediaContractError("timeline bindings must not overlap")
        self._bindings.append(binding)

    def at(self, timestamp_ms: int) -> MediaPositionBinding | None:
        timestamp = _non_negative(timestamp_ms, "timestamp_ms")
        for binding in reversed(self._bindings):
            if binding.start_ms <= timestamp and (binding.end_ms is None or timestamp < binding.end_ms):
                return binding
        return None

    def previous_before(self, timestamp_ms: int) -> MediaPositionBinding | None:
        timestamp = _non_negative(timestamp_ms, "timestamp_ms")
        for binding in reversed(self._bindings):
            if binding.start_ms < timestamp:
                return binding
        return None

    def next_after(self, timestamp_ms: int) -> MediaPositionBinding | None:
        timestamp = _non_negative(timestamp_ms, "timestamp_ms")
        for binding in self._bindings:
            if binding.start_ms > timestamp:
                return binding
        return None

    def restore_fen(self, timestamp_ms: int) -> str:
        binding = self.at(timestamp_ms)
        if binding is None:
            raise MediaContractError("no qualified media position exists at this timestamp")
        return binding.fen

    def to_payload(self) -> dict[str, object]:
        return {
            "version": 1,
            "bindings": [
                {
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "fen": item.fen,
                    "tree_path": list(item.tree_path),
                    "state": item.state.value,
                    "evidence_ids": list(item.evidence_ids),
                }
                for item in self._bindings
            ],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "MediaPositionTimeline":
        if not isinstance(payload, Mapping) or set(payload) != {"version", "bindings"}:
            raise MediaContractError("timeline payload fields are invalid")
        if payload["version"] != 1:
            raise MediaContractError("timeline payload version is unsupported")
        raw_bindings = payload["bindings"]
        if type(raw_bindings) is not list:
            raise MediaContractError("timeline bindings payload must be a list")
        bindings: list[MediaPositionBinding] = []
        for raw in raw_bindings:
            if type(raw) is not dict or set(raw) != {
                "start_ms",
                "end_ms",
                "fen",
                "tree_path",
                "state",
                "evidence_ids",
            }:
                raise MediaContractError("timeline binding payload fields are invalid")
            tree_path = raw["tree_path"]
            evidence_ids = raw["evidence_ids"]
            if type(tree_path) is not list or any(type(item) is not int for item in tree_path):
                raise MediaContractError("timeline tree_path payload is invalid")
            if type(evidence_ids) is not list or any(type(item) is not str for item in evidence_ids):
                raise MediaContractError("timeline evidence_ids payload is invalid")
            bindings.append(
                MediaPositionBinding(
                    start_ms=raw["start_ms"],
                    end_ms=raw["end_ms"],
                    fen=raw["fen"],
                    tree_path=tuple(tree_path),
                    state=ReconciliationState(raw["state"]),
                    evidence_ids=tuple(evidence_ids),
                )
            )
        return cls(tuple(bindings))


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    state: ReconciliationState
    resulting_fen: str | None
    move_san: str | None = None
    candidate_san: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, ReconciliationState):
            raise TypeError("state must be ReconciliationState")
        if self.resulting_fen is not None:
            object.__setattr__(self, "resulting_fen", Board(self.resulting_fen).fen())
        object.__setattr__(self, "confidence", _confidence(self.confidence))


class ChessStateReconciler:
    """Validate media candidates against canonical legal transitions."""

    def __init__(self, *, inference_threshold: float = 0.75) -> None:
        self.inference_threshold = _confidence(inference_threshold)

    def reconcile_structured_move(
        self,
        current_fen: str,
        move_text: str,
        *,
        authoritative: bool = True,
        confidence: float = 1.0,
    ) -> ReconciliationResult:
        board = Board(current_fen)
        conf = _confidence(confidence)
        if type(move_text) is not str or not move_text.strip():
            raise MediaContractError("move_text must be non-empty text")
        try:
            move = board.parse_move(move_text.strip())
            san = board.san(move)
            board.push(move)
        except Exception as exc:
            return ReconciliationResult(
                ReconciliationState.RESYNC_REQUIRED,
                None,
                confidence=conf,
                reason=f"structured move is illegal: {type(exc).__name__}",
            )
        return ReconciliationResult(
            ReconciliationState.VERIFIED if authoritative else ReconciliationState.INFERRED,
            board.fen(),
            move_san=san,
            candidate_san=(san,),
            confidence=conf,
            reason="structured move validated by canonical chess core",
        )

    def reconcile_board_placement(
        self,
        current_fen: str,
        observed_placement: str,
        *,
        confidence: float,
    ) -> ReconciliationResult:
        board = Board(current_fen)
        conf = _confidence(confidence)
        if type(observed_placement) is not str or not observed_placement.strip():
            raise MediaContractError("observed_placement must be non-empty text")
        placement = observed_placement.strip()
        try:
            Board(f"{placement} w - - 0 1")
        except Exception as exc:
            raise MediaContractError("observed board placement is invalid") from exc

        if placement == board.fen().split()[0]:
            return ReconciliationResult(
                ReconciliationState.NO_CHANGE,
                board.fen(),
                confidence=conf,
                reason="observed placement equals canonical placement",
            )

        candidates: list[tuple[str, str]] = []
        for move in board.legal_moves():
            probe = board.clone()
            san = board.san(move)
            probe.push(move)
            if probe.fen().split()[0] == placement:
                candidates.append((san, probe.fen()))

        if len(candidates) == 1:
            san, fen = candidates[0]
            if conf < self.inference_threshold:
                return ReconciliationResult(
                    ReconciliationState.OBSERVED,
                    None,
                    candidate_san=(san,),
                    confidence=conf,
                    reason="unique legal transition below inference threshold",
                )
            return ReconciliationResult(
                ReconciliationState.INFERRED,
                fen,
                move_san=san,
                candidate_san=(san,),
                confidence=conf,
                reason="one canonical legal move explains observed placement",
            )
        if len(candidates) > 1:
            return ReconciliationResult(
                ReconciliationState.AMBIGUOUS,
                None,
                candidate_san=tuple(san for san, _fen in candidates),
                confidence=conf,
                reason="multiple legal transitions explain observed placement",
            )
        return ReconciliationResult(
            ReconciliationState.RESYNC_REQUIRED if conf >= self.inference_threshold else ReconciliationState.OBSERVED,
            None,
            confidence=conf,
            reason="observed placement is not reachable by one legal move",
        )
