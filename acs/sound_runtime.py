from __future__ import annotations

"""Application-level sound playback contract and deterministic dispatcher.

Chess/domain code emits only semantic ``SoundEvent`` values. Infrastructure owns
platform audio APIs and packaged asset paths. This module owns queue semantics,
settings and fault reporting so a missing/broken sound can never mutate chess
state or fall back to a system beep.

The optional profile layer is deliberately downstream from chess-event policy:
it may silence or remap an event to a sound asset, but it cannot add/reorder
semantic chess events. Preview is a separate boundary and never enters game
lifecycle policy.
"""

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Protocol

from .sound_events import MoveSoundFacts, SoundEvent, SoundEventPolicy
from .sound_profiles import SoundProfile


class SoundPlaybackPort(Protocol):
    """Presentation-neutral playback port implemented by infrastructure.

    Returning ``False`` means the event was intentionally suppressed by a
    downstream preference layer. ``None`` remains the legacy successful return
    value, preserving compatibility with existing production adapters.
    """

    def play(self, event: SoundEvent, *, volume: int) -> bool | None: ...


@dataclass(frozen=True)
class SoundRuntimeSettings:
    enabled: bool = True
    volume: int = 80

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be boolean")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise TypeError("volume must be an integer")
        if not 0 <= self.volume <= 100:
            raise ValueError("volume must be in 0..100")

    @classmethod
    def from_mapping(cls, settings: Mapping[str, object]) -> "SoundRuntimeSettings":
        return cls(
            enabled=bool(settings.get("sounds", True)),
            volume=int(settings.get("volume", 80)),
        )


@dataclass(frozen=True)
class SoundPlaybackFailure:
    event: SoundEvent
    error_type: str
    message: str


@dataclass(frozen=True)
class SoundPlaybackReport:
    requested: tuple[SoundEvent, ...]
    delivered: tuple[SoundEvent, ...]
    failures: tuple[SoundPlaybackFailure, ...]
    disabled: bool = False

    @property
    def ok(self) -> bool:
        return not self.failures


class SoundRuntime:
    """Deterministic queue from semantic events to an injected playback port."""

    def __init__(
        self,
        playback: SoundPlaybackPort,
        *,
        settings: SoundRuntimeSettings | Callable[[], SoundRuntimeSettings] | None = None,
        error_sink: Callable[[SoundPlaybackFailure], None] | None = None,
    ) -> None:
        self._playback = playback
        self._settings = settings or SoundRuntimeSettings()
        self._error_sink = error_sink

    def current_settings(self) -> SoundRuntimeSettings:
        value = self._settings() if callable(self._settings) else self._settings
        if not isinstance(value, SoundRuntimeSettings):
            raise TypeError("sound settings provider must return SoundRuntimeSettings")
        return value

    def dispatch(self, events: Iterable[SoundEvent]) -> SoundPlaybackReport:
        ordered: list[SoundEvent] = []
        seen: set[SoundEvent] = set()
        for event in events:
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
            except Exception as exc:
                failure = SoundPlaybackFailure(event, type(exc).__name__, str(exc))
                failures.append(failure)
                if self._error_sink is not None:
                    self._error_sink(failure)
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
        if not self.pack_id or not self.event_id or not self.sound_id:
            raise ValueError("pack_id, event_id and sound_id are required")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise TypeError("volume must be an integer")
        if not 0 <= self.volume <= 100:
            raise ValueError("volume must be in 0..100")


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


class _ProfiledPlaybackBridge:
    def __init__(
        self,
        playback: SoundAssetPlaybackPort,
        profile: Callable[[], SoundProfile],
    ) -> None:
        self._playback = playback
        self._profile = profile

    def play(self, event: SoundEvent, *, volume: int) -> bool:
        profile = self._profile()
        if not isinstance(profile, SoundProfile):
            raise TypeError("sound profile provider must return SoundProfile")
        pref = profile.preference_for(event.value)
        if not pref.enabled or pref.volume_percent == 0:
            return False
        event_volume = round(volume * pref.volume_percent / 100)
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
        profile = self._profile()
        if not isinstance(profile, SoundProfile):
            raise TypeError("sound profile provider must return SoundProfile")
        pref = profile.preference_for(event_id)
        volume = round(profile.master_volume_percent * pref.volume_percent / 100)
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
            return SoundPreviewResult(
                request,
                False,
                error_type=type(exc).__name__,
                message=str(exc),
            )
        return SoundPreviewResult(request, True)


class ProfiledSoundRuntime(SoundRuntime):
    """SoundRuntime wired to a versioned ``SoundProfile``.

    ``SoundEventPolicy`` and ``GameSoundRuntime`` remain the only chess-event
    semantic/order authorities. The profile layer can only filter/remap playback.
    """

    def __init__(
        self,
        playback: SoundAssetPlaybackPort,
        profile: SoundProfile | Callable[[], SoundProfile],
        *,
        error_sink: Callable[[SoundPlaybackFailure], None] | None = None,
    ) -> None:
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
    def __init__(self, runtime: SoundRuntime) -> None:
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
