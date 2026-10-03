from __future__ import annotations

import hashlib
import json
from itertools import islice
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from .chesscore import Board, Move


TRAINING_SNAPSHOT_SCHEMA_VERSION = 3
_MAX_EXERCISE_STEPS = 2048
_MAX_ACCEPTED_MOVES_PER_STEP = 64
_MAX_MOVE_TEXT = 64
_MAX_DEFINITION_TEXT = 4096
_MAX_TRAINING_TAGS = 256
_MAX_TRAINING_METADATA_ITEMS = 256
_MAX_SAFE_COUNTER = (1 << 53) - 1
_TRAINING_SNAPSHOT_V3_FIELDS = frozenset(
    {
        "schema_version",
        "exercise_id",
        "definition_digest",
        "accepted_path",
        "position_fen",
        "step_index",
        "attempts",
        "mistakes",
        "hints_used",
        "status",
    }
)
_TRAINING_SNAPSHOT_V2_FIELDS = frozenset(
    {
        "schema_version",
        "exercise_id",
        "definition_digest",
        "step_index",
        "attempts",
        "mistakes",
        "hints_used",
        "status",
    }
)


class ExerciseStatus(str, Enum):
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ExerciseContentError(ValueError):
    """Raised when authored exercise chess content is invalid for canonical state."""


@dataclass(frozen=True)
class ExerciseStep:
    """One training step containing accepted move spellings.

    Spellings are authoring inputs only. Correctness is decided by the shared
    canonical chess core against the session's exact current position.
    """

    accepted_moves: frozenset[str]
    hint: str | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        if type(self.accepted_moves) is not frozenset:
            raise TypeError("exercise accepted_moves must be an exact frozenset")
        count = len(self.accepted_moves)
        if not count:
            raise ValueError("exercise step requires at least one accepted move")
        if count > _MAX_ACCEPTED_MOVES_PER_STEP:
            raise ValueError("exercise step has too many accepted moves")
        for move in self.accepted_moves:
            if type(move) is not str:
                raise TypeError("move must be a string")
            if len(move) > _MAX_MOVE_TEXT:
                raise ValueError("move text is too long")
        for value, name in (
            (self.hint, "exercise hint"),
            (self.explanation, "exercise explanation"),
        ):
            if value is not None:
                if type(value) is not str:
                    raise TypeError(f"{name} must be a string or None")
                if len(value) > _MAX_DEFINITION_TEXT:
                    raise ValueError(f"{name} is too long")
        normalized = frozenset(_normalize_move(move) for move in self.accepted_moves)
        object.__setattr__(self, "accepted_moves", normalized)



@dataclass(frozen=True)
class ExerciseDefinition:
    """Presentation-neutral local training exercise over canonical chess state."""

    exercise_id: str
    start_fen: str
    steps: tuple[ExerciseStep, ...]
    title: str = ""
    tags: tuple[str, ...] = ()
    source_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.exercise_id) is not str:
            raise TypeError("exercise_id must be a string")
        if len(self.exercise_id) > _MAX_DEFINITION_TEXT:
            raise ValueError("exercise_id is too long")
        exercise_id = self.exercise_id.strip()
        if not exercise_id:
            raise ValueError("exercise_id must not be empty")
        if type(self.start_fen) is not str:
            raise TypeError("start_fen must be a string")
        if len(self.start_fen) > _MAX_DEFINITION_TEXT:
            raise ValueError("start_fen is too long")
        start_fen = self.start_fen.strip()
        if not start_fen:
            raise ValueError("start_fen must not be empty")
        # Position syntax and legality belong to the shared canonical chess core.
        Board(start_fen)
        try:
            step_count = len(self.steps)
        except TypeError:
            try:
                steps = tuple(islice(iter(self.steps), _MAX_EXERCISE_STEPS + 1))
            except TypeError as exc:
                raise TypeError("exercise steps must be a finite collection") from exc
            if len(steps) > _MAX_EXERCISE_STEPS:
                raise ValueError("exercise has too many steps")
            step_count = len(steps)
        else:
            if step_count > _MAX_EXERCISE_STEPS:
                raise ValueError("exercise has too many steps")
            try:
                steps = tuple(self.steps)
            except TypeError as exc:
                raise TypeError("exercise steps must be a finite collection") from exc
            if len(steps) != step_count:
                raise ValueError("exercise steps changed during validation")
        if step_count < 1:
            raise ValueError("exercise requires at least one step")
        if any(type(step) is not ExerciseStep for step in steps):
            raise TypeError("exercise steps must contain exact ExerciseStep values")

        if type(self.title) is not str:
            raise TypeError("exercise title must be a string")
        if len(self.title) > _MAX_DEFINITION_TEXT:
            raise ValueError("exercise title is too long")
        if self.source_id is not None:
            if type(self.source_id) is not str:
                raise TypeError("exercise source_id must be a string or None")
            if len(self.source_id) > _MAX_DEFINITION_TEXT:
                raise ValueError("exercise source_id is too long")

        try:
            tag_count = len(self.tags)
        except TypeError:
            try:
                raw_tags = tuple(islice(iter(self.tags), _MAX_TRAINING_TAGS + 1))
            except TypeError as exc:
                raise TypeError("exercise tags must be a finite collection") from exc
            if len(raw_tags) > _MAX_TRAINING_TAGS:
                raise ValueError("exercise has too many tags")
            tag_count = len(raw_tags)
        else:
            if tag_count > _MAX_TRAINING_TAGS:
                raise ValueError("exercise has too many tags")
            try:
                raw_tags = tuple(self.tags)
            except TypeError as exc:
                raise TypeError("exercise tags must be a finite collection") from exc
            if len(raw_tags) != tag_count:
                raise ValueError("exercise tags changed during validation")
        tags = tuple(_normalize_tag(tag) for tag in raw_tags)

        if not isinstance(self.metadata, Mapping):
            raise TypeError("exercise metadata must be a mapping")
        try:
            metadata_count = len(self.metadata)
        except TypeError as exc:
            raise TypeError("exercise metadata must be a finite mapping") from exc
        if metadata_count > _MAX_TRAINING_METADATA_ITEMS:
            raise ValueError("exercise metadata has too many items")
        for key, value in self.metadata.items():
            if type(key) is not str or type(value) is not str:
                raise TypeError("exercise metadata must map strings to strings")
            if len(key) > _MAX_DEFINITION_TEXT or len(value) > _MAX_DEFINITION_TEXT:
                raise ValueError("exercise metadata text is too long")
        metadata = dict(self.metadata)
        if len(metadata) != metadata_count:
            raise ValueError("exercise metadata changed during validation")

        object.__setattr__(self, "exercise_id", exercise_id)
        object.__setattr__(self, "start_fen", start_fen)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "metadata", metadata)



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
    """Deterministic training-session state backed by the canonical chess core.

    Accepted answers are resolved as legal moves on the exact current canonical
    position, then committed to a private canonical Board snapshot. Incorrect
    answers never mutate the position. The accepted canonical SAN path and FEN
    are persisted so alternative correct moves cannot make resume ambiguous.
    """

    def __init__(self, definition: ExerciseDefinition) -> None:
        definition = _validated_definition(definition)
        self.definition = definition
        self._definition_authority_digest = _definition_authority_digest(definition)
        self._board = Board(definition.start_fen)
        self._accepted_path: list[str] = []
        self._step_index = 0
        self._attempts = 0
        self._mistakes = 0
        self._hints_used = 0
        self._status = ExerciseStatus.READY

    @property
    def canonical_definition(self) -> ExerciseDefinition:
        """Return the exact definition authority bound to this live session."""
        return self._bound_definition()

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
    def current_fen(self) -> str:
        """Canonical position after the accepted answer path."""
        return self._board.fen()

    @property
    def accepted_path(self) -> tuple[str, ...]:
        """Canonical SAN path used to reach :attr:`current_fen`."""
        return tuple(self._accepted_path)

    def current_step(self) -> ExerciseStep | None:
        definition = self._bound_definition()
        if self.completed:
            return None
        return definition.steps[self._step_index]

    def submit(self, move: str) -> ExerciseResult:
        definition = self._bound_definition()
        if self.completed:
            raise ValueError("exercise is already completed")
        submitted = _normalize_move(move)
        step = definition.steps[self._step_index]

        # Validate authored accepted answers before touching counters or state.
        accepted = _resolved_accepted_moves(step, self._board)
        try:
            parsed = self._board.parse_move(submitted)
        except ValueError:
            return self._record_mistake(submitted)

        key = _move_key(parsed)
        if key not in accepted:
            try:
                canonical_rejected = self._board.san(parsed)
            except ValueError:
                canonical_rejected = submitted
            return self._record_mistake(canonical_rejected)

        candidate = Board(self._board.fen())
        candidate_move = candidate.parse_move(submitted)
        canonical_san = candidate.push(candidate_move)
        next_index = self._step_index + 1

        # Fail atomically if the newly reached step contains chess content that
        # cannot be interpreted by the canonical core in this exact position.
        if next_index < len(definition.steps):
            _resolved_accepted_moves(definition.steps[next_index], candidate)

        explanation = step.explanation
        self._board = candidate
        self._accepted_path.append(canonical_san)
        self._attempts += 1
        self._step_index = next_index
        if self._step_index == len(definition.steps):
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
            canonical_san,
            explanation,
        )

    def _record_mistake(self, move: str) -> ExerciseResult:
        self._attempts += 1
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
            move,
            None,
        )

    def request_hint(self) -> HintResult:
        definition = self._bound_definition()
        if self.completed:
            return HintResult(False, self._step_index, None, self._hints_used)
        step = definition.steps[self._step_index]
        if step.hint is None:
            return HintResult(False, self._step_index, None, self._hints_used)
        self._hints_used += 1
        return HintResult(True, self._step_index, step.hint, self._hints_used)

    def reset(self) -> None:
        definition = self._bound_definition()
        # Reconstruct from the authored start position through canonical core;
        # reset never reuses a potentially mutated hidden board object.
        board = Board(definition.start_fen)
        self._board = board
        self._accepted_path = []
        self._step_index = 0
        self._attempts = 0
        self._mistakes = 0
        self._hints_used = 0
        self._status = ExerciseStatus.READY

    def snapshot(self) -> dict[str, object]:
        """Return strict schema-v3 progress with deterministic chess identity."""
        definition = self._bound_definition()
        return {
            "schema_version": TRAINING_SNAPSHOT_SCHEMA_VERSION,
            "exercise_id": definition.exercise_id,
            "definition_digest": _definition_digest(definition),
            "accepted_path": list(self._accepted_path),
            "position_fen": self._board.fen(),
            "step_index": self._step_index,
            "attempts": self._attempts,
            "mistakes": self._mistakes,
            "hints_used": self._hints_used,
            "status": self._status.value,
        }

    def restore_state(self, snapshot: Mapping[str, object]) -> None:
        """Restore one previously validated progress snapshot in place.

        Validation and canonical replay complete on a detached candidate before
        any live field is replaced, so presentation rollback cannot publish a
        half-restored Training session. The ExerciseSession object identity is
        preserved for callers that retain a reference to the active session.
        """
        definition = self._bound_definition()
        restored = ExerciseSession.restore(definition, snapshot)
        self._board = restored._board
        self._accepted_path = list(restored._accepted_path)
        self._step_index = restored._step_index
        self._attempts = restored._attempts
        self._mistakes = restored._mistakes
        self._hints_used = restored._hints_used
        self._status = restored._status

    def _bound_definition(self) -> ExerciseDefinition:
        definition = _validated_definition(self.definition)
        if _definition_authority_digest(definition) != self._definition_authority_digest:
            raise ValueError("exercise definition changed during session")
        return definition

    @classmethod
    def restore(
        cls,
        definition: ExerciseDefinition,
        snapshot: Mapping[str, object],
    ) -> "ExerciseSession":
        """Restore schema-v3, or migrate unambiguous schema-v2 progress.

        Schema v2 lacked the accepted move path/FEN. It is migrated only when
        every already-completed step resolves to one unique canonical move from
        the reconstructed position. Distinct alternatives fail closed instead
        of guessing which position the learner actually reached.
        """
        definition = _validated_definition(definition)
        if not isinstance(snapshot, Mapping):
            raise TypeError("exercise snapshot must be a mapping")
        snapshot = _canonical_snapshot(snapshot)
        fields = frozenset(snapshot)
        if not fields:
            raise ValueError("invalid exercise snapshot field count")
        if "schema_version" not in fields:
            raise ValueError("invalid exercise snapshot fields (missing fields: schema_version)")
        schema_version = _snapshot_value(snapshot, "schema_version")
        if type(schema_version) is not int:
            raise TypeError("exercise snapshot schema_version must be an integer")
        if schema_version == 3:
            return cls._restore_v3(definition, snapshot)
        if schema_version == 2:
            return cls._restore_v2(definition, snapshot)
        raise ValueError(f"unsupported exercise snapshot schema_version: {schema_version}")

    @classmethod
    def _restore_v3(
        cls,
        definition: ExerciseDefinition,
        snapshot: Mapping[str, object],
    ) -> "ExerciseSession":
        _require_snapshot_fields(snapshot, _TRAINING_SNAPSHOT_V3_FIELDS)
        common = _restore_common(definition, snapshot)

        path_value = _snapshot_value(snapshot, "accepted_path")
        if type(path_value) is not list:
            raise TypeError("exercise snapshot accepted_path must be a list")
        if len(path_value) != common[0]:
            raise ValueError("exercise snapshot accepted_path does not match step_index")
        accepted_path = tuple(_snapshot_move(value) for value in path_value)

        board = Board(definition.start_fen)
        replayed: list[str] = []
        for index, recorded_san in enumerate(accepted_path):
            step = definition.steps[index]
            accepted = _resolved_accepted_moves(step, board)
            try:
                move = board.parse_move(recorded_san)
                canonical_san = board.san(move)
            except ValueError as exc:
                raise ValueError("exercise snapshot contains an illegal accepted move") from exc
            if canonical_san != recorded_san:
                raise ValueError("exercise snapshot accepted_path is not canonical SAN")
            if _move_key(move) not in accepted:
                raise ValueError("exercise snapshot move is not accepted by the exercise revision")
            replayed.append(board.push(move))

        position_fen = _snapshot_value(snapshot, "position_fen")
        if type(position_fen) is not str:
            raise TypeError("exercise snapshot position_fen must be a string")
        if len(position_fen) > _MAX_DEFINITION_TEXT:
            raise ValueError("exercise snapshot position_fen is too long")
        if position_fen != board.fen():
            raise ValueError("exercise snapshot position does not match accepted_path")

        step_index, attempts, mistakes, hints_used, status = common
        if step_index < len(definition.steps):
            _resolved_accepted_moves(definition.steps[step_index], board)

        session = cls(definition)
        session._board = board
        session._accepted_path = replayed
        session._step_index = step_index
        session._attempts = attempts
        session._mistakes = mistakes
        session._hints_used = hints_used
        session._status = status
        return session

    @classmethod
    def _restore_v2(
        cls,
        definition: ExerciseDefinition,
        snapshot: Mapping[str, object],
    ) -> "ExerciseSession":
        _require_snapshot_fields(snapshot, _TRAINING_SNAPSHOT_V2_FIELDS)
        step_index, attempts, mistakes, hints_used, status = _restore_common(definition, snapshot)

        board = Board(definition.start_fen)
        accepted_path: list[str] = []
        for index in range(step_index):
            accepted = _resolved_accepted_moves(definition.steps[index], board)
            if len(accepted) != 1:
                raise ValueError(
                    "schema-v2 exercise snapshot is ambiguous without an accepted move path"
                )
            move, _ = next(iter(accepted.values()))
            accepted_path.append(board.push(move))

        if step_index < len(definition.steps):
            _resolved_accepted_moves(definition.steps[step_index], board)

        session = cls(definition)
        session._board = board
        session._accepted_path = accepted_path
        session._step_index = step_index
        session._attempts = attempts
        session._mistakes = mistakes
        session._hints_used = hints_used
        session._status = status
        return session


def _require_exact_definition(definition: object) -> None:
    if type(definition) is not ExerciseDefinition:
        raise TypeError("definition must be an exact ExerciseDefinition")


def _canonical_definition(definition: ExerciseDefinition) -> ExerciseDefinition:
    _require_exact_definition(definition)
    if type(definition.steps) is not tuple:
        raise TypeError("exercise steps must be an exact tuple")
    if type(definition.tags) is not tuple:
        raise TypeError("exercise tags must be an exact tuple")
    if type(definition.metadata) is not dict:
        raise TypeError("exercise metadata must be an exact dict")
    if not definition.steps:
        raise ValueError("exercise requires at least one step")
    if len(definition.steps) > _MAX_EXERCISE_STEPS:
        raise ValueError("exercise has too many steps")

    steps: list[ExerciseStep] = []
    for step in definition.steps:
        if type(step) is not ExerciseStep:
            raise TypeError("exercise steps must contain exact ExerciseStep values")
        steps.append(
            ExerciseStep(
                step.accepted_moves,
                hint=step.hint,
                explanation=step.explanation,
            )
        )

    return ExerciseDefinition(
        definition.exercise_id,
        definition.start_fen,
        tuple(steps),
        title=definition.title,
        tags=definition.tags,
        source_id=definition.source_id,
        metadata=definition.metadata,
    )


def _validated_definition(definition: ExerciseDefinition) -> ExerciseDefinition:
    canonical = _canonical_definition(definition)
    if canonical != definition:
        raise ValueError("exercise definition is not canonical")
    return canonical


def _definition_authority_digest(definition: ExerciseDefinition) -> str:
    payload = {
        "exercise_id": definition.exercise_id,
        "start_fen": definition.start_fen,
        "title": definition.title,
        "tags": list(definition.tags),
        "source_id": definition.source_id,
        "metadata": definition.metadata,
        "steps": [
            {
                "accepted_moves": sorted(step.accepted_moves),
                "hint": step.hint,
                "explanation": step.explanation,
            }
            for step in definition.steps
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _restore_common(
    definition: ExerciseDefinition,
    snapshot: Mapping[str, object],
) -> tuple[int, int, int, int, ExerciseStatus]:
    exercise_id = _snapshot_value(snapshot, "exercise_id")
    if type(exercise_id) is not str:
        raise TypeError("exercise snapshot exercise_id must be a string")
    if len(exercise_id) > _MAX_DEFINITION_TEXT:
        raise ValueError("exercise snapshot exercise_id is too long")
    if exercise_id != definition.exercise_id:
        raise ValueError("exercise snapshot belongs to a different exercise")

    definition_digest = _snapshot_digest(_snapshot_value(snapshot, "definition_digest"))
    if definition_digest != _definition_digest(definition):
        raise ValueError("exercise snapshot belongs to a different exercise revision")

    step_index = _snapshot_counter(_snapshot_value(snapshot, "step_index"), name="step_index")
    attempts = _snapshot_counter(_snapshot_value(snapshot, "attempts"), name="attempts")
    mistakes = _snapshot_counter(_snapshot_value(snapshot, "mistakes"), name="mistakes")
    hints_used = _snapshot_counter(_snapshot_value(snapshot, "hints_used"), name="hints_used")

    status_value = _snapshot_value(snapshot, "status")
    if type(status_value) is not str:
        raise TypeError("exercise snapshot status must be a string")
    if len(status_value) > 32:
        raise ValueError("exercise snapshot status is too long")
    try:
        status = ExerciseStatus(status_value)
    except ValueError as exc:
        raise ValueError("invalid exercise snapshot status") from exc

    _validate_reachable_state(
        definition,
        step_index=step_index,
        attempts=attempts,
        mistakes=mistakes,
        status=status,
    )
    return step_index, attempts, mistakes, hints_used, status


def _validate_reachable_state(
    definition: ExerciseDefinition,
    *,
    step_index: int,
    attempts: int,
    mistakes: int,
    status: ExerciseStatus,
) -> None:
    if step_index > len(definition.steps):
        raise ValueError("invalid exercise step_index")
    if attempts != step_index + mistakes:
        raise ValueError("invalid exercise counters")
    if status is ExerciseStatus.COMPLETED:
        if step_index != len(definition.steps):
            raise ValueError("completed exercise snapshot has unfinished steps")
        return
    if step_index == len(definition.steps):
        raise ValueError("finished step index requires completed status")
    if status is ExerciseStatus.READY:
        if step_index != 0 or attempts != 0 or mistakes != 0:
            raise ValueError("ready exercise snapshot contains progress")
    elif step_index == 0 and attempts == 0:
        raise ValueError("in-progress exercise snapshot has no progress")


def _snapshot_fields(snapshot: Mapping[str, object]) -> frozenset[str]:
    if isinstance(snapshot, dict):
        # Built-in dict subclasses can override len/iter/contains/getitem. Read
        # their underlying dictionary storage directly so durable restore does
        # not execute hostile subclass hooks merely to discover the schema.
        field_count = dict.__len__(snapshot)
        if field_count > 32:
            raise ValueError("invalid exercise snapshot fields (too many fields)")
        raw_fields = tuple(dict.keys(snapshot))
    else:
        try:
            field_count = len(snapshot)
        except TypeError:
            try:
                raw_fields = tuple(islice(iter(snapshot), 33))
            except TypeError as exc:
                raise TypeError("exercise snapshot must be a finite mapping") from exc
            if len(raw_fields) > 32:
                raise ValueError("invalid exercise snapshot fields (too many fields)")
            field_count = len(raw_fields)
        else:
            if field_count > 32:
                raise ValueError("invalid exercise snapshot fields (too many fields)")
            raw_fields = tuple(islice(iter(snapshot), 33))
            if len(raw_fields) != field_count:
                raise ValueError("exercise snapshot fields changed during validation")

    for field_name in raw_fields:
        if type(field_name) is not str:
            raise TypeError("exercise snapshot field names must be strings")
    return frozenset(raw_fields)


def _snapshot_value(snapshot: Mapping[str, object], key: str) -> object:
    if isinstance(snapshot, dict):
        return dict.__getitem__(snapshot, key)
    return snapshot[key]


def _canonical_snapshot(snapshot: Mapping[str, object]) -> dict[str, object]:
    fields = _snapshot_fields(snapshot)
    return {
        key: _snapshot_value(snapshot, key)
        for key in sorted(fields)
    }


def _require_snapshot_fields(
    snapshot: Mapping[str, object],
    expected: frozenset[str],
) -> None:
    fields = _snapshot_fields(snapshot)
    if fields == expected:
        return
    missing = sorted(expected - fields)
    unknown = sorted(fields - expected)
    detail = []
    if missing:
        detail.append("missing fields: " + ", ".join(missing))
    if unknown:
        detail.append("unknown fields: " + ", ".join(unknown))
    raise ValueError("invalid exercise snapshot fields (" + "; ".join(detail) + ")")


def _resolved_accepted_moves(
    step: ExerciseStep,
    board: Board,
) -> dict[tuple[int, int, str | None, bool, bool], tuple[Move, str]]:
    resolved: dict[tuple[int, int, str | None, bool, bool], tuple[Move, str]] = {}
    for authored in sorted(step.accepted_moves):
        try:
            move = board.parse_move(authored)
            san = board.san(move)
        except ValueError as exc:
            raise ExerciseContentError(
                "exercise accepted move is invalid in the canonical position"
            ) from exc
        resolved[_move_key(move)] = (move, san)
    if not resolved:
        raise ExerciseContentError("exercise step has no canonical accepted move")
    return resolved


def _move_key(move: Move) -> tuple[int, int, str | None, bool, bool]:
    return move.frm, move.to, move.promotion, move.en_passant, move.castle


def _definition_digest(definition: ExerciseDefinition) -> str:
    definition = _validated_definition(definition)
    semantic_payload = {
        "start_fen": definition.start_fen,
        "steps": [sorted(step.accepted_moves) for step in definition.steps],
    }
    encoded = json.dumps(
        semantic_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_digest(value: object) -> str:
    if type(value) is not str:
        raise TypeError("exercise snapshot definition_digest must be a string")
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("invalid exercise snapshot definition_digest")
    return value


def _snapshot_counter(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"exercise snapshot {name} must be an integer")
    if value < 0 or value > _MAX_SAFE_COUNTER:
        raise ValueError("invalid exercise counters")
    return value


def _snapshot_move(value: object) -> str:
    if type(value) is not str:
        raise TypeError("exercise snapshot accepted_path entries must be strings")
    return _normalize_move(value)


def _normalize_move(value: str) -> str:
    if type(value) is not str:
        raise TypeError("move must be a string")
    if len(value) > _MAX_MOVE_TEXT:
        raise ValueError("move text is too long")
    text = " ".join(value.strip().split())
    if not text:
        raise ValueError("move must not be empty")
    return text


def _normalize_tag(value: str) -> str:
    if type(value) is not str:
        raise TypeError("exercise tag must be a string")
    if len(value) > _MAX_DEFINITION_TEXT:
        raise ValueError("exercise tag is too long")
    text = value.strip().casefold()
    if not text:
        raise ValueError("exercise tag must not be empty")
    if len(text) > _MAX_DEFINITION_TEXT:
        raise ValueError("exercise tag is too long")
    return text
