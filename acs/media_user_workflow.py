from __future__ import annotations

"""Section 20 application composition for the complete Media user workflow.

This module owns no chess rules, PGN/GameTree parsing, provider recognition, or
media decoding. It composes the already-canonical Media application,
recorded-media accessibility, preprocessing and playback boundaries into one
user-facing workflow.

Browser/provider code may report only playback facts (source identity, clock
position, duration and playback state). It can never supply a chess reference.
All position resolution and Restore Media Position semantics remain owned by
MediaApplicationService.
"""

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .media_application import MediaApplicationService
from .media_preprocess import PreprocessCheckpoint
from .recorded_media_accessibility import (
    RecordedMediaAccessibilityBridge,
    RecordedMediaAccessibilityError,
    RecordedMediaPlayerCommand,
)
from .recorded_media_sync import seek_recorded_media


_MAX_SOURCE_TEXT = 4096
_PROVIDER_KINDS = frozenset({"youtube", "host"})
_PLAYBACK_STATES = frozenset(
    {"unstarted", "playing", "paused", "buffering", "ended"}
)


class MediaUserWorkflowError(ValueError):
    """Fail-closed Section-20 composition error."""


def _text(value: object, name: str, *, limit: int = _MAX_SOURCE_TEXT) -> str:
    if type(value) is not str:
        raise MediaUserWorkflowError(f"{name} must be text")
    selected = value.strip()
    if not selected or len(selected) > limit or "\x00" in selected:
        raise MediaUserWorkflowError(f"invalid {name}")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in selected):
        raise MediaUserWorkflowError(f"unsafe {name}")
    return selected


def _nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise MediaUserWorkflowError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class MediaPlaybackSnapshot:
    """Provider-safe playback facts. No chess identity crosses this boundary."""

    source_id: str
    position_ms: int
    duration_ms: int | None
    playback_state: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id", limit=512))
        object.__setattr__(
            self, "position_ms", _nonnegative_int(self.position_ms, "position_ms")
        )
        if self.duration_ms is not None:
            duration = _nonnegative_int(self.duration_ms, "duration_ms")
            if self.position_ms > duration:
                raise MediaUserWorkflowError("playback position exceeds duration")
            object.__setattr__(self, "duration_ms", duration)
        if type(self.playback_state) is not str or self.playback_state not in _PLAYBACK_STATES:
            raise MediaUserWorkflowError("unsupported playback state")


@runtime_checkable
class HostPlaybackPort(Protocol):
    """Optional trusted host-side playback control for local media."""

    def snapshot(self) -> MediaPlaybackSnapshot: ...
    def play(self) -> object: ...
    def pause(self) -> object: ...
    def seek(self, position_ms: int) -> object: ...


@dataclass(frozen=True, slots=True)
class MediaUserWorkflowContext:
    """One opened media source bound to the canonical Media application."""

    application: MediaApplicationService
    provider_kind: str
    playback: HostPlaybackPort | None = None
    preprocess_provider: Callable[[], PreprocessCheckpoint | None] | None = None
    cancel_preprocess: Callable[[], object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.application, MediaApplicationService):
            raise TypeError("application must be MediaApplicationService")
        if type(self.provider_kind) is not str or self.provider_kind not in _PROVIDER_KINDS:
            raise MediaUserWorkflowError("unsupported media provider kind")
        if self.provider_kind == "host":
            if self.playback is None or not isinstance(self.playback, HostPlaybackPort):
                raise MediaUserWorkflowError("host media requires a playback port")
        elif self.playback is not None:
            raise MediaUserWorkflowError("browser media cannot bind a host playback port")
        if self.preprocess_provider is not None and not callable(self.preprocess_provider):
            raise TypeError("preprocess_provider must be callable or None")
        if self.cancel_preprocess is not None and not callable(self.cancel_preprocess):
            raise TypeError("cancel_preprocess must be callable or None")


class MediaUserWorkflowService:
    """Compose open/paste, playback synchronization, exploration and Restore."""

    def __init__(
        self,
        *,
        open_pasted_source: Callable[[str], MediaUserWorkflowContext],
        open_local_source: Callable[[], MediaUserWorkflowContext | None] | None = None,
        language: str = "uk",
    ) -> None:
        if not callable(open_pasted_source):
            raise TypeError("open_pasted_source must be callable")
        if open_local_source is not None and not callable(open_local_source):
            raise TypeError("open_local_source must be callable or None")
        self._open_pasted_source = open_pasted_source
        self._open_local_source = open_local_source
        self._bridge = RecordedMediaAccessibilityBridge(language=language)
        self._context: MediaUserWorkflowContext | None = None
        self._browser_playback: MediaPlaybackSnapshot | None = None
        self._revision = 0

    @property
    def language(self) -> str:
        return self._bridge.language

    def set_language(self, language: str) -> None:
        self._bridge.set_language(language)

    @property
    def active_context(self) -> MediaUserWorkflowContext | None:
        return self._context

    def _context_or_error(self) -> MediaUserWorkflowContext:
        if self._context is None:
            raise MediaUserWorkflowError("no media source is open")
        return self._context

    @staticmethod
    def _validate_context(context: object) -> MediaUserWorkflowContext:
        if type(context) is not MediaUserWorkflowContext:
            raise MediaUserWorkflowError("media opener returned an invalid context")
        return context

    def _activate(self, context: MediaUserWorkflowContext) -> dict[str, object]:
        selected = self._validate_context(context)
        self._context = selected
        self._browser_playback = None
        self._revision += 1
        if selected.provider_kind == "host":
            state = self.snapshot()["player"]
        else:
            state = self._bridge.error_state()
        state = dict(state)
        state["announcement"] = (
            "Медіа відкрито. Очікується стан програвача."
            if self.language == "uk"
            else "Media opened. Waiting for player state."
        )
        return self._envelope(state)

    def open_pasted(self, source_text: str) -> dict[str, object]:
        selected = _text(source_text, "media source")
        try:
            context = self._open_pasted_source(selected)
        except Exception:
            raise MediaUserWorkflowError("pasted media source could not be opened") from None
        return self._activate(context)

    def open_local(self) -> dict[str, object]:
        opener = self._open_local_source
        if opener is None:
            raise MediaUserWorkflowError("local media opening is unavailable")
        try:
            context = opener()
        except Exception:
            raise MediaUserWorkflowError("local media source could not be opened") from None
        if context is None:
            state = self._bridge.error_state()
            state["announcement"] = (
                "Файл медіа не вибрано."
                if self.language == "uk"
                else "No media file was selected."
            )
            return {
                "ok": False,
                "providerKind": None,
                "sourceTitle": "",
                "revision": self._revision,
                "player": state,
            }
        return self._activate(context)

    def _host_playback_snapshot(self, context: MediaUserWorkflowContext) -> MediaPlaybackSnapshot:
        playback = context.playback
        if playback is None:
            raise MediaUserWorkflowError("host playback is unavailable")
        try:
            snapshot = playback.snapshot()
        except Exception:
            raise MediaUserWorkflowError("media playback state could not be read") from None
        if type(snapshot) is not MediaPlaybackSnapshot:
            raise MediaUserWorkflowError("host playback returned an invalid snapshot")
        return snapshot

    def sync_browser_playback(
        self,
        *,
        source_id: str,
        position_ms: int,
        duration_ms: int | None,
        playback_state: str,
    ) -> dict[str, object]:
        context = self._context_or_error()
        if context.provider_kind != "youtube":
            raise MediaUserWorkflowError("browser playback is not active")
        snapshot = MediaPlaybackSnapshot(
            source_id=source_id,
            position_ms=position_ms,
            duration_ms=duration_ms,
            playback_state=playback_state,
        )
        if snapshot.source_id != context.application.source.source_id:
            raise MediaUserWorkflowError("browser playback belongs to another media source")
        self._browser_playback = snapshot
        return self._envelope(self._project(snapshot))

    def _current_playback(self, context: MediaUserWorkflowContext) -> MediaPlaybackSnapshot:
        if context.provider_kind == "host":
            return self._host_playback_snapshot(context)
        snapshot = self._browser_playback
        if snapshot is None:
            raise MediaUserWorkflowError("browser playback state is not available yet")
        return snapshot

    def _checkpoint(
        self, context: MediaUserWorkflowContext
    ) -> PreprocessCheckpoint | None:
        provider = context.preprocess_provider
        if provider is None:
            return None
        try:
            value = provider()
        except Exception:
            raise MediaUserWorkflowError("media preprocessing state is unavailable") from None
        if value is not None and type(value) is not PreprocessCheckpoint:
            raise MediaUserWorkflowError("preprocessing provider returned invalid state")
        return value

    def _project(self, playback: MediaPlaybackSnapshot) -> dict[str, object]:
        context = self._context_or_error()
        application = context.application
        if playback.source_id != application.source.source_id:
            raise MediaUserWorkflowError("playback source does not match Media application")
        if (
            application.source.duration_ms is not None
            and playback.duration_ms is not None
            and application.source.duration_ms != playback.duration_ms
        ):
            raise MediaUserWorkflowError("playback duration changed from the opened source")
        try:
            application.seek_media(playback.position_ms)
            resolution = seek_recorded_media(
                application.session,
                application.timeline,
                playback.position_ms,
                duration_ms=application.source.duration_ms,
            )
            return self._bridge.snapshot(
                position_ms=playback.position_ms,
                duration_ms=(
                    application.source.duration_ms
                    if application.source.duration_ms is not None
                    else playback.duration_ms
                ),
                playback_state=playback.playback_state,
                revision=self._revision,
                playback=resolution,
                preprocess=self._checkpoint(context),
            )
        except (RecordedMediaAccessibilityError, MediaUserWorkflowError):
            raise
        except Exception:
            raise MediaUserWorkflowError("media synchronization could not be projected") from None

    def snapshot(self) -> dict[str, object]:
        context = self._context_or_error()
        return self._envelope(self._project(self._current_playback(context)))

    def _envelope(self, player: dict[str, object]) -> dict[str, object]:
        context = self._context
        if context is None:
            return {
                "ok": False,
                "providerKind": None,
                "sourceTitle": "",
                "revision": self._revision,
                "player": dict(player),
            }
        return {
            "ok": bool(player.get("ok")),
            "providerKind": context.provider_kind,
            "sourceTitle": context.application.source.title,
            "revision": self._revision,
            "player": dict(player),
        }

    def command(
        self,
        action: str,
        *,
        position_ms: int | None = None,
    ) -> dict[str, object]:
        context = self._context_or_error()
        try:
            command = RecordedMediaPlayerCommand(action, position_ms)
        except RecordedMediaAccessibilityError as exc:
            raise MediaUserWorkflowError(str(exc)) from exc

        if context.provider_kind == "youtube" and command.action in {"play", "pause", "seek"}:
            raise MediaUserWorkflowError(
                "browser playback commands must be handled by the active provider adapter"
            )

        if context.provider_kind == "host":
            playback = context.playback
            if playback is None:
                raise MediaUserWorkflowError("host playback is unavailable")
            try:
                if command.action == "play":
                    playback.play()
                elif command.action == "pause":
                    playback.pause()
                elif command.action == "seek":
                    assert command.position_ms is not None
                    playback.seek(command.position_ms)
            except Exception:
                raise MediaUserWorkflowError("media playback command failed") from None

        if command.action == "restore":
            playback_state = self._current_playback(context)
            try:
                context.application.seek_media(playback_state.position_ms)
                context.application.restore_media_position()
            except Exception:
                state = self._project(playback_state)
                state["ok"] = False
                state["announcement"] = (
                    "Не вдалося безпечно відновити позицію медіа."
                    if self.language == "uk"
                    else "The media position could not be restored safely."
                )
                return self._envelope(state)
            state = self._project(playback_state)
            state["announcement"] = (
                "Відновлено шахову позицію, синхронізовану з поточним часом медіа."
                if self.language == "uk"
                else "Restored the chess position synchronized with the current media time."
            )
            return self._envelope(state)

        if command.action == "cancel":
            cancel = context.cancel_preprocess
            if cancel is None:
                raise MediaUserWorkflowError("media preprocessing cannot be canceled")
            try:
                cancel()
            except Exception:
                raise MediaUserWorkflowError("media preprocessing cancel failed") from None

        return self.snapshot()


__all__ = [
    "HostPlaybackPort",
    "MediaPlaybackSnapshot",
    "MediaUserWorkflowContext",
    "MediaUserWorkflowError",
    "MediaUserWorkflowService",
]
