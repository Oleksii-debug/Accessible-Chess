from __future__ import annotations

"""Presentation-neutral media/chess synchronization primitives.

This module deliberately does *not* understand chess moves, FEN, SAN, UCI, or
legality. ``chess_ref`` values are opaque references owned by the canonical
GameTree/application layer. Media recognition may propose links to those
references, but only the canonical chess services may create/validate the
underlying chess state.

The model keeps the media cursor and chess cursor independent. Synchronization
is an explicit operation and never silently resolves ambiguous recognition.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from enum import Enum
import json
import math
from typing import Any, Iterable, Protocol


MEDIA_STATE_SCHEMA = "accessible-chess.media-state"
MEDIA_STATE_VERSION = 1
MEDIA_SESSION_SCHEMA = "accessible-chess.media-session"
MEDIA_SESSION_VERSION = 1
MAX_MEDIA_LINKS = 100_000
MAX_MEDIA_STATE_BYTES = 8 * 1024 * 1024
MAX_MEDIA_EVIDENCE_FIELDS = 64
MAX_MEDIA_RECONCILIATION_REFS = 64
MAX_MEDIA_CONTRACT_TEXT = 16 * 1024


class MediaErrorCode(str, Enum):
    INVALID_TEXT = "invalid_text"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_DURATION = "invalid_duration"
    INVALID_CONFIDENCE = "invalid_confidence"
    INVALID_PLAYBACK_RATE = "invalid_playback_rate"
    RECONCILIATION_FAILED = "reconciliation_failed"
    SOURCE_MISMATCH = "source_mismatch"
    DUPLICATE_LINK = "duplicate_link"
    LINK_LIMIT = "link_limit"
    LINK_NOT_FOUND = "link_not_found"
    CONFIRMATION_CONFLICT = "confirmation_conflict"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_CONTAINER = "invalid_container"
    STATE_TOO_LARGE = "state_too_large"
    SOURCE_NOT_FOUND = "source_not_found"


class MediaContractError(ValueError):
    """Stable validation error for reusable media-domain data."""

    def __init__(self, message: str, *, code: MediaErrorCode) -> None:
        super().__init__(message)
        self.code = MediaErrorCode(code)


class MediaSourceKind(str, Enum):
    LOCAL_FILE = "local_file"
    PROVIDER = "provider"
    REMOTE_URL = "remote_url"


class MediaLinkStatus(str, Enum):
    """Recognition/reconciliation state for one source-to-chess link."""

    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"


class MediaPlaybackState(str, Enum):
    """Provider-neutral playback state owned by the media clock."""

    UNSTARTED = "unstarted"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ENDED = "ended"



class MediaEvidenceKind(str, Enum):
    """Provider-neutral evidence categories; evidence is never chess truth."""

    STRUCTURED_CHESS = "structured_chess"
    BOARD_OBSERVATION = "board_observation"
    SPEECH_CONTEXT = "speech_context"
    KNOWN_GAME_CANDIDATE = "known_game_candidate"
    USER_CORRECTION = "user_correction"


class MediaReconciliationState(str, Enum):
    """Qualification returned by the canonical chess application boundary."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    VERIFIED = "verified"
    AMBIGUOUS = "ambiguous"
    RESYNC_REQUIRED = "resync_required"
    NO_CHANGE = "no_change"


@dataclass(frozen=True, slots=True)
class MediaEvidenceField:
    """One bounded immutable evidence datum with opaque text semantics."""

    name: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            _require_bounded_text(self.name, "evidence field name", max_chars=256),
        )
        object.__setattr__(
            self,
            "value",
            _require_bounded_text(
                self.value,
                "evidence field value",
                max_chars=MAX_MEDIA_CONTRACT_TEXT,
            ),
        )


@dataclass(frozen=True, slots=True)
class MediaEvidence:
    """Deeply immutable, provider-neutral media evidence envelope."""

    evidence_id: str
    source_id: str
    kind: MediaEvidenceKind
    start_ms: int
    end_ms: int
    fields: tuple[MediaEvidenceField, ...] = ()
    confidence: float = 1.0
    source_authoritative: bool = False
    source_revision: str | None = None
    provider_id: str | None = None
    producer_revision: str | None = None
    provenance: str | None = None
    raw_candidate_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _require_bounded_text(self.evidence_id, "evidence_id", max_chars=512),
        )
        object.__setattr__(
            self,
            "source_id",
            _require_bounded_text(self.source_id, "source_id", max_chars=512),
        )
        if type(self.kind) is MediaEvidenceKind:
            kind = self.kind
        elif type(self.kind) is str:
            try:
                kind = MediaEvidenceKind(self.kind)
            except ValueError as exc:
                raise MediaContractError(
                    "unsupported media evidence kind",
                    code=MediaErrorCode.INVALID_CONTAINER,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported media evidence kind",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "kind", kind)
        start = _require_nonnegative_int(self.start_ms, "start_ms")
        end = _require_nonnegative_int(self.end_ms, "end_ms")
        if end < start:
            raise MediaContractError(
                "evidence end_ms must be greater than or equal to start_ms",
                code=MediaErrorCode.INVALID_TIMESTAMP,
            )
        if type(self.fields) is not tuple:
            raise MediaContractError(
                "evidence fields must be an immutable tuple",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if len(self.fields) > MAX_MEDIA_EVIDENCE_FIELDS:
            raise MediaContractError(
                f"media evidence exceeds {MAX_MEDIA_EVIDENCE_FIELDS} fields",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        names: set[str] = set()
        normalized_fields: list[MediaEvidenceField] = []
        for field in self.fields:
            if type(field) is not MediaEvidenceField:
                raise MediaContractError(
                    "evidence fields must contain MediaEvidenceField values",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            if field.name in names:
                raise MediaContractError(
                    "duplicate media evidence field name",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            names.add(field.name)
            normalized_fields.append(field)
        object.__setattr__(
            self,
            "fields",
            tuple(sorted(normalized_fields, key=lambda item: (item.name, item.value))),
        )
        object.__setattr__(self, "confidence", _require_confidence(self.confidence))
        if type(self.source_authoritative) is not bool:
            raise MediaContractError(
                "source_authoritative must be an exact boolean",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        for attribute, field_name, limit in (
            ("source_revision", "source_revision", 512),
            ("provider_id", "provider_id", 512),
            ("producer_revision", "producer_revision", 512),
            ("provenance", "provenance", 4096),
            ("raw_candidate_ref", "raw_candidate_ref", 4096),
        ):
            value = getattr(self, attribute)
            if value is not None:
                object.__setattr__(
                    self,
                    attribute,
                    _require_bounded_text(value, field_name, max_chars=limit),
                )


@dataclass(frozen=True, slots=True)
class MediaClockSnapshot:
    """Immutable playback-clock observation at one monotonic host time."""

    position_ms: int
    state: MediaPlaybackState
    playback_rate: float
    duration_ms: int | None
    revision: int

    def __post_init__(self) -> None:
        position = _require_nonnegative_int(self.position_ms, "position_ms")
        if type(self.state) is MediaPlaybackState:
            state = self.state
        elif type(self.state) is str:
            try:
                state = MediaPlaybackState(self.state)
            except ValueError as exc:
                raise MediaContractError(
                    "unsupported media playback state",
                    code=MediaErrorCode.INVALID_CONTAINER,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported media playback state",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "playback_rate",
            MediaClock._require_rate(self.playback_rate),
        )
        if self.duration_ms is not None:
            try:
                duration = _require_nonnegative_int(self.duration_ms, "duration_ms")
            except MediaContractError as exc:
                raise MediaContractError(
                    str(exc),
                    code=MediaErrorCode.INVALID_DURATION,
                ) from exc
            if position > duration:
                raise MediaContractError(
                    "clock position exceeds media duration",
                    code=MediaErrorCode.INVALID_TIMESTAMP,
                )
            object.__setattr__(self, "duration_ms", duration)
        _require_nonnegative_int(self.revision, "revision")


class MediaClock:
    """Deterministic provider-neutral media clock with explicit host time."""

    __slots__ = (
        "_position_ms",
        "_fractional_ms",
        "_last_now_ms",
        "_playback_rate",
        "_duration_ms",
        "_state",
        "_revision",
    )

    def __init__(
        self, *, position_ms: int = 0,
        state: MediaPlaybackState = MediaPlaybackState.UNSTARTED,
        playback_rate: float = 1.0, duration_ms: int | None = None,
    ) -> None:
        self._position_ms = _require_nonnegative_int(position_ms, "position_ms")
        if duration_ms is not None:
            try:
                duration = _require_nonnegative_int(duration_ms, "duration_ms")
            except MediaContractError as exc:
                raise MediaContractError(
                    str(exc),
                    code=MediaErrorCode.INVALID_DURATION,
                ) from exc
            if self._position_ms > duration:
                raise MediaContractError(
                    "position exceeds media duration",
                    code=MediaErrorCode.INVALID_TIMESTAMP,
                )
        else:
            duration = None
        if type(state) is MediaPlaybackState:
            normalized_state = state
        elif type(state) is str:
            try:
                normalized_state = MediaPlaybackState(state)
            except ValueError as exc:
                raise MediaContractError(
                    f"unsupported media playback state: {state!r}",
                    code=MediaErrorCode.INVALID_CONTAINER,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported media playback state",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        self._playback_rate = self._require_rate(playback_rate)
        self._fractional_ms = 0.0
        self._duration_ms = duration
        self._state = normalized_state
        self._last_now_ms = 0
        self._revision = 0
        if duration is not None and self._position_ms == duration:
            self._state = MediaPlaybackState.ENDED

    @classmethod
    def from_snapshot(
        cls,
        snapshot: MediaClockSnapshot,
        *,
        now_ms: int = 0,
    ) -> "MediaClock":
        """Restore one persisted clock snapshot without replaying downtime.

        Host monotonic time is re-anchored at now_ms. A PLAYING snapshot
        resumes from its persisted media position and advances only after the
        restored process observes new host time.
        """

        if type(snapshot) is not MediaClockSnapshot:
            raise MediaContractError(
                "snapshot must be an exact MediaClockSnapshot",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        now = cls._require_now(now_ms)
        restored = cls(
            position_ms=snapshot.position_ms,
            state=snapshot.state,
            playback_rate=snapshot.playback_rate,
            duration_ms=snapshot.duration_ms,
        )
        restored._revision = snapshot.revision
        restored._last_now_ms = now
        restored._fractional_ms = 0.0
        return restored

    @staticmethod
    def _require_now(now_ms: object) -> int:
        return _require_nonnegative_int(now_ms, "now_ms")

    @staticmethod
    def _require_rate(value: object) -> float:
        if type(value) not in (int, float) or isinstance(value, bool):
            raise MediaContractError(
                "playback_rate must be a finite positive number",
                code=MediaErrorCode.INVALID_PLAYBACK_RATE,
            )
        try:
            rate = float(value)
        except (OverflowError, ValueError) as exc:
            raise MediaContractError(
                "playback_rate must be a finite positive number",
                code=MediaErrorCode.INVALID_PLAYBACK_RATE,
            ) from exc
        if not math.isfinite(rate) or rate <= 0.0:
            raise MediaContractError(
                "playback_rate must be a finite positive number",
                code=MediaErrorCode.INVALID_PLAYBACK_RATE,
            )
        return rate

    def _materialize(self, now_ms: int) -> None:
        now = self._require_now(now_ms)
        if now < self._last_now_ms:
            raise MediaContractError(
                "media clock time cannot move backwards",
                code=MediaErrorCode.INVALID_TIMESTAMP,
            )
        elapsed = now - self._last_now_ms
        if self._state is MediaPlaybackState.PLAYING and elapsed:
            try:
                media_elapsed = elapsed * self._playback_rate + self._fractional_ms
            except (OverflowError, ValueError) as exc:
                raise MediaContractError(
                    "media clock delta is not representable",
                    code=MediaErrorCode.INVALID_TIMESTAMP,
                ) from exc
            if not math.isfinite(media_elapsed):
                raise MediaContractError(
                    "media clock delta is not representable",
                    code=MediaErrorCode.INVALID_TIMESTAMP,
                )
            whole_elapsed = int(media_elapsed)
            self._fractional_ms = media_elapsed - whole_elapsed
            self._position_ms += whole_elapsed
            if (
                self._duration_ms is not None
                and self._position_ms >= self._duration_ms
            ):
                self._position_ms = self._duration_ms
                self._fractional_ms = 0.0
                if self._state is not MediaPlaybackState.ENDED:
                    self._state = MediaPlaybackState.ENDED
                    self._revision += 1
        self._last_now_ms = now

    def _snapshot(self) -> MediaClockSnapshot:
        return MediaClockSnapshot(
            self._position_ms,
            self._state,
            self._playback_rate,
            self._duration_ms,
            self._revision,
        )

    @property
    def revision(self) -> int:
        return self._revision

    def snapshot(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
        return self._snapshot()

    def play(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
        if self._state is MediaPlaybackState.ENDED:
            return self._snapshot()
        if self._duration_ms is not None and self._position_ms >= self._duration_ms:
            self._state = MediaPlaybackState.ENDED
            self._revision += 1
            return self._snapshot()
        if self._state is not MediaPlaybackState.PLAYING:
            self._state = MediaPlaybackState.PLAYING
            self._revision += 1
        return self._snapshot()

    def pause(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
        if self._state in (
            MediaPlaybackState.PLAYING,
            MediaPlaybackState.BUFFERING,
        ):
            self._state = MediaPlaybackState.PAUSED
            self._fractional_ms = 0.0
            self._revision += 1
        return self._snapshot()

    def buffer(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
        if self._state in (
            MediaPlaybackState.ENDED,
            MediaPlaybackState.PAUSED,
        ):
            return self._snapshot()
        if self._state is not MediaPlaybackState.BUFFERING:
            self._state = MediaPlaybackState.BUFFERING
            self._fractional_ms = 0.0
            self._revision += 1
        return self._snapshot()

    def resume(self, now_ms: int) -> MediaClockSnapshot:
        return self.play(now_ms)

    def seek(self, position_ms: int, now_ms: int) -> MediaClockSnapshot:
        position = _require_nonnegative_int(position_ms, "position_ms")
        if self._duration_ms is not None and position > self._duration_ms:
            raise MediaContractError(
                "media position exceeds source duration",
                code=MediaErrorCode.INVALID_TIMESTAMP,
            )
        self._materialize(now_ms)
        self._position_ms = position
        self._fractional_ms = 0.0
        self._last_now_ms = self._require_now(now_ms)
        if self._duration_ms is not None and position == self._duration_ms:
            self._state = MediaPlaybackState.ENDED
        elif self._state is MediaPlaybackState.ENDED:
            self._state = MediaPlaybackState.PAUSED
        self._revision += 1
        return self._snapshot()

    def set_playback_rate(
        self,
        playback_rate: float,
        now_ms: int,
    ) -> MediaClockSnapshot:
        rate = self._require_rate(playback_rate)
        self._materialize(now_ms)
        if rate != self._playback_rate:
            self._playback_rate = rate
            self._fractional_ms = 0.0
            self._revision += 1
        return self._snapshot()

    def end(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
        if self._duration_ms is not None:
            self._position_ms = self._duration_ms
            self._fractional_ms = 0.0
        if self._state is not MediaPlaybackState.ENDED:
            self._state = MediaPlaybackState.ENDED
            self._revision += 1
        return self._snapshot()



def _require_text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise MediaContractError(
            f"{field_name} must be non-empty text",
            code=MediaErrorCode.INVALID_TEXT,
        )
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise MediaContractError(
            f"{field_name} must be valid UTF-8 text",
            code=MediaErrorCode.INVALID_TEXT,
        ) from exc
    return value


def _require_bounded_text(
    value: object,
    field_name: str,
    *,
    max_chars: int = MAX_MEDIA_CONTRACT_TEXT,
) -> str:
    text = _require_text(value, field_name)
    if len(text) > max_chars:
        raise MediaContractError(
            f"{field_name} exceeds the safety limit",
            code=MediaErrorCode.INVALID_TEXT,
        )
    return text


def _require_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise MediaContractError(
            f"{field_name} must be a non-negative exact integer",
            code=MediaErrorCode.INVALID_TIMESTAMP,
        )
    return value


def _require_confidence(value: object) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise MediaContractError(
            "confidence must be a finite number in the range 0..1",
            code=MediaErrorCode.INVALID_CONFIDENCE,
        )
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise MediaContractError(
            "confidence must be a finite number in the range 0..1",
            code=MediaErrorCode.INVALID_CONFIDENCE,
        ) from exc
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise MediaContractError(
            "confidence must be a finite number in the range 0..1",
            code=MediaErrorCode.INVALID_CONFIDENCE,
        )
    return number


@dataclass(frozen=True, slots=True)
class MediaSource:
    """One user-visible media item.

    ``source_ref`` is an opaque provider/storage reference. The core never
    opens it, treats it as a filesystem path, or displays it as trusted text.
    """

    source_id: str
    title: str
    kind: MediaSourceKind
    source_ref: str | None = None
    duration_ms: int | None = None
    attribution: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _require_text(self.source_id, "source_id"))
        object.__setattr__(self, "title", _require_text(self.title, "title"))
        if type(self.kind) is MediaSourceKind:
            kind = self.kind
        elif type(self.kind) is str:
            try:
                kind = MediaSourceKind(self.kind)
            except ValueError as exc:
                raise MediaContractError(
                    "unsupported media source kind",
                    code=MediaErrorCode.INVALID_CONTAINER,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported media source kind",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "source_ref",
            _require_optional_text(self.source_ref, "source_ref"),
        )
        object.__setattr__(
            self,
            "attribution",
            _require_optional_text(self.attribution, "attribution"),
        )
        if self.duration_ms is not None:
            try:
                duration = _require_nonnegative_int(self.duration_ms, "duration_ms")
            except MediaContractError as exc:
                raise MediaContractError(
                    str(exc), code=MediaErrorCode.INVALID_DURATION
                ) from exc
            object.__setattr__(self, "duration_ms", duration)



@dataclass(frozen=True, slots=True)
class MediaTimelineIdentity:
    """Dependency identity for one reusable MediaPositionTimeline cache."""

    source_id: str
    source_revision: str
    recognizer_revision: str
    reconciliation_revision: str
    provider_revision: str | None = None
    cache_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_id",
            _require_bounded_text(self.source_id, "source_id", max_chars=512),
        )
        object.__setattr__(
            self,
            "source_revision",
            _require_bounded_text(
                self.source_revision, "source_revision", max_chars=512
            ),
        )
        object.__setattr__(
            self,
            "recognizer_revision",
            _require_bounded_text(
                self.recognizer_revision, "recognizer_revision", max_chars=512
            ),
        )
        object.__setattr__(
            self,
            "reconciliation_revision",
            _require_bounded_text(
                self.reconciliation_revision,
                "reconciliation_revision",
                max_chars=512,
            ),
        )
        if self.provider_revision is not None:
            object.__setattr__(
                self,
                "provider_revision",
                _require_bounded_text(
                    self.provider_revision,
                    "provider_revision",
                    max_chars=512,
                ),
            )
        cache_version = _require_nonnegative_int(self.cache_version, "cache_version")
        if cache_version < 1:
            raise MediaContractError(
                "cache_version must be a positive integer",
                code=MediaErrorCode.INVALID_CONTAINER,
            )

    def compatible_with(self, other: "MediaTimelineIdentity") -> bool:
        if type(other) is not MediaTimelineIdentity:
            return False
        return self == other


@dataclass(frozen=True, slots=True)
class MediaChessLink:
    """A timestamped recognition/reconciliation link to canonical chess state."""

    source_id: str
    timestamp_ms: int
    chess_ref: str
    status: MediaLinkStatus = MediaLinkStatus.CANDIDATE
    confidence: float = 0.0
    evidence: str | None = None
    end_timestamp_ms: int | None = None
    segment_id: str | None = None
    position_id: str | None = None
    qualification: MediaReconciliationState | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _require_text(self.source_id, "source_id"))
        object.__setattr__(
            self,
            "timestamp_ms",
            _require_nonnegative_int(self.timestamp_ms, "timestamp_ms"),
        )
        object.__setattr__(self, "chess_ref", _require_text(self.chess_ref, "chess_ref"))
        if type(self.status) is MediaLinkStatus:
            status = self.status
        elif type(self.status) is str:
            try:
                status = MediaLinkStatus(self.status)
            except ValueError as exc:
                raise MediaContractError(
                    "unsupported media link status",
                    code=MediaErrorCode.INVALID_CONTAINER,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported media link status",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "confidence", _require_confidence(self.confidence))
        object.__setattr__(
            self, "evidence", _require_optional_text(self.evidence, "evidence")
        )
        if self.end_timestamp_ms is not None:
            end_timestamp = _require_nonnegative_int(
                self.end_timestamp_ms,
                "end_timestamp_ms",
            )
            if end_timestamp < self.timestamp_ms:
                raise MediaContractError(
                    "link end_timestamp_ms cannot precede timestamp_ms",
                    code=MediaErrorCode.INVALID_TIMESTAMP,
                )
            object.__setattr__(self, "end_timestamp_ms", end_timestamp)
        for attribute, field_name, limit in (
            ("segment_id", "segment_id", 512),
            ("position_id", "position_id", 2048),
        ):
            value = getattr(self, attribute)
            if value is not None:
                object.__setattr__(
                    self,
                    attribute,
                    _require_bounded_text(value, field_name, max_chars=limit),
                )
        if self.qualification is None:
            qualification = (
                MediaReconciliationState.VERIFIED
                if status is MediaLinkStatus.CONFIRMED
                else MediaReconciliationState.OBSERVED
            )
        elif type(self.qualification) is MediaReconciliationState:
            qualification = self.qualification
        elif type(self.qualification) is str:
            try:
                qualification = MediaReconciliationState(self.qualification)
            except ValueError as exc:
                raise MediaContractError(
                    "unsupported media link qualification",
                    code=MediaErrorCode.INVALID_CONTAINER,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported media link qualification",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if status is MediaLinkStatus.CONFIRMED:
            if qualification not in (
                MediaReconciliationState.VERIFIED,
                MediaReconciliationState.INFERRED,
            ):
                raise MediaContractError(
                    "confirmed link requires VERIFIED or INFERRED qualification",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
        elif qualification is not MediaReconciliationState.OBSERVED:
            raise MediaContractError(
                "candidate link must remain OBSERVED until reconciliation",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "qualification", qualification)
        if type(self.evidence_ids) is not tuple:
            raise MediaContractError(
                "link evidence_ids must be an immutable tuple",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if len(self.evidence_ids) > MAX_MEDIA_RECONCILIATION_REFS:
            raise MediaContractError(
                "link evidence_ids exceed the safety limit",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        evidence_ids = tuple(
            _require_bounded_text(item, "evidence_id", max_chars=512)
            for item in self.evidence_ids
        )
        if len(set(evidence_ids)) != len(evidence_ids):
            raise MediaContractError(
                "link evidence_ids must be unique",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "evidence_ids", evidence_ids)

    @property
    def confirmed(self) -> bool:
        return self.status is MediaLinkStatus.CONFIRMED



@dataclass(frozen=True, slots=True)
class MediaTimelineBarrier:
    """An explicit unresolved anchor that blocks stale confirmed fallback."""

    source_id: str
    timestamp_ms: int
    state: MediaReconciliationState = MediaReconciliationState.RESYNC_REQUIRED
    segment_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    reason: str = "media timeline requires resynchronization"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_id",
            _require_bounded_text(self.source_id, "source_id", max_chars=512),
        )
        object.__setattr__(
            self,
            "timestamp_ms",
            _require_nonnegative_int(self.timestamp_ms, "timestamp_ms"),
        )
        if type(self.state) is MediaReconciliationState:
            state = self.state
        elif type(self.state) is str:
            try:
                state = MediaReconciliationState(self.state)
            except ValueError as exc:
                raise MediaContractError(
                    "unsupported timeline barrier state",
                    code=MediaErrorCode.INVALID_CONTAINER,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported timeline barrier state",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if state not in (
            MediaReconciliationState.OBSERVED,
            MediaReconciliationState.AMBIGUOUS,
            MediaReconciliationState.RESYNC_REQUIRED,
        ):
            raise MediaContractError(
                "timeline barrier must represent an unresolved state",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "state", state)
        if self.segment_id is not None:
            object.__setattr__(
                self,
                "segment_id",
                _require_bounded_text(self.segment_id, "segment_id", max_chars=512),
            )
        if type(self.evidence_ids) is not tuple:
            raise MediaContractError(
                "barrier evidence_ids must be an immutable tuple",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if len(self.evidence_ids) > MAX_MEDIA_RECONCILIATION_REFS:
            raise MediaContractError(
                "barrier evidence_ids exceed the safety limit",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        evidence_ids = tuple(
            _require_bounded_text(item, "evidence_id", max_chars=512)
            for item in self.evidence_ids
        )
        if len(set(evidence_ids)) != len(evidence_ids):
            raise MediaContractError(
                "barrier evidence_ids must be unique",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(
            self,
            "reason",
            _require_bounded_text(self.reason, "barrier reason", max_chars=4096),
        )


@dataclass(frozen=True, slots=True)
class TimelineResolution:
    """Resolution of one media time without hiding uncertainty."""

    source_id: str
    requested_timestamp_ms: int
    anchor_timestamp_ms: int | None
    links: tuple[MediaChessLink, ...]
    chess_ref: str | None
    ambiguous: bool
    barrier: MediaTimelineBarrier | None = None
    qualification: MediaReconciliationState | None = None
    end_timestamp_ms: int | None = None
    segment_id: str | None = None
    position_id: str | None = None
    evidence_ids: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.chess_ref is not None and not self.ambiguous



@dataclass(frozen=True, slots=True)
class MediaReconciliationResult:
    """Validated result from canonical chess-state reconciliation."""

    source_id: str
    state: MediaReconciliationState
    evidence_ids: tuple[str, ...]
    chess_ref: str | None = None
    candidate_refs: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = "reconciliation result"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_id",
            _require_bounded_text(self.source_id, "source_id", max_chars=512),
        )
        if type(self.state) is MediaReconciliationState:
            state = self.state
        elif type(self.state) is str:
            try:
                state = MediaReconciliationState(self.state)
            except ValueError as exc:
                raise MediaContractError(
                    "unsupported media reconciliation state",
                    code=MediaErrorCode.RECONCILIATION_FAILED,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported media reconciliation state",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        object.__setattr__(self, "state", state)
        if type(self.evidence_ids) is not tuple:
            raise MediaContractError(
                "reconciliation evidence_ids must be an immutable tuple",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        if not self.evidence_ids or len(self.evidence_ids) > MAX_MEDIA_RECONCILIATION_REFS:
            raise MediaContractError(
                "reconciliation evidence_ids are empty or exceed the safety limit",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        evidence_ids = tuple(
            _require_bounded_text(item, "evidence_id", max_chars=512)
            for item in self.evidence_ids
        )
        if len(set(evidence_ids)) != len(evidence_ids):
            raise MediaContractError(
                "reconciliation evidence_ids must be unique",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        object.__setattr__(self, "evidence_ids", evidence_ids)
        chess_ref = (
            None
            if self.chess_ref is None
            else _require_bounded_text(self.chess_ref, "chess_ref", max_chars=2048)
        )
        object.__setattr__(self, "chess_ref", chess_ref)
        if type(self.candidate_refs) is not tuple:
            raise MediaContractError(
                "candidate_refs must be an immutable tuple",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        if len(self.candidate_refs) > MAX_MEDIA_RECONCILIATION_REFS:
            raise MediaContractError(
                "candidate_refs exceed the safety limit",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        candidate_refs = tuple(
            _require_bounded_text(item, "candidate_ref", max_chars=2048)
            for item in self.candidate_refs
        )
        if len(set(candidate_refs)) != len(candidate_refs):
            raise MediaContractError(
                "candidate_refs must be unique",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        object.__setattr__(self, "candidate_refs", candidate_refs)
        object.__setattr__(self, "confidence", _require_confidence(self.confidence))
        object.__setattr__(
            self,
            "reason",
            _require_bounded_text(
                self.reason,
                "reconciliation reason",
                max_chars=4096,
            ),
        )
        resolved_states = (
            MediaReconciliationState.VERIFIED,
            MediaReconciliationState.INFERRED,
        )
        unresolved_states = (
            MediaReconciliationState.OBSERVED,
            MediaReconciliationState.AMBIGUOUS,
            MediaReconciliationState.RESYNC_REQUIRED,
        )
        if state in resolved_states and chess_ref is None:
            raise MediaContractError(
                "verified/inferred reconciliation requires one canonical chess_ref",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        if state in unresolved_states and chess_ref is not None:
            raise MediaContractError(
                "unresolved reconciliation cannot publish canonical chess_ref",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        if state is MediaReconciliationState.AMBIGUOUS and len(candidate_refs) < 2:
            raise MediaContractError(
                "ambiguous reconciliation requires at least two candidate refs",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )


class CanonicalChessReconciliationPort(Protocol):
    """Application-owned legality/reconciliation authority consumed by Media Core."""

    def reconcile_media_evidence(
        self,
        *,
        current_chess_ref: str | None,
        evidence: MediaEvidence,
    ) -> MediaReconciliationResult:
        ...

    def reconcile_media_evidence_batch(
        self,
        *,
        current_chess_ref: str | None,
        evidence: tuple[MediaEvidence, ...],
    ) -> MediaReconciliationResult:
        ...


class ChessStateReconciler:
    """Fail-closed boundary around canonical chess application authority."""

    __slots__ = ("_port",)

    def __init__(self, port: CanonicalChessReconciliationPort) -> None:
        single = getattr(port, "reconcile_media_evidence", None)
        batch = getattr(port, "reconcile_media_evidence_batch", None)
        if not callable(single) and not callable(batch):
            raise MediaContractError(
                "canonical reconciliation port is unavailable",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        self._port = port

    @staticmethod
    def _current_ref(current_chess_ref: str | None) -> str | None:
        return (
            None
            if current_chess_ref is None
            else _require_bounded_text(
                current_chess_ref,
                "current_chess_ref",
                max_chars=2048,
            )
        )

    @staticmethod
    def _validate_result(
        result: object,
        *,
        source_id: str,
        evidence_ids: tuple[str, ...],
    ) -> MediaReconciliationResult:
        if type(result) is not MediaReconciliationResult:
            raise MediaContractError(
                "canonical reconciliation returned an invalid result",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        if result.source_id != source_id:
            raise MediaContractError(
                "reconciliation result source does not match evidence source",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        if set(result.evidence_ids) != set(evidence_ids):
            raise MediaContractError(
                "reconciliation result is not bound exactly to supplied evidence",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        return result

    def reconcile(
        self,
        evidence: MediaEvidence,
        *,
        current_chess_ref: str | None = None,
    ) -> MediaReconciliationResult:
        if type(evidence) is not MediaEvidence:
            raise MediaContractError(
                "evidence must be an exact MediaEvidence value",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        current = self._current_ref(current_chess_ref)
        method = getattr(self._port, "reconcile_media_evidence", None)
        if not callable(method):
            raise MediaContractError(
                "canonical single-evidence reconciliation is unavailable",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        try:
            result = method(
                current_chess_ref=current,
                evidence=evidence,
            )
        except Exception as exc:
            raise MediaContractError(
                "canonical chess reconciliation failed closed",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            ) from exc
        return self._validate_result(
            result,
            source_id=evidence.source_id,
            evidence_ids=(evidence.evidence_id,),
        )

    def reconcile_many(
        self,
        evidence: tuple[MediaEvidence, ...],
        *,
        current_chess_ref: str | None = None,
    ) -> MediaReconciliationResult:
        """Reconcile one bounded same-source evidence bundle atomically."""

        if type(evidence) is not tuple:
            raise MediaContractError(
                "evidence bundle must be an immutable tuple",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if not evidence or len(evidence) > MAX_MEDIA_RECONCILIATION_REFS:
            raise MediaContractError(
                "evidence bundle is empty or exceeds the safety limit",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        source_id: str | None = None
        source_revisions: set[str] = set()
        evidence_ids: list[str] = []
        seen_ids: set[str] = set()
        for item in evidence:
            if type(item) is not MediaEvidence:
                raise MediaContractError(
                    "evidence bundle must contain exact MediaEvidence values",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            if source_id is None:
                source_id = item.source_id
            elif item.source_id != source_id:
                raise MediaContractError(
                    "evidence bundle crosses media sources",
                    code=MediaErrorCode.SOURCE_MISMATCH,
                )
            if item.source_revision is not None:
                source_revisions.add(item.source_revision)
            if item.evidence_id in seen_ids:
                raise MediaContractError(
                    "evidence bundle contains duplicate evidence IDs",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            seen_ids.add(item.evidence_id)
            evidence_ids.append(item.evidence_id)
        if len(source_revisions) > 1:
            raise MediaContractError(
                "evidence bundle crosses source revisions",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        if source_id is None:
            raise MediaContractError(
                "evidence bundle has no source",
                code=MediaErrorCode.INVALID_CONTAINER,
            )

        current = self._current_ref(current_chess_ref)
        method = getattr(self._port, "reconcile_media_evidence_batch", None)
        if not callable(method):
            raise MediaContractError(
                "canonical batch reconciliation is unavailable",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            )
        try:
            result = method(
                current_chess_ref=current,
                evidence=evidence,
            )
        except Exception as exc:
            raise MediaContractError(
                "canonical chess batch reconciliation failed closed",
                code=MediaErrorCode.RECONCILIATION_FAILED,
            ) from exc
        return self._validate_result(
            result,
            source_id=source_id,
            evidence_ids=tuple(evidence_ids),
        )


class MediaPositionTimeline:
    """Deterministic, immutable timeline of media-to-chess links."""

    __slots__ = (
        "source_id",
        "_links",
        "_timestamps",
        "_links_by_timestamp",
        "_confirmed_timestamps_by_ref",
        "_barriers",
        "_barriers_by_timestamp",
        "identity",
    )

    def __init__(
        self,
        source_id: str,
        links: Iterable[MediaChessLink] = (),
        *,
        identity: MediaTimelineIdentity | None = None,
        barriers: Iterable[MediaTimelineBarrier] = (),
    ) -> None:
        self.source_id = _require_text(source_id, "source_id")
        if identity is not None:
            if type(identity) is not MediaTimelineIdentity:
                raise MediaContractError(
                    "timeline identity must be MediaTimelineIdentity",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            if identity.source_id != self.source_id:
                raise MediaContractError(
                    "timeline identity source does not match timeline source",
                    code=MediaErrorCode.SOURCE_MISMATCH,
                )
        self.identity = identity
        try:
            iterator = iter(links)
        except BaseException as exc:
            raise MediaContractError(
                "timeline links must be safely iterable",
                code=MediaErrorCode.INVALID_CONTAINER,
            ) from exc

        materialized: list[MediaChessLink] = []
        try:
            for _ in range(MAX_MEDIA_LINKS + 1):
                try:
                    materialized.append(next(iterator))
                except StopIteration:
                    break
        except BaseException as exc:
            raise MediaContractError(
                "timeline links must be safely iterable",
                code=MediaErrorCode.INVALID_CONTAINER,
            ) from exc

        if len(materialized) > MAX_MEDIA_LINKS:
            raise MediaContractError(
                f"media timeline exceeds {MAX_MEDIA_LINKS} links",
                code=MediaErrorCode.LINK_LIMIT,
            )
        materialized = tuple(materialized)

        try:
            barrier_iterator = iter(barriers)
        except BaseException as exc:
            raise MediaContractError(
                "timeline barriers must be safely iterable",
                code=MediaErrorCode.INVALID_CONTAINER,
            ) from exc
        materialized_barriers: list[MediaTimelineBarrier] = []
        try:
            for _ in range(MAX_MEDIA_LINKS + 1):
                try:
                    materialized_barriers.append(next(barrier_iterator))
                except StopIteration:
                    break
        except BaseException as exc:
            raise MediaContractError(
                "timeline barriers must be safely iterable",
                code=MediaErrorCode.INVALID_CONTAINER,
            ) from exc
        if len(materialized) + len(materialized_barriers) > MAX_MEDIA_LINKS:
            raise MediaContractError(
                f"media timeline exceeds {MAX_MEDIA_LINKS} total events",
                code=MediaErrorCode.LINK_LIMIT,
            )
        materialized_barriers = tuple(materialized_barriers)

        seen: set[tuple[int, str]] = set()
        for link in materialized:
            if type(link) is not MediaChessLink:
                raise MediaContractError(
                    "timeline links must be MediaChessLink values",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            if link.source_id != self.source_id:
                raise MediaContractError(
                    f"link source {link.source_id!r} does not match timeline source "
                    f"{self.source_id!r}",
                    code=MediaErrorCode.SOURCE_MISMATCH,
                )
            key = (link.timestamp_ms, link.chess_ref)
            if key in seen:
                raise MediaContractError(
                    "duplicate media/chess link",
                    code=MediaErrorCode.DUPLICATE_LINK,
                )
            seen.add(key)

        self._links = tuple(
            sorted(
                materialized,
                key=lambda link: (
                    link.timestamp_ms,
                    0 if link.confirmed else 1,
                    -link.confidence,
                    link.chess_ref,
                    link.evidence or "",
                ),
            )
        )

        barrier_by_timestamp: dict[int, MediaTimelineBarrier] = {}
        for barrier in materialized_barriers:
            if type(barrier) is not MediaTimelineBarrier:
                raise MediaContractError(
                    "timeline barriers must be MediaTimelineBarrier values",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            if barrier.source_id != self.source_id:
                raise MediaContractError(
                    "barrier source does not match timeline source",
                    code=MediaErrorCode.SOURCE_MISMATCH,
                )
            if barrier.timestamp_ms in barrier_by_timestamp:
                raise MediaContractError(
                    "duplicate timeline barrier timestamp",
                    code=MediaErrorCode.DUPLICATE_LINK,
                )
            barrier_by_timestamp[barrier.timestamp_ms] = barrier

        grouped: dict[int, list[MediaChessLink]] = {}
        confirmed_by_ref: dict[str, set[int]] = {}
        for link in self._links:
            grouped.setdefault(link.timestamp_ms, []).append(link)
            if link.confirmed:
                confirmed_by_ref.setdefault(link.chess_ref, set()).add(link.timestamp_ms)

        self._links_by_timestamp = {
            timestamp: tuple(group) for timestamp, group in grouped.items()
        }
        for timestamp, barrier in barrier_by_timestamp.items():
            if any(link.confirmed for link in self._links_by_timestamp.get(timestamp, ())):
                raise MediaContractError(
                    "unresolved barrier cannot coexist with confirmed link",
                    code=MediaErrorCode.CONFIRMATION_CONFLICT,
                )
        self._barriers = tuple(
            sorted(materialized_barriers, key=lambda item: item.timestamp_ms)
        )
        self._barriers_by_timestamp = dict(barrier_by_timestamp)
        self._timestamps = tuple(
            sorted(set(self._links_by_timestamp) | set(self._barriers_by_timestamp))
        )
        self._confirmed_timestamps_by_ref = {
            chess_ref: tuple(sorted(timestamps))
            for chess_ref, timestamps in confirmed_by_ref.items()
        }

    @property
    def links(self) -> tuple[MediaChessLink, ...]:
        return self._links

    @property
    def timestamps(self) -> tuple[int, ...]:
        return self._timestamps

    @property
    def barriers(self) -> tuple[MediaTimelineBarrier, ...]:
        return self._barriers

    def barrier_at(self, timestamp_ms: int) -> MediaTimelineBarrier | None:
        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        return self._barriers_by_timestamp.get(timestamp)

    def links_at(self, timestamp_ms: int) -> tuple[MediaChessLink, ...]:
        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        return self._links_by_timestamp.get(timestamp, ())

    def links_covering(self, timestamp_ms: int) -> tuple[MediaChessLink, ...]:
        """Return only links that explicitly declare a range covering time."""

        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        return tuple(
            link
            for link in self._links
            if link.end_timestamp_ms is not None
            and link.timestamp_ms <= timestamp <= link.end_timestamp_ms
        )

    def next_resolved(
        self,
        after_timestamp_ms: int,
    ) -> TimelineResolution | None:
        """Return the next unambiguous confirmed media position."""

        timestamp = _require_nonnegative_int(
            after_timestamp_ms,
            "after_timestamp_ms",
        )
        index = bisect_right(self._timestamps, timestamp)
        while index < len(self._timestamps):
            resolution = self.resolve_exact(self._timestamps[index])
            if resolution.resolved:
                return resolution
            index += 1
        return None

    def previous_resolved(
        self,
        before_timestamp_ms: int,
    ) -> TimelineResolution | None:
        """Return the previous unambiguous confirmed media position."""

        timestamp = _require_nonnegative_int(
            before_timestamp_ms,
            "before_timestamp_ms",
        )
        index = bisect_left(self._timestamps, timestamp) - 1
        while index >= 0:
            resolution = self.resolve_exact(self._timestamps[index])
            if resolution.resolved:
                return resolution
            index -= 1
        return None

    def resolve_exact(self, timestamp_ms: int) -> TimelineResolution:
        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        return self._resolution(
            timestamp,
            timestamp,
            self.links_at(timestamp),
            self.barrier_at(timestamp),
        )

    def resolve_at_or_before(self, timestamp_ms: int) -> TimelineResolution:
        requested = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        index = bisect_right(self._timestamps, requested) - 1
        if index < 0:
            return TimelineResolution(
                self.source_id, requested, None, (), None, False
            )
        anchor = self._timestamps[index]
        return self._resolution(
            requested,
            anchor,
            self.links_at(anchor),
            self.barrier_at(anchor),
        )

    def _resolution(
        self,
        requested: int,
        anchor: int,
        links: tuple[MediaChessLink, ...],
        barrier: MediaTimelineBarrier | None,
    ) -> TimelineResolution:
        if barrier is not None:
            return TimelineResolution(
                source_id=self.source_id,
                requested_timestamp_ms=requested,
                anchor_timestamp_ms=anchor,
                links=links,
                chess_ref=None,
                ambiguous=barrier.state is MediaReconciliationState.AMBIGUOUS,
                barrier=barrier,
                qualification=barrier.state,
                segment_id=barrier.segment_id,
                evidence_ids=barrier.evidence_ids,
            )
        confirmed_refs = tuple(
            sorted({link.chess_ref for link in links if link.confirmed})
        )
        candidate_refs = tuple(
            sorted({link.chess_ref for link in links if not link.confirmed})
        )
        chess_ref = confirmed_refs[0] if len(confirmed_refs) == 1 else None
        ambiguous = len(confirmed_refs) > 1 or (
            not confirmed_refs and len(candidate_refs) > 1
        )
        selected_link = next(
            (
                link
                for link in links
                if chess_ref is not None
                and link.confirmed
                and link.chess_ref == chess_ref
            ),
            None,
        )
        if selected_link is not None:
            qualification = selected_link.qualification
        elif ambiguous:
            qualification = MediaReconciliationState.AMBIGUOUS
        elif len(links) == 1:
            qualification = links[0].qualification
        elif candidate_refs:
            qualification = MediaReconciliationState.OBSERVED
        else:
            qualification = None
        segment_ids = {link.segment_id for link in links if link.segment_id is not None}
        common_segment = next(iter(segment_ids)) if len(segment_ids) == 1 else None
        evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for link in links
                    for evidence_id in link.evidence_ids
                }
            )
        )
        return TimelineResolution(
            source_id=self.source_id,
            requested_timestamp_ms=requested,
            anchor_timestamp_ms=anchor,
            links=links,
            chess_ref=chess_ref,
            ambiguous=ambiguous,
            qualification=qualification,
            end_timestamp_ms=(
                selected_link.end_timestamp_ms
                if selected_link is not None
                else None
            ),
            segment_id=(
                selected_link.segment_id
                if selected_link is not None
                else common_segment
            ),
            position_id=(
                selected_link.position_id
                if selected_link is not None
                else None
            ),
            evidence_ids=evidence_ids,
        )

    def confirmed_timestamps_for(self, chess_ref: str) -> tuple[int, ...]:
        ref = _require_text(chess_ref, "chess_ref")
        return self._confirmed_timestamps_by_ref.get(ref, ())

    def with_link(self, link: MediaChessLink) -> "MediaPositionTimeline":
        return MediaPositionTimeline(
            self.source_id,
            (*self._links, link),
            identity=self.identity,
            barriers=self._barriers,
        )

    def with_barrier(
        self,
        barrier: MediaTimelineBarrier,
    ) -> "MediaPositionTimeline":
        if type(barrier) is not MediaTimelineBarrier:
            raise MediaContractError(
                "barrier must be MediaTimelineBarrier",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        return MediaPositionTimeline(
            self.source_id,
            self._links,
            identity=self.identity,
            barriers=(*self._barriers, barrier),
        )

    def confirm_candidate(
        self,
        timestamp_ms: int,
        chess_ref: str,
        *,
        replace_confirmed: bool = False,
        evidence: str | None = None,
    ) -> "MediaPositionTimeline":
        """Explicitly confirm an existing recognition candidate.

        The operation never invents a new chess reference. If a different
        confirmed reference already exists at the same timestamp, callers must
        explicitly opt into replacing it. Replacement demotes the old
        confirmation(s) to candidates so the evidence remains reviewable.
        """

        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        ref = _require_text(chess_ref, "chess_ref")
        replacement_evidence = _require_optional_text(evidence, "evidence")
        at_timestamp = self.links_at(timestamp)
        selected = next((link for link in at_timestamp if link.chess_ref == ref), None)
        if selected is None:
            raise MediaContractError(
                "cannot confirm a chess reference that is not an existing link",
                code=MediaErrorCode.LINK_NOT_FOUND,
            )

        conflicts = tuple(
            link
            for link in at_timestamp
            if link.confirmed and link.chess_ref != ref
        )
        if conflicts and not replace_confirmed:
            raise MediaContractError(
                "a different chess reference is already confirmed at this timestamp",
                code=MediaErrorCode.CONFIRMATION_CONFLICT,
            )

        if (
            selected.confirmed
            and not conflicts
            and self.barrier_at(timestamp) is None
            and (replacement_evidence is None or replacement_evidence == selected.evidence)
        ):
            return self

        reconciled: list[MediaChessLink] = []
        for link in self._links:
            if link.timestamp_ms != timestamp:
                reconciled.append(link)
                continue
            if link.chess_ref == ref:
                reconciled.append(
                    replace(
                        link,
                        status=MediaLinkStatus.CONFIRMED,
                        qualification=MediaReconciliationState.VERIFIED,
                        evidence=(
                            replacement_evidence
                            if replacement_evidence is not None
                            else link.evidence
                        ),
                    )
                )
                continue
            if link.confirmed and replace_confirmed:
                reconciled.append(
                    replace(
                        link,
                        status=MediaLinkStatus.CANDIDATE,
                        qualification=MediaReconciliationState.OBSERVED,
                    )
                )
                continue
            reconciled.append(link)
        return MediaPositionTimeline(
            self.source_id,
            reconciled,
            identity=self.identity,
            barriers=tuple(
                barrier
                for barrier in self._barriers
                if barrier.timestamp_ms != timestamp
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "identity": _timeline_identity_to_dict(self.identity),
            "barriers": [
                {
                    "timestamp_ms": barrier.timestamp_ms,
                    "state": barrier.state.value,
                    "segment_id": barrier.segment_id,
                    "evidence_ids": list(barrier.evidence_ids),
                    "reason": barrier.reason,
                }
                for barrier in self._barriers
            ],
            "links": [
                {
                    "timestamp_ms": link.timestamp_ms,
                    "chess_ref": link.chess_ref,
                    "status": link.status.value,
                    "confidence": link.confidence,
                    "evidence": link.evidence,
                    "end_timestamp_ms": link.end_timestamp_ms,
                    "segment_id": link.segment_id,
                    "position_id": link.position_id,
                    "qualification": link.qualification.value,
                    "evidence_ids": list(link.evidence_ids),
                }
                for link in self._links
            ],
        }

    @classmethod
    def from_dict(cls, data: object) -> "MediaPositionTimeline":
        if type(data) is not dict:
            raise MediaContractError(
                "timeline must be an object",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        source_id = data.get("source_id")
        raw_identity = data.get("identity")
        identity = _timeline_identity_from_dict(raw_identity)
        raw_barriers = data.get("barriers", [])
        if type(raw_barriers) is not list:
            raise MediaContractError(
                "timeline barriers must be a list",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        barriers: list[MediaTimelineBarrier] = []
        for raw_barrier in raw_barriers:
            if type(raw_barrier) is not dict:
                raise MediaContractError(
                    "timeline barrier must be an object",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            evidence_ids = raw_barrier.get("evidence_ids", [])
            if type(evidence_ids) is not list:
                raise MediaContractError(
                    "barrier evidence_ids must be a list",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            barriers.append(
                MediaTimelineBarrier(
                    source_id=source_id,
                    timestamp_ms=raw_barrier.get("timestamp_ms"),
                    state=raw_barrier.get(
                        "state", MediaReconciliationState.RESYNC_REQUIRED.value
                    ),
                    segment_id=raw_barrier.get("segment_id"),
                    evidence_ids=tuple(evidence_ids),
                    reason=raw_barrier.get(
                        "reason", "media timeline requires resynchronization"
                    ),
                )
            )
        raw_links = data.get("links")
        if type(raw_links) is not list:
            raise MediaContractError(
                "timeline links must be a list",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if len(raw_links) > MAX_MEDIA_LINKS:
            raise MediaContractError(
                f"media timeline exceeds {MAX_MEDIA_LINKS} links",
                code=MediaErrorCode.LINK_LIMIT,
            )
        links: list[MediaChessLink] = []
        for raw_link in raw_links:
            if type(raw_link) is not dict:
                raise MediaContractError(
                    "timeline link must be an object",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            raw_evidence_ids = raw_link.get("evidence_ids", [])
            if type(raw_evidence_ids) is not list:
                raise MediaContractError(
                    "link evidence_ids must be a list",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            links.append(
                MediaChessLink(
                    source_id=source_id,
                    timestamp_ms=raw_link.get("timestamp_ms"),
                    chess_ref=raw_link.get("chess_ref"),
                    status=raw_link.get("status", MediaLinkStatus.CANDIDATE.value),
                    confidence=raw_link.get("confidence", 0.0),
                    evidence=raw_link.get("evidence"),
                    end_timestamp_ms=raw_link.get("end_timestamp_ms"),
                    segment_id=raw_link.get("segment_id"),
                    position_id=raw_link.get("position_id"),
                    qualification=raw_link.get("qualification"),
                    evidence_ids=tuple(raw_evidence_ids),
                )
            )
        return cls(
            source_id,
            links,
            identity=identity,
            barriers=barriers,
        )


@dataclass(frozen=True, slots=True)
class MediaCursor:
    source_id: str
    position_ms: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _require_text(self.source_id, "source_id"))
        object.__setattr__(
            self,
            "position_ms",
            _require_nonnegative_int(self.position_ms, "position_ms"),
        )



@dataclass(frozen=True, slots=True)
class MediaSession:
    """Durable provider-neutral media session state.

    The media-synchronized chess cursor and the user's analysis cursor are
    explicit independent opaque references. This type owns no chess semantics
    and performs no Restore Media Position mutation.
    """

    session_id: str
    source_id: str
    source_kind: MediaSourceKind
    source_revision: str
    clock: MediaClockSnapshot
    source_ref: str | None = None
    timeline_identity: MediaTimelineIdentity | None = None
    media_chess_ref: str | None = None
    analysis_chess_ref: str | None = None
    timeline_invalidated_reason: str | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "session_id",
            _require_bounded_text(self.session_id, "session_id", max_chars=512),
        )
        object.__setattr__(
            self,
            "source_id",
            _require_bounded_text(self.source_id, "source_id", max_chars=512),
        )
        if type(self.source_kind) is MediaSourceKind:
            source_kind = self.source_kind
        elif type(self.source_kind) is str:
            try:
                source_kind = MediaSourceKind(self.source_kind)
            except ValueError as exc:
                raise MediaContractError(
                    "unsupported media source kind",
                    code=MediaErrorCode.INVALID_CONTAINER,
                ) from exc
        else:
            raise MediaContractError(
                "unsupported media source kind",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(
            self,
            "source_revision",
            _require_bounded_text(
                self.source_revision, "source_revision", max_chars=512
            ),
        )
        if type(self.clock) is not MediaClockSnapshot:
            raise MediaContractError(
                "clock must be an exact MediaClockSnapshot",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if self.source_ref is not None:
            object.__setattr__(
                self,
                "source_ref",
                _require_bounded_text(self.source_ref, "source_ref", max_chars=4096),
            )
        if self.timeline_identity is not None:
            if type(self.timeline_identity) is not MediaTimelineIdentity:
                raise MediaContractError(
                    "timeline_identity must be MediaTimelineIdentity",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            if self.timeline_identity.source_id != self.source_id:
                raise MediaContractError(
                    "timeline identity source does not match media session",
                    code=MediaErrorCode.SOURCE_MISMATCH,
                )
            if self.timeline_identity.source_revision != self.source_revision:
                raise MediaContractError(
                    "timeline identity source revision is stale",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
        if self.media_chess_ref is not None:
            if self.timeline_identity is None:
                raise MediaContractError(
                    "media chess cursor requires a valid timeline identity",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            object.__setattr__(
                self,
                "media_chess_ref",
                _require_bounded_text(
                    self.media_chess_ref, "media_chess_ref", max_chars=2048
                ),
            )
        if self.analysis_chess_ref is not None:
            object.__setattr__(
                self,
                "analysis_chess_ref",
                _require_bounded_text(
                    self.analysis_chess_ref, "analysis_chess_ref", max_chars=2048
                ),
            )
        if self.timeline_invalidated_reason is not None:
            if self.timeline_identity is not None or self.media_chess_ref is not None:
                raise MediaContractError(
                    "invalidated timeline cannot retain timeline identity/media cursor",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            object.__setattr__(
                self,
                "timeline_invalidated_reason",
                _require_bounded_text(
                    self.timeline_invalidated_reason,
                    "timeline_invalidated_reason",
                    max_chars=4096,
                ),
            )
        _require_nonnegative_int(self.revision, "revision")

    def with_clock(self, clock: MediaClockSnapshot) -> "MediaSession":
        if type(clock) is not MediaClockSnapshot:
            raise MediaContractError(
                "clock must be an exact MediaClockSnapshot",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if clock == self.clock:
            return self
        if clock.revision < self.clock.revision:
            raise MediaContractError(
                "stale media clock revision cannot replace current session clock",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if clock.revision == self.clock.revision:
            if (
                clock.state is not self.clock.state
                or clock.playback_rate != self.clock.playback_rate
                or clock.duration_ms != self.clock.duration_ms
            ):
                raise MediaContractError(
                    "clock control state changed without revision advance",
                    code=MediaErrorCode.INVALID_CONTAINER,
                )
            if clock.position_ms < self.clock.position_ms:
                raise MediaContractError(
                    "clock position moved backwards without revision advance",
                    code=MediaErrorCode.INVALID_TIMESTAMP,
                )
        return replace(self, clock=clock, revision=self.revision + 1)

    def select_analysis_cursor(self, chess_ref: str | None) -> "MediaSession":
        ref = (
            None
            if chess_ref is None
            else _require_bounded_text(
                chess_ref, "analysis_chess_ref", max_chars=2048
            )
        )
        if ref == self.analysis_chess_ref:
            return self
        return replace(self, analysis_chess_ref=ref, revision=self.revision + 1)

    def bind_media_cursor(
        self,
        timeline_identity: MediaTimelineIdentity,
        chess_ref: str,
    ) -> "MediaSession":
        if type(timeline_identity) is not MediaTimelineIdentity:
            raise MediaContractError(
                "timeline_identity must be MediaTimelineIdentity",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if timeline_identity.source_id != self.source_id:
            raise MediaContractError(
                "timeline identity source does not match media session",
                code=MediaErrorCode.SOURCE_MISMATCH,
            )
        if timeline_identity.source_revision != self.source_revision:
            raise MediaContractError(
                "cannot bind a stale timeline identity",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        ref = _require_bounded_text(chess_ref, "media_chess_ref", max_chars=2048)
        if (
            timeline_identity == self.timeline_identity
            and ref == self.media_chess_ref
            and self.timeline_invalidated_reason is None
        ):
            return self
        return replace(
            self,
            timeline_identity=timeline_identity,
            media_chess_ref=ref,
            timeline_invalidated_reason=None,
            revision=self.revision + 1,
        )

    def invalidate_timeline(self, reason: str) -> "MediaSession":
        normalized_reason = _require_bounded_text(
            reason, "timeline invalidation reason", max_chars=4096
        )
        if (
            self.timeline_identity is None
            and self.media_chess_ref is None
            and self.timeline_invalidated_reason == normalized_reason
        ):
            return self
        return replace(
            self,
            timeline_identity=None,
            media_chess_ref=None,
            timeline_invalidated_reason=normalized_reason,
            revision=self.revision + 1,
        )

    def with_source_revision(self, source_revision: str) -> "MediaSession":
        revision = _require_bounded_text(
            source_revision, "source_revision", max_chars=512
        )
        if revision == self.source_revision:
            return self
        return replace(
            self,
            source_revision=revision,
            timeline_identity=None,
            media_chess_ref=None,
            timeline_invalidated_reason="source revision changed",
            revision=self.revision + 1,
        )

    def timeline_compatible(self, expected: MediaTimelineIdentity) -> bool:
        if type(expected) is not MediaTimelineIdentity:
            return False
        return (
            self.timeline_invalidated_reason is None
            and self.timeline_identity is not None
            and self.timeline_identity.compatible_with(expected)
        )

    def invalidate_if_timeline_changed(
        self,
        expected: MediaTimelineIdentity,
    ) -> "MediaSession":
        if type(expected) is not MediaTimelineIdentity:
            raise MediaContractError(
                "expected timeline identity must be MediaTimelineIdentity",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if expected.source_id != self.source_id:
            raise MediaContractError(
                "expected timeline source does not match media session",
                code=MediaErrorCode.SOURCE_MISMATCH,
            )
        if self.timeline_compatible(expected):
            return self
        return self.invalidate_timeline("timeline dependency revision changed")


@dataclass(frozen=True, slots=True)
class MediaChessSession:
    """Separate media/chess cursors; synchronization is always explicit."""

    media_cursor: MediaCursor
    chess_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.media_cursor) is not MediaCursor:
            raise MediaContractError(
                "media_cursor must be a MediaCursor",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        object.__setattr__(
            self, "chess_ref", _require_optional_text(self.chess_ref, "chess_ref")
        )

    def seek_media(
        self,
        position_ms: int,
        *,
        duration_ms: int | None = None,
    ) -> "MediaChessSession":
        position = _require_nonnegative_int(position_ms, "position_ms")
        if duration_ms is not None:
            try:
                duration = _require_nonnegative_int(duration_ms, "duration_ms")
            except MediaContractError as exc:
                raise MediaContractError(
                    str(exc), code=MediaErrorCode.INVALID_DURATION
                ) from exc
            if position > duration:
                raise MediaContractError(
                    "media position exceeds source duration",
                    code=MediaErrorCode.INVALID_TIMESTAMP,
                )
        return replace(
            self,
            media_cursor=MediaCursor(self.media_cursor.source_id, position),
        )

    def select_chess(self, chess_ref: str | None) -> "MediaChessSession":
        if chess_ref is None:
            return replace(self, chess_ref=None)
        return replace(self, chess_ref=_require_text(chess_ref, "chess_ref"))

    def sync_chess_from_media(
        self, timeline: MediaPositionTimeline
    ) -> tuple["MediaChessSession", TimelineResolution]:
        self._require_timeline_source(timeline)
        resolution = timeline.resolve_at_or_before(self.media_cursor.position_ms)
        if not resolution.resolved:
            return self, resolution
        return replace(self, chess_ref=resolution.chess_ref), resolution

    def sync_media_from_chess(
        self, timeline: MediaPositionTimeline
    ) -> "MediaChessSession":
        self._require_timeline_source(timeline)
        if self.chess_ref is None:
            return self
        timestamps = timeline.confirmed_timestamps_for(self.chess_ref)
        if not timestamps:
            return self
        current = self.media_cursor.position_ms
        target = min(timestamps, key=lambda timestamp: (abs(timestamp - current), timestamp))
        return replace(self, media_cursor=MediaCursor(timeline.source_id, target))

    def _require_timeline_source(self, timeline: MediaPositionTimeline) -> None:
        if type(timeline) is not MediaPositionTimeline:
            raise MediaContractError(
                "timeline must be a MediaPositionTimeline",
                code=MediaErrorCode.INVALID_CONTAINER,
            )
        if timeline.source_id != self.media_cursor.source_id:
            raise MediaContractError(
                "session and timeline source IDs differ",
                code=MediaErrorCode.SOURCE_MISMATCH,
            )


def _source_to_dict(source: MediaSource) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "title": source.title,
        "kind": source.kind.value,
        "source_ref": source.source_ref,
        "duration_ms": source.duration_ms,
        "attribution": source.attribution,
    }


def _source_from_dict(data: object) -> MediaSource:
    if type(data) is not dict:
        raise MediaContractError(
            "source must be an object",
            code=MediaErrorCode.INVALID_CONTAINER,
        )
    return MediaSource(
        source_id=data.get("source_id"),
        title=data.get("title"),
        kind=data.get("kind"),
        source_ref=data.get("source_ref"),
        duration_ms=data.get("duration_ms"),
        attribution=data.get("attribution"),
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MediaContractError(
                f"duplicate JSON object key: {key}",
                code=MediaErrorCode.INVALID_SCHEMA,
            )
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> object:
    raise MediaContractError(
        f"media state contains non-finite JSON number: {value}",
        code=MediaErrorCode.INVALID_SCHEMA,
    )



def _timeline_identity_to_dict(
    identity: MediaTimelineIdentity | None,
) -> dict[str, Any] | None:
    if identity is None:
        return None
    return {
        "source_id": identity.source_id,
        "source_revision": identity.source_revision,
        "recognizer_revision": identity.recognizer_revision,
        "reconciliation_revision": identity.reconciliation_revision,
        "provider_revision": identity.provider_revision,
        "cache_version": identity.cache_version,
    }


def _timeline_identity_from_dict(data: object) -> MediaTimelineIdentity | None:
    if data is None:
        return None
    if type(data) is not dict or set(data) != {
        "source_id",
        "source_revision",
        "recognizer_revision",
        "reconciliation_revision",
        "provider_revision",
        "cache_version",
    }:
        raise MediaContractError(
            "timeline identity payload is invalid",
            code=MediaErrorCode.INVALID_SCHEMA,
        )
    return MediaTimelineIdentity(
        source_id=data["source_id"],
        source_revision=data["source_revision"],
        recognizer_revision=data["recognizer_revision"],
        reconciliation_revision=data["reconciliation_revision"],
        provider_revision=data["provider_revision"],
        cache_version=data["cache_version"],
    )


def serialize_media_session(session: MediaSession) -> str:
    """Serialize one durable provider-neutral MediaSession snapshot."""

    if type(session) is not MediaSession:
        raise MediaContractError(
            "session must be an exact MediaSession",
            code=MediaErrorCode.INVALID_CONTAINER,
        )
    payload = {
        "schema": MEDIA_SESSION_SCHEMA,
        "version": MEDIA_SESSION_VERSION,
        "session": {
            "session_id": session.session_id,
            "source_id": session.source_id,
            "source_kind": session.source_kind.value,
            "source_revision": session.source_revision,
            "source_ref": session.source_ref,
            "clock": {
                "position_ms": session.clock.position_ms,
                "state": session.clock.state.value,
                "playback_rate": session.clock.playback_rate,
                "duration_ms": session.clock.duration_ms,
                "revision": session.clock.revision,
            },
            "timeline_identity": _timeline_identity_to_dict(
                session.timeline_identity
            ),
            "media_chess_ref": session.media_chess_ref,
            "analysis_chess_ref": session.analysis_chess_ref,
            "timeline_invalidated_reason": session.timeline_invalidated_reason,
            "revision": session.revision,
        },
    }
    try:
        text = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded_length = len(text.encode("utf-8", errors="strict"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise MediaContractError(
            "media session contains invalid serialized values",
            code=MediaErrorCode.INVALID_SCHEMA,
        ) from exc
    if encoded_length > MAX_MEDIA_STATE_BYTES:
        raise MediaContractError(
            "serialized media session exceeds the safety limit",
            code=MediaErrorCode.STATE_TOO_LARGE,
        )
    return text


def deserialize_media_session(text: str) -> MediaSession:
    """Load one durable MediaSession snapshot with closed-schema validation."""

    if type(text) is not str:
        raise MediaContractError(
            "media session state must be text",
            code=MediaErrorCode.INVALID_TEXT,
        )
    try:
        encoded_length = len(text.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise MediaContractError(
            "media session state must be valid UTF-8 text",
            code=MediaErrorCode.INVALID_TEXT,
        ) from exc
    if encoded_length > MAX_MEDIA_STATE_BYTES:
        raise MediaContractError(
            "media session state exceeds the safety limit",
            code=MediaErrorCode.STATE_TOO_LARGE,
        )
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise MediaContractError(
            "media session state is not valid JSON",
            code=MediaErrorCode.INVALID_SCHEMA,
        ) from exc
    if (
        type(payload) is not dict
        or set(payload) != {"schema", "version", "session"}
        or payload.get("schema") != MEDIA_SESSION_SCHEMA
        or payload.get("version") != MEDIA_SESSION_VERSION
    ):
        raise MediaContractError(
            "unsupported media session schema/version",
            code=MediaErrorCode.INVALID_SCHEMA,
        )
    data = payload.get("session")
    if type(data) is not dict or set(data) != {
        "session_id",
        "source_id",
        "source_kind",
        "source_revision",
        "source_ref",
        "clock",
        "timeline_identity",
        "media_chess_ref",
        "analysis_chess_ref",
        "timeline_invalidated_reason",
        "revision",
    }:
        raise MediaContractError(
            "media session payload fields are invalid",
            code=MediaErrorCode.INVALID_SCHEMA,
        )
    clock_data = data["clock"]
    if type(clock_data) is not dict or set(clock_data) != {
        "position_ms",
        "state",
        "playback_rate",
        "duration_ms",
        "revision",
    }:
        raise MediaContractError(
            "media session clock payload is invalid",
            code=MediaErrorCode.INVALID_SCHEMA,
        )
    return MediaSession(
        session_id=data["session_id"],
        source_id=data["source_id"],
        source_kind=data["source_kind"],
        source_revision=data["source_revision"],
        source_ref=data["source_ref"],
        clock=MediaClockSnapshot(
            position_ms=clock_data["position_ms"],
            state=clock_data["state"],
            playback_rate=clock_data["playback_rate"],
            duration_ms=clock_data["duration_ms"],
            revision=clock_data["revision"],
        ),
        timeline_identity=_timeline_identity_from_dict(data["timeline_identity"]),
        media_chess_ref=data["media_chess_ref"],
        analysis_chess_ref=data["analysis_chess_ref"],
        timeline_invalidated_reason=data["timeline_invalidated_reason"],
        revision=data["revision"],
    )


def serialize_media_state(
    source: MediaSource,
    timeline: MediaPositionTimeline,
    session: MediaChessSession,
) -> str:
    """Serialize a bounded, versioned media state snapshot."""

    if type(source) is not MediaSource:
        raise MediaContractError(
            "source must be a MediaSource",
            code=MediaErrorCode.INVALID_CONTAINER,
        )
    if type(timeline) is not MediaPositionTimeline:
        raise MediaContractError(
            "timeline must be a MediaPositionTimeline",
            code=MediaErrorCode.INVALID_CONTAINER,
        )
    if type(session) is not MediaChessSession:
        raise MediaContractError(
            "session must be a MediaChessSession",
            code=MediaErrorCode.INVALID_CONTAINER,
        )
    if timeline.source_id != source.source_id or session.media_cursor.source_id != source.source_id:
        raise MediaContractError(
            "source, timeline and session IDs must match",
            code=MediaErrorCode.SOURCE_MISMATCH,
        )
    payload = {
        "schema": MEDIA_STATE_SCHEMA,
        "version": MEDIA_STATE_VERSION,
        "source": _source_to_dict(source),
        "timeline": timeline.to_dict(),
        "session": {
            "position_ms": session.media_cursor.position_ms,
            "chess_ref": session.chess_ref,
        },
    }
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        encoded_length = len(text.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise MediaContractError(
            "serialized media state contains invalid UTF-8 text",
            code=MediaErrorCode.INVALID_TEXT,
        ) from exc
    if encoded_length > MAX_MEDIA_STATE_BYTES:
        raise MediaContractError(
            "serialized media state exceeds the safety limit",
            code=MediaErrorCode.STATE_TOO_LARGE,
        )
    return text


def deserialize_media_state(
    text: str,
) -> tuple[MediaSource, MediaPositionTimeline, MediaChessSession]:
    """Load one bounded media snapshot and fail closed on malformed schema."""

    if type(text) is not str:
        raise MediaContractError(
            "media state must be text",
            code=MediaErrorCode.INVALID_TEXT,
        )
    try:
        encoded_length = len(text.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise MediaContractError(
            "media state must be valid UTF-8 text",
            code=MediaErrorCode.INVALID_TEXT,
        ) from exc
    if encoded_length > MAX_MEDIA_STATE_BYTES:
        raise MediaContractError(
            "media state exceeds the safety limit",
            code=MediaErrorCode.STATE_TOO_LARGE,
        )
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise MediaContractError(
            "media state is not valid JSON",
            code=MediaErrorCode.INVALID_SCHEMA,
        ) from exc
    if type(payload) is not dict:
        raise MediaContractError(
            "media state root must be an object",
            code=MediaErrorCode.INVALID_SCHEMA,
        )
    if payload.get("schema") != MEDIA_STATE_SCHEMA or payload.get("version") != MEDIA_STATE_VERSION:
        raise MediaContractError(
            "unsupported media state schema/version",
            code=MediaErrorCode.INVALID_SCHEMA,
        )

    source = _source_from_dict(payload.get("source"))
    timeline = MediaPositionTimeline.from_dict(payload.get("timeline"))
    raw_session = payload.get("session")
    if type(raw_session) is not dict:
        raise MediaContractError(
            "session must be an object",
            code=MediaErrorCode.INVALID_CONTAINER,
        )
    session = MediaChessSession(
        MediaCursor(source.source_id, raw_session.get("position_ms")),
        raw_session.get("chess_ref"),
    )
    if timeline.source_id != source.source_id:
        raise MediaContractError(
            "source and timeline IDs differ",
            code=MediaErrorCode.SOURCE_MISMATCH,
        )
    if source.duration_ms is not None and session.media_cursor.position_ms > source.duration_ms:
        raise MediaContractError(
            "saved media position exceeds source duration",
            code=MediaErrorCode.INVALID_TIMESTAMP,
        )
    return source, timeline, session
