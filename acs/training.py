from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .chesscore import Board, canonical_fen


TRAINING_SNAPSHOT_SCHEMA_VERSION = 2
TRAINING_DEFINITION_SCHEMA_VERSION = 1
MAX_TRAINING_STEPS = 512
MAX_ACCEPTED_MOVES_PER_STEP = 256
MAX_REACHABLE_POSITIONS = 4096
MAX_TRAINING_LINK_OPERATIONS = 100_000


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


class SolutionRevealPolicy(str, Enum):
    NEVER = "never"
    AFTER_ATTEMPT = "after_attempt"
    AFTER_HINT = "after_hint"
    ANYTIME = "anytime"


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
        if len(normalized) > MAX_ACCEPTED_MOVES_PER_STEP:
            raise TrainingError(
                "exercise step has too many accepted moves",
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

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted_moves": sorted(self.accepted_moves),
            "hint": self.hint,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ExerciseStep":
        if not isinstance(payload, Mapping):
            raise TrainingError(
                "exercise step payload must be a mapping",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        data = dict(payload)
        if set(data) != {"accepted_moves", "hint", "explanation"}:
            raise TrainingError(
                "exercise step fields are missing or unsupported",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        moves = data["accepted_moves"]
        if (
            type(moves) is not list
            or len(moves) > MAX_ACCEPTED_MOVES_PER_STEP
            or any(type(move) is not str for move in moves)
        ):
            raise TrainingError(
                "exercise accepted_moves must be a text list",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        return cls(
            frozenset(moves),
            hint=data["hint"],
            explanation=data["explanation"],
        )


@dataclass(frozen=True)
class ExerciseDefinition:
    """Presentation-neutral local training exercise.

    Every solution token is linked against the shared chess core at definition
    construction.  This prevents a training adapter from treating plausible
    move text as trusted chess state.
    """

    exercise_id: str
    start_fen: str
    steps: tuple[ExerciseStep, ...]
    title: str = ""
    tags: tuple[str, ...] = ()
    source_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    solution_reveal_policy: SolutionRevealPolicy = SolutionRevealPolicy.AFTER_ATTEMPT
    allow_analysis_after_completion: bool = True

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
        if len(self.steps) > MAX_TRAINING_STEPS:
            raise TrainingError(
                "exercise has too many steps",
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
        try:
            reveal_policy = SolutionRevealPolicy(self.solution_reveal_policy)
        except (TypeError, ValueError) as exc:
            raise TrainingError(
                "solution_reveal_policy is invalid",
                code=TrainingErrorCode.INVALID_DEFINITION,
            ) from exc
        if type(self.allow_analysis_after_completion) is not bool:
            raise TrainingError(
                "allow_analysis_after_completion must be a boolean",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        try:
            start_fen = canonical_fen(start_fen)
            canonical_steps = _link_definition_steps(start_fen, self.steps)
        except (TypeError, ValueError) as exc:
            if isinstance(exc, TrainingError):
                raise
            raise TrainingError(
                f"exercise chess content is invalid: {exc}",
                code=TrainingErrorCode.INVALID_DEFINITION,
            ) from exc
        object.__setattr__(self, "exercise_id", exercise_id)
        object.__setattr__(self, "start_fen", start_fen)
        object.__setattr__(self, "steps", canonical_steps)
        object.__setattr__(self, "tags", tuple(_normalize_tag(tag) for tag in self.tags))
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))
        object.__setattr__(self, "solution_reveal_policy", reveal_policy)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": TRAINING_DEFINITION_SCHEMA_VERSION,
            "exercise_id": self.exercise_id,
            "start_fen": self.start_fen,
            "steps": [step.as_dict() for step in self.steps],
            "title": self.title,
            "tags": list(self.tags),
            "source_id": self.source_id,
            "metadata": dict(self.metadata),
            "solution_reveal_policy": self.solution_reveal_policy.value,
            "allow_analysis_after_completion": self.allow_analysis_after_completion,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ExerciseDefinition":
        if not isinstance(payload, Mapping):
            raise TrainingError(
                "exercise definition payload must be a mapping",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        data = dict(payload)
        expected = {
            "schema_version",
            "exercise_id",
            "start_fen",
            "steps",
            "title",
            "tags",
            "source_id",
            "metadata",
            "solution_reveal_policy",
            "allow_analysis_after_completion",
        }
        if set(data) != expected:
            raise TrainingError(
                "exercise definition fields are missing or unsupported",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        if (
            type(data["schema_version"]) is not int
            or data["schema_version"] != TRAINING_DEFINITION_SCHEMA_VERSION
            or type(data["steps"]) is not list
            or len(data["steps"]) > MAX_TRAINING_STEPS
            or type(data["tags"]) is not list
            or type(data["metadata"]) is not dict
        ):
            raise TrainingError(
                "exercise definition schema or containers are invalid",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        return cls(
            exercise_id=data["exercise_id"],
            start_fen=data["start_fen"],
            steps=tuple(ExerciseStep.from_dict(step) for step in data["steps"]),
            title=data["title"],
            tags=tuple(data["tags"]),
            source_id=data["source_id"],
            metadata=data["metadata"],
            solution_reveal_policy=data["solution_reveal_policy"],
            allow_analysis_after_completion=data["allow_analysis_after_completion"],
        )


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
    position_fen: str | None = None


@dataclass(frozen=True)
class HintResult:
    available: bool
    step_index: int
    hint: str | None
    hints_used: int


@dataclass(frozen=True)
class SolutionResult:
    available: bool
    step_index: int
    moves: tuple[str, ...]
    solution_revealed: bool


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
        self._board = Board(definition.start_fen)
        self._move_history: list[str] = []
        self._current_step_attempts = 0
        self._current_step_hints = 0
        self._solution_revealed = False

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

    @property
    def position_fen(self) -> str:
        return self._board.fen()

    @property
    def move_history(self) -> tuple[str, ...]:
        return tuple(self._move_history)

    @property
    def solution_revealed(self) -> bool:
        return self._solution_revealed

    @property
    def analysis_allowed(self) -> bool:
        return bool(
            self.completed and self.definition.allow_analysis_after_completion
        )

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
        normalized = _normalize_move(move)
        step = self.definition.steps[self._step_index]
        candidate = self._board.clone()
        try:
            parsed = candidate.parse_move(normalized)
            canonical = candidate.san(parsed)
        except ValueError:
            parsed = None
            canonical = normalized
        self._attempts += 1
        self._current_step_attempts += 1

        if parsed is None or canonical not in step.accepted_moves:
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
                self.position_fen,
            )

        candidate.push(parsed)
        self._board = candidate
        self._move_history.append(canonical)
        explanation = step.explanation
        self._step_index += 1
        self._current_step_attempts = 0
        self._current_step_hints = 0
        self._solution_revealed = False
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
            self.position_fen,
        )

    def request_hint(self) -> HintResult:
        if self.completed:
            return HintResult(False, self._step_index, None, self._hints_used)
        step = self.definition.steps[self._step_index]
        if step.hint is None:
            return HintResult(False, self._step_index, None, self._hints_used)
        self._hints_used += 1
        self._current_step_hints += 1
        return HintResult(True, self._step_index, step.hint, self._hints_used)

    def reveal_solution(self) -> SolutionResult:
        """Reveal only the current answer and only when policy permits it."""

        if self.completed:
            return SolutionResult(False, self._step_index, (), False)
        if not self._solution_is_available():
            return SolutionResult(False, self._step_index, (), False)
        self._solution_revealed = True
        return SolutionResult(
            True,
            self._step_index,
            tuple(sorted(self.definition.steps[self._step_index].accepted_moves)),
            True,
        )

    def _solution_is_available(self) -> bool:
        if self.completed:
            return False
        policy = self.definition.solution_reveal_policy
        return bool(
            policy is SolutionRevealPolicy.ANYTIME
            or (
                policy is SolutionRevealPolicy.AFTER_ATTEMPT
                and self._current_step_attempts > 0
            )
            or (
                policy is SolutionRevealPolicy.AFTER_HINT
                and self._current_step_hints > 0
            )
        )

    def reset(self) -> None:
        self._step_index = 0
        self._attempts = 0
        self._mistakes = 0
        self._hints_used = 0
        self._status = ExerciseStatus.READY
        self._board = Board(self.definition.start_fen)
        self._move_history = []
        self._current_step_attempts = 0
        self._current_step_hints = 0
        self._solution_revealed = False

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
            "move_history": list(self._move_history),
            "current_fen": self.position_fen,
            "current_step_attempts": self._current_step_attempts,
            "current_step_hints": self._current_step_hints,
            "solution_revealed": self._solution_revealed,
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
                or schema_version not in {1, TRAINING_SNAPSHOT_SCHEMA_VERSION}
            ):
                raise TrainingError(
                    "unsupported exercise snapshot schema",
                    code=TrainingErrorCode.UNSUPPORTED_SCHEMA,
                )
        else:
            schema_version = 0
        common_required = {
            "exercise_id",
            "step_index",
            "attempts",
            "mistakes",
            "hints_used",
            "status",
        }
        v2_required = {
            "move_history",
            "current_fen",
            "current_step_attempts",
            "current_step_hints",
            "solution_revealed",
        }
        required = common_required | (
            v2_required if schema_version == TRAINING_SNAPSHOT_SCHEMA_VERSION else set()
        )
        expected = required | ({"schema_version"} if has_schema_version else set())
        if set(payload) != expected:
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
        if schema_version == TRAINING_SNAPSHOT_SCHEMA_VERSION:
            counters.update(
                current_step_attempts=payload["current_step_attempts"],
                current_step_hints=payload["current_step_hints"],
            )
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
        current_step_attempts = counters.get("current_step_attempts", 0)
        current_step_hints = counters.get("current_step_hints", 0)
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
        if min(
            attempts,
            mistakes,
            hints_used,
            current_step_attempts,
            current_step_hints,
        ) < 0:
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
        if current_step_attempts > mistakes or current_step_hints > hints_used:
            raise TrainingError(
                "current-step counters exceed aggregate counters",
                code=TrainingErrorCode.INVALID_STATE,
            )
        if status in {ExerciseStatus.READY, ExerciseStatus.COMPLETED} and (
            current_step_attempts or current_step_hints
        ):
            raise TrainingError(
                "ready or completed snapshots cannot retain current-step counters",
                code=TrainingErrorCode.INVALID_STATE,
            )

        session = cls(definition)
        if schema_version == TRAINING_SNAPSHOT_SCHEMA_VERSION:
            history = payload["move_history"]
            current_fen = payload["current_fen"]
            solution_revealed = payload["solution_revealed"]
            if (
                type(history) is not list
                or any(type(move) is not str or not move for move in history)
                or len(history) != step_index
                or type(current_fen) is not str
                or type(solution_revealed) is not bool
            ):
                raise TrainingError(
                    "exercise snapshot chess state is invalid",
                    code=TrainingErrorCode.INVALID_SNAPSHOT,
                )
            _restore_move_history(session, history)
            try:
                canonical_current_fen = canonical_fen(current_fen)
            except (TypeError, ValueError) as exc:
                raise TrainingError(
                    "exercise snapshot current_fen is invalid",
                    code=TrainingErrorCode.INVALID_SNAPSHOT,
                ) from exc
            if current_fen != canonical_current_fen or session.position_fen != current_fen:
                raise TrainingError(
                    "exercise snapshot current_fen does not match move history",
                    code=TrainingErrorCode.INVALID_STATE,
                )
            session._solution_revealed = solution_revealed
        else:
            legacy_history: list[str] = []
            for step in definition.steps[:step_index]:
                if len(step.accepted_moves) != 1:
                    raise TrainingError(
                        "legacy snapshot cannot reconstruct an ambiguous legal line",
                        code=TrainingErrorCode.INVALID_SNAPSHOT,
                    )
                legacy_history.append(next(iter(step.accepted_moves)))
            _restore_move_history(session, legacy_history)

        session._step_index = step_index
        session._attempts = attempts
        session._mistakes = mistakes
        session._hints_used = hints_used
        session._status = status
        session._current_step_attempts = current_step_attempts
        session._current_step_hints = current_step_hints
        if session._solution_revealed:
            if session.completed or not session._solution_is_available():
                raise TrainingError(
                    "exercise snapshot claims an unavailable solution reveal",
                    code=TrainingErrorCode.INVALID_STATE,
                )
        return session


def _link_definition_steps(
    start_fen: str,
    steps: tuple[ExerciseStep, ...],
) -> tuple[ExerciseStep, ...]:
    """Canonicalize every accepted move over every reachable prior position."""

    reachable = {start_fen}
    linked: list[ExerciseStep] = []
    operations = 0
    for step_index, step in enumerate(steps):
        operations += len(reachable) * len(step.accepted_moves)
        if operations > MAX_TRAINING_LINK_OPERATIONS:
            raise TrainingError(
                "exercise solution validation exceeds the operation safety limit",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        canonical_moves: set[str] = set()
        next_positions: set[str] = set()
        for source_move in sorted(step.accepted_moves):
            spelling_results: set[str] = set()
            spelling_positions: set[str] = set()
            for fen in reachable:
                board = Board(fen)
                try:
                    move = board.parse_move(source_move)
                    canonical = board.push(move)
                except ValueError as exc:
                    raise TrainingError(
                        f"accepted move {source_move!r} is illegal at step {step_index}",
                        code=TrainingErrorCode.INVALID_DEFINITION,
                    ) from exc
                spelling_results.add(canonical)
                spelling_positions.add(board.fen())
            if len(spelling_results) != 1:
                raise TrainingError(
                    f"accepted move {source_move!r} is ambiguous across solution branches",
                    code=TrainingErrorCode.INVALID_DEFINITION,
                )
            canonical_moves.update(spelling_results)
            next_positions.update(spelling_positions)
        if len(next_positions) > MAX_REACHABLE_POSITIONS:
            raise TrainingError(
                "exercise solution branches exceed the position safety limit",
                code=TrainingErrorCode.INVALID_DEFINITION,
            )
        linked.append(
            ExerciseStep(
                frozenset(canonical_moves),
                hint=step.hint,
                explanation=step.explanation,
            )
        )
        reachable = next_positions
    return tuple(linked)


def _restore_move_history(session: ExerciseSession, history: list[str]) -> None:
    board = Board(session.definition.start_fen)
    canonical_history: list[str] = []
    for step_index, source_move in enumerate(history):
        try:
            move = board.parse_move(source_move)
            canonical = board.push(move)
        except ValueError as exc:
            raise TrainingError(
                "exercise snapshot move history contains an illegal move",
                code=TrainingErrorCode.INVALID_SNAPSHOT,
            ) from exc
        if (
            canonical != source_move
            or canonical not in session.definition.steps[step_index].accepted_moves
        ):
            raise TrainingError(
                "exercise snapshot move history is not canonical for the solution",
                code=TrainingErrorCode.INVALID_STATE,
            )
        canonical_history.append(canonical)
    session._board = board
    session._move_history = canonical_history


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
