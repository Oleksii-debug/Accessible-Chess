from __future__ import annotations

"""Atomic copy-on-write annotation editing for the canonical GameTree.

Comments and NAGs are structural chess-record data, not presentation state.  Every
edit target is bound to the exact semantic game digest so a stale address cannot
silently modify a different move/variation after concurrent or intervening work.
The source ``PgnGame`` and caller-owned annotation objects are never mutated.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import re

from .game_identity import GameIdentityContractError, identity_for_game
from .gametree import (
    Comment,
    CommentStyle,
    GameTreeContractError,
    GameTreeSerializationError,
    MoveNode,
    NAG_RE,
    NAG_SYMBOLS,
    PgnGame,
    VariationLine,
    serialize_game,
)
from .gametree_navigation import (
    GameTreeNavigationCode,
    GameTreePathError,
    VariationPath,
    VariationStep,
    iter_move_addresses,
    resolve_line,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class AnnotationEditCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    INVALID_TARGET = "invalid_target"
    INVALID_COMMENT = "invalid_comment"
    INVALID_NAG = "invalid_nag"
    STALE_REVISION = "stale_revision"
    GRAPH_CYCLE = "graph_cycle"
    GRAPH_REUSE = "graph_reuse"
    GRAPH_DEPTH_LIMIT = "graph_depth_limit"
    GRAPH_NODE_LIMIT = "graph_node_limit"
    UNREPRESENTABLE = "unrepresentable"


class AnnotationEditError(ValueError):
    def __init__(self, message: str, *, code: AnnotationEditCode) -> None:
        super().__init__(message)
        self.code = AnnotationEditCode(code)


@dataclass(frozen=True, slots=True)
class MoveAnnotationTarget:
    line_path: VariationPath
    move_index: int
    expected_record_digest: str

    def __post_init__(self) -> None:
        _validate_path(self.line_path)
        if type(self.move_index) is not int or self.move_index < 0:
            raise TypeError("move_index must be a non-negative exact integer")
        _validate_digest(self.expected_record_digest)


@dataclass(frozen=True, slots=True)
class LineAnnotationTarget:
    line_path: VariationPath
    expected_record_digest: str

    def __post_init__(self) -> None:
        _validate_path(self.line_path)
        _validate_digest(self.expected_record_digest)


@dataclass(frozen=True, slots=True)
class MoveAnnotationPatch:
    comments_before: tuple[Comment, ...] | None = None
    comments_after: tuple[Comment, ...] | None = None
    nags: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.comments_before is not None:
            _validate_comment_tuple(self.comments_before, "comments_before")
        if self.comments_after is not None:
            _validate_comment_tuple(self.comments_after, "comments_after")
        if self.nags is not None:
            _validate_nag_tuple(self.nags)
        if self.comments_before is None and self.comments_after is None and self.nags is None:
            raise ValueError("annotation patch must change at least one field")


@dataclass(frozen=True, slots=True)
class LineAnnotationPatch:
    leading_comments: tuple[Comment, ...] | None = None
    trailing_comments: tuple[Comment, ...] | None = None

    def __post_init__(self) -> None:
        if self.leading_comments is not None:
            _validate_comment_tuple(self.leading_comments, "leading_comments")
        if self.trailing_comments is not None:
            _validate_comment_tuple(self.trailing_comments, "trailing_comments")
        if self.leading_comments is None and self.trailing_comments is None:
            raise ValueError("annotation patch must change at least one field")


@dataclass(frozen=True, slots=True)
class AnnotationEditResult:
    game: PgnGame
    before_record_digest: str
    after_record_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.game, PgnGame):
            raise TypeError("game must be a PgnGame")
        _validate_digest(self.before_record_digest)
        _validate_digest(self.after_record_digest)


def _validate_path(path: object) -> VariationPath:
    if not isinstance(path, tuple) or any(not isinstance(step, VariationStep) for step in path):
        raise TypeError("line_path must be a tuple of VariationStep values")
    return path


def _validate_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError("expected_record_digest must be a lowercase SHA-256 digest")
    return value


def _validate_comment_tuple(value: object, field_name: str) -> tuple[Comment, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    for comment in value:
        if not isinstance(comment, Comment):
            raise TypeError(f"{field_name} must contain Comment values")
        if not isinstance(comment.text, str):
            raise TypeError("comment text must be a string")
        try:
            CommentStyle(comment.style)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported comment style") from exc
    return value


def _validate_nag_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError("nags must be a tuple")
    for nag in value:
        if not isinstance(nag, str) or (NAG_RE.fullmatch(nag) is None and nag not in NAG_SYMBOLS):
            raise ValueError("nags must contain canonical PGN NAG strings")
    return value


def _map_navigation_code(code: GameTreeNavigationCode) -> AnnotationEditCode:
    return {
        GameTreeNavigationCode.GRAPH_CYCLE: AnnotationEditCode.GRAPH_CYCLE,
        GameTreeNavigationCode.GRAPH_REUSE: AnnotationEditCode.GRAPH_REUSE,
        GameTreeNavigationCode.GRAPH_DEPTH_LIMIT: AnnotationEditCode.GRAPH_DEPTH_LIMIT,
        GameTreeNavigationCode.GRAPH_NODE_LIMIT: AnnotationEditCode.GRAPH_NODE_LIMIT,
    }.get(code, AnnotationEditCode.INVALID_INPUT)


def _validated_digest(game: object) -> str:
    if not isinstance(game, PgnGame):
        raise AnnotationEditError("annotation editing requires a PgnGame", code=AnnotationEditCode.INVALID_INPUT)
    try:
        for _ in iter_move_addresses(game):
            pass
        digest = identity_for_game(game).record_digest
        serialize_game(game)
        return digest
    except GameTreePathError as exc:
        raise AnnotationEditError(str(exc), code=_map_navigation_code(exc.code)) from exc
    except GameIdentityContractError as exc:
        code = (
            AnnotationEditCode.GRAPH_CYCLE
            if exc.code.value == "cyclic_tree"
            else AnnotationEditCode.GRAPH_DEPTH_LIMIT
            if exc.code.value == "tree_limit_exceeded"
            else AnnotationEditCode.INVALID_INPUT
        )
        raise AnnotationEditError(str(exc), code=code) from exc
    except GameTreeSerializationError as exc:
        raise AnnotationEditError(str(exc), code=AnnotationEditCode.UNREPRESENTABLE) from exc
    except GameTreeContractError as exc:
        raise AnnotationEditError(str(exc), code=AnnotationEditCode.INVALID_INPUT) from exc


def move_annotation_target(game: PgnGame, line_path: VariationPath, move_index: int) -> MoveAnnotationTarget:
    digest = _validated_digest(game)
    try:
        _validate_path(line_path)
    except (TypeError, ValueError) as exc:
        raise AnnotationEditError(str(exc), code=AnnotationEditCode.INVALID_TARGET) from exc
    if type(move_index) is not int or move_index < 0:
        raise AnnotationEditError("move_index must be a non-negative exact integer", code=AnnotationEditCode.INVALID_TARGET)
    try:
        line = resolve_line(game, line_path)
    except GameTreePathError as exc:
        raise AnnotationEditError(str(exc), code=AnnotationEditCode.INVALID_TARGET) from exc
    if move_index >= len(line.moves):
        raise AnnotationEditError("move index is out of range", code=AnnotationEditCode.INVALID_TARGET)
    return MoveAnnotationTarget(line_path, move_index, digest)


def line_annotation_target(game: PgnGame, line_path: VariationPath) -> LineAnnotationTarget:
    digest = _validated_digest(game)
    try:
        _validate_path(line_path)
        resolve_line(game, line_path)
    except (TypeError, ValueError, GameTreePathError) as exc:
        raise AnnotationEditError(str(exc), code=AnnotationEditCode.INVALID_TARGET) from exc
    return LineAnnotationTarget(line_path, digest)


def _assert_fresh(game: PgnGame, expected: str) -> str:
    digest = _validated_digest(game)
    if digest != expected:
        raise AnnotationEditError(
            "GameTree changed after the annotation target was created",
            code=AnnotationEditCode.STALE_REVISION,
        )
    return digest


def _finish(edited: PgnGame, before_digest: str) -> AnnotationEditResult:
    after_digest = _validated_digest(edited)
    return AnnotationEditResult(edited, before_digest, after_digest)


def edit_move_annotations(
    game: PgnGame,
    target: MoveAnnotationTarget,
    patch: MoveAnnotationPatch,
) -> AnnotationEditResult:
    """Replace selected MoveNode annotation fields atomically and copy-on-write."""

    if not isinstance(target, MoveAnnotationTarget):
        raise TypeError("target must be a MoveAnnotationTarget")
    if not isinstance(patch, MoveAnnotationPatch):
        raise TypeError("patch must be a MoveAnnotationPatch")
    before_digest = _assert_fresh(game, target.expected_record_digest)
    try:
        source_line = resolve_line(game, target.line_path)
    except GameTreePathError as exc:
        raise AnnotationEditError(str(exc), code=AnnotationEditCode.INVALID_TARGET) from exc
    if target.move_index >= len(source_line.moves):
        raise AnnotationEditError("move index is out of range", code=AnnotationEditCode.INVALID_TARGET)

    edited = deepcopy(game)
    move = resolve_line(edited, target.line_path).moves[target.move_index]
    if patch.comments_before is not None:
        move.comments_before = deepcopy(list(patch.comments_before))
    if patch.comments_after is not None:
        move.comments_after = deepcopy(list(patch.comments_after))
    if patch.nags is not None:
        move.nags = list(patch.nags)
    return _finish(edited, before_digest)


def edit_line_annotations(
    game: PgnGame,
    target: LineAnnotationTarget,
    patch: LineAnnotationPatch,
) -> AnnotationEditResult:
    """Replace selected VariationLine leading/trailing comments atomically."""

    if not isinstance(target, LineAnnotationTarget):
        raise TypeError("target must be a LineAnnotationTarget")
    if not isinstance(patch, LineAnnotationPatch):
        raise TypeError("patch must be a LineAnnotationPatch")
    before_digest = _assert_fresh(game, target.expected_record_digest)
    edited = deepcopy(game)
    try:
        line = resolve_line(edited, target.line_path)
    except GameTreePathError as exc:
        raise AnnotationEditError(str(exc), code=AnnotationEditCode.INVALID_TARGET) from exc
    if patch.leading_comments is not None:
        line.leading_comments = deepcopy(list(patch.leading_comments))
    if patch.trailing_comments is not None:
        line.trailing_comments = deepcopy(list(patch.trailing_comments))
    return _finish(edited, before_digest)
