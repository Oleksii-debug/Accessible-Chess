from __future__ import annotations

"""Append-only student/session review records and deterministic progress metrics.

This module stores review metadata only. It never stores canonical chess state,
engine PVs/scores, or UI state, and it never overwrites a prior review attempt.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from threading import RLock

from .engine_assisted_workflows import AudienceAnalysisResult
from .training import ExerciseSession


STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION = 1
STUDENT_PROGRESS_MAX_SNAPSHOT_RECORDS = 50_000
_MAX_ID_LENGTH = 256
_MAX_PAGE_SIZE = 1000
_RECORD_FIELDS = frozenset(
    {
        "record_id",
        "student_id",
        "session_id",
        "kind",
        "source_id",
        "source_revision",
        "sequence",
        "attempts",
        "mistakes",
        "hints_used",
        "completed",
        "engine_generation",
        "engine_stale",
        "engine_available",
    }
)
_SNAPSHOT_FIELDS = frozenset({"schema_version", "records"})


class ReviewKind(str, Enum):
    TRAINING = "training"
    GAME = "game"


def _identifier(value: object, *, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be text")
    token = value.strip()
    if not token or len(token) > _MAX_ID_LENGTH:
        raise ValueError(f"{name} must be bounded non-empty text")
    if any(ord(character) < 32 or ord(character) == 127 for character in token):
        raise ValueError(f"{name} must not contain control characters")
    return token


def _counter(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _engine_metadata(
    result: AudienceAnalysisResult | None,
) -> tuple[int | None, bool, bool]:
    if result is None:
        return None, False, False
    if not isinstance(result, AudienceAnalysisResult):
        raise TypeError("engine_result must be AudienceAnalysisResult or None")
    available = result.available_to_teacher or result.available_to_student
    return result.generation, result.stale, available


@dataclass(frozen=True, slots=True)
class StudentReviewRecord:
    """One immutable append-only review event."""

    record_id: str
    student_id: str
    session_id: str
    kind: ReviewKind
    source_id: str
    source_revision: str
    sequence: int
    attempts: int
    mistakes: int
    hints_used: int
    completed: bool
    engine_generation: int | None = None
    engine_stale: bool = False
    engine_available: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _identifier(self.record_id, name="record_id")
        )
        object.__setattr__(
            self, "student_id", _identifier(self.student_id, name="student_id")
        )
        object.__setattr__(
            self, "session_id", _identifier(self.session_id, name="session_id")
        )
        if not isinstance(self.kind, ReviewKind):
            raise TypeError("kind must be ReviewKind")
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, name="source_id")
        )
        object.__setattr__(
            self,
            "source_revision",
            _identifier(self.source_revision, name="source_revision"),
        )

        sequence = _counter(self.sequence, name="sequence")
        attempts = _counter(self.attempts, name="attempts")
        mistakes = _counter(self.mistakes, name="mistakes")
        hints_used = _counter(self.hints_used, name="hints_used")
        if mistakes > attempts:
            raise ValueError("mistakes cannot exceed attempts")
        if type(self.completed) is not bool:
            raise TypeError("completed must be boolean")

        generation = self.engine_generation
        if generation is not None:
            generation = _counter(generation, name="engine_generation")
        if type(self.engine_stale) is not bool:
            raise TypeError("engine_stale must be boolean")
        if type(self.engine_available) is not bool:
            raise TypeError("engine_available must be boolean")
        if (self.engine_stale or self.engine_available) and generation is None:
            raise ValueError("engine status requires an engine_generation")
        if self.engine_stale and self.engine_available:
            raise ValueError("stale engine result cannot be available")

        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "attempts", attempts)
        object.__setattr__(self, "mistakes", mistakes)
        object.__setattr__(self, "hints_used", hints_used)
        object.__setattr__(self, "engine_generation", generation)

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "student_id": self.student_id,
            "session_id": self.session_id,
            "kind": self.kind.value,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "sequence": self.sequence,
            "attempts": self.attempts,
            "mistakes": self.mistakes,
            "hints_used": self.hints_used,
            "completed": self.completed,
            "engine_generation": self.engine_generation,
            "engine_stale": self.engine_stale,
            "engine_available": self.engine_available,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "StudentReviewRecord":
        if not isinstance(data, Mapping):
            raise TypeError("student review record must be a mapping")
        fields = set(data)
        if fields != _RECORD_FIELDS:
            raise ValueError("student review record fields are invalid")
        raw_kind = data["kind"]
        if type(raw_kind) is not str:
            raise TypeError("kind must be text")
        try:
            kind = ReviewKind(raw_kind)
        except ValueError as exc:
            raise ValueError("unsupported student review kind") from exc
        return cls(
            record_id=data["record_id"],
            student_id=data["student_id"],
            session_id=data["session_id"],
            kind=kind,
            source_id=data["source_id"],
            source_revision=data["source_revision"],
            sequence=data["sequence"],
            attempts=data["attempts"],
            mistakes=data["mistakes"],
            hints_used=data["hints_used"],
            completed=data["completed"],
            engine_generation=data["engine_generation"],
            engine_stale=data["engine_stale"],
            engine_available=data["engine_available"],
        )


@dataclass(frozen=True, slots=True)
class StudentProgressSummary:
    student_id: str
    session_id: str
    record_count: int
    training_reviews: int
    game_reviews: int
    completed_training_reviews: int
    attempts: int
    mistakes: int
    hints_used: int
    engine_reviews: int
    stale_engine_reviews: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "student_id", _identifier(self.student_id, name="student_id")
        )
        object.__setattr__(
            self, "session_id", _identifier(self.session_id, name="session_id")
        )
        for field_name in (
            "record_count",
            "training_reviews",
            "game_reviews",
            "completed_training_reviews",
            "attempts",
            "mistakes",
            "hints_used",
            "engine_reviews",
            "stale_engine_reviews",
        ):
            object.__setattr__(
                self,
                field_name,
                _counter(getattr(self, field_name), name=field_name),
            )
        if self.mistakes > self.attempts:
            raise ValueError("summary mistakes cannot exceed attempts")
        if self.completed_training_reviews > self.training_reviews:
            raise ValueError(
                "completed training reviews cannot exceed training reviews"
            )
        if self.training_reviews + self.game_reviews != self.record_count:
            raise ValueError("summary review counts are inconsistent")
        if self.stale_engine_reviews > self.engine_reviews:
            raise ValueError("stale engine reviews cannot exceed engine reviews")

    @property
    def accepted_attempts(self) -> int:
        return self.attempts - self.mistakes

    @property
    def accuracy_permille(self) -> int | None:
        if self.attempts == 0:
            return None
        return self.accepted_attempts * 1000 // self.attempts


class StudentProgressLedger:
    """Thread-safe append-only review ledger with keyset paging."""

    def __init__(self) -> None:
        self._records: list[StudentReviewRecord] = []
        self._record_ids: set[str] = set()
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._lock = RLock()

    def append(self, record: StudentReviewRecord) -> StudentReviewRecord:
        if not isinstance(record, StudentReviewRecord):
            raise TypeError("record must be StudentReviewRecord")
        key = (record.student_id, record.session_id)
        with self._lock:
            if record.record_id in self._record_ids:
                raise ValueError("duplicate student review record_id")
            previous = self._last_sequence.get(key)
            if previous is not None and record.sequence <= previous:
                raise ValueError(
                    "student review sequence must increase within a session"
                )
            self._records.append(record)
            self._record_ids.add(record.record_id)
            self._last_sequence[key] = record.sequence
            return record

    def append_training_review(
        self,
        *,
        record_id: str,
        student_id: str,
        session_id: str,
        sequence: int,
        training_session: ExerciseSession,
        engine_result: AudienceAnalysisResult | None = None,
    ) -> StudentReviewRecord:
        if not isinstance(training_session, ExerciseSession):
            raise TypeError("training_session must be ExerciseSession")
        snapshot = training_session.snapshot()
        generation, stale, available = _engine_metadata(engine_result)
        record = StudentReviewRecord(
            record_id=record_id,
            student_id=student_id,
            session_id=session_id,
            kind=ReviewKind.TRAINING,
            source_id=training_session.definition.exercise_id,
            source_revision=str(snapshot["definition_digest"]),
            sequence=sequence,
            attempts=snapshot["attempts"],
            mistakes=snapshot["mistakes"],
            hints_used=snapshot["hints_used"],
            completed=training_session.completed,
            engine_generation=generation,
            engine_stale=stale,
            engine_available=available,
        )
        return self.append(record)

    def append_game_review(
        self,
        *,
        record_id: str,
        student_id: str,
        session_id: str,
        sequence: int,
        game_ref: str,
        source_revision: str,
        engine_result: AudienceAnalysisResult | None = None,
    ) -> StudentReviewRecord:
        generation, stale, available = _engine_metadata(engine_result)
        record = StudentReviewRecord(
            record_id=record_id,
            student_id=student_id,
            session_id=session_id,
            kind=ReviewKind.GAME,
            source_id=game_ref,
            source_revision=source_revision,
            sequence=sequence,
            attempts=0,
            mistakes=0,
            hints_used=0,
            completed=True,
            engine_generation=generation,
            engine_stale=stale,
            engine_available=available,
        )
        return self.append(record)

    def records(
        self,
        student_id: str,
        session_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> tuple[StudentReviewRecord, ...]:
        student = _identifier(student_id, name="student_id")
        session = _identifier(session_id, name="session_id")
        if after_sequence is not None:
            after_sequence = _counter(after_sequence, name="after_sequence")
        if type(limit) is not int:
            raise TypeError("limit must be an integer")
        if not 1 <= limit <= _MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {_MAX_PAGE_SIZE}")
        with self._lock:
            out: list[StudentReviewRecord] = []
            for record in self._records:
                if record.student_id != student or record.session_id != session:
                    continue
                if after_sequence is not None and record.sequence <= after_sequence:
                    continue
                out.append(record)
                if len(out) == limit:
                    break
            return tuple(out)

    def summary(
        self, student_id: str, session_id: str
    ) -> StudentProgressSummary:
        student = _identifier(student_id, name="student_id")
        session = _identifier(session_id, name="session_id")
        with self._lock:
            records = tuple(
                record
                for record in self._records
                if record.student_id == student and record.session_id == session
            )

        training = tuple(
            record for record in records if record.kind is ReviewKind.TRAINING
        )
        game = tuple(record for record in records if record.kind is ReviewKind.GAME)
        return StudentProgressSummary(
            student_id=student,
            session_id=session,
            record_count=len(records),
            training_reviews=len(training),
            game_reviews=len(game),
            completed_training_reviews=sum(
                1 for record in training if record.completed
            ),
            attempts=sum(record.attempts for record in training),
            mistakes=sum(record.mistakes for record in training),
            hints_used=sum(record.hints_used for record in training),
            engine_reviews=sum(
                1 for record in records if record.engine_generation is not None
            ),
            stale_engine_reviews=sum(
                1 for record in records if record.engine_stale
            ),
        )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            records = [record.as_dict() for record in self._records]
        return {
            "schema_version": STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION,
            "records": records,
        }

    @classmethod
    def restore(cls, payload: Mapping[str, object]) -> "StudentProgressLedger":
        if not isinstance(payload, Mapping):
            raise TypeError("student progress snapshot must be a mapping")
        if set(payload) != _SNAPSHOT_FIELDS:
            raise ValueError("student progress snapshot fields are invalid")
        schema = payload["schema_version"]
        if type(schema) is not int:
            raise TypeError(
                "student progress snapshot schema_version must be an integer"
            )
        if schema != STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported student progress snapshot schema_version: {schema}"
            )
        raw_records = payload["records"]
        if not isinstance(raw_records, list):
            raise TypeError("student progress snapshot records must be a list")
        if len(raw_records) > STUDENT_PROGRESS_MAX_SNAPSHOT_RECORDS:
            raise ValueError(
                "student progress snapshot exceeds maximum record count"
            )

        ledger = cls()
        for raw_record in raw_records:
            if not isinstance(raw_record, Mapping):
                raise TypeError("student progress record must be a mapping")
            ledger.append(StudentReviewRecord.from_dict(raw_record))
        return ledger
