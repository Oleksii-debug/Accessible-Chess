from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


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
        normalized = frozenset(_normalize_move(move) for move in self.accepted_moves)
        if not normalized:
            raise ValueError("exercise step requires at least one accepted move")
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
        exercise_id = str(self.exercise_id).strip()
        if not exercise_id:
            raise ValueError("exercise_id must not be empty")
        if not str(self.start_fen).strip():
            raise ValueError("start_fen must not be empty")
        if not self.steps:
            raise ValueError("exercise requires at least one step")
        object.__setattr__(self, "exercise_id", exercise_id)
        object.__setattr__(self, "start_fen", str(self.start_fen).strip())
        object.__setattr__(self, "tags", tuple(_normalize_tag(tag) for tag in self.tags))
        object.__setattr__(self, "metadata", dict(self.metadata))


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
        self.definition = definition
        self._step_index = 0
        self._attempts = 0
        self._mistakes = 0
        self._hints_used = 0
        self._status = ExerciseStatus.READY

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
            raise ValueError("exercise is already completed")
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
            "exercise_id": self.definition.exercise_id,
            "step_index": self._step_index,
            "attempts": self._attempts,
            "mistakes": self._mistakes,
            "hints_used": self._hints_used,
            "status": self._status.value,
        }

    @classmethod
    def restore(cls, definition: ExerciseDefinition, snapshot: Mapping[str, object]) -> "ExerciseSession":
        if snapshot.get("exercise_id") != definition.exercise_id:
            raise ValueError("exercise snapshot belongs to a different exercise")
        session = cls(definition)
        try:
            step_index = int(snapshot.get("step_index", 0))
            attempts = int(snapshot.get("attempts", 0))
            mistakes = int(snapshot.get("mistakes", 0))
            hints_used = int(snapshot.get("hints_used", 0))
            status = ExerciseStatus(str(snapshot.get("status", ExerciseStatus.READY.value)))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid exercise snapshot") from exc

        if not 0 <= step_index <= len(definition.steps):
            raise ValueError("invalid exercise step_index")
        if min(attempts, mistakes, hints_used) < 0 or mistakes > attempts:
            raise ValueError("invalid exercise counters")
        if status is ExerciseStatus.COMPLETED and step_index != len(definition.steps):
            raise ValueError("completed exercise snapshot has unfinished steps")
        if status is not ExerciseStatus.COMPLETED and step_index == len(definition.steps):
            raise ValueError("finished step index requires completed status")

        session._step_index = step_index
        session._attempts = attempts
        session._mistakes = mistakes
        session._hints_used = hints_used
        session._status = status
        return session


def _normalize_move(value: str) -> str:
    text = " ".join(str(value).strip().split())
    if not text:
        raise ValueError("move must not be empty")
    return text


def _normalize_tag(value: str) -> str:
    text = str(value).strip().casefold()
    if not text:
        raise ValueError("exercise tag must not be empty")
    return text
