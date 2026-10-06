from __future__ import annotations

"""Chunked local speech-recognition contracts for Accessible Chess media.

Adapted from Oleksii-debug/Nika-Core@6df8b80b7a248f1559a0ff96f74efa2d2c47ad14
src/nika_core/media/transcription.py and media/contracts.py.
The original Pydantic storage models are reduced to stdlib dataclasses so the
desktop product does not gain a mandatory Pydantic dependency.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from .media_errors import MediaError, MediaErrorCode
from .media_foundation import TranscriptSegment

Segment = TranscriptSegment


class ChunkState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    engine_id: str
    name: str
    version: str
    license_id: str
    source_reference: str

    def __post_init__(self) -> None:
        for field_name in (
            "engine_id",
            "name",
            "version",
            "license_id",
            "source_reference",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{field_name} must be non-empty text")


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    model_id: str
    engine_id: str
    version: str
    license_reference: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "model_id",
            "engine_id",
            "version",
            "license_reference",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{field_name} must be non-empty text")
        if self.sha256 is not None:
            if (
                type(self.sha256) is not str
                or len(self.sha256) != 64
                or any(ch not in "0123456789abcdef" for ch in self.sha256)
            ):
                raise ValueError("sha256 must be lowercase SHA-256 text")


@dataclass(frozen=True, slots=True)
class TranscriptionChunk:
    chunk_id: str
    job_id: str
    ordinal: int
    start_ms: int
    end_ms: int
    core_start_ms: int
    core_end_ms: int
    state: ChunkState = ChunkState.PENDING
    audio_sha256: str | None = None
    segments: tuple[Segment, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("chunk_id", "job_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{field_name} must be non-empty text")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        for field_name in (
            "start_ms",
            "end_ms",
            "core_start_ms",
            "core_end_ms",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.end_ms <= self.start_ms:
            raise ValueError("chunk end_ms must be greater than start_ms")
        if not (
            self.start_ms
            <= self.core_start_ms
            < self.core_end_ms
            <= self.end_ms
        ):
            raise ValueError("chunk core bounds must lie inside chunk bounds")
        if not isinstance(self.state, ChunkState):
            object.__setattr__(self, "state", ChunkState(self.state))
        if self.audio_sha256 is not None and (
            type(self.audio_sha256) is not str
            or len(self.audio_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.audio_sha256)
        ):
            raise ValueError("audio_sha256 must be lowercase SHA-256 text")
        if type(self.segments) is not tuple or any(
            type(item) is not Segment for item in self.segments
        ):
            raise TypeError("segments must be a Segment tuple")


@dataclass(frozen=True, slots=True)
class TranscriptionRequest:
    chunk_id: str
    audio_path: Path
    offset_ms: int = 0
    language: str | None = None
    prompt: str | None = None

    def __post_init__(self) -> None:
        if type(self.chunk_id) is not str or not self.chunk_id.strip():
            raise ValueError("chunk_id must be non-empty text")
        if type(self.audio_path) is not type(Path()):
            raise TypeError("audio_path must be Path")
        if type(self.offset_ms) is not int or self.offset_ms < 0:
            raise ValueError("offset_ms must be non-negative")
        if self.language is not None and (
            type(self.language) is not str or not self.language.strip()
        ):
            raise ValueError("language must be non-empty text or None")
        if self.prompt is not None and (
            type(self.prompt) is not str or len(self.prompt) > 2000
        ):
            raise ValueError("prompt must be text up to 2000 characters")


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    chunk_id: str
    language: str | None
    segments: tuple[Segment, ...]
    engine: EngineDescriptor
    model: ModelDescriptor
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if type(self.chunk_id) is not str or not self.chunk_id.strip():
            raise ValueError("chunk_id must be non-empty text")
        if type(self.segments) is not tuple or any(
            type(item) is not Segment for item in self.segments
        ):
            raise TypeError("segments must be a Segment tuple")
        if isinstance(self.elapsed_seconds, bool) or not isinstance(
            self.elapsed_seconds, (int, float)
        ) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be non-negative")


class OfflineTranscriberPort(Protocol):
    @property
    def engine(self) -> EngineDescriptor: ...

    @property
    def model(self) -> ModelDescriptor: ...

    def transcribe(
        self,
        request: TranscriptionRequest,
    ) -> TranscriptionResult: ...


@dataclass(frozen=True, slots=True)
class ChunkPlanPolicy:
    chunk_ms: int = 30_000
    overlap_ms: int = 2_000

    def __post_init__(self) -> None:
        if type(self.chunk_ms) is not int or self.chunk_ms <= 0:
            raise ValueError("chunk_ms must be positive")
        if (
            type(self.overlap_ms) is not int
            or self.overlap_ms < 0
            or self.overlap_ms * 2 >= self.chunk_ms
        ):
            raise ValueError(
                "overlap_ms must be non-negative and less than half chunk_ms"
            )


def plan_chunks(
    *,
    job_id: str,
    duration_ms: int,
    policy: ChunkPlanPolicy | None = None,
) -> tuple[TranscriptionChunk, ...]:
    if type(job_id) is not str or not job_id.strip():
        raise ValueError("job_id must be non-empty text")
    if type(duration_ms) is not int or duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    if duration_ms == 0:
        return ()
    selected = policy or ChunkPlanPolicy()
    chunks: list[TranscriptionChunk] = []
    core_start = 0
    ordinal = 0
    while core_start < duration_ms:
        core_end = min(core_start + selected.chunk_ms, duration_ms)
        start = max(0, core_start - selected.overlap_ms)
        end = min(duration_ms, core_end + selected.overlap_ms)
        chunks.append(
            TranscriptionChunk(
                chunk_id=f"{job_id}:{ordinal:06d}",
                job_id=job_id,
                ordinal=ordinal,
                start_ms=start,
                end_ms=end,
                core_start_ms=core_start,
                core_end_ms=core_end,
            )
        )
        core_start = core_end
        ordinal += 1
    return tuple(chunks)


def merge_completed_chunks(
    chunks: tuple[TranscriptionChunk, ...],
) -> tuple[Segment, ...]:
    if not chunks:
        return ()
    ordered = sorted(chunks, key=lambda item: item.ordinal)
    if [item.ordinal for item in ordered] != list(range(len(ordered))):
        raise ValueError("chunk ordinals must be contiguous from zero")

    merged: list[Segment] = []
    for chunk in ordered:
        if chunk.state is not ChunkState.COMPLETED:
            raise MediaError(
                MediaErrorCode.COMPONENT_MISSING,
                f"transcription chunk {chunk.chunk_id} is not completed",
                retryable=True,
            )
        for segment in chunk.segments:
            midpoint = (
                segment.start_ms
                + (segment.end_ms - segment.start_ms) // 2
            )
            if (
                midpoint < chunk.core_start_ms
                or midpoint >= chunk.core_end_ms
            ):
                continue
            if merged and segment.start_ms < merged[-1].start_ms:
                raise ValueError(
                    "merged transcription segments must remain monotonic"
                )
            merged.append(segment)
    return tuple(merged)
