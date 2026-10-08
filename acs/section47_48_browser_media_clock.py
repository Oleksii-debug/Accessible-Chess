from __future__ import annotations

"""Trust-boundary adapter for Section 47/48 browser media-clock observations.

Only canonical MediaClockSnapshot / MediaSession may own media state.
Never accepts a browser claim of verified chess, PGN, FEN, or Restore position.
It is not a provider decoder, chess parser, or second recognition authority.
"""

from dataclasses import dataclass
from typing import Mapping

from .media_core import (
    MediaClockSnapshot,
    MediaPlaybackState,
    MediaSession,
    MediaSourceKind,
    MediaPositionTimeline,
    MediaReconciliationState,
    TimelineResolution,
)

LOCAL_PROVIDER = "html5_local_file_v1"
YOUTUBE_PROVIDER = "youtube_iframe_v1"
MAX_POSITION_MS = 7 * 24 * 60 * 60 * 1000
_LOCAL_KEYS = frozenset({
    "providerId", "sourceId", "sourceKind", "sourceRevision", "ok", "ready",
    "playbackState", "positionMs", "durationMs", "playbackRate",
    "qualification", "chessRef",
})
_REMOTE_KEYS = frozenset({
    "providerId", "sourceId", "sourceKind", "videoId", "ok", "ready",
    "playbackState", "positionMs", "durationMs", "errorCode",
    "autoplayBlocked", "qualification", "chessRef",
})


class BrowserMediaClockError(ValueError):
    """Fail-closed ingress error; never echo untrusted private file paths."""


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise BrowserMediaClockError("invalid " + field)
    if any(ord(ch) < 32 for ch in value):
        raise BrowserMediaClockError("invalid " + field)
    return value


def _clock_ms(value: object, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or not 0 <= value <= MAX_POSITION_MS:
        raise BrowserMediaClockError("invalid " + field)
    return value


@dataclass(frozen=True, slots=True)
class BrowserSourceAuthority:
    """Source identity must be assigned and checked by the trusted host."""

    source_id: str
    source_revision: str
    session_id: str
    source_kind: MediaSourceKind
    browser_revision: int | None = None

    def __post_init__(self) -> None:
        for name in ("source_id", "source_revision", "session_id"):
            _text(getattr(self, name), name)
        if type(self.source_kind) is not MediaSourceKind:
            raise BrowserMediaClockError("source kind must be trusted MediaSourceKind")
        if self.source_kind is MediaSourceKind.LOCAL_FILE:
            if type(self.browser_revision) is not int or self.browser_revision < 1:
                raise BrowserMediaClockError("local source requires trusted browser revision")
        elif self.browser_revision is not None:
            raise BrowserMediaClockError("remote source must not carry local browser revision")


def accept_browser_clock(
    snapshot: Mapping[str, object],
    *,
    authority: BrowserSourceAuthority,
    previous: MediaSession | None = None,
) -> MediaSession:
    """Adapt a *non-authoritative* playback sample into canonical session types.

    A snapshot alone never creates MediaChessLink or a verified timeline.
    MediaSession remains unlinked until existing canonical position evidence
    explicitly qualifies it. Once linked, updates must go through existing
    authoritative application/reconciliation APIs instead of this helper.
    """
    if type(authority) is not BrowserSourceAuthority:
        raise BrowserMediaClockError("trusted source authority unavailable")
    if type(snapshot) is not dict:
        raise BrowserMediaClockError("media snapshot must be plain object")
    provider = snapshot.get("providerId")
    is_local = provider == LOCAL_PROVIDER
    if not is_local and provider != YOUTUBE_PROVIDER:
        raise BrowserMediaClockError("unsupported provider")
    expected = _LOCAL_KEYS if is_local else _REMOTE_KEYS
    if frozenset(snapshot) != expected:
        raise BrowserMediaClockError("media snapshot fields differ from recorded adapter")
    kind = MediaSourceKind.LOCAL_FILE if is_local else MediaSourceKind.PROVIDER
    if authority.source_kind is not kind:
        raise BrowserMediaClockError("source class mismatch")
    expected_browser_kind = "local_file" if is_local else "remote_media"
    if snapshot["sourceKind"] != expected_browser_kind:
        raise BrowserMediaClockError("browser source class mismatch")
    if snapshot["sourceId"] != authority.source_id:
        raise BrowserMediaClockError("source identity mismatch")
    if is_local:
        revision = snapshot["sourceRevision"]
        if type(revision) is not int or revision <= 0:
            raise BrowserMediaClockError("invalid local transient source revision")
        if revision != authority.browser_revision:
            raise BrowserMediaClockError("stale or foreign local browser revision")
    else:
        video_id = snapshot["videoId"]
        if type(video_id) is not str or len(video_id) != 11:
            raise BrowserMediaClockError("invalid YouTube video ID")
        if "youtube:" + video_id != authority.source_id:
            raise BrowserMediaClockError("provider ID does not match trusted source")
        if type(snapshot["errorCode"]) not in (int, type(None)):
            raise BrowserMediaClockError("invalid provider error code")
        if type(snapshot["autoplayBlocked"]) is not bool:
            raise BrowserMediaClockError("invalid provider autoplay-blocked flag")
    if snapshot["qualification"] != "unlinked" or snapshot["chessRef"] is not None:
        raise BrowserMediaClockError("browser attempted to publish chess authority")
    if snapshot["ok"] is not True or snapshot["ready"] is not True:
        raise BrowserMediaClockError("player is unavailable or not ready")
    position = _clock_ms(snapshot["positionMs"], "position")
    duration = _clock_ms(snapshot["durationMs"], "duration", optional=True)
    if duration is not None and position > duration:
        raise BrowserMediaClockError("position exceeds duration")
    try:
        state = MediaPlaybackState(snapshot["playbackState"])
    except (TypeError, ValueError) as error:
        raise BrowserMediaClockError("invalid playback state") from error
    if is_local:
        rate = snapshot["playbackRate"]
        if type(rate) not in (float, int) or not 0.25 <= rate <= 4:
            raise BrowserMediaClockError("invalid local playback rate")
    else:
        rate = 1.0
    if previous is not None:
        if type(previous) is not MediaSession:
            raise BrowserMediaClockError("invalid previous canonical MediaSession")
        if (previous.source_id, previous.source_revision, previous.session_id,
            previous.source_kind) != (
            authority.source_id, authority.source_revision, authority.session_id,
            authority.source_kind,
        ):
            raise BrowserMediaClockError("stale or foreign session")
        if previous.media_chess_ref is not None or previous.timeline_identity is not None:
            raise BrowserMediaClockError("linked session belongs to canonical chess reconciliation")
    revision = 0 if previous is None else previous.clock.revision + 1
    clock = MediaClockSnapshot(
        position_ms=position, duration_ms=duration, state=state,
        playback_rate=float(rate), revision=revision,
    )
    if previous is not None:
        return previous.with_clock(clock)
    return MediaSession(
        session_id=authority.session_id,
        source_id=authority.source_id,
        source_kind=authority.source_kind,
        source_revision=authority.source_revision,
        clock=clock,
    )


def resolve_only_verified_canonical_position(
    session: MediaSession,
    timeline: MediaPositionTimeline,
) -> TimelineResolution | None:
    """Read existing qualified timeline at real media time; never infer chess.

    A genuine MediaClock snapshot by itself contains ZERO chess evidence.
    Return a position only when the *existing canonical* MediaPositionTimeline
    was built for the same verified source revision and says VERIFIED. Missing,
    stale, candidate, ambiguous and explicit resync barriers yield no position.
    """
    if type(session) is not MediaSession or type(timeline) is not MediaPositionTimeline:
        raise BrowserMediaClockError("canonical MediaSession and timeline required")
    if timeline.source_id != session.source_id or timeline.identity is None:
        raise BrowserMediaClockError("missing or mismatched canonical timeline identity")
    if timeline.identity.source_revision != session.source_revision:
        raise BrowserMediaClockError("stale timeline source revision")
    result = timeline.resolve_at_or_before(session.clock.position_ms)
    if (
        result.resolved
        and result.qualification is MediaReconciliationState.VERIFIED
        and result.barrier is None
        and result.chess_ref is not None
    ):
        return result
    return None
