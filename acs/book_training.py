from __future__ import annotations

"""Provenance-safe bridge from semantic chess books to canonical training.

This module is deliberately presentation-neutral.  It does not parse chess moves
itself and it does not own a second board.  Book structure is read through the
existing BookDocument/BookIndex contracts, solution PGN is read through the
existing GameTree parser, and every answer is resolved by ``chesscore.Board``.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Mapping

from .book_index import AmbiguousBookTargetError, BookIndex
from .bookdocument import BookDocument, Exercise
from .bookreader import BookReader, ReadingLocation
from .chesscore import Board
from .gametree import GameTreeContractError, MoveNode, PgnGame, parse_games
from .training import ExerciseDefinition, ExerciseStep


BOOK_TRAINING_SCHEMA_VERSION = 1
_MAX_SOLUTION_PGN_TEXT = 256_000
_MAX_ORIGIN_TEXT = 4096
_MATERIAL_FIELDS = frozenset({"schema_version", "origin", "definition"})
_ORIGIN_FIELDS = frozenset(
    {
        "target_key",
        "block_digest",
        "index_at_export",
        "block_id",
        "source_anchor",
        "heading_path",
        "book_fingerprint",
    }
)
_DEFINITION_FIELDS = frozenset(
    {"exercise_id", "start_fen", "steps", "title", "tags", "source_id", "metadata"}
)
_STEP_FIELDS = frozenset({"accepted_moves", "hint", "explanation"})


class BookTrainingErrorCode(str, Enum):
    INVALID_FIELD = "invalid_field"
    INVALID_TARGET = "invalid_target"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    UNKNOWN_FIELD = "unknown_field"
    UNSUPPORTED_SOLUTION = "unsupported_solution"
    UNSUPPORTED_SOLUTION_STRUCTURE = "unsupported_solution_structure"
    ILLEGAL_SOLUTION = "illegal_solution"
    STALE_ORIGIN = "stale_origin"


class BookTrainingError(ValueError):
    """Stable failure for BookDocument -> TrainingDefinition conversion."""

    def __init__(self, message: str, *, code: BookTrainingErrorCode) -> None:
        super().__init__(message)
        self.code = BookTrainingErrorCode(code)


def _bounded_text(value: object, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str:
        raise BookTrainingError(
            f"{name} must be text" if not allow_none else f"{name} must be text or null",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    text = value.strip()
    if not text or len(text) > _MAX_ORIGIN_TEXT:
        raise BookTrainingError(
            f"{name} is empty or exceeds the safety limit",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    return text


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _book_fingerprint(document: BookDocument) -> str:
    # The fingerprint binds stable book-level provenance while keeping source_name
    # (which may be a private local path) out of exported training payloads.
    return _sha256_json(
        {
            "title": document.title,
            "language": document.language,
            "author": document.author,
            "source_name": document.source_name,
        }
    )


def _block_digest(block: Exercise) -> str:
    return _sha256_json(block.as_dict())


def _require_sha256(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise BookTrainingError(
            f"{name} must be lowercase SHA-256 hex",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    return value


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: frozenset[str],
    name: str,
) -> None:
    fields = set(payload)
    if fields == expected:
        return
    missing = sorted(expected - fields)
    unknown = sorted(fields - expected)
    details: list[str] = []
    if missing:
        details.append("missing fields: " + ", ".join(missing))
    if unknown:
        details.append("unknown fields: " + ", ".join(unknown))
    code = BookTrainingErrorCode.UNKNOWN_FIELD if unknown else BookTrainingErrorCode.INVALID_FIELD
    raise BookTrainingError(
        f"invalid {name} fields (" + "; ".join(details) + ")",
        code=code,
    )


@dataclass(frozen=True, slots=True)
class BookTrainingOrigin:
    """Durable semantic return identity for one book exercise.

    ``target_key`` follows BookIndex semantics: block/source identities survive
    surrounding reordering, while an index-only fallback intentionally remains
    snapshot-bound.  ``block_digest`` prevents a stable key from silently
    resolving to revised exercise content.
    """

    target_key: str
    block_digest: str
    index_at_export: int
    block_id: str | None
    source_anchor: str | None
    heading_path: tuple[str, ...]
    book_fingerprint: str

    def __post_init__(self) -> None:
        target_key = _bounded_text(self.target_key, "book training target_key")
        if not (
            target_key.startswith("block:")
            or target_key.startswith("source:")
            or target_key.startswith("index:")
        ):
            raise BookTrainingError(
                "book training target_key uses an unsupported target family",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        _require_sha256(self.block_digest, "book training block_digest")
        _require_sha256(self.book_fingerprint, "book training book_fingerprint")
        if type(self.index_at_export) is not int or self.index_at_export < 0:
            raise BookTrainingError(
                "book training index_at_export must be a non-negative integer",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        block_id = _bounded_text(self.block_id, "book training block_id", allow_none=True)
        source_anchor = _bounded_text(
            self.source_anchor,
            "book training source_anchor",
            allow_none=True,
        )
        if type(self.heading_path) is not tuple or any(
            type(item) is not str or not item.strip() or len(item) > _MAX_ORIGIN_TEXT
            for item in self.heading_path
        ):
            raise BookTrainingError(
                "book training heading_path must be a tuple of bounded non-empty text",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        object.__setattr__(self, "target_key", target_key)
        object.__setattr__(self, "block_id", block_id)
        object.__setattr__(self, "source_anchor", source_anchor)

    def as_dict(self) -> dict[str, object]:
        return {
            "target_key": self.target_key,
            "block_digest": self.block_digest,
            "index_at_export": self.index_at_export,
            "block_id": self.block_id,
            "source_anchor": self.source_anchor,
            "heading_path": list(self.heading_path),
            "book_fingerprint": self.book_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "BookTrainingOrigin":
        if not isinstance(payload, Mapping):
            raise BookTrainingError(
                "book training origin must be a mapping",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        _require_exact_fields(payload, _ORIGIN_FIELDS, "book training origin")
        heading_path = payload["heading_path"]
        if type(heading_path) is not list:
            raise BookTrainingError(
                "book training heading_path must be a list",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        return cls(
            target_key=payload["target_key"],  # type: ignore[arg-type]
            block_digest=payload["block_digest"],  # type: ignore[arg-type]
            index_at_export=payload["index_at_export"],  # type: ignore[arg-type]
            block_id=payload["block_id"],  # type: ignore[arg-type]
            source_anchor=payload["source_anchor"],  # type: ignore[arg-type]
            heading_path=tuple(heading_path),
            book_fingerprint=payload["book_fingerprint"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class BookTrainingMaterial:
    """Detached canonical training definition plus its exact book origin."""

    origin: BookTrainingOrigin
    definition: ExerciseDefinition

    def __post_init__(self) -> None:
        if not isinstance(self.origin, BookTrainingOrigin):
            raise TypeError("origin must be a BookTrainingOrigin")
        if not isinstance(self.definition, ExerciseDefinition):
            raise TypeError("definition must be an ExerciseDefinition")

    def as_dict(self) -> dict[str, object]:
        # Rebuild the definition through the strict wire decoder so a caller that
        # mutated the Mapping held by a frozen ExerciseDefinition cannot publish
        # malformed or coercive content.
        canonical = _definition_from_dict(_definition_to_dict(self.definition))
        return {
            "schema_version": BOOK_TRAINING_SCHEMA_VERSION,
            "origin": self.origin.as_dict(),
            "definition": _definition_to_dict(canonical),
        }


def _definition_to_dict(definition: ExerciseDefinition) -> dict[str, object]:
    if not isinstance(definition, ExerciseDefinition):
        raise TypeError("definition must be an ExerciseDefinition")
    if type(definition.title) is not str:
        raise BookTrainingError(
            "exercise title must be text",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    if type(definition.tags) is not tuple or any(type(tag) is not str for tag in definition.tags):
        raise BookTrainingError(
            "exercise tags must be a tuple of text",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    if not isinstance(definition.metadata, Mapping) or any(
        type(key) is not str or type(value) is not str
        for key, value in definition.metadata.items()
    ):
        raise BookTrainingError(
            "exercise metadata must map text keys to text values",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    return {
        "exercise_id": definition.exercise_id,
        "start_fen": definition.start_fen,
        "steps": [
            {
                "accepted_moves": sorted(step.accepted_moves),
                "hint": step.hint,
                "explanation": step.explanation,
            }
            for step in definition.steps
        ],
        "title": definition.title,
        "tags": list(definition.tags),
        "source_id": definition.source_id,
        "metadata": dict(sorted(definition.metadata.items())),
    }


def _definition_from_dict(payload: Mapping[str, object]) -> ExerciseDefinition:
    if not isinstance(payload, Mapping):
        raise BookTrainingError(
            "book training definition must be a mapping",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    _require_exact_fields(payload, _DEFINITION_FIELDS, "book training definition")
    steps_value = payload["steps"]
    if type(steps_value) is not list:
        raise BookTrainingError(
            "book training definition steps must be a list",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    steps: list[ExerciseStep] = []
    for raw_step in steps_value:
        if not isinstance(raw_step, Mapping):
            raise BookTrainingError(
                "book training step must be a mapping",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        _require_exact_fields(raw_step, _STEP_FIELDS, "book training step")
        accepted = raw_step["accepted_moves"]
        if type(accepted) is not list or any(type(move) is not str for move in accepted):
            raise BookTrainingError(
                "book training accepted_moves must be a list of text",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        hint = raw_step["hint"]
        explanation = raw_step["explanation"]
        if hint is not None and type(hint) is not str:
            raise BookTrainingError(
                "book training hint must be text or null",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        if explanation is not None and type(explanation) is not str:
            raise BookTrainingError(
                "book training explanation must be text or null",
                code=BookTrainingErrorCode.INVALID_FIELD,
            )
        try:
            steps.append(ExerciseStep(frozenset(accepted), hint=hint, explanation=explanation))
        except (TypeError, ValueError) as exc:
            raise BookTrainingError(
                "book training step is invalid",
                code=BookTrainingErrorCode.INVALID_FIELD,
            ) from exc

    tags = payload["tags"]
    metadata = payload["metadata"]
    if type(tags) is not list or any(type(tag) is not str for tag in tags):
        raise BookTrainingError(
            "book training tags must be a list of text",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    if not isinstance(metadata, Mapping) or any(
        type(key) is not str or type(value) is not str for key, value in metadata.items()
    ):
        raise BookTrainingError(
            "book training metadata must map text keys to text values",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    source_id = payload["source_id"]
    if source_id is not None and type(source_id) is not str:
        raise BookTrainingError(
            "book training source_id must be text or null",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    if type(payload["exercise_id"]) is not str or type(payload["start_fen"]) is not str:
        raise BookTrainingError(
            "book training exercise_id and start_fen must be text",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    if type(payload["title"]) is not str:
        raise BookTrainingError(
            "book training title must be text",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    try:
        return ExerciseDefinition(
            exercise_id=payload["exercise_id"],
            start_fen=payload["start_fen"],
            steps=tuple(steps),
            title=payload["title"],
            tags=tuple(tags),
            source_id=source_id,
            metadata=dict(metadata),
        )
    except (TypeError, ValueError) as exc:
        raise BookTrainingError(
            "book training definition is invalid",
            code=BookTrainingErrorCode.INVALID_FIELD,
        ) from exc


def _line_has_unsupported_structure(game: PgnGame) -> bool:
    line = game.line
    if line.leading_comments or line.trailing_comments:
        return True
    for node in line.moves:
        if (
            node.nags
            or node.comments_before
            or node.comments_after
            or node.variations
        ):
            return True
    return False


def _canonical_steps_from_nodes(start_board: Board, nodes: list[MoveNode]) -> tuple[ExerciseStep, ...]:
    if not nodes:
        raise BookTrainingError(
            "book exercise solution contains no moves",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION,
        )
    board = Board(start_board.fen())
    steps: list[ExerciseStep] = []
    for node in nodes:
        try:
            move = board.parse_move(node.san)
            canonical_san = board.san(move)
            step = ExerciseStep(frozenset({canonical_san}))
            board.push(move)
        except (TypeError, ValueError) as exc:
            raise BookTrainingError(
                "book exercise solution contains a move illegal in the canonical position",
                code=BookTrainingErrorCode.ILLEGAL_SOLUTION,
            ) from exc
        steps.append(step)
    return tuple(steps)


def _canonical_steps_from_answer(start_board: Board, answer_text: str) -> tuple[ExerciseStep, ...]:
    try:
        bounded = ExerciseStep(frozenset({answer_text}))
        authored = next(iter(bounded.accepted_moves))
        board = Board(start_board.fen())
        move = board.parse_move(authored)
        canonical_san = board.san(move)
    except (TypeError, ValueError) as exc:
        raise BookTrainingError(
            "book exercise answer_text is not one legal canonical chess move",
            code=BookTrainingErrorCode.ILLEGAL_SOLUTION,
        ) from exc
    return (ExerciseStep(frozenset({canonical_san})),)


def _canonical_steps_from_pgn(start_board: Board, solution_pgn: str) -> tuple[ExerciseStep, ...]:
    if len(solution_pgn) > _MAX_SOLUTION_PGN_TEXT:
        raise BookTrainingError(
            "book exercise solution_pgn exceeds the safety limit",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    try:
        games = parse_games(solution_pgn)
    except (GameTreeContractError, TypeError, ValueError) as exc:
        raise BookTrainingError(
            "book exercise solution_pgn is structurally invalid",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION,
        ) from exc
    if len(games) != 1:
        raise BookTrainingError(
            "book exercise solution_pgn must contain exactly one game/line",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
        )
    game = games[0]
    if game.warnings:
        raise BookTrainingError(
            "book exercise solution_pgn contains recovery warnings",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
        )
    if _line_has_unsupported_structure(game):
        raise BookTrainingError(
            "book exercise solution_pgn contains annotations or variations that cannot be silently flattened",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
        )

    setup = game.tags.get("SetUp")
    tagged_fen = game.tags.get("FEN")
    if setup not in {None, "0", "1"}:
        raise BookTrainingError(
            "book exercise solution_pgn has an invalid SetUp tag",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
        )
    if setup == "1" and tagged_fen is None:
        raise BookTrainingError(
            "book exercise solution_pgn SetUp tag requires FEN",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
        )
    if setup == "0" and tagged_fen is not None:
        raise BookTrainingError(
            "book exercise solution_pgn has contradictory SetUp/FEN tags",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
        )
    if tagged_fen is not None:
        try:
            tagged = Board(tagged_fen).fen()
        except (TypeError, ValueError) as exc:
            raise BookTrainingError(
                "book exercise solution_pgn FEN is invalid",
                code=BookTrainingErrorCode.ILLEGAL_SOLUTION,
            ) from exc
        if tagged != start_board.fen():
            raise BookTrainingError(
                "book exercise solution_pgn FEN does not match the Exercise position",
                code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
            )
    return _canonical_steps_from_nodes(start_board, game.line.moves)


def _definition_from_book_exercise(
    document: BookDocument,
    exercise: Exercise,
    *,
    target_key: str,
    book_fingerprint: str,
) -> ExerciseDefinition:
    try:
        start_board = Board(exercise.fen)
    except (TypeError, ValueError) as exc:
        raise BookTrainingError(
            "book exercise position is invalid in the canonical chess core",
            code=BookTrainingErrorCode.ILLEGAL_SOLUTION,
        ) from exc

    if exercise.solution_pgn is not None and exercise.answer_text is not None:
        raise BookTrainingError(
            "book exercise has both solution_pgn and answer_text; an explicit solution policy is required",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION,
        )
    if exercise.solution_pgn is not None:
        steps = _canonical_steps_from_pgn(start_board, exercise.solution_pgn)
    elif exercise.answer_text is not None:
        steps = _canonical_steps_from_answer(start_board, exercise.answer_text)
    else:
        raise BookTrainingError(
            "book exercise has no training solution",
            code=BookTrainingErrorCode.UNSUPPORTED_SOLUTION,
        )

    block_digest = _block_digest(exercise)
    identity_seed = book_fingerprint + "\0" + target_key + "\0" + block_digest
    exercise_id = "book-exercise:" + hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()
    source_seed = book_fingerprint + "\0" + target_key
    source_id = "book:" + hashlib.sha256(source_seed.encode("utf-8")).hexdigest()
    metadata: dict[str, str] = {"content_kind": "book_exercise"}
    if exercise.difficulty is not None:
        metadata["difficulty"] = exercise.difficulty

    return ExerciseDefinition(
        exercise_id=exercise_id,
        start_fen=start_board.fen(),
        steps=steps,
        title=exercise.prompt,
        source_id=source_id,
        metadata=metadata,
    )


def build_book_training_material(
    document: BookDocument,
    target: str | int,
) -> BookTrainingMaterial:
    """Derive canonical training from one semantic BookDocument Exercise.

    ``target`` may be a BookIndex target key or an exact current linear index.
    Semantic duplicate keys fail closed through BookIndex instead of silently
    selecting the first matching exercise.
    """
    if not isinstance(document, BookDocument):
        raise TypeError("document must be a BookDocument")
    index = BookIndex(document)
    if type(target) is int:
        if not 0 <= target < len(index.entries):
            raise BookTrainingError(
                "book exercise index is outside the document",
                code=BookTrainingErrorCode.INVALID_TARGET,
            )
        entry = index.entries[target]
        try:
            entry = index.resolve(entry.target.key)
        except (LookupError, AmbiguousBookTargetError) as exc:
            raise BookTrainingError(
                "book exercise target is missing or ambiguous",
                code=BookTrainingErrorCode.INVALID_TARGET,
            ) from exc
    elif type(target) is str:
        try:
            entry = index.resolve(target)
        except (LookupError, AmbiguousBookTargetError) as exc:
            raise BookTrainingError(
                "book exercise target is missing or ambiguous",
                code=BookTrainingErrorCode.INVALID_TARGET,
            ) from exc
    else:
        raise BookTrainingError(
            "book exercise target must be a target key or integer index",
            code=BookTrainingErrorCode.INVALID_TARGET,
        )

    block = document.blocks[entry.target.index]
    if not isinstance(block, Exercise):
        raise BookTrainingError(
            "book target is not an Exercise block",
            code=BookTrainingErrorCode.INVALID_TARGET,
        )
    fingerprint = _book_fingerprint(document)
    origin = BookTrainingOrigin(
        target_key=entry.target.key,
        block_digest=_block_digest(block),
        index_at_export=entry.target.index,
        block_id=entry.target.block_id,
        source_anchor=entry.target.source_anchor,
        heading_path=entry.heading_path,
        book_fingerprint=fingerprint,
    )
    definition = _definition_from_book_exercise(
        document,
        block,
        target_key=entry.target.key,
        book_fingerprint=fingerprint,
    )
    return BookTrainingMaterial(origin, definition)


def build_current_book_training_material(reader: BookReader) -> BookTrainingMaterial:
    """Create training from the reader's exact current semantic exercise."""
    if not isinstance(reader, BookReader):
        raise TypeError("reader must be a BookReader")
    location = reader.location()
    if location.kind != "Exercise":
        raise BookTrainingError(
            "current BookReader location is not an Exercise",
            code=BookTrainingErrorCode.INVALID_TARGET,
        )
    return build_book_training_material(reader.document, location.index)


def resolve_book_training_origin(
    document: BookDocument,
    origin: BookTrainingOrigin,
) -> ReadingLocation:
    """Resolve a durable origin without mutating chess/application state."""
    if not isinstance(document, BookDocument):
        raise TypeError("document must be a BookDocument")
    if not isinstance(origin, BookTrainingOrigin):
        raise TypeError("origin must be a BookTrainingOrigin")
    if _book_fingerprint(document) != origin.book_fingerprint:
        raise BookTrainingError(
            "book training origin belongs to a different book identity",
            code=BookTrainingErrorCode.STALE_ORIGIN,
        )
    index = BookIndex(document)
    try:
        entry = index.resolve(origin.target_key)
    except (LookupError, AmbiguousBookTargetError) as exc:
        raise BookTrainingError(
            "book training origin no longer resolves uniquely",
            code=BookTrainingErrorCode.STALE_ORIGIN,
        ) from exc
    block = document.blocks[entry.target.index]
    if not isinstance(block, Exercise) or _block_digest(block) != origin.block_digest:
        raise BookTrainingError(
            "book training origin exercise content changed",
            code=BookTrainingErrorCode.STALE_ORIGIN,
        )
    if entry.target.block_id != origin.block_id or entry.target.source_anchor != origin.source_anchor:
        raise BookTrainingError(
            "book training origin semantic identity changed",
            code=BookTrainingErrorCode.STALE_ORIGIN,
        )
    reader = BookReader(document)
    return reader.go_to(entry.target.index)


def return_reader_to_book_training_origin(
    reader: BookReader,
    origin: BookTrainingOrigin,
) -> ReadingLocation:
    """Return an existing reader to the exact source exercise.

    This moves only the presentation-neutral reading cursor.  It never changes a
    chess Position, ExerciseSession, Teacher/Classroom state or persistence.
    """
    if not isinstance(reader, BookReader):
        raise TypeError("reader must be a BookReader")
    location = resolve_book_training_origin(reader.document, origin)
    return reader.go_to(location.index)


def restore_book_training_material(
    document: BookDocument,
    payload: Mapping[str, object],
) -> BookTrainingMaterial:
    """Restore a versioned exported material and prove it still matches source.

    The payload is not trusted as a new source of chess truth.  Its origin is
    resolved back to BookDocument and the canonical definition is regenerated;
    any stale/tampered definition fails closed.
    """
    if not isinstance(payload, Mapping):
        raise BookTrainingError(
            "book training material must be a mapping",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    _require_exact_fields(payload, _MATERIAL_FIELDS, "book training material")
    version = payload["schema_version"]
    if type(version) is not int:
        raise BookTrainingError(
            "book training schema_version must be an integer",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    if version != BOOK_TRAINING_SCHEMA_VERSION:
        raise BookTrainingError(
            f"unsupported book training schema_version: {version}",
            code=BookTrainingErrorCode.UNSUPPORTED_SCHEMA,
        )
    origin_value = payload["origin"]
    definition_value = payload["definition"]
    if not isinstance(origin_value, Mapping) or not isinstance(definition_value, Mapping):
        raise BookTrainingError(
            "book training origin and definition must be mappings",
            code=BookTrainingErrorCode.INVALID_FIELD,
        )
    origin = BookTrainingOrigin.from_dict(origin_value)
    definition = _definition_from_dict(definition_value)
    resolve_book_training_origin(document, origin)
    expected = build_book_training_material(document, origin.target_key)
    if _definition_to_dict(definition) != _definition_to_dict(expected.definition):
        raise BookTrainingError(
            "book training definition no longer matches its canonical source exercise",
            code=BookTrainingErrorCode.STALE_ORIGIN,
        )
    return BookTrainingMaterial(origin, definition)
