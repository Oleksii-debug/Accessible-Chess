from __future__ import annotations

"""Application service for media-synchronized canonical positions.

This service owns media/analysis cursor separation and delegates actual board
publication to an injected canonical application callback. It never constructs
or validates chess positions itself.
"""

from collections.abc import Callable
from dataclasses import replace

from .keyed_async_lock import KeyedAsyncLock
from .media_core import MediaPositionTimeline, MediaSession, TimelineEntry


PositionPublisher = Callable[[str], object]


class MediaApplicationService:
    def __init__(
        self,
        session: MediaSession,
        timeline: MediaPositionTimeline,
        *,
        publish_position: PositionPublisher,
    ) -> None:
        if not isinstance(session, MediaSession):
            raise TypeError("session must be MediaSession")
        if not isinstance(timeline, MediaPositionTimeline):
            raise TypeError("timeline must be MediaPositionTimeline")
        if not callable(publish_position):
            raise TypeError("publish_position must be callable")
        self._session = session
        self._timeline = timeline
        self._publish_position = publish_position
        self._analysis_detached = False
        self._media_entry: TimelineEntry | None = timeline.at(session.current_ms)
        self._lock = KeyedAsyncLock()

    @property
    def session(self) -> MediaSession:
        return self._session

    @property
    def analysis_detached(self) -> bool:
        return self._analysis_detached

    @property
    def media_entry(self) -> TimelineEntry | None:
        return self._media_entry

    def status(self) -> dict[str, object]:
        entry = self._media_entry
        return {
            "session_id": self._session.session_id,
            "playback_state": self._session.state.value,
            "current_ms": self._session.current_ms,
            "analysis_detached": self._analysis_detached,
            "position_id": None if entry is None else entry.position_id,
            "gametree_node_id": None if entry is None else entry.gametree_node_id,
            "reconciliation_status": (
                "unavailable" if entry is None else entry.qualification.value
            ),
        }

    async def seek(self, timestamp_ms: int, *, publish: bool = True) -> TimelineEntry | None:
        if type(timestamp_ms) is not int or timestamp_ms < 0:
            raise ValueError("timestamp_ms must be a non-negative integer")

        async def operation() -> TimelineEntry | None:
            entry = self._timeline.at(timestamp_ms)
            self._session = replace(
                self._session,
                current_ms=timestamp_ms,
                revision=self._session.revision + 1,
            )
            self._media_entry = entry
            self._analysis_detached = False
            if publish and entry is not None:
                self._publish_position(entry.position_id)
            return entry

        return await self._lock.run(self._session.session_id, operation)

    def detach_for_analysis(self) -> None:
        self._analysis_detached = True

    async def restore_media_position(self) -> TimelineEntry:
        async def operation() -> TimelineEntry:
            entry = self._timeline.at(self._session.current_ms)
            if entry is None:
                raise RuntimeError("no qualified media position at current timestamp")
            self._publish_position(entry.position_id)
            self._media_entry = entry
            self._analysis_detached = False
            return entry

        return await self._lock.run(self._session.session_id, operation)

    async def previous_media_position(self) -> TimelineEntry | None:
        entry = self._timeline.previous(self._session.current_ms)
        if entry is None:
            return None
        return await self.seek(entry.start_ms)

    async def next_media_position(self) -> TimelineEntry | None:
        entry = self._timeline.next(self._session.current_ms)
        if entry is None:
            return None
        return await self.seek(entry.start_ms)


__all__ = ["MediaApplicationService", "PositionPublisher"]
