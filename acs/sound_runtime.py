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


class SoundPlaybackPort(Protocol):
    """Presentation-neutral playback port implemented by infrastructure.

    ``play`` is an acceptance boundary: implementations must return only after
    the event has been accepted/played in order, or raise an exception. This
    gives deterministic capture->check->end sequencing without Core threads.
    """

    def play(self, event: SoundEvent, *, volume: int) -> None: ...


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
    """Deterministic queue from semantic events to an injected playback port.

    Rules:
    * preserve event order supplied by ``SoundEventPolicy``;
    * collapse duplicate event IDs within one dispatch batch, preserving first;
    * when disabled or volume=0, do not touch the playback port;
    * isolate adapter failures, report/log them, and continue with later events;
    * never synthesize a fallback beep or alternate system sound.
    """

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
                self._playback.play(event, volume=settings.volume)
            except Exception as exc:  # infrastructure boundary
                failure = SoundPlaybackFailure(event, type(exc).__name__, str(exc))
                failures.append(failure)
                if self._error_sink is not None:
                    self._error_sink(failure)
            else:
                delivered.append(event)
        return SoundPlaybackReport(requested, tuple(delivered), tuple(failures))


class GameSoundRuntime:
    """Lifecycle-aware facade used by move/game application services.

    It prevents duplicate game-end playback when a terminal move already emitted
    ``END`` and a lifecycle service subsequently records the same outcome.
    """

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

    def resume_after_takeback(self) -> SoundPlaybackReport:
        """Re-arm a terminal game after takeback without replaying START."""
        self._ended = False
        return SoundPlaybackReport((), (), ())
