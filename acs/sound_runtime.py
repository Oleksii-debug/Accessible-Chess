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
from .sound_profiles import SoundProfile, canonical_sound_event_id, canonical_sound_id


class SoundPlaybackPort(Protocol):
    """Presentation-neutral playback port implemented by infrastructure.

    ``play`` is an acceptance boundary: implementations return only after the
    event has been accepted/played in order, return ``False`` for intentional
    downstream suppression, or raise an exception. This preserves deterministic
    capture->check->end sequencing without Core threads.
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
                message = str(exc).strip() or type(exc).__name__
                failure = SoundPlaybackFailure(event, type(exc).__name__, message)
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


@dataclass(frozen=True, slots=True)
class SoundAssetRequest:
    pack_id: str
    event_id: str
    sound_id: str
    volume: int
    preview: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "pack_id", canonical_sound_id(self.pack_id, label="sound pack id"))
        object.__setattr__(self, "event_id", canonical_sound_event_id(self.event_id))
        object.__setattr__(self, "sound_id", canonical_sound_id(self.sound_id, label="sound id"))
        if type(self.volume) is not int:
            raise TypeError("volume must be an integer")
        if not 0 <= self.volume <= 100:
            raise ValueError("volume must be in 0..100")
        if type(self.preview) is not bool:
            raise TypeError("preview must be boolean")


class SoundAssetPlaybackPort(Protocol):
    def play_sound(self, request: SoundAssetRequest) -> None: ...


@dataclass(frozen=True, slots=True)
class SoundPreviewResult:
    request: SoundAssetRequest | None
    delivered: bool
    error_type: str | None = None

    def __post_init__(self) -> None:
        if self.request is not None and not isinstance(self.request, SoundAssetRequest):
            raise TypeError("preview request must be SoundAssetRequest or None")
        if type(self.delivered) is not bool:
            raise TypeError("preview delivered must be boolean")
        if self.error_type is not None:
            if not isinstance(self.error_type, str) or not self.error_type.strip():
                raise TypeError("preview error_type must be non-empty text or None")
            object.__setattr__(self, "error_type", self.error_type.strip())

    @property
    def ok(self) -> bool:
        return self.error_type is None


class _ProfiledPlaybackBridge:
    def __init__(
        self,
        playback: SoundAssetPlaybackPort,
        profile: Callable[[], SoundProfile],
    ) -> None:
        if isinstance(playback, type) or not callable(getattr(playback, "play_sound", None)):
            raise TypeError("profile playback must expose callable play_sound")
        self._playback = playback
        self._profile = profile

    def _current_profile(self) -> SoundProfile:
        profile = self._profile()
        if not isinstance(profile, SoundProfile):
            raise TypeError("sound profile provider must return SoundProfile")
        return profile

    def play(self, event: SoundEvent, *, volume: int) -> bool:
        profile = self._current_profile()
        preference = profile.preference_for(event.value)
        if not preference.enabled or preference.volume_percent == 0:
            return False
        event_volume = round(volume * preference.volume_percent / 100)
        if event_volume == 0:
            return False
        self._playback.play_sound(
            SoundAssetRequest(
                pack_id=profile.pack_id,
                event_id=event.value,
                sound_id=profile.selected_sound_id(event.value),
                volume=event_volume,
            )
        )
        return True

    def preview(self, event_id: str) -> SoundPreviewResult:
        event_id = canonical_sound_event_id(event_id)
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
            self._playback.play_sound(request)
        except Exception as exc:
            return SoundPreviewResult(request, False, error_type=type(exc).__name__)
        return SoundPreviewResult(request, True)


class ProfiledSoundRuntime(SoundRuntime):
    """SoundRuntime adapter that filters/remaps playback through one SoundProfile.

    SoundEventPolicy and GameSoundRuntime remain the only semantic chess-event
    ordering authorities. Profiles may only silence/remap downstream playback.
    """

    def __init__(
        self,
        playback: SoundAssetPlaybackPort,
        profile: SoundProfile | Callable[[], SoundProfile],
        *,
        error_sink: Callable[[SoundPlaybackFailure], None] | None = None,
    ) -> None:
        if not isinstance(profile, SoundProfile) and not callable(profile):
            raise TypeError("profile must be SoundProfile or callable")
        provider = profile if callable(profile) else lambda: profile
        self._profile_provider = provider
        self._profiled_playback = _ProfiledPlaybackBridge(playback, provider)
        super().__init__(
            self._profiled_playback,
            settings=self._runtime_settings,
            error_sink=error_sink,
        )

    def _runtime_settings(self) -> SoundRuntimeSettings:
        profile = self._profile_provider()
        if not isinstance(profile, SoundProfile):
            raise TypeError("sound profile provider must return SoundProfile")
        return SoundRuntimeSettings(
            enabled=profile.master_enabled,
            volume=profile.master_volume_percent,
        )

    def preview(self, event_id: str) -> SoundPreviewResult:
        return self._profiled_playback.preview(event_id)


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
