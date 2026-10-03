from __future__ import annotations

"""Application-level sound playback contract and deterministic dispatcher.

Chess/domain code emits only semantic ``SoundEvent`` values. Infrastructure owns
platform audio APIs and packaged asset paths. This module owns queue semantics,
settings and fault reporting so a missing/broken sound can never mutate chess
state or fall back to a system beep.
"""

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Protocol

from .sound_events import MoveSoundFacts, SoundEvent, SoundEventPolicy
from .sound_profiles import SoundProfile


class SoundPlaybackPort(Protocol):
    """Presentation-neutral playback port implemented by infrastructure.

    ``play`` is an acceptance boundary: implementations return only after the
    event has been accepted/played in order, may return ``False`` only for an
    intentional downstream preference suppression, or raise an exception. This
    preserves deterministic capture->check->end sequencing without Core threads.
    """

    def play(self, event: SoundEvent, *, volume: int) -> bool | None: ...


@dataclass(frozen=True)
class SoundRuntimeSettings:
    enabled: bool = True
    volume: int = 80

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be boolean")
        if type(self.volume) is not int:
            raise TypeError("volume must be an integer")
        if not 0 <= self.volume <= 100:
            raise ValueError("volume must be in 0..100")

    @classmethod
    def from_mapping(cls, settings: Mapping[str, object]) -> "SoundRuntimeSettings":
        if not isinstance(settings, Mapping):
            raise TypeError("settings must be a mapping")
        enabled = settings.get("sounds", True)
        volume = settings.get("volume", 80)
        return cls(enabled=enabled, volume=volume)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SoundPlaybackFailure:
    event: SoundEvent
    error_type: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.event, SoundEvent):
            raise TypeError("failure event must be SoundEvent")
        for name in ("error_type", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TypeError(f"failure {name} must be non-empty text")
            object.__setattr__(self, name, value.strip())


@dataclass(frozen=True)
class SoundPlaybackReport:
    requested: tuple[SoundEvent, ...]
    delivered: tuple[SoundEvent, ...]
    failures: tuple[SoundPlaybackFailure, ...]
    disabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.requested, tuple) or any(
            not isinstance(event, SoundEvent) for event in self.requested
        ):
            raise TypeError("requested must be a SoundEvent tuple")
        if not isinstance(self.delivered, tuple) or any(
            not isinstance(event, SoundEvent) for event in self.delivered
        ):
            raise TypeError("delivered must be a SoundEvent tuple")
        if not isinstance(self.failures, tuple) or any(
            not isinstance(failure, SoundPlaybackFailure) for failure in self.failures
        ):
            raise TypeError("failures must be a SoundPlaybackFailure tuple")
        if type(self.disabled) is not bool:
            raise TypeError("disabled must be boolean")

    @property
    def ok(self) -> bool:
        return not self.failures


class SoundRuntime:
    """Deterministic queue from semantic events to an injected playback port.

    Rules:
    * preserve event order supplied by ``SoundEventPolicy``;
    * collapse duplicate event IDs within one dispatch batch, preserving first;
    * when disabled or volume=0, do not touch the playback port;
    * isolate adapter and diagnostic-sink failures, and continue with later events;
    * never synthesize a fallback beep or alternate system sound.
    """

    def __init__(
        self,
        playback: SoundPlaybackPort,
        *,
        settings: SoundRuntimeSettings | Callable[[], SoundRuntimeSettings] | None = None,
        error_sink: Callable[[SoundPlaybackFailure], None] | None = None,
    ) -> None:
        if isinstance(playback, type) or not callable(getattr(playback, "play", None)):
            raise TypeError("playback must expose callable play")
        if settings is not None and not isinstance(settings, SoundRuntimeSettings) and not callable(settings):
            raise TypeError("settings must be SoundRuntimeSettings, callable, or None")
        if error_sink is not None and not callable(error_sink):
            raise TypeError("error_sink must be callable or None")
        self._playback = playback
        self._settings = SoundRuntimeSettings() if settings is None else settings
        self._error_sink = error_sink

    def current_settings(self) -> SoundRuntimeSettings:
        value = self._settings() if callable(self._settings) else self._settings
        if not isinstance(value, SoundRuntimeSettings):
            raise TypeError("sound settings provider must return SoundRuntimeSettings")
        return value

    def dispatch(self, events: Iterable[SoundEvent]) -> SoundPlaybackReport:
        ordered: list[SoundEvent] = []
        seen: set[SoundEvent] = set()
        try:
            iterator = iter(events)
        except TypeError as exc:
            raise TypeError("sound dispatch requires an iterable of SoundEvent values") from exc
        for event in iterator:
            if not isinstance(event, SoundEvent):
                raise TypeError("sound dispatch accepts SoundEvent values only")
            if event not in seen:
                seen.add(event)
                ordered.append(event)
        requested = tuple(ordered)
        settings = self.current_settings()
        if not settings.enabled or settings.volume == 0:
            return SoundPlaybackReport(requested, (), (), disabled=True)

        delivered: list[SoundEvent] = []
        failures: list[SoundPlaybackFailure] = []
        for event in requested:
            try:
                accepted = self._playback.play(event, volume=settings.volume)
            except Exception as exc:  # infrastructure boundary
                failure = SoundPlaybackFailure(
                    event,
                    type(exc).__name__,
                    "sound playback adapter failed",
                )
                failures.append(failure)
                if self._error_sink is not None:
                    try:
                        self._error_sink(failure)
                    except Exception:
                        # Diagnostic/reporting infrastructure must never corrupt
                        # chess state, queue ordering, or later sound delivery.
                        pass
            else:
                if accepted is not False:
                    delivered.append(event)
        return SoundPlaybackReport(requested, tuple(delivered), tuple(failures))


@dataclass(frozen=True)
class SoundAssetRequest:
    pack_id: str
    event_id: str
    sound_id: str
    volume: int
    preview: bool = False

    def __post_init__(self) -> None:
        for name in ("pack_id", "event_id", "sound_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TypeError(f"{name} must be non-empty text")
            object.__setattr__(self, name, value.strip())
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise TypeError("volume must be an integer")
        if not 0 <= self.volume <= 100:
            raise ValueError("volume must be in 0..100")
        if type(self.preview) is not bool:
            raise TypeError("preview must be boolean")


class SoundAssetPlaybackPort(Protocol):
    def play_sound(self, request: SoundAssetRequest) -> None: ...


@dataclass(frozen=True)
class SoundPreviewResult:
    request: SoundAssetRequest | None
    delivered: bool
    error_type: str | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.error_type is None


class _ResolvedProfilePlayback:
    """Playback bridge bound to one immutable profile snapshot for one dispatch."""

    def __init__(self, playback: SoundAssetPlaybackPort, profile: SoundProfile) -> None:
        if isinstance(playback, type) or not callable(getattr(playback, "play_sound", None)):
            raise TypeError("asset playback must expose callable play_sound")
        if not isinstance(profile, SoundProfile):
            raise TypeError("sound profile provider must return SoundProfile")
        self._playback = playback
        self._profile = profile

    def play(self, event: SoundEvent, *, volume: int) -> bool:
        pref = self._profile.preference_for(event.value)
        if not pref.enabled or pref.volume_percent == 0:
            return False
        event_volume = round(volume * pref.volume_percent / 100)
        if event_volume == 0:
            return False
        self._playback.play_sound(
            SoundAssetRequest(
                pack_id=self._profile.pack_id,
                event_id=event.value,
                sound_id=self._profile.selected_sound_id(event.value),
                volume=event_volume,
            )
        )
        return True


class ProfiledSoundRuntime(SoundRuntime):
    """SoundRuntime wired to a versioned ``SoundProfile``.

    ``SoundEventPolicy`` and ``GameSoundRuntime`` remain the only chess-event
    semantic/order authorities. The profile layer can only filter/remap playback.
    Each semantic dispatch resolves exactly one profile snapshot, so a dynamic
    provider cannot mix packs or preferences within one ordered chess-event batch.
    """

    def __init__(
        self,
        playback: SoundAssetPlaybackPort,
        profile: SoundProfile | Callable[[], SoundProfile],
        *,
        error_sink: Callable[[SoundPlaybackFailure], None] | None = None,
    ) -> None:
        if isinstance(playback, type) or not callable(getattr(playback, "play_sound", None)):
            raise TypeError("asset playback must expose callable play_sound")
        if not isinstance(profile, SoundProfile) and not callable(profile):
            raise TypeError("profile must be SoundProfile or callable")
        if error_sink is not None and not callable(error_sink):
            raise TypeError("error_sink must be callable or None")
        self._profile_provider = profile if callable(profile) else lambda: profile
        self._asset_playback = playback
        self._profile_error_sink = error_sink
        initial = self._current_profile()
        super().__init__(
            _ResolvedProfilePlayback(playback, initial),
            settings=SoundRuntimeSettings(
                enabled=initial.master_enabled,
                volume=initial.master_volume_percent,
            ),
            error_sink=error_sink,
        )

    def _current_profile(self) -> SoundProfile:
        profile = self._profile_provider()
        if not isinstance(profile, SoundProfile):
            raise TypeError("sound profile provider must return SoundProfile")
        return profile

    def dispatch(self, events: Iterable[SoundEvent]) -> SoundPlaybackReport:
        profile = self._current_profile()
        runtime = SoundRuntime(
            _ResolvedProfilePlayback(self._asset_playback, profile),
            settings=SoundRuntimeSettings(
                enabled=profile.master_enabled,
                volume=profile.master_volume_percent,
            ),
            error_sink=self._profile_error_sink,
        )
        return runtime.dispatch(events)

    def preview(self, event_id: str) -> SoundPreviewResult:
        profile = self._current_profile()
        volume = profile.effective_volume(event_id)
        if volume == 0:
            return SoundPreviewResult(None, False)
        request = SoundAssetRequest(
            pack_id=profile.pack_id,
            event_id=event_id,
            sound_id=profile.selected_sound_id(event_id),
            volume=volume,
            preview=True,
        )
        try:
            self._asset_playback.play_sound(request)
        except Exception as exc:
            return SoundPreviewResult(
                request,
                False,
                error_type=type(exc).__name__,
                message="sound preview adapter failed",
            )
        return SoundPreviewResult(request, True)


class GameSoundRuntime:
    """Lifecycle-aware facade used by move/game application services.

    It prevents duplicate game-end playback when a terminal move already emitted
    ``END`` and a lifecycle service subsequently records the same outcome.
    """

    def __init__(self, runtime: SoundRuntime) -> None:
        if not isinstance(runtime, SoundRuntime):
            raise TypeError("runtime must be SoundRuntime")
        self._runtime = runtime
        self._ended = False

    def start(self) -> SoundPlaybackReport:
        self._ended = False
        return self._runtime.dispatch(SoundEventPolicy.game_start())

    def move(self, facts: MoveSoundFacts) -> SoundPlaybackReport:
        events = SoundEventPolicy.for_move(facts)
        if SoundEvent.END in events:
            self._ended = True
        return self._runtime.dispatch(events)

    def illegal(self) -> SoundPlaybackReport:
        return self._runtime.dispatch(SoundEventPolicy.illegal())

    def tick(self) -> SoundPlaybackReport:
        return self._runtime.dispatch(SoundEventPolicy.clock_tick())

    def end(self) -> SoundPlaybackReport:
        if self._ended:
            return SoundPlaybackReport((), (), ())
        self._ended = True
        return self._runtime.dispatch(SoundEventPolicy.game_end())

    def resume_after_takeback(self) -> SoundPlaybackReport:
        """Re-arm a terminal game after takeback without replaying START."""
        self._ended = False
        return SoundPlaybackReport((), (), ())
