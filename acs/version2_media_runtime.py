from __future__ import annotations

"""Trusted local/YouTube source factory for the packaged V2 Media workflow.

Paths never become MediaCore identity. Local files are identified by content
SHA-256 and only the trusted local WebView receives a file URI for rendering.
The canonical Media timeline starts empty and therefore cannot restore/mutate
chess state until later preprocessing publishes confirmed links.
"""

from collections.abc import Callable
import hashlib
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from .local_video_library import sha256_file
from .media_application import MediaApplicationService
from .media_core import MediaChessSession, MediaCursor, MediaPositionTimeline, MediaSource, MediaSourceKind
from .media_user_workflow import MediaUserWorkflowContext, MediaUserWorkflowService

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ALLOWED_LOCAL_SUFFIXES = frozenset({".mp4", ".webm"})


def _youtube_id(source: str) -> str:
    """Parse only approved, single-video YouTube HTTPS URLs or exact IDs.

    Remote media requests cannot specify arbitrary authority/transport data.
    The browser's documented IFrame adapter uses the same allowlist, so a
    source accepted by the native host cannot subsequently be rejected as an
    unsafe URL by the provider layer.
    """
    if type(source) is not str or not source or source != source.strip():
        raise ValueError("YouTube source must be a non-empty exact URL or ID")
    if len(source) > 2048 or any(ord(char) < 32 for char in source):
        raise ValueError("invalid YouTube source")
    if _YOUTUBE_ID.fullmatch(source):
        return source
    parsed = urlparse(source)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("YouTube URL must use plain HTTPS")
    host = (parsed.hostname or "").casefold()
    if parsed.fragment:
        # Fragments have no IFrame source identity and are easy to confuse
        # with another video or a navigation command.
        raise ValueError("YouTube fragment is not supported")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if "list" in query or "playlist" in query or len(query.get("v", [])) > 1:
        raise ValueError("YouTube playlists and duplicate video IDs are not accepted")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if host == "youtu.be":
        if len(segments) != 1:
            raise ValueError("invalid YouTube short URL")
        candidate = segments[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            if len(query.get("v", [])) != 1:
                raise ValueError("single YouTube watch ID required")
            candidate = query["v"][0]
        elif len(segments) == 2 and segments[0] in {"embed", "shorts", "live"}:
            candidate = segments[1]
        else:
            raise ValueError("unsupported YouTube path")
    elif host in {"youtube-nocookie.com", "www.youtube-nocookie.com"}:
        if len(segments) != 2 or segments[0] != "embed":
            raise ValueError("unsupported YouTube no-cookie path")
        candidate = segments[1]
    else:
        raise ValueError("unapproved YouTube host")
    if not _YOUTUBE_ID.fullmatch(candidate):
        raise ValueError("invalid YouTube ID")
    return candidate


def _application(
    *,
    source: MediaSource,
    restore_chess_ref: Callable[[str], object],
) -> MediaApplicationService:
    timeline = MediaPositionTimeline(source.source_id, ())
    session = MediaChessSession(MediaCursor(source.source_id, 0), None)
    return MediaApplicationService(
        source=source,
        timeline=timeline,
        session=session,
        restore_chess_ref=restore_chess_ref,
    )


def build_packaged_media_workflow(
    *,
    open_local_path: Callable[[], Path | None],
    restore_chess_ref: Callable[[str], object],
    language: str = "uk",
) -> MediaUserWorkflowService:
    if not callable(open_local_path) or not callable(restore_chess_ref):
        raise TypeError("packaged Media workflow callbacks must be callable")

    def open_local() -> MediaUserWorkflowContext | None:
        selected = open_local_path()
        if selected is None:
            return None
        if type(selected) is not Path:
            selected = Path(selected)
        selected = selected.expanduser().resolve()
        if not selected.is_file() or selected.suffix.casefold() not in _ALLOWED_LOCAL_SUFFIXES:
            raise ValueError("local video must be an existing MP4/WebM file")
        digest = sha256_file(selected)
        source_id = f"local:sha256:{digest}"
        source = MediaSource(
            source_id=source_id,
            title=selected.name,
            kind=MediaSourceKind.LOCAL_FILE,
            source_ref=f"sha256:{digest}",
            duration_ms=None,
        )
        return MediaUserWorkflowContext(
            application=_application(source=source, restore_chess_ref=restore_chess_ref),
            provider_kind="browser_local",
            browser_source_url=selected.as_uri(),
        )

    def open_pasted(source_text: str) -> MediaUserWorkflowContext:
        video_id = _youtube_id(source_text)
        source_id = f"youtube:{video_id}"
        source = MediaSource(
            source_id=source_id,
            title=f"YouTube {video_id}",
            kind=MediaSourceKind.PROVIDER,
            source_ref=source_id,
            duration_ms=None,
            attribution="YouTube IFrame Player API",
        )
        return MediaUserWorkflowContext(
            application=_application(source=source, restore_chess_ref=restore_chess_ref),
            provider_kind="youtube",
        )

    return MediaUserWorkflowService(
        open_pasted_source=open_pasted,
        open_local_source=open_local,
        language=language,
    )


__all__ = ["build_packaged_media_workflow"]
