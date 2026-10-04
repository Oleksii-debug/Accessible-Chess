from __future__ import annotations

import hashlib
import json
from itertools import islice
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from .chesscore import Board, Move


TRAINING_SNAPSHOT_SCHEMA_VERSION = 4
_MAX_EXERCISE_STEPS = 2048
_MAX_ACCEPTED_MOVES_PER_STEP = 64
_MAX_MOVE_TEXT = 64
_MAX_EXERCISE_ID_TEXT = 4096
_MAX_START_FEN_TEXT = 4096
_MAX_EXERCISE_AUX_TEXT = 4096
_MAX_EXERCISE_TAGS = 256
_MAX_EXERCISE_METADATA_ITEMS = 256
_MAX_SAFE_COUNTER = (1 << 53) - 1
_MAX_SNAPSHOT_FIELD_NAME = 128
_TRAINING_SNAPSHOT_V4_FIELDS = frozenset(
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
_TRAINING_SNAPSHOT_V3_FIELDS = _TRAINING_SNAPSHOT_V4_FIELDS
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
        try:
            count = len(self.accepted_moves)
        except TypeError as exc:
            raise TypeError("exercise accepted_moves must be a finite collection") from exc
        if count > _MAX_ACCEPTED_MOVES_PER_STEP:
            raise ValueError("exercise step has too many accepted moves")
        if self.hint is not None and (
            type(self.hint) is not str or len(self.hint) > _MAX_EXERCISE_AUX_TEXT
        ):
            raise ValueError("exercise hint must be bounded text or None")
        if self.explanation is not None and (
            type(self.explanation) is not str
            or len(self.explanation) > _MAX_EXERCISE_AUX_TEXT
        ):
            raise ValueError("exercise explanation must be bounded text or None")
        normalized = frozenset(_normalize_move(move) for move in self.accepted_moves)
        if not normalized:
            raise ValueError("exercise step requires at least one accepted move")
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
        if len(self.exercise_id) > _MAX_EXERCISE_ID_TEXT:
            raise ValueError("exercise_id is too long")
        exercise_id = self.exercise_id.strip()
        if not exercise_id:
            raise ValueError("exercise_id must not be empty")

        if type(self.start_fen) is not str:
            raise TypeError("start_fen must be a string")
        if len(self.start_fen) > _MAX_START_FEN_TEXT:
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
        if any(not isinstance(step, ExerciseStep) for step in steps):
            raise TypeError("exercise steps must contain ExerciseStep values")

        if type(self.title) is not str:
            raise TypeError("exercise title must be a string")
        if len(self.title) > _MAX_EXERCISE_AUX_TEXT:
            raise ValueError("exercise title is too long")
        if self.source_id is not None:
            if type(self.source_id) is not str:
                raise TypeError("exercise source_id must be a string or None")
            if len(self.source_id) > _MAX_EXERCISE_AUX_TEXT:
                raise ValueError("exercise source_id is too long")

        try:
            tag_count = len(self.tags)
        except TypeError:
            try:
                raw_tags = tuple(islice(iter(self.tags), _MAX_EXERCISE_TAGS + 1))
            except TypeError as exc:
                raise TypeError("exercise tags must be a finite collection") from exc
            if len(raw_tags) > _MAX_EXERCISE_TAGS:
                raise ValueError("exercise has too many tags")
            tag_count = len(raw_tags)
        else:
            if tag_count > _MAX_EXERCISE_TAGS:
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
        if metadata_count > _MAX_EXERCISE_METADATA_ITEMS:
            raise ValueError("exercise metadata has too many items")
        for key, value in self.metadata.items():
            if (
                type(key) is not str
                or type(value) is not str
                or len(key) > _MAX_EXERCISE_AUX_TEXT
                or len(value) > _MAX_EXERCISE_AUX_TEXT
            ):
                raise ValueError("exercise metadata must map bounded text to bounded text")
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
        definition = _canonical_definition_snapshot(definition)
        self.definition = definition
        self._definition_authority = definition
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
        """Return a detached canonical copy of the live definition authority."""
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
        """Return strict schema-v4 progress bound to the full exercise definition."""
        definition = self._bound_definition()
        return {
            "schema_version": TRAINING_SNAPSHOT_SCHEMA_VERSION,
            "exercise_id": definition.exercise_id,
            "definition_digest": _definition_authority_digest(definition),
            "accepted_path": list(self._accepted_path),
            "position_fen": self._board.fen(),
            "step_index": self._step_index,
            "attempts": self._attempts,
            "mistakes": self._mistakes,
            "hints_used": self._hints_used,
            "status": self._status.value,
        }

    def restore_state(self, snapshot: Mapping[str, object]) -> None:
        """Atomically restore trusted progress without replacing this session.

        All durable-field validation, bounded key discovery and canonical chess
        replay complete on a detached candidate first. Live progress is mutated
        only after that candidate is fully valid, preserving both the active
        ExerciseSession identity and its bound definition authority.
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
        if self.definition is not self._definition_authority:
            raise ValueError("exercise definition authority was replaced during session")
        definition = _canonical_session_definition(self._definition_authority)
        if _definition_authority_digest(definition) != self._definition_authority_digest:
            raise ValueError("exercise definition changed during session")
        return definition

    @classmethod
    def restore(
        cls,
        definition: ExerciseDefinition,
        snapshot: Mapping[str, object],
    ) -> "ExerciseSession":
        """Restore schema-v4 progress or migrate legacy schema-v3/v2 progress.

        Schema v4 binds durable progress to the complete normalized authored
        definition. Historical schema-v3/v2 snapshots remain readable with the
        exact legacy chess-semantic digest and upgrade to v4 on the next snapshot.
        Schema v2 lacked accepted_path/FEN and is still migrated only when every
        completed step resolves to one unique canonical move.
        """
        definition = _canonical_definition_snapshot(definition)
        field_names = _snapshot_field_names(snapshot)
        if "schema_version" not in field_names:
            raise ValueError("invalid exercise snapshot fields (missing fields: schema_version)")
        schema_version = snapshot["schema_version"]
        if type(schema_version) is not int:
            raise TypeError("exercise snapshot schema_version must be an integer")
        if schema_version == 4:
            _require_snapshot_field_names(field_names, _TRAINING_SNAPSHOT_V4_FIELDS)
            return cls._restore_path_snapshot(
                definition,
                snapshot,
                expected_definition_digest=_definition_authority_digest(definition),
            )
        if schema_version == 3:
            _require_snapshot_field_names(field_names, _TRAINING_SNAPSHOT_V3_FIELDS)
            return cls._restore_path_snapshot(
                definition,
                snapshot,
                expected_definition_digest=_definition_digest(definition),
            )
        if schema_version == 2:
            _require_snapshot_field_names(field_names, _TRAINING_SNAPSHOT_V2_FIELDS)
            return cls._restore_v2(definition, snapshot)
        raise ValueError("unsupported exercise snapshot schema_version")

    @classmethod
    def _restore_path_snapshot(
        cls,
        definition: ExerciseDefinition,
        snapshot: Mapping[str, object],
        *,
        expected_definition_digest: str,
    ) -> "ExerciseSession":
        common = _restore_common(
            definition,
            snapshot,
            expected_definition_digest=expected_definition_digest,
        )

        path_value = snapshot["accepted_path"]
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

        position_fen = snapshot["position_fen"]
        if type(position_fen) is not str:
            raise TypeError("exercise snapshot position_fen must be a string")
        if len(position_fen) > _MAX_START_FEN_TEXT:
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
        step_index, attempts, mistakes, hints_used, status = _restore_common(
            definition,
            snapshot,
            expected_definition_digest=_definition_digest(definition),
        )

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


def _restore_common(
    definition: ExerciseDefinition,
    snapshot: Mapping[str, object],
    *,
    expected_definition_digest: str,
) -> tuple[int, int, int, int, ExerciseStatus]:
    exercise_id = snapshot["exercise_id"]
    if type(exercise_id) is not str:
        raise TypeError("exercise snapshot exercise_id must be a string")
    if len(exercise_id) > _MAX_EXERCISE_ID_TEXT:
        raise ValueError("exercise snapshot exercise_id is too long")
    if exercise_id != definition.exercise_id:
        raise ValueError("exercise snapshot belongs to a different exercise")

    definition_digest = _snapshot_digest(snapshot["definition_digest"])
    if definition_digest != expected_definition_digest:
        raise ValueError("exercise snapshot belongs to a different exercise revision")

    step_index = _snapshot_counter(snapshot["step_index"], name="step_index")
    attempts = _snapshot_counter(snapshot["attempts"], name="attempts")
    mistakes = _snapshot_counter(snapshot["mistakes"], name="mistakes")
    hints_used = _snapshot_counter(snapshot["hints_used"], name="hints_used")

    status_value = snapshot["status"]
    if type(status_value) is not str:
        raise TypeError("exercise snapshot status must be a string")
    if len(status_value) > 32:
        raise ValueError("invalid exercise snapshot status")
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


def _snapshot_field_names(snapshot: Mapping[str, object]) -> tuple[str, ...]:
    if not isinstance(snapshot, Mapping):
        raise TypeError("exercise snapshot must be a mapping")
    allowed_counts = {
        len(_TRAINING_SNAPSHOT_V2_FIELDS),
        len(_TRAINING_SNAPSHOT_V3_FIELDS),
        len(_TRAINING_SNAPSHOT_V4_FIELDS),
    }
    max_fields = max(allowed_counts)

    # JSON recovery yields a built-in dict. For dict subclasses, inspect the
    # underlying built-in container count without dispatching an overridden
    # __len__ hook. An impossible backing size can therefore fail before any
    # provider-defined iteration/key hook. Non-dict Mapping implementations keep
    # the historical bounded max_fields+1 probe below.
    if isinstance(snapshot, dict):
        backing_count = dict.__len__(snapshot)
        if backing_count not in allowed_counts:
            raise ValueError("invalid exercise snapshot field count")

    try:
        field_names = tuple(islice(iter(snapshot), max_fields + 1))
    except TypeError as exc:
        raise TypeError("exercise snapshot must expose finite field names") from exc
    if len(field_names) not in allowed_counts:
        raise ValueError("invalid exercise snapshot field count")
    for field_name in field_names:
        if type(field_name) is not str:
            raise TypeError("exercise snapshot field names must be strings")
        if len(field_name) > _MAX_SNAPSHOT_FIELD_NAME:
            raise ValueError("exercise snapshot field name is too long")
    return field_names


def _require_snapshot_field_names(
    field_names: tuple[str, ...],
    expected: frozenset[str],
) -> None:
    if len(field_names) != len(expected):
        raise ValueError("invalid exercise snapshot field count")
    fields = set(field_names)
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


def _canonical_definition_snapshot(definition: ExerciseDefinition) -> ExerciseDefinition:
    # ExerciseDefinition is the canonical authored Training root. Its public
    # constructor already normalizes ordinary iterables/mappings into built-in
    # tuple/dict/frozenset containers, so session/persistence ingress can require
    # those closed roots before any detached-copy traversal executes hooks.
    if type(definition) is not ExerciseDefinition:
        raise TypeError("definition must be an ExerciseDefinition")
    if type(definition.steps) is not tuple:
        raise ValueError("exercise definition steps must be canonical")
    if type(definition.tags) is not tuple:
        raise ValueError("exercise definition tags must be canonical")
    if type(definition.metadata) is not dict:
        raise ValueError("exercise definition metadata must be canonical")
    for step in definition.steps:
        if type(step) is not ExerciseStep:
            raise ValueError("exercise definition steps must be canonical")
        if type(step.accepted_moves) is not frozenset:
            raise ValueError("exercise accepted moves must be canonical")
    normalized = ExerciseDefinition(
        definition.exercise_id,
        definition.start_fen,
        definition.steps,
        title=definition.title,
        tags=definition.tags,
        source_id=definition.source_id,
        metadata=definition.metadata,
    )
    detached_steps = tuple(
        ExerciseStep(
            step.accepted_moves,
            hint=step.hint,
            explanation=step.explanation,
        )
        for step in normalized.steps
    )
    return ExerciseDefinition(
        normalized.exercise_id,
        normalized.start_fen,
        detached_steps,
        title=normalized.title,
        tags=normalized.tags,
        source_id=normalized.source_id,
        metadata=normalized.metadata,
    )


def _canonical_session_definition(definition: ExerciseDefinition) -> ExerciseDefinition:
    if type(definition) is not ExerciseDefinition:
        raise ValueError("exercise definition authority type changed during session")
    if type(definition.steps) is not tuple:
        raise ValueError("exercise definition steps changed during session")
    if type(definition.tags) is not tuple:
        raise ValueError("exercise definition tags changed during session")
    if type(definition.metadata) is not dict:
        raise ValueError("exercise definition metadata changed during session")
    for step in definition.steps:
        if type(step) is not ExerciseStep:
            raise ValueError("exercise definition step authority changed during session")
        if type(step.accepted_moves) is not frozenset:
            raise ValueError("exercise accepted move authority changed during session")
    return _canonical_definition_snapshot(definition)


def _definition_authority_digest(definition: ExerciseDefinition) -> str:
    payload = {
        "exercise_id": definition.exercise_id,
        "start_fen": definition.start_fen,
        "title": definition.title,
        "tags": list(definition.tags),
        "source_id": definition.source_id,
        "metadata": dict(definition.metadata),
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
    definition = _canonical_definition_snapshot(definition)
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
    # Raw authoring/submission/snapshot data must fit the canonical scalar
    # envelope before strip/split/join scans it.
    if len(value) > _MAX_MOVE_TEXT:
        raise ValueError("move text is too long")
    text = " ".join(value.strip().split())
    if not text:
        raise ValueError("move must not be empty")
    if len(text) > _MAX_MOVE_TEXT:
        raise ValueError("move text is too long")
    return text


def _normalize_tag(value: str) -> str:
    if type(value) is not str:
        raise TypeError("exercise tag must be a string")
    if len(value) > _MAX_EXERCISE_AUX_TEXT:
        raise ValueError("exercise tag is too long")
    text = value.strip().casefold()
    if not text:
        raise ValueError("exercise tag must not be empty")
    if len(text) > _MAX_EXERCISE_AUX_TEXT:
        raise ValueError("exercise tag is too long")
    return text
