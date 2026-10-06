from __future__ import annotations

"""Application boundary for canonical Media Core synchronization.

This module deliberately owns no chess rules, FEN parsing, PGN parsing, or
GameTree structure. Media Core supplies an opaque canonical chess reference;
a caller-provided application command remains the sole authority that can
restore that reference into the chess product.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .media_core import (
    MediaChessSession,
    MediaPositionTimeline,
    MediaSource,
    TimelineResolution,
)


class MediaApplicationCode(str, Enum):
    SOURCE_MISMATCH = "source_mismatch"
    INVALID_STATE = "invalid_state"
    NO_CONFIRMED_POSITION = "no_confirmed_position"
    AMBIGUOUS_POSITION = "ambiguous_position"
    NO_NEXT_POSITION = "no_next_position"
    NO_PREVIOUS_POSITION = "no_previous_position"


class MediaApplicationError(ValueError):
    def __init__(self, message: str, *, code: MediaApplicationCode) -> None:
        super().__init__(message)
        self.code = MediaApplicationCode(code)


@dataclass(frozen=True, slots=True)
class MediaApplicationSnapshot:
    source_id: str
    revision: int
    position_ms: int
    duration_ms: int | None
    analysis_chess_ref: str | None
    synchronized_chess_ref: str | None
    anchor_timestamp_ms: int | None
    qualification: str
    can_restore: bool
    status_text: str


@dataclass(frozen=True, slots=True)
class MediaNavigationTarget:
    source_id: str
    revision: int
    from_position_ms: int
    target_position_ms: int
    chess_ref: str
    direction: str
    accessible_text: str


@dataclass(frozen=True, slots=True)
class RestoreMediaPositionResult:
    source_id: str
    revision: int
    position_ms: int
    anchor_timestamp_ms: int
    previous_chess_ref: str | None
    chess_ref: str
    changed: bool
    accessible_text: str


class MediaApplicationService:
    """Keep media and analysis cursors separate until an explicit command."""

    def __init__(
        self,
        *,
        source: MediaSource,
        timeline: MediaPositionTimeline,
        session: MediaChessSession,
        restore_chess_ref: Callable[[str], object],
    ) -> None:
        if type(source) is not MediaSource:
            raise TypeError("source must be MediaSource")
        if type(timeline) is not MediaPositionTimeline:
            raise TypeError("timeline must be MediaPositionTimeline")
        if type(session) is not MediaChessSession:
            raise TypeError("session must be MediaChessSession")
        if not callable(restore_chess_ref):
            raise TypeError("restore_chess_ref must be callable")
        if (
            timeline.source_id != source.source_id
            or session.media_cursor.source_id != source.source_id
        ):
            raise MediaApplicationError(
                "source, timeline and session IDs must match",
                code=MediaApplicationCode.SOURCE_MISMATCH,
            )
        if (
            source.duration_ms is not None
            and session.media_cursor.position_ms > source.duration_ms
        ):
            raise MediaApplicationError(
                "media cursor exceeds source duration",
                code=MediaApplicationCode.INVALID_STATE,
            )
        self._source = source
        self._timeline = timeline
        self._session = session
        self._restore_chess_ref = restore_chess_ref
        self._revision = 0
        self._restore_in_progress = False

    @property
    def source(self) -> MediaSource:
        return self._source

    @property
    def timeline(self) -> MediaPositionTimeline:
        return self._timeline

    @property
    def session(self) -> MediaChessSession:
        return self._session

    @property
    def revision(self) -> int:
        return self._revision

    def _resolution(
        self, session: MediaChessSession | None = None
    ) -> TimelineResolution:
        selected = self._session if session is None else session
        return self._timeline.resolve_at_or_before(
            selected.media_cursor.position_ms
        )

    @staticmethod
    def _qualification(resolution: TimelineResolution) -> str:
        if resolution.anchor_timestamp_ms is None:
            return "unlinked"
        if resolution.ambiguous:
            return "ambiguous"
        if resolution.chess_ref is not None:
            return "confirmed"
        return "candidate"

    @staticmethod
    def _status_text(qualification: str, position_ms: int) -> str:
        if qualification == "confirmed":
            return (
                "A confirmed chess position is synchronized with media at "
                f"{position_ms} ms."
            )
        if qualification == "ambiguous":
            return (
                "The media position is ambiguous; no chess position will be "
                "restored."
            )
        if qualification == "candidate":
            return (
                "The media position has unconfirmed chess candidates; no chess "
                "position will be restored."
            )
        return "No chess position is synchronized with the current media time."

    def _snapshot_for(
        self, session: MediaChessSession
    ) -> MediaApplicationSnapshot:
        resolution = self._resolution(session)
        qualification = self._qualification(resolution)
        return MediaApplicationSnapshot(
            source_id=self._source.source_id,
            revision=self._revision,
            position_ms=session.media_cursor.position_ms,
            duration_ms=self._source.duration_ms,
            analysis_chess_ref=session.chess_ref,
            synchronized_chess_ref=resolution.chess_ref,
            anchor_timestamp_ms=resolution.anchor_timestamp_ms,
            qualification=qualification,
            can_restore=resolution.resolved,
            status_text=self._status_text(
                qualification, session.media_cursor.position_ms
            ),
        )

    def snapshot(self) -> MediaApplicationSnapshot:
        return self._snapshot_for(self._session)

    def snapshot_at(self, position_ms: int) -> MediaApplicationSnapshot:
        candidate = self._session.seek_media(
            position_ms,
            duration_ms=self._source.duration_ms,
        )
        return self._snapshot_for(candidate)

    def _require_mutation_available(self) -> None:
        if self._restore_in_progress:
            raise MediaApplicationError(
                "media application restore is already in progress",
                code=MediaApplicationCode.INVALID_STATE,
            )

    def seek_media(self, position_ms: int) -> MediaApplicationSnapshot:
        self._require_mutation_available()
        candidate = self._session.seek_media(
            position_ms,
            duration_ms=self._source.duration_ms,
        )
        if candidate != self._session:
            self._session = candidate
            self._revision += 1
        return self.snapshot()

    def select_analysis_chess_ref(
        self, chess_ref: str | None
    ) -> MediaApplicationSnapshot:
        self._require_mutation_available()
        candidate = self._session.select_chess(chess_ref)
        if candidate != self._session:
            self._session = candidate
            self._revision += 1
        return self.snapshot()

    def align_media_to_analysis(self) -> MediaApplicationSnapshot:
        self._require_mutation_available()
        candidate = self._session.sync_media_from_chess(self._timeline)
        if candidate != self._session:
            if (
                self._source.duration_ms is not None
                and candidate.media_cursor.position_ms > self._source.duration_ms
            ):
                raise MediaApplicationError(
                    "timeline target exceeds source duration",
                    code=MediaApplicationCode.INVALID_STATE,
                )
            self._session = candidate
            self._revision += 1
        return self.snapshot()

    def _media_navigation_target(
        self,
        position_ms: int,
        *,
        direction: str,
    ) -> MediaNavigationTarget:
        candidate = self._session.seek_media(
            position_ms,
            duration_ms=self._source.duration_ms,
        )
        current = candidate.media_cursor.position_ms
        if direction == "next":
            timestamps = (item for item in self._timeline.timestamps if item > current)
            missing_code = MediaApplicationCode.NO_NEXT_POSITION
            missing_message = "no later media chess position exists"
            label = "Next"
        elif direction == "previous":
            timestamps = (
                item for item in reversed(self._timeline.timestamps) if item < current
            )
            missing_code = MediaApplicationCode.NO_PREVIOUS_POSITION
            missing_message = "no earlier media chess position exists"
            label = "Previous"
        else:
            raise ValueError("unsupported media navigation direction")

        target = next(timestamps, None)
        if target is None:
            raise MediaApplicationError(missing_message, code=missing_code)
        if self._source.duration_ms is not None and target > self._source.duration_ms:
            raise MediaApplicationError(
                "timeline navigation target exceeds source duration",
                code=MediaApplicationCode.INVALID_STATE,
            )

        resolution = self._timeline.resolve_exact(target)
        if resolution.ambiguous:
            raise MediaApplicationError(
                "nearest media navigation target is ambiguous",
                code=MediaApplicationCode.AMBIGUOUS_POSITION,
            )
        if not resolution.resolved or resolution.chess_ref is None:
            raise MediaApplicationError(
                "nearest media navigation target is not confirmed",
                code=MediaApplicationCode.NO_CONFIRMED_POSITION,
            )

        return MediaNavigationTarget(
            source_id=self._source.source_id,
            revision=self._revision,
            from_position_ms=current,
            target_position_ms=target,
            chess_ref=resolution.chess_ref,
            direction=direction,
            accessible_text=(
                f"{label} confirmed media chess position is at {target} ms."
            ),
        )

    def next_media_position(self, position_ms: int) -> MediaNavigationTarget:
        """Resolve the nearest later timeline anchor without mutating cursors."""

        return self._media_navigation_target(position_ms, direction="next")

    def previous_media_position(self, position_ms: int) -> MediaNavigationTarget:
        """Resolve the nearest earlier timeline anchor without mutating cursors."""

        return self._media_navigation_target(position_ms, direction="previous")

    def restore_media_position(
        self, position_ms: int | None = None
    ) -> RestoreMediaPositionResult:
        self._require_mutation_available()
        working_session = self._session
        if position_ms is not None:
            working_session = working_session.seek_media(
                position_ms,
                duration_ms=self._source.duration_ms,
            )
        candidate, resolution = working_session.sync_chess_from_media(self._timeline)
        if resolution.ambiguous:
            raise MediaApplicationError(
                "media position has conflicting canonical chess references",
                code=MediaApplicationCode.AMBIGUOUS_POSITION,
            )
        if not resolution.resolved or resolution.chess_ref is None:
            raise MediaApplicationError(
                "media position has no confirmed canonical chess reference",
                code=MediaApplicationCode.NO_CONFIRMED_POSITION,
            )
        anchor = resolution.anchor_timestamp_ms
        if anchor is None:
            raise MediaApplicationError(
                "resolved media position has no anchor timestamp",
                code=MediaApplicationCode.INVALID_STATE,
            )

        previous = self._session.chess_ref
        chess_ref = resolution.chess_ref
        self._restore_in_progress = True
        try:
            self._restore_chess_ref(chess_ref)
        finally:
            self._restore_in_progress = False
        self._session = candidate
        self._revision += 1

        return RestoreMediaPositionResult(
            source_id=self._source.source_id,
            revision=self._revision,
            position_ms=self._session.media_cursor.position_ms,
            anchor_timestamp_ms=anchor,
            previous_chess_ref=previous,
            chess_ref=chess_ref,
            changed=previous != chess_ref,
            accessible_text=(
                "Restored the chess position synchronized with media at "
                f"{self._session.media_cursor.position_ms} ms."
            ),
        )
