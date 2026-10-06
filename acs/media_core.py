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

from bisect import bisect_right
from dataclasses import dataclass, replace
from enum import Enum
import json
import math
from typing import Any, Iterable


MEDIA_STATE_SCHEMA = "accessible-chess.media-state"
MEDIA_STATE_VERSION = 1
MAX_MEDIA_LINKS = 100_000
MAX_MEDIA_STATE_BYTES = 8 * 1024 * 1024


class MediaErrorCode(str, Enum):
    INVALID_TEXT = "invalid_text"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_DURATION = "invalid_duration"
    INVALID_CONFIDENCE = "invalid_confidence"
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


@dataclass(frozen=True, slots=True)
class MediaClockSnapshot:
    """Immutable playback-clock observation at one monotonic host time."""

    position_ms: int
    state: MediaPlaybackState
    playback_rate: float
    duration_ms: int | None
    revision: int


class MediaClock:
    """Deterministic provider-neutral media clock with explicit host time."""

    __slots__ = ("_position_ms", "_fractional_ms", "_last_now_ms", "_playback_rate", "_duration_ms", "_state", "_revision")

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
                raise MediaContractError(str(exc), code=MediaErrorCode.INVALID_DURATION) from exc
            if self._position_ms > duration:
                raise MediaContractError("position exceeds media duration", code=MediaErrorCode.INVALID_TIMESTAMP)
        else:
            duration = None
        try:
            normalized_state = MediaPlaybackState(state)
        except (TypeError, ValueError) as exc:
            raise MediaContractError(
                f"unsupported media playback state: {state!r}",
                code=MediaErrorCode.INVALID_CONTAINER,
            ) from exc
        self._playback_rate = self._require_rate(playback_rate)
        self._fractional_ms = 0.0
        self._duration_ms = duration
        self._state = normalized_state
        self._last_now_ms = 0
        self._revision = 0
        if duration is not None and self._position_ms == duration:
            self._state = MediaPlaybackState.ENDED

    @staticmethod
    def _require_now(now_ms: object) -> int:
        return _require_nonnegative_int(now_ms, "now_ms")

    @staticmethod
    def _require_rate(value: object) -> float:
        if type(value) not in (int, float) or isinstance(value, bool):
            raise MediaContractError("playback_rate must be a finite positive number", code=MediaErrorCode.INVALID_CONTAINER)
        rate = float(value)
        if not math.isfinite(rate) or rate <= 0.0:
            raise MediaContractError("playback_rate must be a finite positive number", code=MediaErrorCode.INVALID_CONTAINER)
        return rate

    def _materialize(self, now_ms: int) -> None:
        now = self._require_now(now_ms)
        if now < self._last_now_ms:
            raise MediaContractError("media clock time cannot move backwards", code=MediaErrorCode.INVALID_TIMESTAMP)
        elapsed = now - self._last_now_ms
        if self._state is MediaPlaybackState.PLAYING and elapsed:
            media_elapsed = elapsed * self._playback_rate + self._fractional_ms
            if not math.isfinite(media_elapsed):
                raise MediaContractError("media clock delta is not representable", code=MediaErrorCode.INVALID_TIMESTAMP)
            whole_elapsed = int(media_elapsed)
            self._fractional_ms = media_elapsed - whole_elapsed
            self._position_ms += whole_elapsed
            if self._duration_ms is not None and self._position_ms >= self._duration_ms:
                self._position_ms = self._duration_ms
                self._fractional_ms = 0.0
                if self._state is not MediaPlaybackState.ENDED:
                    self._state = MediaPlaybackState.ENDED
                    self._revision += 1
        self._last_now_ms = now

    def _snapshot(self) -> MediaClockSnapshot:
        return MediaClockSnapshot(self._position_ms, self._state, self._playback_rate, self._duration_ms, self._revision)

    @property
    def revision(self) -> int:
        return self._revision

    def snapshot(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
        return self._snapshot()

    def play(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
        if self._duration_ms is not None and self._position_ms >= self._duration_ms:
            if self._state is not MediaPlaybackState.ENDED:
                self._state = MediaPlaybackState.ENDED
                self._revision += 1
            return self._snapshot()
        if self._state is not MediaPlaybackState.PLAYING:
            self._state = MediaPlaybackState.PLAYING
            self._revision += 1
        return self._snapshot()

    def pause(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
        if self._state in (MediaPlaybackState.PLAYING, MediaPlaybackState.BUFFERING):
            self._state = MediaPlaybackState.PAUSED
            self._fractional_ms = 0.0
            self._revision += 1
        return self._snapshot()

    def buffer(self, now_ms: int) -> MediaClockSnapshot:
        self._materialize(now_ms)
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
            raise MediaContractError("media position exceeds source duration", code=MediaErrorCode.INVALID_TIMESTAMP)
        self._materialize(now_ms)
        self._position_ms = position
        self._fractional_ms = 0.0
        self._last_now_ms = self._require_now(now_ms)
        if self._duration_ms is not None and position == self._duration_ms:
            self._state = MediaPlaybackState.ENDED
        elif self._state is MediaPlaybackState.ENDED:
            self._state = MediaPlaybackState.PLAYING
        self._revision += 1
        return self._snapshot()

    def set_playback_rate(self, playback_rate: float, now_ms: int) -> MediaClockSnapshot:
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
    return value


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
    number = float(value)
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
        try:
            kind = MediaSourceKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise MediaContractError(
                f"unsupported media source kind: {self.kind!r}",
                code=MediaErrorCode.INVALID_CONTAINER,
            ) from exc
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
class MediaChessLink:
    """A timestamped recognition/reconciliation link to canonical chess state."""

    source_id: str
    timestamp_ms: int
    chess_ref: str
    status: MediaLinkStatus = MediaLinkStatus.CANDIDATE
    confidence: float = 0.0
    evidence: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _require_text(self.source_id, "source_id"))
        object.__setattr__(
            self,
            "timestamp_ms",
            _require_nonnegative_int(self.timestamp_ms, "timestamp_ms"),
        )
        object.__setattr__(self, "chess_ref", _require_text(self.chess_ref, "chess_ref"))
        try:
            status = MediaLinkStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise MediaContractError(
                f"unsupported media link status: {self.status!r}",
                code=MediaErrorCode.INVALID_CONTAINER,
            ) from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "confidence", _require_confidence(self.confidence))
        object.__setattr__(
            self, "evidence", _require_optional_text(self.evidence, "evidence")
        )

    @property
    def confirmed(self) -> bool:
        return self.status is MediaLinkStatus.CONFIRMED


@dataclass(frozen=True, slots=True)
class TimelineResolution:
    """Resolution of one media time without hiding uncertainty."""

    source_id: str
    requested_timestamp_ms: int
    anchor_timestamp_ms: int | None
    links: tuple[MediaChessLink, ...]
    chess_ref: str | None
    ambiguous: bool

    @property
    def resolved(self) -> bool:
        return self.chess_ref is not None and not self.ambiguous


class MediaPositionTimeline:
    """Deterministic, immutable timeline of media-to-chess links."""

    __slots__ = (
        "source_id",
        "_links",
        "_timestamps",
        "_links_by_timestamp",
        "_confirmed_timestamps_by_ref",
    )

    def __init__(
        self,
        source_id: str,
        links: Iterable[MediaChessLink] = (),
    ) -> None:
        self.source_id = _require_text(source_id, "source_id")
        materialized = tuple(links)
        if len(materialized) > MAX_MEDIA_LINKS:
            raise MediaContractError(
                f"media timeline exceeds {MAX_MEDIA_LINKS} links",
                code=MediaErrorCode.LINK_LIMIT,
            )
        seen: set[tuple[int, str]] = set()
        for link in materialized:
            if not isinstance(link, MediaChessLink):
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

        grouped: dict[int, list[MediaChessLink]] = {}
        confirmed_by_ref: dict[str, set[int]] = {}
        for link in self._links:
            grouped.setdefault(link.timestamp_ms, []).append(link)
            if link.confirmed:
                confirmed_by_ref.setdefault(link.chess_ref, set()).add(link.timestamp_ms)

        self._links_by_timestamp = {
            timestamp: tuple(group) for timestamp, group in grouped.items()
        }
        self._timestamps = tuple(self._links_by_timestamp)
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

    def links_at(self, timestamp_ms: int) -> tuple[MediaChessLink, ...]:
        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        return self._links_by_timestamp.get(timestamp, ())

    def resolve_exact(self, timestamp_ms: int) -> TimelineResolution:
        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        return self._resolution(timestamp, timestamp, self.links_at(timestamp))

    def resolve_at_or_before(self, timestamp_ms: int) -> TimelineResolution:
        requested = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        index = bisect_right(self._timestamps, requested) - 1
        if index < 0:
            return TimelineResolution(
                self.source_id, requested, None, (), None, False
            )
        anchor = self._timestamps[index]
        return self._resolution(requested, anchor, self.links_at(anchor))

    def _resolution(
        self,
        requested: int,
        anchor: int,
        links: tuple[MediaChessLink, ...],
    ) -> TimelineResolution:
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
        return TimelineResolution(
            source_id=self.source_id,
            requested_timestamp_ms=requested,
            anchor_timestamp_ms=anchor,
            links=links,
            chess_ref=chess_ref,
            ambiguous=ambiguous,
        )

    def confirmed_timestamps_for(self, chess_ref: str) -> tuple[int, ...]:
        ref = _require_text(chess_ref, "chess_ref")
        return self._confirmed_timestamps_by_ref.get(ref, ())

    def with_link(self, link: MediaChessLink) -> "MediaPositionTimeline":
        return MediaPositionTimeline(self.source_id, (*self._links, link))

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
                        evidence=(
                            replacement_evidence
                            if replacement_evidence is not None
                            else link.evidence
                        ),
                    )
                )
                continue
            if link.confirmed and replace_confirmed:
                reconciled.append(replace(link, status=MediaLinkStatus.CANDIDATE))
                continue
            reconciled.append(link)
        return MediaPositionTimeline(self.source_id, reconciled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "links": [
                {
                    "timestamp_ms": link.timestamp_ms,
                    "chess_ref": link.chess_ref,
                    "status": link.status.value,
                    "confidence": link.confidence,
                    "evidence": link.evidence,
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
            links.append(
                MediaChessLink(
                    source_id=source_id,
                    timestamp_ms=raw_link.get("timestamp_ms"),
                    chess_ref=raw_link.get("chess_ref"),
                    status=raw_link.get("status", MediaLinkStatus.CANDIDATE.value),
                    confidence=raw_link.get("confidence", 0.0),
                    evidence=raw_link.get("evidence"),
                )
            )
        return cls(source_id, links)


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
class MediaChessSession:
    """Separate media/chess cursors; synchronization is always explicit."""

    media_cursor: MediaCursor
    chess_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.media_cursor, MediaCursor):
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
        if not isinstance(timeline, MediaPositionTimeline):
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


def serialize_media_state(
    source: MediaSource,
    timeline: MediaPositionTimeline,
    session: MediaChessSession,
) -> str:
    """Serialize a bounded, versioned media state snapshot."""

    if not isinstance(source, MediaSource):
        raise MediaContractError(
            "source must be a MediaSource",
            code=MediaErrorCode.INVALID_CONTAINER,
        )
    if not isinstance(timeline, MediaPositionTimeline):
        raise MediaContractError(
            "timeline must be a MediaPositionTimeline",
            code=MediaErrorCode.INVALID_CONTAINER,
        )
    if not isinstance(session, MediaChessSession):
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
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text.encode("utf-8")) > MAX_MEDIA_STATE_BYTES:
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
    if len(text.encode("utf-8")) > MAX_MEDIA_STATE_BYTES:
        raise MediaContractError(
            "media state exceeds the safety limit",
            code=MediaErrorCode.STATE_TOO_LARGE,
        )
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
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
