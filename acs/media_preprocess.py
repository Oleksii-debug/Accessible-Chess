from __future__ import annotations

"""Bounded recorded-media evidence preprocessing; never a chess-rules authority."""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from typing import Iterable, Protocol

SCHEMA = "accessible-chess.recorded-media-preprocess"
VERSION = 1
MAX_DURATION_MS = 7 * 24 * 60 * 60 * 1000
MAX_SAMPLES = 250_000
MAX_HINTS = 50_000
MAX_SPEECH = 500_000
MAX_TEXT = 16_384
MAX_CHECKPOINT_BYTES = 64 * 1024


class PreprocessErrorCode(str, Enum):
    INVALID = "invalid"
    LIMIT = "limit"
    SOURCE_MISMATCH = "source_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    REQUEST_MISMATCH = "request_mismatch"
    CHECKPOINT_MISMATCH = "checkpoint_mismatch"
    INVALID_STATE = "invalid_state"
    INVALID_SCHEMA = "invalid_schema"


class PreprocessContractError(ValueError):
    def __init__(self, message: str, *, code: PreprocessErrorCode):
        super().__init__(message)
        self.code = PreprocessErrorCode(code)


def _text(value: object, name: str, limit: int = 512) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise PreprocessContractError(f"invalid {name}", code=PreprocessErrorCode.INVALID)
    return value


def _nat(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise PreprocessContractError(f"invalid {name}", code=PreprocessErrorCode.INVALID)
    return value


def _confidence(value: object) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise PreprocessContractError("invalid confidence", code=PreprocessErrorCode.INVALID)
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise PreprocessContractError("invalid confidence", code=PreprocessErrorCode.INVALID)
    return value


def _bounded_tuple(
    values: Iterable[object],
    *,
    limit: int,
    too_many: str,
) -> tuple[object, ...]:
    """Materialize at most the configured limit without exhausting an untrusted iterable."""

    try:
        iterator = iter(values)
    except TypeError as exc:
        raise PreprocessContractError("invalid iterable", code=PreprocessErrorCode.INVALID) from exc
    items: list[object] = []
    for index, item in enumerate(iterator):
        if index >= limit:
            raise PreprocessContractError(too_many, code=PreprocessErrorCode.LIMIT)
        items.append(item)
    return tuple(items)


class FrameDisposition(str, Enum):
    STABLE = "stable"
    TRANSITION = "transition"
    OCCLUDED = "occluded"
    AMBIGUOUS = "ambiguous"


class BoardOrientation(str, Enum):
    WHITE_BOTTOM = "white_bottom"
    BLACK_BOTTOM = "black_bottom"
    UNKNOWN = "unknown"


class PreprocessStatus(str, Enum):
    RUNNING = "running"
    CANCELED = "canceled"
    COMPLETE = "complete"


class BoardVisionPort(Protocol):
    revision_id: str
    def observe(self, source_ref: str, timestamp_ms: int) -> "BoardFrameEvidence": ...


class SpeechContextPort(Protocol):
    revision_id: str
    def evidence_for_range(self, source_ref: str, start_ms: int, end_ms: int) -> Iterable["SpeechEvidence"]: ...


@dataclass(frozen=True, slots=True)
class RecordedMediaSourceRevision:
    source_id: str
    source_revision: str
    source_ref: str
    duration_ms: int

    def __post_init__(self):
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "source_revision", _text(self.source_revision, "source_revision"))
        object.__setattr__(self, "source_ref", _text(self.source_ref, "source_ref", 4096))
        duration = _nat(self.duration_ms, "duration_ms")
        if duration > MAX_DURATION_MS:
            raise PreprocessContractError("duration too large", code=PreprocessErrorCode.LIMIT)
        object.__setattr__(self, "duration_ms", duration)


@dataclass(frozen=True, slots=True)
class PreprocessCacheKey:
    source_id: str
    source_revision: str
    board_revision: str
    speech_revision: str | None
    policy_revision: str

    def __post_init__(self):
        for name in ("source_id", "source_revision", "board_revision", "policy_revision"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.speech_revision is not None:
            object.__setattr__(self, "speech_revision", _text(self.speech_revision, "speech_revision"))

    def fingerprint(self) -> str:
        body = json.dumps([self.source_id, self.source_revision, self.board_revision,
                           self.speech_revision, self.policy_revision], ensure_ascii=False,
                          separators=(",", ":")).encode()
        return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True, slots=True)
class FrameSampleRequest:
    timestamp_ms: int
    refined: bool = False

    def __post_init__(self):
        object.__setattr__(self, "timestamp_ms", _nat(self.timestamp_ms, "timestamp_ms"))
        if type(self.refined) is not bool:
            raise PreprocessContractError("invalid refined", code=PreprocessErrorCode.INVALID)


@dataclass(frozen=True, slots=True)
class AdaptiveSamplingPolicy:
    baseline_interval_ms: int = 1000
    refinement_interval_ms: int = 200
    refinement_radius_ms: int = 1000
    max_samples: int = MAX_SAMPLES
    revision: str = "adaptive-v1"

    def __post_init__(self):
        for n in ("baseline_interval_ms", "refinement_interval_ms"):
            if type(getattr(self, n)) is not int or getattr(self, n) <= 0:
                raise PreprocessContractError(f"invalid {n}", code=PreprocessErrorCode.INVALID)
        _nat(self.refinement_radius_ms, "refinement_radius_ms")
        if type(self.max_samples) is not int or not 0 < self.max_samples <= MAX_SAMPLES:
            raise PreprocessContractError("invalid max_samples", code=PreprocessErrorCode.LIMIT)
        object.__setattr__(self, "revision", _text(self.revision, "revision"))

    def requests(self, duration_ms: int, transition_hints_ms: Iterable[int] = ()) -> tuple[FrameSampleRequest, ...]:
        duration = _nat(duration_ms, "duration_ms")
        if duration > MAX_DURATION_MS:
            raise PreprocessContractError("duration too large", code=PreprocessErrorCode.LIMIT)
        hints = _bounded_tuple(
            transition_hints_ms,
            limit=MAX_HINTS,
            too_many="too many hints",
        )
        baseline_count = duration // self.baseline_interval_ms + 1
        if duration % self.baseline_interval_ms:
            baseline_count += 1  # explicit terminal sample
        if baseline_count > self.max_samples:
            raise PreprocessContractError("sampling limit", code=PreprocessErrorCode.LIMIT)
        points: dict[int, bool] = {t: False for t in range(0, duration + 1, self.baseline_interval_ms)}
        points[duration] = points.get(duration, False)
        for raw in hints:
            hint = _nat(raw, "transition_hint")
            if hint > duration:
                raise PreprocessContractError("hint outside duration", code=PreprocessErrorCode.INVALID)
            lo, hi = max(0, hint - self.refinement_radius_ms), min(duration, hint + self.refinement_radius_ms)
            for t in range(lo, hi + 1, self.refinement_interval_ms):
                points[t] = True
            points[hint] = True
            points[hi] = True
            if len(points) > self.max_samples:
                raise PreprocessContractError("sampling limit", code=PreprocessErrorCode.LIMIT)
        return tuple(FrameSampleRequest(t, points[t]) for t in sorted(points))


@dataclass(frozen=True, slots=True)
class BoardFrameEvidence:
    source_id: str
    source_revision: str
    timestamp_ms: int
    disposition: FrameDisposition
    orientation: BoardOrientation = BoardOrientation.UNKNOWN
    confidence: float = 0.0
    observation_ref: str | None = None
    square_confidence: tuple[float, ...] | None = None

    def __post_init__(self):
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "source_revision", _text(self.source_revision, "source_revision"))
        object.__setattr__(self, "timestamp_ms", _nat(self.timestamp_ms, "timestamp_ms"))
        try:
            object.__setattr__(self, "disposition", FrameDisposition(self.disposition))
            object.__setattr__(self, "orientation", BoardOrientation(self.orientation))
        except (TypeError, ValueError) as exc:
            raise PreprocessContractError("invalid evidence enum", code=PreprocessErrorCode.INVALID) from exc
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.observation_ref is not None:
            object.__setattr__(self, "observation_ref", _text(self.observation_ref, "observation_ref", 4096))
        if self.disposition in (FrameDisposition.STABLE, FrameDisposition.AMBIGUOUS) and self.observation_ref is None:
            raise PreprocessContractError("board evidence needs opaque observation", code=PreprocessErrorCode.INVALID_STATE)
        if self.square_confidence is not None:
            if type(self.square_confidence) is not tuple or len(self.square_confidence) != 64:
                raise PreprocessContractError("square confidence must have 64 values", code=PreprocessErrorCode.INVALID)
            object.__setattr__(self, "square_confidence", tuple(_confidence(v) for v in self.square_confidence))


@dataclass(frozen=True, slots=True)
class SpeechEvidence:
    source_id: str
    source_revision: str
    start_ms: int
    end_ms: int
    text: str
    is_final: bool
    confidence: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "source_revision", _text(self.source_revision, "source_revision"))
        start, end = _nat(self.start_ms, "start_ms"), _nat(self.end_ms, "end_ms")
        if end < start or type(self.is_final) is not bool:
            raise PreprocessContractError("invalid speech range/state", code=PreprocessErrorCode.INVALID)
        object.__setattr__(self, "start_ms", start); object.__setattr__(self, "end_ms", end)
        object.__setattr__(self, "text", _text(self.text, "text", MAX_TEXT))
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True, slots=True)
class RecordedMediaPreprocessPlan:
    source: RecordedMediaSourceRevision
    cache_key: PreprocessCacheKey
    requests: tuple[FrameSampleRequest, ...]

    def __post_init__(self):
        if not isinstance(self.source, RecordedMediaSourceRevision) or not isinstance(self.cache_key, PreprocessCacheKey):
            raise PreprocessContractError("invalid plan authority", code=PreprocessErrorCode.INVALID)
        if (self.cache_key.source_id, self.cache_key.source_revision) != (self.source.source_id, self.source.source_revision):
            raise PreprocessContractError("plan/cache source mismatch", code=PreprocessErrorCode.SOURCE_MISMATCH)
        if type(self.requests) is not tuple or not self.requests or len(self.requests) > MAX_SAMPLES:
            raise PreprocessContractError("invalid request set", code=PreprocessErrorCode.LIMIT)
        previous = -1
        for request in self.requests:
            if not isinstance(request, FrameSampleRequest):
                raise PreprocessContractError("invalid frame request", code=PreprocessErrorCode.INVALID)
            if request.timestamp_ms <= previous or request.timestamp_ms > self.source.duration_ms:
                raise PreprocessContractError("invalid request order/range", code=PreprocessErrorCode.INVALID)
            previous = request.timestamp_ms

    @classmethod
    def build(cls, source: RecordedMediaSourceRevision, *, board_revision: str,
              speech_revision: str | None = None, policy: AdaptiveSamplingPolicy | None = None,
              transition_hints_ms: Iterable[int] = ()) -> "RecordedMediaPreprocessPlan":
        if not isinstance(source, RecordedMediaSourceRevision):
            raise PreprocessContractError("invalid source", code=PreprocessErrorCode.INVALID)
        policy = policy or AdaptiveSamplingPolicy()
        key = PreprocessCacheKey(source.source_id, source.source_revision, board_revision,
                                 speech_revision, policy.revision)
        return cls(source, key, policy.requests(source.duration_ms, transition_hints_ms))

    def digest(self) -> str:
        body = json.dumps([self.cache_key.fingerprint(), self.source.duration_ms,
                           [(r.timestamp_ms, r.refined) for r in self.requests]], separators=(",", ":")).encode()
        return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True, slots=True)
class PreprocessCheckpoint:
    source_id: str
    source_revision: str
    cache_fingerprint: str
    plan_digest: str
    next_index: int
    total: int
    board_count: int
    speech_count: int
    status: PreprocessStatus

    def __post_init__(self):
        for n in ("source_id", "source_revision", "cache_fingerprint", "plan_digest"):
            object.__setattr__(self, n, _text(getattr(self, n), n))
        vals = [_nat(getattr(self, n), n) for n in ("next_index", "total", "board_count", "speech_count")]
        if vals[0] > vals[1] or vals[2] != vals[0] or vals[3] > MAX_SPEECH or vals[1] > MAX_SAMPLES:
            raise PreprocessContractError("inconsistent checkpoint", code=PreprocessErrorCode.INVALID_STATE)
        try: object.__setattr__(self, "status", PreprocessStatus(self.status))
        except (TypeError, ValueError) as exc: raise PreprocessContractError("invalid status", code=PreprocessErrorCode.INVALID) from exc
        if self.status is PreprocessStatus.COMPLETE and self.next_index != self.total:
            raise PreprocessContractError("incomplete complete checkpoint", code=PreprocessErrorCode.INVALID_STATE)
        if self.status is PreprocessStatus.RUNNING and self.next_index >= self.total:
            raise PreprocessContractError("finished checkpoint cannot be running", code=PreprocessErrorCode.INVALID_STATE)


class RecordedMediaPreprocessRun:
    def __init__(self, plan: RecordedMediaPreprocessPlan, checkpoint: PreprocessCheckpoint | None = None):
        if not isinstance(plan, RecordedMediaPreprocessPlan):
            raise PreprocessContractError("invalid plan", code=PreprocessErrorCode.INVALID)
        self.plan = plan; self._next = 0; self._boards = 0; self._speech = 0
        self._status = PreprocessStatus.COMPLETE if not plan.requests else PreprocessStatus.RUNNING
        if checkpoint is not None: self._restore(checkpoint)

    def _restore(self, c: PreprocessCheckpoint):
        if not isinstance(c, PreprocessCheckpoint):
            raise PreprocessContractError("invalid checkpoint", code=PreprocessErrorCode.INVALID)
        expected = (self.plan.source.source_id, self.plan.source.source_revision,
                    self.plan.cache_key.fingerprint(), self.plan.digest(), len(self.plan.requests))
        actual = (c.source_id, c.source_revision, c.cache_fingerprint, c.plan_digest, c.total)
        if actual != expected:
            raise PreprocessContractError("checkpoint no longer matches plan", code=PreprocessErrorCode.CHECKPOINT_MISMATCH)
        self._next, self._boards, self._speech = c.next_index, c.board_count, c.speech_count
        self._status = PreprocessStatus.COMPLETE if self._next == len(self.plan.requests) else PreprocessStatus.RUNNING

    @property
    def current_request(self) -> FrameSampleRequest | None:
        return self.plan.requests[self._next] if self._status is PreprocessStatus.RUNNING else None

    @property
    def status(self) -> PreprocessStatus: return self._status

    def accept_board(self, evidence: BoardFrameEvidence):
        if self._status is not PreprocessStatus.RUNNING:
            raise PreprocessContractError("run not running", code=PreprocessErrorCode.INVALID_STATE)
        if not isinstance(evidence, BoardFrameEvidence):
            raise PreprocessContractError("invalid board evidence", code=PreprocessErrorCode.INVALID)
        if evidence.source_id != self.plan.source.source_id:
            raise PreprocessContractError("wrong source", code=PreprocessErrorCode.SOURCE_MISMATCH)
        if evidence.source_revision != self.plan.source.source_revision:
            raise PreprocessContractError("stale source revision", code=PreprocessErrorCode.REVISION_MISMATCH)
        if self.current_request is None or evidence.timestamp_ms != self.current_request.timestamp_ms:
            raise PreprocessContractError("wrong requested timestamp", code=PreprocessErrorCode.REQUEST_MISMATCH)
        self._next += 1; self._boards += 1
        if self._next == len(self.plan.requests): self._status = PreprocessStatus.COMPLETE

    @property
    def speech_count(self) -> int:
        return self._speech

    def validate_speech(self, evidence: SpeechEvidence) -> None:
        if self._status is not PreprocessStatus.RUNNING:
            raise PreprocessContractError("run not running", code=PreprocessErrorCode.INVALID_STATE)
        if not isinstance(evidence, SpeechEvidence):
            raise PreprocessContractError("invalid speech evidence", code=PreprocessErrorCode.INVALID)
        if evidence.source_id != self.plan.source.source_id:
            raise PreprocessContractError("wrong source", code=PreprocessErrorCode.SOURCE_MISMATCH)
        if evidence.source_revision != self.plan.source.source_revision:
            raise PreprocessContractError("stale source revision", code=PreprocessErrorCode.REVISION_MISMATCH)
        if evidence.end_ms > self.plan.source.duration_ms:
            raise PreprocessContractError("speech outside duration", code=PreprocessErrorCode.INVALID)

    def accept_speech(self, evidence: SpeechEvidence):
        self.validate_speech(evidence)
        if self._speech >= MAX_SPEECH:
            raise PreprocessContractError("speech evidence limit", code=PreprocessErrorCode.LIMIT)
        self._speech += 1

    def cancel(self) -> PreprocessCheckpoint:
        if self._status is PreprocessStatus.RUNNING: self._status = PreprocessStatus.CANCELED
        return self.checkpoint()

    def checkpoint(self) -> PreprocessCheckpoint:
        return PreprocessCheckpoint(self.plan.source.source_id, self.plan.source.source_revision,
            self.plan.cache_key.fingerprint(), self.plan.digest(), self._next, len(self.plan.requests),
            self._boards, self._speech, self._status)


def serialize_checkpoint(c: PreprocessCheckpoint) -> str:
    if not isinstance(c, PreprocessCheckpoint):
        raise PreprocessContractError("invalid checkpoint", code=PreprocessErrorCode.INVALID)
    body = {"schema": SCHEMA, "version": VERSION, "source_id": c.source_id,
            "source_revision": c.source_revision, "cache_fingerprint": c.cache_fingerprint,
            "plan_digest": c.plan_digest, "next_index": c.next_index, "total": c.total,
            "board_count": c.board_count, "speech_count": c.speech_count, "status": c.status.value}
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text.encode()) > MAX_CHECKPOINT_BYTES:
        raise PreprocessContractError("checkpoint too large", code=PreprocessErrorCode.LIMIT)
    return text


def deserialize_checkpoint(text: str) -> PreprocessCheckpoint:
    raw = _text(text, "checkpoint", MAX_CHECKPOINT_BYTES)
    if len(raw.encode()) > MAX_CHECKPOINT_BYTES:
        raise PreprocessContractError("checkpoint too large", code=PreprocessErrorCode.LIMIT)
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise PreprocessContractError("duplicate JSON key", code=PreprocessErrorCode.INVALID_SCHEMA)
            out[k] = v
        return out
    try: data = json.loads(raw, object_pairs_hook=pairs)
    except PreprocessContractError: raise
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise PreprocessContractError("malformed checkpoint", code=PreprocessErrorCode.INVALID_SCHEMA) from exc
    expected = {"schema", "version", "source_id", "source_revision", "cache_fingerprint",
                "plan_digest", "next_index", "total", "board_count", "speech_count", "status"}
    if type(data) is not dict or set(data) != expected or data.get("schema") != SCHEMA or data.get("version") != VERSION:
        raise PreprocessContractError("unsupported checkpoint", code=PreprocessErrorCode.INVALID_SCHEMA)
    return PreprocessCheckpoint(data["source_id"], data["source_revision"], data["cache_fingerprint"],
        data["plan_digest"], data["next_index"], data["total"], data["board_count"],
        data["speech_count"], data["status"])
