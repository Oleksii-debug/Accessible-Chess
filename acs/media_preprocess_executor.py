from __future__ import annotations

"""Synchronous adapter runner for recorded-media preprocessing evidence."""

from dataclasses import dataclass
from typing import Iterable

from acs.media_preprocess import (
    BoardFrameEvidence,
    BoardVisionPort,
    MAX_SPEECH,
    PreprocessCheckpoint,
    PreprocessContractError,
    PreprocessErrorCode,
    PreprocessStatus,
    RecordedMediaPreprocessPlan,
    RecordedMediaPreprocessRun,
    SpeechContextPort,
    SpeechEvidence,
)


@dataclass(frozen=True, slots=True)
class PreprocessStepResult:
    board_evidence: BoardFrameEvidence
    checkpoint: PreprocessCheckpoint


def _revision(port: object, name: str) -> str:
    revision = getattr(port, "revision_id", None)
    if type(revision) is not str or not revision.strip():
        raise PreprocessContractError(f"invalid {name} revision", code=PreprocessErrorCode.INVALID)
    return revision


class RecordedMediaPreprocessExecutor:
    """Calls replaceable evidence ports while the core run owns progress and validation."""

    def __init__(
        self,
        plan: RecordedMediaPreprocessPlan,
        board_port: BoardVisionPort,
        *,
        speech_port: SpeechContextPort | None = None,
        checkpoint: PreprocessCheckpoint | None = None,
    ):
        if not isinstance(plan, RecordedMediaPreprocessPlan):
            raise PreprocessContractError("invalid plan", code=PreprocessErrorCode.INVALID)
        board_revision = _revision(board_port, "board")
        if board_revision != plan.cache_key.board_revision:
            raise PreprocessContractError("board revision mismatch", code=PreprocessErrorCode.REVISION_MISMATCH)
        if speech_port is None:
            if plan.cache_key.speech_revision is not None:
                raise PreprocessContractError("speech port required", code=PreprocessErrorCode.INVALID_STATE)
        else:
            speech_revision = _revision(speech_port, "speech")
            if speech_revision != plan.cache_key.speech_revision:
                raise PreprocessContractError("speech revision mismatch", code=PreprocessErrorCode.REVISION_MISMATCH)
        self.plan = plan
        self.board_port = board_port
        self.speech_port = speech_port
        self.run = RecordedMediaPreprocessRun(plan, checkpoint)

    def step_board(self) -> PreprocessStepResult | None:
        request = self.run.current_request
        if request is None:
            return None
        evidence = self.board_port.observe(self.plan.source.source_ref, request.timestamp_ms)
        # Progress changes only after the core accepts exact source/revision/timestamp evidence.
        self.run.accept_board(evidence)
        return PreprocessStepResult(evidence, self.run.checkpoint())

    def collect_speech(self, start_ms: int, end_ms: int) -> tuple[SpeechEvidence, ...]:
        if type(start_ms) is not int or type(end_ms) is not int or start_ms < 0 or end_ms < start_ms:
            raise PreprocessContractError("invalid speech request range", code=PreprocessErrorCode.INVALID)
        if end_ms > self.plan.source.duration_ms:
            raise PreprocessContractError("speech request outside duration", code=PreprocessErrorCode.INVALID)
        if self.run.status is not PreprocessStatus.RUNNING:
            raise PreprocessContractError("run not running", code=PreprocessErrorCode.INVALID_STATE)
        if self.speech_port is None:
            raise PreprocessContractError("speech port unavailable", code=PreprocessErrorCode.INVALID_STATE)

        remaining = MAX_SPEECH - self.run.speech_count
        if remaining <= 0:
            raise PreprocessContractError("speech evidence limit", code=PreprocessErrorCode.LIMIT)

        # Validate the complete bounded provider batch before publishing any
        # checkpoint progress. A malformed or interrupted provider stream must
        # therefore be retryable without duplicating earlier evidence counts.
        accepted: list[SpeechEvidence] = []
        for index, evidence in enumerate(
            self.speech_port.evidence_for_range(
                self.plan.source.source_ref,
                start_ms,
                end_ms,
            )
        ):
            if index >= remaining:
                raise PreprocessContractError("speech provider result limit", code=PreprocessErrorCode.LIMIT)
            self.run.validate_speech(evidence)
            accepted.append(evidence)

        for evidence in accepted:
            self.run.accept_speech(evidence)
        return tuple(accepted)

    def cancel(self) -> PreprocessCheckpoint:
        return self.run.cancel()

    @property
    def status(self) -> PreprocessStatus:
        return self.run.status


class FixtureBoardVisionPort:
    """Deterministic offline evidence port for qualification fixtures."""

    def __init__(self, revision_id: str, evidence: Iterable[BoardFrameEvidence]):
        self.revision_id = revision_id
        self._by_timestamp: dict[int, BoardFrameEvidence] = {}
        for item in evidence:
            if not isinstance(item, BoardFrameEvidence) or item.timestamp_ms in self._by_timestamp:
                raise PreprocessContractError("invalid/duplicate board fixture", code=PreprocessErrorCode.INVALID)
            self._by_timestamp[item.timestamp_ms] = item

    def observe(self, source_ref: str, timestamp_ms: int) -> BoardFrameEvidence:
        try:
            return self._by_timestamp[timestamp_ms]
        except KeyError as exc:
            raise PreprocessContractError("missing board fixture", code=PreprocessErrorCode.REQUEST_MISMATCH) from exc


class FixtureSpeechContextPort:
    """Deterministic offline speech evidence port for qualification fixtures."""

    def __init__(self, revision_id: str, evidence: Iterable[SpeechEvidence]):
        self.revision_id = revision_id
        items = tuple(evidence)
        if any(not isinstance(item, SpeechEvidence) for item in items):
            raise PreprocessContractError("invalid speech fixture", code=PreprocessErrorCode.INVALID)
        self._evidence = tuple(sorted(items, key=lambda item: (item.start_ms, item.end_ms, item.text)))

    def evidence_for_range(self, source_ref: str, start_ms: int, end_ms: int) -> tuple[SpeechEvidence, ...]:
        return tuple(item for item in self._evidence if item.end_ms >= start_ms and item.start_ms <= end_ms)
