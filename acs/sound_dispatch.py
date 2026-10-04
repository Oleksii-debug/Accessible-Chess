from __future__ import annotations

"""Presentation-neutral delivery registry for semantic chess sound events.

Core emits stable ``SoundEvent`` values. Infrastructure registers one or more
named sinks at the composition root. A broken playback adapter is isolated and
reported instead of corrupting chess/game state.
"""

from dataclasses import dataclass
from typing import Callable, Iterable

from .sound_events import SoundEvent


SoundEventSink = Callable[[SoundEvent], None]


@dataclass(frozen=True)
class SoundSinkDescriptor:
    sink_id: str
    title: str
    events: frozenset[SoundEvent] | None = None

    def __post_init__(self) -> None:
        sink_id = self.sink_id.strip()
        title = self.title.strip()
        if not sink_id:
            raise ValueError("sink_id must not be empty")
        if sink_id != self.sink_id:
            raise ValueError("sink_id must not contain surrounding whitespace")
        if sink_id.casefold() != sink_id:
            raise ValueError("sink_id must be lowercase and stable")
        if not title:
            raise ValueError("sink title must not be empty")
        if self.events is not None and not self.events:
            raise ValueError("events filter must be non-empty when provided")

    def accepts(self, event: SoundEvent) -> bool:
        return self.events is None or event in self.events


@dataclass(frozen=True)
class SoundDeliveryFailure:
    sink_id: str
    event: SoundEvent
    error_type: str
    message: str


@dataclass(frozen=True)
class SoundDeliveryReport:
    attempted: int
    delivered: int
    failures: tuple[SoundDeliveryFailure, ...]

    @property
    def ok(self) -> bool:
        return not self.failures


class SoundEventSinkRegistry:
    """Named registration point and fault-isolating dispatcher for sound sinks."""

    def __init__(self) -> None:
        self._descriptors: dict[str, SoundSinkDescriptor] = {}
        self._sinks: dict[str, SoundEventSink] = {}

    def register(self, descriptor: SoundSinkDescriptor, sink: SoundEventSink) -> None:
        if descriptor.sink_id in self._descriptors:
            raise ValueError(f"sound sink already registered: {descriptor.sink_id}")
        if not callable(sink):
            raise TypeError("sound sink must be callable")
        self._descriptors[descriptor.sink_id] = descriptor
        self._sinks[descriptor.sink_id] = sink

    def unregister(self, sink_id: str) -> None:
        sink_id = self._normalize_sink_id(sink_id)
        if sink_id not in self._descriptors:
            raise KeyError(f"unknown sound sink: {sink_id}")
        del self._descriptors[sink_id]
        del self._sinks[sink_id]

    def descriptor(self, sink_id: str) -> SoundSinkDescriptor:
        sink_id = self._normalize_sink_id(sink_id)
        try:
            return self._descriptors[sink_id]
        except KeyError as exc:
            raise KeyError(f"unknown sound sink: {sink_id}") from exc

    def descriptors(self, *, event: SoundEvent | None = None) -> tuple[SoundSinkDescriptor, ...]:
        values: Iterable[SoundSinkDescriptor] = self._descriptors.values()
        if event is not None:
            values = (item for item in values if item.accepts(event))
        return tuple(values)

    def emit(self, event: SoundEvent) -> SoundDeliveryReport:
        if not isinstance(event, SoundEvent):
            raise TypeError("event must be a SoundEvent")
        failures: list[SoundDeliveryFailure] = []
        attempted = 0
        delivered = 0
        for descriptor in self.descriptors(event=event):
            attempted += 1
            try:
                self._sinks[descriptor.sink_id](event)
            except Exception as exc:  # adapter boundary: report and continue
                failures.append(
                    SoundDeliveryFailure(
                        sink_id=descriptor.sink_id,
                        event=event,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
            else:
                delivered += 1
        return SoundDeliveryReport(attempted, delivered, tuple(failures))

    def emit_many(self, events: Iterable[SoundEvent]) -> tuple[SoundDeliveryReport, ...]:
        return tuple(self.emit(event) for event in events)

    @staticmethod
    def _normalize_sink_id(sink_id: str) -> str:
        value = str(sink_id).strip().casefold()
        if not value:
            raise ValueError("sink_id must not be empty")
        return value
