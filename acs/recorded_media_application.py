from __future__ import annotations

"""Bridge recorded-media evidence to the canonical chess application authority.

This adapter intentionally owns no chess parsing, move legality, board mutation,
or game-tree semantics. It gives the existing application authority typed media
evidence and converts only its opaque canonical reference into Media Core data.
"""

from dataclasses import dataclass
import math
from typing import Protocol, runtime_checkable

from .media_core import MediaChessLink, MediaLinkStatus
from .media_preprocess import BoardFrameEvidence, FrameDisposition, SpeechEvidence


MAX_APPLICATION_REF = 4096


class RecordedMediaApplicationAdapterError(ValueError):
    """Fail-closed contract error at the media/application boundary."""


def _text(value: object, name: str, *, limit: int = MAX_APPLICATION_REF) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise RecordedMediaApplicationAdapterError(f"invalid {name}")
    if "\x00" in value or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise RecordedMediaApplicationAdapterError(f"unsafe {name}")
    return value


def _confidence(value: object) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise RecordedMediaApplicationAdapterError("invalid canonical confidence")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise RecordedMediaApplicationAdapterError("invalid canonical confidence")
    return number


@dataclass(frozen=True, slots=True)
class CanonicalRecordedPositionResolution:
    """Opaque decision returned by the canonical application layer.

    ``chess_ref`` identifies state already owned by that layer. The adapter
    never interprets it and therefore cannot become an alternate rules engine.
    """

    chess_ref: str
    confirmed: bool
    confidence: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "chess_ref", _text(self.chess_ref, "chess_ref"))
        if type(self.confirmed) is not bool:
            raise RecordedMediaApplicationAdapterError("confirmed must be boolean")
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@runtime_checkable
class CanonicalPositionApplicationPort(Protocol):
    """Existing application authority capable of reconciling media evidence.

    Implementations are responsible for all canonical chess semantics. They
    may consult the application's current GameTree/position services, but must
    return only a reference to canonical state that already belongs to them.
    """

    def reconcile_recorded_observation(
        self,
        *,
        frame: BoardFrameEvidence,
        speech_context: tuple[SpeechEvidence, ...],
    ) -> CanonicalRecordedPositionResolution | None: ...


class CanonicalRecordedFrameApplicationAdapter:
    """Concrete ``CanonicalRecordedFramePort`` backed by application authority."""

    def __init__(self, application: CanonicalPositionApplicationPort) -> None:
        reconcile = getattr(application, "reconcile_recorded_observation", None)
        if not callable(reconcile):
            raise RecordedMediaApplicationAdapterError(
                "canonical position application port is required"
            )
        self._application = application

    def resolve_recorded_frame(
        self,
        *,
        frame: BoardFrameEvidence,
        speech_context: tuple[SpeechEvidence, ...],
    ) -> MediaChessLink | None:
        if type(frame) is not BoardFrameEvidence:
            raise RecordedMediaApplicationAdapterError(
                "frame must be an exact BoardFrameEvidence"
            )
        if type(speech_context) is not tuple or any(
            type(item) is not SpeechEvidence for item in speech_context
        ):
            raise RecordedMediaApplicationAdapterError(
                "speech_context must contain exact SpeechEvidence values"
            )
        if frame.disposition in (FrameDisposition.TRANSITION, FrameDisposition.OCCLUDED):
            raise RecordedMediaApplicationAdapterError(
                "non-resolvable frame disposition reached canonical application adapter"
            )

        resolution = self._application.reconcile_recorded_observation(
            frame=frame,
            speech_context=speech_context,
        )
        if resolution is None:
            return None
        if type(resolution) is not CanonicalRecordedPositionResolution:
            raise RecordedMediaApplicationAdapterError(
                "application returned an invalid recorded-position resolution"
            )
        if frame.disposition is FrameDisposition.AMBIGUOUS and resolution.confirmed:
            raise RecordedMediaApplicationAdapterError(
                "ambiguous recorded evidence cannot confirm canonical chess state"
            )

        return MediaChessLink(
            source_id=frame.source_id,
            timestamp_ms=frame.timestamp_ms,
            chess_ref=resolution.chess_ref,
            status=(
                MediaLinkStatus.CONFIRMED
                if resolution.confirmed
                else MediaLinkStatus.CANDIDATE
            ),
            confidence=resolution.confidence,
            evidence="recorded-media canonical application reconciliation",
        )
