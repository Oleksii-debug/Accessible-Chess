from __future__ import annotations

"""Bridge recorded-media adapter evidence to canonical chess reconciliation.

BoardVision/Speech DTOs stop at this boundary. They are revalidated and converted
into provider-neutral MediaEvidence values before canonical chess application
code is invoked. Chess legality and GameTree semantics remain application-owned.
"""

from hashlib import sha256
import json
from typing import Protocol, runtime_checkable

from .media_core import (
    MAX_MEDIA_RECONCILIATION_REFS,
    ChessStateReconciler,
    MediaContractError,
    MediaEvidence,
    MediaEvidenceField,
    MediaEvidenceKind,
    MediaReconciliationResult,
    MediaReconciliationState,
)
from .media_preprocess import (
    BoardFrameEvidence,
    BoardOrientation,
    FrameDisposition,
    SpeechEvidence,
)
from .recorded_media_sync import MAX_SPEECH_CONTEXT


MAX_APPLICATION_REF = 4096


class RecordedMediaApplicationAdapterError(ValueError):
    """Fail-closed contract error at the media/application boundary."""


def _text(value: object, name: str, *, limit: int = MAX_APPLICATION_REF) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise RecordedMediaApplicationAdapterError(f"invalid {name}")
    if "\x00" in value or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise RecordedMediaApplicationAdapterError(f"unsafe {name}")
    return value


def _detached_frame(frame: object) -> BoardFrameEvidence:
    if type(frame) is not BoardFrameEvidence:
        raise RecordedMediaApplicationAdapterError(
            "frame must be an exact BoardFrameEvidence"
        )
    if (
        type(frame.disposition) is not FrameDisposition
        or type(frame.orientation) is not BoardOrientation
    ):
        raise RecordedMediaApplicationAdapterError("frame evidence enum is invalid")
    try:
        return BoardFrameEvidence(
            source_id=frame.source_id,
            source_revision=frame.source_revision,
            timestamp_ms=frame.timestamp_ms,
            disposition=frame.disposition,
            orientation=frame.orientation,
            confidence=frame.confidence,
            observation_ref=frame.observation_ref,
            square_confidence=frame.square_confidence,
        )
    except Exception:
        raise RecordedMediaApplicationAdapterError(
            "frame evidence is malformed"
        ) from None


def _detached_speech(value: object) -> tuple[SpeechEvidence, ...]:
    if type(value) is not tuple:
        raise RecordedMediaApplicationAdapterError(
            "speech_context must contain exact SpeechEvidence values"
        )
    if len(value) > MAX_SPEECH_CONTEXT:
        raise RecordedMediaApplicationAdapterError(
            "speech_context exceeds the recorded-sync limit"
        )
    # One board item is always part of the reconciliation bundle.
    if len(value) + 1 > MAX_MEDIA_RECONCILIATION_REFS:
        raise RecordedMediaApplicationAdapterError(
            "speech_context exceeds the canonical evidence-bundle limit"
        )
    detached: list[SpeechEvidence] = []
    for item in value:
        if type(item) is not SpeechEvidence:
            raise RecordedMediaApplicationAdapterError(
                "speech_context must contain exact SpeechEvidence values"
            )
        try:
            detached.append(
                SpeechEvidence(
                    source_id=item.source_id,
                    source_revision=item.source_revision,
                    start_ms=item.start_ms,
                    end_ms=item.end_ms,
                    text=item.text,
                    is_final=item.is_final,
                    confidence=item.confidence,
                )
            )
        except Exception:
            raise RecordedMediaApplicationAdapterError(
                "speech_context contains malformed evidence"
            ) from None
    return tuple(detached)


def _evidence_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")
    return f"{prefix}:{sha256(encoded).hexdigest()}"


def _board_media_evidence(frame: BoardFrameEvidence) -> MediaEvidence:
    square_text = None
    if frame.square_confidence is not None:
        square_text = ",".join(format(value, ".8g") for value in frame.square_confidence)
    fields = [
        MediaEvidenceField("disposition", frame.disposition.value),
        MediaEvidenceField("orientation", frame.orientation.value),
    ]
    if square_text is not None:
        fields.append(MediaEvidenceField("square_confidence", square_text))
    identity_payload = {
        "source_id": frame.source_id,
        "source_revision": frame.source_revision,
        "timestamp_ms": frame.timestamp_ms,
        "disposition": frame.disposition.value,
        "orientation": frame.orientation.value,
        "confidence": frame.confidence,
        "observation_ref": frame.observation_ref,
        "square_confidence": frame.square_confidence,
    }
    return MediaEvidence(
        evidence_id=_evidence_id("recorded-board", identity_payload),
        source_id=frame.source_id,
        kind=MediaEvidenceKind.BOARD_OBSERVATION,
        start_ms=frame.timestamp_ms,
        end_ms=frame.timestamp_ms,
        fields=tuple(fields),
        confidence=frame.confidence,
        source_authoritative=False,
        source_revision=frame.source_revision,
        provider_id="recorded-media",
        producer_revision="board-vision-adapter-v1",
        provenance="recorded board observation; chess truth remains canonical",
        raw_candidate_ref=frame.observation_ref,
    )


def _speech_media_evidence(item: SpeechEvidence, index: int) -> MediaEvidence:
    payload = {
        "source_id": item.source_id,
        "source_revision": item.source_revision,
        "start_ms": item.start_ms,
        "end_ms": item.end_ms,
        "text": item.text,
        "is_final": item.is_final,
        "confidence": item.confidence,
        "index": index,
    }
    return MediaEvidence(
        evidence_id=_evidence_id("recorded-speech", payload),
        source_id=item.source_id,
        kind=MediaEvidenceKind.SPEECH_CONTEXT,
        start_ms=item.start_ms,
        end_ms=item.end_ms,
        fields=(
            MediaEvidenceField("text", item.text),
            MediaEvidenceField("is_final", "true" if item.is_final else "false"),
        ),
        confidence=item.confidence,
        source_authoritative=False,
        source_revision=item.source_revision,
        provider_id="recorded-media",
        producer_revision="speech-context-adapter-v1",
        provenance="recorded speech context; never legal-move authority",
    )


@runtime_checkable
class CanonicalPositionApplicationPort(Protocol):
    """Canonical chess authority consumed through Media Core reconciliation."""

    def reconcile_media_evidence_batch(
        self,
        *,
        current_chess_ref: str | None,
        evidence: tuple[MediaEvidence, ...],
    ) -> MediaReconciliationResult:
        ...


class CanonicalRecordedFrameApplicationAdapter:
    """Concrete recorded-frame port backed by canonical Media reconciliation."""

    def __init__(self, application: CanonicalPositionApplicationPort) -> None:
        reconcile = getattr(application, "reconcile_media_evidence_batch", None)
        if not callable(reconcile):
            raise RecordedMediaApplicationAdapterError(
                "canonical batch reconciliation port is required"
            )
        try:
            self._reconciler = ChessStateReconciler(application)
        except MediaContractError:
            raise RecordedMediaApplicationAdapterError(
                "canonical reconciliation port is invalid"
            ) from None

    @staticmethod
    def _bundle(
        frame: BoardFrameEvidence,
        speech_context: tuple[SpeechEvidence, ...],
    ) -> tuple[MediaEvidence, ...]:
        return (
            _board_media_evidence(frame),
            *tuple(
                _speech_media_evidence(item, index)
                for index, item in enumerate(speech_context)
            ),
        )

    def resolve_recorded_frame(
        self,
        *,
        frame: BoardFrameEvidence,
        speech_context: tuple[SpeechEvidence, ...],
    ) -> MediaReconciliationResult:
        safe_frame = _detached_frame(frame)
        safe_speech = _detached_speech(speech_context)
        for item in safe_speech:
            if item.source_id != safe_frame.source_id:
                raise RecordedMediaApplicationAdapterError(
                    "speech_context belongs to a different recorded source"
                )
            if item.source_revision != safe_frame.source_revision:
                raise RecordedMediaApplicationAdapterError(
                    "speech_context belongs to a stale recorded source revision"
                )
        if safe_frame.disposition in (
            FrameDisposition.TRANSITION,
            FrameDisposition.OCCLUDED,
        ):
            raise RecordedMediaApplicationAdapterError(
                "non-resolvable frame disposition reached canonical application adapter"
            )

        bundle = self._bundle(safe_frame, safe_speech)
        try:
            result = self._reconciler.reconcile_many(bundle)
        except MediaContractError:
            raise RecordedMediaApplicationAdapterError(
                "canonical recorded-media reconciliation failed closed"
            ) from None

        if (
            safe_frame.disposition is FrameDisposition.AMBIGUOUS
            and result.state
            in (
                MediaReconciliationState.VERIFIED,
                MediaReconciliationState.INFERRED,
            )
        ):
            raise RecordedMediaApplicationAdapterError(
                "ambiguous recorded evidence cannot confirm canonical chess state"
            )
        return result


__all__ = [
    "CanonicalPositionApplicationPort",
    "CanonicalRecordedFrameApplicationAdapter",
    "RecordedMediaApplicationAdapterError",
]
