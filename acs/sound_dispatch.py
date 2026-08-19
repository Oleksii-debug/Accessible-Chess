from __future__ import annotations

"""Presentation-neutral delivery registry for semantic chess sound events.

Core emits stable ``SoundEvent`` values. Infrastructure registers one or more
named sinks at the composition root. A broken playback adapter is isolated and
reported instead of corrupting chess/game state.
"""

from dataclasses import dataclass
import re
from typing import Callable, Iterable

from .sound_events import SoundEvent


SoundEventSink = Callable[[SoundEvent], None]


_SINK_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class SoundSinkDescriptor:
    sink_id: str
    title: str
    events: frozenset[SoundEvent] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.sink_id, str):
            raise TypeError("sink_id must be text")
        if not isinstance(self.title, str):
            raise TypeError("sink title must be text")
        sink_id = self.sink_id.strip()
        title = self.title.strip()
        if not sink_id:
            raise ValueError("sink_id must not be empty")
        if sink_id != self.sink_id:
            raise ValueError("sink_id must not contain surrounding whitespace")
        if _SINK_ID_RE.fullmatch(sink_id) is None:
            raise ValueError("sink_id must be a lowercase ASCII slug")
        if not title or "\n" in title or "\r" in title:
            raise ValueError("sink title must be non-empty single-line text")
        if self.events is not None:
            if not isinstance(self.events, frozenset) or any(
                not isinstance(event, SoundEvent) for event in self.events
            ):
                raise TypeError(
                    "events filter must be a SoundEvent frozenset or None"
                )
            if not self.events:
                raise ValueError("events filter must be non-empty when provided")
        object.__setattr__(self, "title", title)

    def accepts(self, event: SoundEvent) -> bool:
        if not isinstance(event, SoundEvent):
            raise TypeError("event must be a SoundEvent")
        return self.events is None or event in self.events


@dataclass(frozen=True)
class SoundDeliveryFailure:
    sink_id: str
    event: SoundEvent
    error_type: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.sink_id, str):
            raise TypeError("failure sink_id must be text")
        if _SINK_ID_RE.fullmatch(self.sink_id) is None:
            raise ValueError("failure sink_id must be a canonical ASCII slug")
        if not isinstance(self.event, SoundEvent):
            raise TypeError("failure event must be a SoundEvent")
        if (
            not isinstance(self.error_type, str)
            or not self.error_type.strip()
            or "\n" in self.error_type
            or "\r" in self.error_type
        ):
            raise ValueError("failure error_type must be non-empty single-line text")
        if not isinstance(self.message, str):
            raise TypeError("failure message must be text")


@dataclass(frozen=True)
class SoundDeliveryReport:
    attempted: int
    delivered: int
    failures: tuple[SoundDeliveryFailure, ...]

    def __post_init__(self) -> None:
        if type(self.attempted) is not int:
            raise TypeError("attempted must be an integer")
        if self.attempted < 0:
            raise ValueError("attempted must be a non-negative integer")
        if type(self.delivered) is not int:
            raise TypeError("delivered must be an integer")
        if self.delivered < 0:
            raise ValueError("delivered must be a non-negative integer")
        if (
            not isinstance(self.failures, tuple)
            or any(not isinstance(item, SoundDeliveryFailure) for item in self.failures)
        ):
            raise TypeError("failures must be a tuple of SoundDeliveryFailure")
        if self.attempted != self.delivered + len(self.failures):
            raise ValueError("attempted must equal delivered plus failures")

    @property
    def ok(self) -> bool:
        return not self.failures


class SoundEventSinkRegistry:
    """Named registration point and fault-isolating dispatcher for sound sinks."""

    def __init__(self) -> None:
        self._descriptors: dict[str, SoundSinkDescriptor] = {}
        self._sinks: dict[str, SoundEventSink] = {}

    def register(self, descriptor: SoundSinkDescriptor, sink: SoundEventSink) -> None:
        if not isinstance(descriptor, SoundSinkDescriptor):
            raise TypeError("descriptor must be SoundSinkDescriptor")
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
        if event is not None and not isinstance(event, SoundEvent):
            raise TypeError("event must be a SoundEvent or None")
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
                try:
                    message = str(exc)
                except Exception:
                    message = "<unprintable adapter error>"
                failures.append(
                    SoundDeliveryFailure(
                        sink_id=descriptor.sink_id,
                        event=event,
                        error_type=type(exc).__name__,
                        message=message,
                    )
                )
            else:
                delivered += 1
        return SoundDeliveryReport(attempted, delivered, tuple(failures))

    def emit_many(self, events: Iterable[SoundEvent]) -> tuple[SoundDeliveryReport, ...]:
        try:
            queued = tuple(events)
        except TypeError as exc:
            raise TypeError("events must be an iterable of SoundEvent") from exc
        for event in queued:
            if not isinstance(event, SoundEvent):
                raise TypeError("events must contain only SoundEvent values")
        return tuple(self.emit(event) for event in queued)

    @staticmethod
    def _normalize_sink_id(sink_id: str) -> str:
        if not isinstance(sink_id, str):
            raise TypeError("sink_id must be text")
        value = sink_id.strip().casefold()
        if not value or _SINK_ID_RE.fullmatch(value) is None:
            raise ValueError("sink_id must be a non-empty ASCII slug")
        return value
