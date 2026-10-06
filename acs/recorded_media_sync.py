from __future__ import annotations

"""Recorded-media synchronization over the canonical Media Core.

This module never parses FEN/SAN/UCI/PGN and never decides chess legality.
Board/speech observations are evidence only. An injected application port may
map qualified evidence to an opaque canonical chess_ref, after which this layer
stores only the existing Media Core link/timeline/session types.
"""

from dataclasses import dataclass
from enum import Enum
import json
from typing import Protocol, runtime_checkable

from .media_core import (
    MAX_MEDIA_STATE_BYTES,
    MediaChessLink,
    MediaChessSession,
    MediaContractError,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaReconciliationState,
    MediaTimelineBarrier,
    MediaSource,
    MediaSourceKind,
    TimelineResolution,
    deserialize_media_state,
    serialize_media_state,
)
from .media_preprocess import (
    BoardFrameEvidence,
    FrameDisposition,
    RecordedMediaPreprocessPlan,
    SpeechEvidence,
)


RECORDED_SYNC_SCHEMA = "accessible-chess.recorded-media-sync"
RECORDED_SYNC_VERSION = 1
MAX_SPEECH_CONTEXT = 256
MAX_RECORDED_SYNC_STATE_BYTES = MAX_MEDIA_STATE_BYTES + 256 * 1024


class RecordedSyncErrorCode(str, Enum):
    INVALID = "invalid"
    SOURCE_MISMATCH = "source_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    CANONICAL_REJECTED = "canonical_rejected"
    INVALID_CANONICAL_RESULT = "invalid_canonical_result"
    UNSAFE_CONFIRMATION = "unsafe_confirmation"
    REPLAY_CONFLICT = "replay_conflict"
    STATE_MISMATCH = "state_mismatch"
    INVALID_SCHEMA = "invalid_schema"
    STATE_TOO_LARGE = "state_too_large"


class RecordedSyncContractError(ValueError):
    def __init__(self, message: str, *, code: RecordedSyncErrorCode) -> None:
        super().__init__(message)
        self.code = RecordedSyncErrorCode(code)


class RecordedSyncStepKind(str, Enum):
    LINKED = "linked"
    NO_CHANGE = "no_change"
    NO_LINK = "no_link"
    SKIPPED = "skipped"


def _exact_text(value: object, name: str, *, max_length: int = 4096) -> str:
    if type(value) is not str or not value.strip() or len(value) > max_length:
        raise RecordedSyncContractError(
            f"invalid {name}", code=RecordedSyncErrorCode.INVALID
        )
    if "\x00" in value or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise RecordedSyncContractError(
            f"unsafe {name}", code=RecordedSyncErrorCode.INVALID
        )
    return value


@dataclass(frozen=True, slots=True)
class AccessibleRecordedSyncEvent:
    """One text value shared by visible/copyable UI and screen-reader output."""

    visible_text: str
    announcement_text: str

    def __post_init__(self) -> None:
        visible = _exact_text(self.visible_text, "visible_text", max_length=1024)
        announcement = _exact_text(
            self.announcement_text, "announcement_text", max_length=1024
        )
        if visible != announcement:
            raise RecordedSyncContractError(
                "recorded sync event must remain announcement-equivalent",
                code=RecordedSyncErrorCode.INVALID,
            )


@dataclass(frozen=True, slots=True)
class RecordedSyncStep:
    kind: RecordedSyncStepKind
    timestamp_ms: int
    link: MediaChessLink | None
    event: AccessibleRecordedSyncEvent

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "kind", RecordedSyncStepKind(self.kind))
        except (TypeError, ValueError) as exc:
            raise RecordedSyncContractError(
                "invalid recorded sync step kind",
                code=RecordedSyncErrorCode.INVALID,
            ) from exc
        if type(self.timestamp_ms) is not int or self.timestamp_ms < 0:
            raise RecordedSyncContractError(
                "invalid recorded sync timestamp",
                code=RecordedSyncErrorCode.INVALID,
            )
        if self.link is not None and type(self.link) is not MediaChessLink:
            raise RecordedSyncContractError(
                "invalid recorded sync link",
                code=RecordedSyncErrorCode.INVALID,
            )
        if type(self.event) is not AccessibleRecordedSyncEvent:
            raise RecordedSyncContractError(
                "invalid recorded sync event",
                code=RecordedSyncErrorCode.INVALID,
            )


@runtime_checkable
class CanonicalRecordedFramePort(Protocol):
    """Canonical application seam used to resolve recorded evidence.

    Implementations may consult the existing Board/GameTree/application services.
    This module intentionally does not know how a chess_ref is created.
    """

    def resolve_recorded_frame(
        self,
        *,
        frame: BoardFrameEvidence,
        speech_context: tuple[SpeechEvidence, ...],
    ) -> MediaChessLink | None: ...


def _event(text: str) -> AccessibleRecordedSyncEvent:
    return AccessibleRecordedSyncEvent(text, text)


class RecordedMediaTimelineBuilder:
    """Build a Media Core timeline without owning chess semantics."""

    def __init__(
        self,
        plan: RecordedMediaPreprocessPlan,
        canonical: CanonicalRecordedFramePort,
        *,
        timeline: MediaPositionTimeline | None = None,
    ) -> None:
        if type(plan) is not RecordedMediaPreprocessPlan:
            raise RecordedSyncContractError(
                "plan must be an exact RecordedMediaPreprocessPlan",
                code=RecordedSyncErrorCode.INVALID,
            )
        resolver = getattr(canonical, "resolve_recorded_frame", None)
        if not callable(resolver):
            raise RecordedSyncContractError(
                "canonical recorded-frame port is required",
                code=RecordedSyncErrorCode.INVALID,
            )
        if timeline is None:
            timeline = MediaPositionTimeline(plan.source.source_id)
        if type(timeline) is not MediaPositionTimeline:
            raise RecordedSyncContractError(
                "timeline must be an exact MediaPositionTimeline",
                code=RecordedSyncErrorCode.INVALID,
            )
        if timeline.source_id != plan.source.source_id:
            raise RecordedSyncContractError(
                "timeline and recorded source IDs differ",
                code=RecordedSyncErrorCode.SOURCE_MISMATCH,
            )
        self.plan = plan
        self.canonical = canonical
        self.timeline = timeline

    def _validate_frame(self, frame: BoardFrameEvidence) -> None:
        if type(frame) is not BoardFrameEvidence:
            raise RecordedSyncContractError(
                "frame must be an exact BoardFrameEvidence",
                code=RecordedSyncErrorCode.INVALID,
            )
        if frame.source_id != self.plan.source.source_id:
            raise RecordedSyncContractError(
                "frame belongs to a different recorded source",
                code=RecordedSyncErrorCode.SOURCE_MISMATCH,
            )
        if frame.source_revision != self.plan.source.source_revision:
            raise RecordedSyncContractError(
                "frame belongs to a stale recorded source revision",
                code=RecordedSyncErrorCode.REVISION_MISMATCH,
            )
        if frame.timestamp_ms > self.plan.source.duration_ms:
            raise RecordedSyncContractError(
                "frame timestamp exceeds recorded source duration",
                code=RecordedSyncErrorCode.INVALID,
            )

    def _validate_speech(
        self, speech_context: tuple[SpeechEvidence, ...]
    ) -> tuple[SpeechEvidence, ...]:
        if type(speech_context) is not tuple:
            raise RecordedSyncContractError(
                "speech context must be an exact tuple",
                code=RecordedSyncErrorCode.INVALID,
            )
        if len(speech_context) > MAX_SPEECH_CONTEXT:
            raise RecordedSyncContractError(
                "speech context exceeds the per-frame limit",
                code=RecordedSyncErrorCode.INVALID,
            )
        for item in speech_context:
            if type(item) is not SpeechEvidence:
                raise RecordedSyncContractError(
                    "speech context contains an invalid item",
                    code=RecordedSyncErrorCode.INVALID,
                )
            if item.source_id != self.plan.source.source_id:
                raise RecordedSyncContractError(
                    "speech context belongs to a different recorded source",
                    code=RecordedSyncErrorCode.SOURCE_MISMATCH,
                )
            if item.source_revision != self.plan.source.source_revision:
                raise RecordedSyncContractError(
                    "speech context belongs to a stale recorded source revision",
                    code=RecordedSyncErrorCode.REVISION_MISMATCH,
                )
            if item.end_ms > self.plan.source.duration_ms:
                raise RecordedSyncContractError(
                    "speech context exceeds recorded source duration",
                    code=RecordedSyncErrorCode.INVALID,
                )
        return speech_context

    def _record_barrier(
        self,
        frame: BoardFrameEvidence,
        *,
        state: MediaReconciliationState,
        reason: str,
    ) -> None:
        barrier = MediaTimelineBarrier(
            source_id=self.plan.source.source_id,
            timestamp_ms=frame.timestamp_ms,
            state=state,
            evidence_ids=(
                frame.observation_ref,
            ) if frame.observation_ref is not None else (),
            reason=reason,
        )
        existing = self.timeline.barrier_at(frame.timestamp_ms)
        if existing == barrier:
            return
        if existing is not None:
            self.timeline = MediaPositionTimeline(
                self.timeline.source_id,
                self.timeline.links,
                identity=self.timeline.identity,
                barriers=tuple(
                    item
                    for item in self.timeline.barriers
                    if item.timestamp_ms != frame.timestamp_ms
                ),
            )
        self.timeline = self.timeline.with_barrier(barrier)

    def _without_barrier_at(self, timestamp_ms: int) -> MediaPositionTimeline:
        if self.timeline.barrier_at(timestamp_ms) is None:
            return self.timeline
        return MediaPositionTimeline(
            self.timeline.source_id,
            self.timeline.links,
            identity=self.timeline.identity,
            barriers=tuple(
                item
                for item in self.timeline.barriers
                if item.timestamp_ms != timestamp_ms
            ),
        )

    def accept(
        self,
        frame: BoardFrameEvidence,
        *,
        speech_context: tuple[SpeechEvidence, ...] = (),
    ) -> RecordedSyncStep:
        self._validate_frame(frame)
        context = self._validate_speech(speech_context)

        if frame.disposition is FrameDisposition.TRANSITION:
            self._record_barrier(
                frame,
                state=MediaReconciliationState.RESYNC_REQUIRED,
                reason="recorded media frame is a transition",
            )
            return RecordedSyncStep(
                RecordedSyncStepKind.SKIPPED,
                frame.timestamp_ms,
                None,
                _event(
                    "Recorded media frame is a transition; synchronization was skipped."
                ),
            )
        if frame.disposition is FrameDisposition.OCCLUDED:
            self._record_barrier(
                frame,
                state=MediaReconciliationState.RESYNC_REQUIRED,
                reason="recorded media board is occluded",
            )
            return RecordedSyncStep(
                RecordedSyncStepKind.SKIPPED,
                frame.timestamp_ms,
                None,
                _event(
                    "Recorded media board is occluded; synchronization was skipped."
                ),
            )

        try:
            link = self.canonical.resolve_recorded_frame(
                frame=frame,
                speech_context=context,
            )
        except Exception:
            raise RecordedSyncContractError(
                "canonical chess application rejected recorded-media evidence",
                code=RecordedSyncErrorCode.CANONICAL_REJECTED,
            ) from None

        if link is None:
            if frame.disposition is FrameDisposition.AMBIGUOUS:
                self._record_barrier(
                    frame,
                    state=MediaReconciliationState.AMBIGUOUS,
                    reason="recorded media frame remains ambiguous",
                )
                text = (
                    "Recorded media frame is ambiguous; canonical position was not changed."
                )
            else:
                self._record_barrier(
                    frame,
                    state=MediaReconciliationState.OBSERVED,
                    reason="recorded media frame has no accepted canonical position",
                )
                text = (
                    "No canonical chess position was accepted for this recorded frame."
                )
            return RecordedSyncStep(
                RecordedSyncStepKind.NO_LINK,
                frame.timestamp_ms,
                None,
                _event(text),
            )

        if type(link) is not MediaChessLink:
            raise RecordedSyncContractError(
                "canonical recorded-frame port returned an invalid link",
                code=RecordedSyncErrorCode.INVALID_CANONICAL_RESULT,
            )
        if link.source_id != self.plan.source.source_id:
            raise RecordedSyncContractError(
                "canonical link belongs to a different media source",
                code=RecordedSyncErrorCode.SOURCE_MISMATCH,
            )
        if link.timestamp_ms != frame.timestamp_ms:
            raise RecordedSyncContractError(
                "canonical link timestamp does not match the observed frame",
                code=RecordedSyncErrorCode.INVALID_CANONICAL_RESULT,
            )
        if frame.disposition is FrameDisposition.AMBIGUOUS and link.confirmed:
            raise RecordedSyncContractError(
                "ambiguous visual evidence cannot publish a confirmed chess link",
                code=RecordedSyncErrorCode.UNSAFE_CONFIRMATION,
            )

        clean_timeline = self._without_barrier_at(frame.timestamp_ms)
        same_key = tuple(
            item
            for item in clean_timeline.links_at(frame.timestamp_ms)
            if item.chess_ref == link.chess_ref
        )
        if same_key:
            existing = same_key[0]
            if existing != link:
                raise RecordedSyncContractError(
                    "replayed frame conflicts with the existing media/chess link",
                    code=RecordedSyncErrorCode.REPLAY_CONFLICT,
                )
            return RecordedSyncStep(
                RecordedSyncStepKind.NO_CHANGE,
                frame.timestamp_ms,
                existing,
                _event("Recorded media evidence was already synchronized."),
            )

        try:
            self.timeline = clean_timeline.with_link(link)
        except MediaContractError as exc:
            raise RecordedSyncContractError(
                "canonical Media Core rejected the recorded-media link",
                code=RecordedSyncErrorCode.INVALID_CANONICAL_RESULT,
            ) from exc

        text = (
            "Recorded media position was canonically confirmed."
            if link.status is MediaLinkStatus.CONFIRMED
            else "Recorded media position candidate recorded; confirmation is required."
        )
        return RecordedSyncStep(
            RecordedSyncStepKind.LINKED,
            frame.timestamp_ms,
            link,
            _event(text),
        )


@dataclass(frozen=True, slots=True)
class RecordedPlaybackResolution:
    session: MediaChessSession
    resolution: TimelineResolution
    event: AccessibleRecordedSyncEvent

    def __post_init__(self) -> None:
        if type(self.session) is not MediaChessSession:
            raise RecordedSyncContractError(
                "invalid recorded playback session",
                code=RecordedSyncErrorCode.INVALID,
            )
        if type(self.resolution) is not TimelineResolution:
            raise RecordedSyncContractError(
                "invalid recorded playback resolution",
                code=RecordedSyncErrorCode.INVALID,
            )
        if type(self.event) is not AccessibleRecordedSyncEvent:
            raise RecordedSyncContractError(
                "invalid recorded playback event",
                code=RecordedSyncErrorCode.INVALID,
            )


def seek_recorded_media(
    session: MediaChessSession,
    timeline: MediaPositionTimeline,
    position_ms: int,
    *,
    duration_ms: int | None = None,
) -> RecordedPlaybackResolution:
    """Seek the media cursor and resolve, but do not mutate the application board."""

    if type(session) is not MediaChessSession or type(timeline) is not MediaPositionTimeline:
        raise RecordedSyncContractError(
            "recorded playback requires exact Media Core session/timeline values",
            code=RecordedSyncErrorCode.INVALID,
        )
    try:
        sought = session.seek_media(position_ms, duration_ms=duration_ms)
        synchronized, resolution = sought.sync_chess_from_media(timeline)
    except MediaContractError as exc:
        raise RecordedSyncContractError(
            str(exc), code=RecordedSyncErrorCode.INVALID
        ) from exc

    if resolution.resolved:
        text = "Recorded media position is synchronized to canonical chess state."
    elif resolution.ambiguous:
        text = (
            "Recorded media position is ambiguous; the chess cursor was not changed."
        )
    elif resolution.anchor_timestamp_ms is None:
        text = "No qualified recorded media position is available at this time."
    else:
        text = (
            "Recorded media position is not yet confirmed; the chess cursor was not changed."
        )
    return RecordedPlaybackResolution(synchronized, resolution, _event(text))


@dataclass(frozen=True, slots=True)
class RecordedSyncSnapshot:
    source_revision: str
    cache_fingerprint: str
    plan_digest: str
    source: MediaSource
    timeline: MediaPositionTimeline
    session: MediaChessSession

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_revision",
            _exact_text(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "cache_fingerprint",
            _exact_text(self.cache_fingerprint, "cache_fingerprint"),
        )
        object.__setattr__(
            self,
            "plan_digest",
            _exact_text(self.plan_digest, "plan_digest"),
        )
        if type(self.source) is not MediaSource:
            raise RecordedSyncContractError(
                "snapshot source is invalid", code=RecordedSyncErrorCode.INVALID
            )
        if type(self.timeline) is not MediaPositionTimeline:
            raise RecordedSyncContractError(
                "snapshot timeline is invalid", code=RecordedSyncErrorCode.INVALID
            )
        if type(self.session) is not MediaChessSession:
            raise RecordedSyncContractError(
                "snapshot session is invalid", code=RecordedSyncErrorCode.INVALID
            )


def serialize_recorded_sync_state(
    plan: RecordedMediaPreprocessPlan,
    *,
    title: str,
    timeline: MediaPositionTimeline,
    session: MediaChessSession,
) -> str:
    """Persist revision identity around the canonical Media Core state payload."""

    if type(plan) is not RecordedMediaPreprocessPlan:
        raise RecordedSyncContractError(
            "plan must be an exact RecordedMediaPreprocessPlan",
            code=RecordedSyncErrorCode.INVALID,
        )
    if type(timeline) is not MediaPositionTimeline or type(session) is not MediaChessSession:
        raise RecordedSyncContractError(
            "timeline/session must be exact Media Core values",
            code=RecordedSyncErrorCode.INVALID,
        )
    if (
        timeline.source_id != plan.source.source_id
        or session.media_cursor.source_id != plan.source.source_id
    ):
        raise RecordedSyncContractError(
            "recorded plan, timeline and session source IDs differ",
            code=RecordedSyncErrorCode.SOURCE_MISMATCH,
        )

    source = MediaSource(
        source_id=plan.source.source_id,
        title=_exact_text(title, "title"),
        kind=MediaSourceKind.LOCAL_FILE,
        source_ref=plan.source.source_ref,
        duration_ms=plan.source.duration_ms,
    )
    try:
        media_state = serialize_media_state(source, timeline, session)
    except MediaContractError as exc:
        raise RecordedSyncContractError(
            "canonical Media Core refused recorded state persistence",
            code=RecordedSyncErrorCode.INVALID,
        ) from exc

    payload = {
        "schema": RECORDED_SYNC_SCHEMA,
        "version": RECORDED_SYNC_VERSION,
        "source_revision": plan.source.source_revision,
        "cache_fingerprint": plan.cache_key.fingerprint(),
        "plan_digest": plan.digest(),
        "media_state": media_state,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text.encode("utf-8")) > MAX_RECORDED_SYNC_STATE_BYTES:
        raise RecordedSyncContractError(
            "recorded sync state exceeds the safety limit",
            code=RecordedSyncErrorCode.STATE_TOO_LARGE,
        )
    return text


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RecordedSyncContractError(
                "recorded sync state contains duplicate JSON keys",
                code=RecordedSyncErrorCode.INVALID_SCHEMA,
            )
        result[key] = value
    return result


def deserialize_recorded_sync_state(
    text: str,
    *,
    expected_plan: RecordedMediaPreprocessPlan | None = None,
) -> RecordedSyncSnapshot:
    if type(text) is not str:
        raise RecordedSyncContractError(
            "recorded sync state must be text",
            code=RecordedSyncErrorCode.INVALID_SCHEMA,
        )
    if len(text.encode("utf-8")) > MAX_RECORDED_SYNC_STATE_BYTES:
        raise RecordedSyncContractError(
            "recorded sync state exceeds the safety limit",
            code=RecordedSyncErrorCode.STATE_TOO_LARGE,
        )
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except RecordedSyncContractError:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise RecordedSyncContractError(
            "recorded sync state is malformed JSON",
            code=RecordedSyncErrorCode.INVALID_SCHEMA,
        ) from exc

    required = {
        "schema",
        "version",
        "source_revision",
        "cache_fingerprint",
        "plan_digest",
        "media_state",
    }
    if (
        type(payload) is not dict
        or set(payload) != required
        or payload.get("schema") != RECORDED_SYNC_SCHEMA
        or payload.get("version") != RECORDED_SYNC_VERSION
    ):
        raise RecordedSyncContractError(
            "recorded sync state schema/version is unsupported",
            code=RecordedSyncErrorCode.INVALID_SCHEMA,
        )

    source_revision = _exact_text(payload["source_revision"], "source_revision")
    cache_fingerprint = _exact_text(
        payload["cache_fingerprint"], "cache_fingerprint"
    )
    plan_digest = _exact_text(payload["plan_digest"], "plan_digest")
    media_state = payload["media_state"]
    if type(media_state) is not str:
        raise RecordedSyncContractError(
            "recorded sync media_state must be text",
            code=RecordedSyncErrorCode.INVALID_SCHEMA,
        )

    try:
        source, timeline, session = deserialize_media_state(media_state)
    except MediaContractError as exc:
        raise RecordedSyncContractError(
            "canonical Media Core rejected saved recorded state",
            code=RecordedSyncErrorCode.INVALID_SCHEMA,
        ) from exc

    snapshot = RecordedSyncSnapshot(
        source_revision,
        cache_fingerprint,
        plan_digest,
        source,
        timeline,
        session,
    )
    if expected_plan is not None:
        if type(expected_plan) is not RecordedMediaPreprocessPlan:
            raise RecordedSyncContractError(
                "expected_plan must be an exact RecordedMediaPreprocessPlan",
                code=RecordedSyncErrorCode.INVALID,
            )
        expected = (
            expected_plan.source.source_id,
            expected_plan.source.source_revision,
            expected_plan.source.source_ref,
            expected_plan.source.duration_ms,
            expected_plan.cache_key.fingerprint(),
            expected_plan.digest(),
        )
        actual = (
            source.source_id,
            snapshot.source_revision,
            source.source_ref,
            source.duration_ms,
            snapshot.cache_fingerprint,
            snapshot.plan_digest,
        )
        if actual != expected:
            raise RecordedSyncContractError(
                "saved recorded timeline no longer matches preprocessing authority",
                code=RecordedSyncErrorCode.STATE_MISMATCH,
            )
    return snapshot
