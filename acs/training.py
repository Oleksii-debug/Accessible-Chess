from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


TRAINING_SNAPSHOT_SCHEMA_VERSION = 1


class TrainingErrorCode(str, Enum):
    INVALID_DEFINITION = "invalid_definition"
    INVALID_COMMAND = "invalid_command"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    INVALID_SNAPSHOT = "invalid_snapshot"
    EXERCISE_MISMATCH = "exercise_mismatch"
    INVALID_STATE = "invalid_state"


class TrainingError(ValueError):
    """Stable failure at the presentation-neutral training boundary."""

    def __init__(self, message: str, *, code: TrainingErrorCode) -> None:
        super().__init__(message)
        self.code = TrainingErrorCode(code)


class ExerciseStatus(str, Enum):
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ExerciseStep:
    """One canonical training step with one or more accepted chess moves."""

    accepted_moves: frozenset[str]
    hint: str | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.accepted_moves, frozenset):
            raise TrainingError(
                "accepted_moves must be a frozenset",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        normalized = frozenset(
            _normalize_move(move, code=TrainingErrorCode.INVALID_DEFINITION)
            for move in self.accepted_moves
        )
        if not normalized:
            raise TrainingError(
                "exercise step requires at least one accepted move",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        for field_name in ("hint", "explanation"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise TrainingError(
                    f"{field_name} must be non-empty text or None",
                    code=TrainingErrorCode.INVALID_DEFINITION,
                )
        object.__setattr__(self, "accepted_moves", normalized)


@dataclass(frozen=True)
class ExerciseDefinition:
    """Presentation-neutral local training exercise.

    `start_fen` is intentionally opaque here: chess legality stays owned by the
    chess core / game adapter rather than being duplicated in the training
    module. Submitted moves are expected in canonical SAN/Lichess text from the
    shared move parser.
    """

    exercise_id: str
    start_fen: str
    steps: tuple[ExerciseStep, ...]
    title: str = ""
    tags: tuple[str, ...] = ()
    source_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        exercise_id = _required_definition_text(
            self.exercise_id,
            "exercise_id",
        ).strip()
        start_fen = _required_definition_text(self.start_fen, "start_fen").strip()
        if not isinstance(self.steps, tuple) or not self.steps:
            raise TrainingError(
                "exercise steps must be a non-empty tuple",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        if not all(isinstance(step, ExerciseStep) for step in self.steps):
            raise TrainingError(
                "exercise steps must contain only ExerciseStep values",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        if not isinstance(self.title, str):
            raise TrainingError(
                "exercise title must be text",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        if not isinstance(self.tags, tuple):
            raise TrainingError(
                "exercise tags must be a tuple",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        if self.source_id is not None:
            source_id = _required_definition_text(self.source_id, "source_id").strip()
        else:
            source_id = None
        if not isinstance(self.metadata, Mapping):
            raise TrainingError(
                "exercise metadata must be a mapping",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        metadata: dict[str, str] = {}
        for key, value in self.metadata.items():
            if (
                not isinstance(key, str)
                or not key.strip()
                or not isinstance(value, str)
            ):
                raise TrainingError(
                    "exercise metadata keys must be non-empty text and values must be text",
                    code=TrainingErrorCode.INVALID_DEFINITION,
                )
            normalized_key = key.strip()
            if normalized_key in metadata:
                raise TrainingError(
                    "exercise metadata keys collide after normalization",
                    code=TrainingErrorCode.INVALID_DEFINITION,
                )
            metadata[normalized_key] = value
        object.__setattr__(self, "exercise_id", exercise_id)
        object.__setattr__(self, "start_fen", start_fen)
        object.__setattr__(self, "tags", tuple(_normalize_tag(tag) for tag in self.tags))
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))


@dataclass(frozen=True)
class ExerciseResult:
    accepted: bool
    status: ExerciseStatus
    step_index: int
    attempts: int
    mistakes: int
    completed: bool
    move: str | None = None
    explanation: str | None = None


@dataclass(frozen=True)
class HintResult:
    available: bool
    step_index: int
    hint: str | None
    hints_used: int


class ExerciseSession:
    """Deterministic, resettable training-session state.

    Incorrect moves never advance the solution. Hints never mutate chess state.
    The service contains no clock, UI, persistence, or engine-provider logic.
    """

    def __init__(self, definition: ExerciseDefinition) -> None:
        if not isinstance(definition, ExerciseDefinition):
            raise TrainingError(
                "ExerciseSession requires an ExerciseDefinition",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        self._definition = definition
        self._step_index = 0
        self._attempts = 0
        self._mistakes = 0
        self._hints_used = 0
        self._status = ExerciseStatus.READY

    @property
    def definition(self) -> ExerciseDefinition:
        return self._definition

    @property
    def status(self) -> ExerciseStatus:
        return self._status

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def mistakes(self) -> int:
        return self._mistakes

    @property
    def hints_used(self) -> int:
        return self._hints_used

    @property
    def completed(self) -> bool:
        return self._status is ExerciseStatus.COMPLETED

    def current_step(self) -> ExerciseStep | None:
        if self.completed:
            return None
        return self.definition.steps[self._step_index]

    def submit(self, move: str) -> ExerciseResult:
        if self.completed:
            raise TrainingError(
                "exercise is already completed",
                code=TrainingErrorCode.INVALID_STATE,
            )
        canonical = _normalize_move(move)
        step = self.definition.steps[self._step_index]
        self._attempts += 1

        if canonical not in step.accepted_moves:
            self._mistakes += 1
            if self._status is ExerciseStatus.READY:
                self._status = ExerciseStatus.IN_PROGRESS
            return ExerciseResult(
                False,
                self._status,
                self._step_index,
                self._attempts,
                self._mistakes,
                False,
                canonical,
                None,
            )

        explanation = step.explanation
        self._step_index += 1
        if self._step_index == len(self.definition.steps):
            self._status = ExerciseStatus.COMPLETED
        else:
            self._status = ExerciseStatus.IN_PROGRESS
        return ExerciseResult(
            True,
            self._status,
            self._step_index,
            self._attempts,
            self._mistakes,
            self.completed,
            canonical,
            explanation,
        )

    def request_hint(self) -> HintResult:
        if self.completed:
            return HintResult(False, self._step_index, None, self._hints_used)
        step = self.definition.steps[self._step_index]
        if step.hint is None:
            return HintResult(False, self._step_index, None, self._hints_used)
        self._hints_used += 1
        return HintResult(True, self._step_index, step.hint, self._hints_used)

    def reset(self) -> None:
        self._step_index = 0
        self._attempts = 0
        self._mistakes = 0
        self._hints_used = 0
        self._status = ExerciseStatus.READY

    def snapshot(self) -> dict[str, object]:
        """Return non-secret state suitable for persistence adapters."""
        return {
            "schema_version": TRAINING_SNAPSHOT_SCHEMA_VERSION,
            "exercise_id": self.definition.exercise_id,
            "step_index": self._step_index,
            "attempts": self._attempts,
            "mistakes": self._mistakes,
            "hints_used": self._hints_used,
            "status": self._status.value,
        }

    @classmethod
    def restore(
        cls,
        definition: ExerciseDefinition,
        snapshot: Mapping[str, object],
    ) -> "ExerciseSession":
        if not isinstance(definition, ExerciseDefinition):
            raise TrainingError(
                "ExerciseSession requires an ExerciseDefinition",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        if not isinstance(snapshot, Mapping):
            raise TrainingError(
                "exercise snapshot must be a mapping",
                code=TrainingErrorCode.INVALID_SNAPSHOT,
            )

        payload = dict(snapshot)
        has_schema_version = "schema_version" in payload
        if has_schema_version:
            schema_version = payload["schema_version"]
            if (
                not isinstance(schema_version, int)
                or isinstance(schema_version, bool)
                or schema_version != TRAINING_SNAPSHOT_SCHEMA_VERSION
            ):
                raise TrainingError(
                    "unsupported exercise snapshot schema",
                    code=TrainingErrorCode.UNSUPPORTED_SCHEMA,
                )
        else:
            schema_version = 0
        required = {
            "exercise_id",
            "step_index",
            "attempts",
            "mistakes",
            "hints_used",
            "status",
        }
        allowed = required | ({"schema_version"} if has_schema_version else set())
        if set(payload) != allowed:
            raise TrainingError(
                "exercise snapshot fields are missing or unsupported",
                code=TrainingErrorCode.INVALID_SNAPSHOT,
            )

        exercise_id = payload["exercise_id"]
        if not isinstance(exercise_id, str) or not exercise_id.strip():
            raise TrainingError(
                "exercise snapshot exercise_id must be non-empty text",
                code=TrainingErrorCode.INVALID_SNAPSHOT,
            )
        if exercise_id != definition.exercise_id:
            raise TrainingError(
                "exercise snapshot belongs to a different exercise",
                code=TrainingErrorCode.EXERCISE_MISMATCH,
            )

        counters = {
            name: payload[name]
            for name in ("step_index", "attempts", "mistakes", "hints_used")
        }
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in counters.values()
        ):
            raise TrainingError(
                "exercise snapshot counters must be integers",
                code=TrainingErrorCode.INVALID_SNAPSHOT,
            )
        step_index = counters["step_index"]
        attempts = counters["attempts"]
        mistakes = counters["mistakes"]
        hints_used = counters["hints_used"]
        raw_status = payload["status"]
        if not isinstance(raw_status, str):
            raise TrainingError(
                "exercise snapshot status must be text",
                code=TrainingErrorCode.INVALID_SNAPSHOT,
            )
        try:
            status = ExerciseStatus(raw_status)
        except ValueError as exc:
            raise TrainingError(
                "exercise snapshot status is invalid",
                code=TrainingErrorCode.INVALID_SNAPSHOT,
            ) from exc

        if not 0 <= step_index <= len(definition.steps):
            raise TrainingError(
                "invalid exercise step_index",
                code=TrainingErrorCode.INVALID_STATE,
            )
        if min(attempts, mistakes, hints_used) < 0:
            raise TrainingError(
                "invalid exercise counters",
                code=TrainingErrorCode.INVALID_STATE,
            )
        if attempts != step_index + mistakes:
            raise TrainingError(
                "exercise attempts must equal completed steps plus mistakes",
                code=TrainingErrorCode.INVALID_STATE,
            )
        if status is ExerciseStatus.READY and (
            step_index != 0 or attempts != 0 or mistakes != 0
        ):
            raise TrainingError(
                "ready exercise snapshot contains move progress",
                code=TrainingErrorCode.INVALID_STATE,
            )
        if status is ExerciseStatus.IN_PROGRESS and attempts == 0:
            raise TrainingError(
                "in-progress exercise snapshot has no attempts",
                code=TrainingErrorCode.INVALID_STATE,
            )
        if status is ExerciseStatus.COMPLETED and step_index != len(definition.steps):
            raise TrainingError(
                "completed exercise snapshot has unfinished steps",
                code=TrainingErrorCode.INVALID_STATE,
            )
        if status is not ExerciseStatus.COMPLETED and step_index == len(definition.steps):
            raise TrainingError(
                "finished step index requires completed status",
                code=TrainingErrorCode.INVALID_STATE,
            )

        session = cls(definition)
        session._step_index = step_index
        session._attempts = attempts
        session._mistakes = mistakes
        session._hints_used = hints_used
        session._status = status
        return session


def _normalize_move(
    value: str,
    *,
    code: TrainingErrorCode = TrainingErrorCode.INVALID_COMMAND,
) -> str:
    if not isinstance(value, str):
        raise TrainingError("move must be text", code=code)
    text = " ".join(value.strip().split())
    if not text:
        raise TrainingError("move must not be empty", code=code)
    return text


def _normalize_tag(value: str) -> str:
    if not isinstance(value, str):
        raise TrainingError(
            "exercise tag must be text",
            code=TrainingErrorCode.INVALID_DEFINITION,
        )
    text = value.strip().casefold()
    if not text:
        raise TrainingError(
            "exercise tag must not be empty",
            code=TrainingErrorCode.INVALID_DEFINITION,
        )
    return text


def _required_definition_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrainingError(
            f"{field_name} must be non-empty text",
            code=TrainingErrorCode.INVALID_DEFINITION,
        )
    return value
