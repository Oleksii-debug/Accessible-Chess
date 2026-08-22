from __future__ import annotations

"""Bounded, presentation-neutral navigation over the canonical PGN GameTree.

The structural parser owns the only GameTree.  This module adds immutable
addresses and cursors over that same tree; it never flattens, copies, or
normalizes the source.  A RAV is addressed exactly where the parser attached
it: to one move in its parent line.  Leaving a RAV resumes immediately after
that owning move, including when the result is the parent line's end cursor.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from .gametree import (
    MAX_TREE_NODES,
    MAX_VARIATION_DEPTH,
    MoveNode,
    PgnGame,
    VariationLine,
)


class GameTreeNavigationCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    INVALID_PATH = "invalid_path"
    INVALID_CURSOR = "invalid_cursor"
    GRAPH_CYCLE = "graph_cycle"
    GRAPH_REUSE = "graph_reuse"
    GRAPH_DEPTH_LIMIT = "graph_depth_limit"
    GRAPH_NODE_LIMIT = "graph_node_limit"


class GameTreeNavigationError(ValueError):
    """Stable base error for invalid or unsafe structural navigation."""

    def __init__(self, message: str, *, code: GameTreeNavigationCode) -> None:
        super().__init__(message)
        self.code = GameTreeNavigationCode(code)


class GameTreePathError(GameTreeNavigationError):
    """Raised when an exact variation or move path cannot be resolved."""


class GameTreeCursorError(GameTreeNavigationError):
    """Raised when an immutable cursor transition is invalid."""


def _exact_nonnegative(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class VariationStep:
    """One descent into a variation attached to one parent move."""

    parent_move_index: int
    variation_index: int

    def __post_init__(self) -> None:
        _exact_nonnegative(self.parent_move_index, "parent_move_index")
        _exact_nonnegative(self.variation_index, "variation_index")


VariationPath = tuple[VariationStep, ...]
ROOT_PATH: VariationPath = ()


def _validate_path(path: object) -> VariationPath:
    if not isinstance(path, tuple) or any(
        not isinstance(step, VariationStep) for step in path
    ):
        raise TypeError("variation path must be a tuple of VariationStep values")
    if len(path) > MAX_VARIATION_DEPTH:
        raise GameTreePathError(
            "variation path exceeds the supported depth",
            code=GameTreeNavigationCode.GRAPH_DEPTH_LIMIT,
        )
    return path


@dataclass(frozen=True, slots=True)
class MoveAddress:
    """Stable structural address of one move inside one parsed game."""

    line_path: VariationPath
    move_index: int

    def __post_init__(self) -> None:
        _validate_path(self.line_path)
        _exact_nonnegative(self.move_index, "move_index")


@dataclass(frozen=True, slots=True)
class BranchReturnContext:
    """Exact parent, child, and resume location for one existing RAV."""

    parent_path: VariationPath
    child_path: VariationPath
    branch_from_move_index: int
    variation_index: int
    resume_parent_move_index: int

    def __post_init__(self) -> None:
        parent = _validate_path(self.parent_path)
        child = _validate_path(self.child_path)
        owner = _exact_nonnegative(
            self.branch_from_move_index, "branch_from_move_index"
        )
        variation = _exact_nonnegative(self.variation_index, "variation_index")
        resume = _exact_nonnegative(
            self.resume_parent_move_index, "resume_parent_move_index"
        )
        expected = parent + (VariationStep(owner, variation),)
        if child != expected or resume != owner + 1:
            raise ValueError("branch return context is internally inconsistent")


@dataclass(frozen=True, slots=True)
class GameTreeCursor:
    """Immutable next-move cursor; line length is a valid end position."""

    line_path: VariationPath = ROOT_PATH
    next_move_index: int = 0

    def __post_init__(self) -> None:
        _validate_path(self.line_path)
        _exact_nonnegative(self.next_move_index, "next_move_index")


def _root_line(game: object) -> VariationLine:
    if not isinstance(game, PgnGame):
        raise GameTreePathError(
            "navigation requires a PgnGame",
            code=GameTreeNavigationCode.INVALID_INPUT,
        )
    if not isinstance(game.line, VariationLine):
        raise GameTreePathError(
            "game root must be a VariationLine",
            code=GameTreeNavigationCode.INVALID_INPUT,
        )
    return game.line


def _line_moves(line: VariationLine) -> list[MoveNode]:
    if not isinstance(line.moves, list):
        raise GameTreePathError(
            "variation moves must be a list of MoveNode values",
            code=GameTreeNavigationCode.INVALID_INPUT,
        )
    if len(line.moves) > MAX_TREE_NODES:
        raise GameTreePathError(
            "variation move count exceeds the node safety limit",
            code=GameTreeNavigationCode.GRAPH_NODE_LIMIT,
        )
    if any(
        not isinstance(move, MoveNode) for move in line.moves
    ):
        raise GameTreePathError(
            "variation moves must be a list of MoveNode values",
            code=GameTreeNavigationCode.INVALID_INPUT,
        )
    return line.moves


def _move_variations(move: MoveNode) -> list[VariationLine]:
    if not isinstance(move.variations, list):
        raise GameTreePathError(
            "move variations must be a list of VariationLine values",
            code=GameTreeNavigationCode.INVALID_INPUT,
        )
    if len(move.variations) > MAX_TREE_NODES:
        raise GameTreePathError(
            "move variation count exceeds the node safety limit",
            code=GameTreeNavigationCode.GRAPH_NODE_LIMIT,
        )
    if any(
        not isinstance(line, VariationLine) for line in move.variations
    ):
        raise GameTreePathError(
            "move variations must be a list of VariationLine values",
            code=GameTreeNavigationCode.INVALID_INPUT,
        )
    return move.variations


def resolve_line(game: PgnGame, path: VariationPath = ROOT_PATH) -> VariationLine:
    """Resolve an exact path without fallback, coercion, or mutation."""

    path = _validate_path(path)
    line = _root_line(game)
    seen = {id(line)}
    seen_moves: set[int] = set()
    traversed: list[VariationStep] = []
    for step in path:
        moves = _line_moves(line)
        if step.parent_move_index >= len(moves):
            raise GameTreePathError(
                "variation path references parent move "
                f"{step.parent_move_index} outside line length {len(moves)} "
                f"after path {tuple(traversed)!r}",
                code=GameTreeNavigationCode.INVALID_PATH,
            )
        parent_move = moves[step.parent_move_index]
        move_identity = id(parent_move)
        if move_identity in seen_moves:
            raise GameTreePathError(
                "variation path revisits a move object",
                code=GameTreeNavigationCode.GRAPH_REUSE,
            )
        seen_moves.add(move_identity)
        variations = _move_variations(parent_move)
        if step.variation_index >= len(variations):
            raise GameTreePathError(
                "variation path references variation "
                f"{step.variation_index} outside count {len(variations)} "
                f"at parent move {step.parent_move_index} after path "
                f"{tuple(traversed)!r}",
                code=GameTreeNavigationCode.INVALID_PATH,
            )
        line = variations[step.variation_index]
        identity = id(line)
        if identity in seen:
            raise GameTreePathError(
                "variation path revisits a line object",
                code=GameTreeNavigationCode.GRAPH_CYCLE,
            )
        seen.add(identity)
        traversed.append(step)
    return line


def resolve_move(game: PgnGame, address: MoveAddress) -> MoveNode:
    """Resolve one exact move address or fail explicitly."""

    if not isinstance(address, MoveAddress):
        raise TypeError("address must be a MoveAddress")
    moves = _line_moves(resolve_line(game, address.line_path))
    if address.move_index >= len(moves):
        raise GameTreePathError(
            f"move index {address.move_index} outside line length {len(moves)}",
            code=GameTreeNavigationCode.INVALID_PATH,
        )
    return moves[address.move_index]


def branch_context(
    game: PgnGame,
    parent_path: VariationPath,
    parent_move_index: int,
    variation_index: int,
) -> BranchReturnContext:
    """Return exact enter/return coordinates for one existing branch."""

    parent_path = _validate_path(parent_path)
    try:
        parent_move_index = _exact_nonnegative(
            parent_move_index, "parent_move_index"
        )
        variation_index = _exact_nonnegative(variation_index, "variation_index")
    except (TypeError, ValueError) as exc:
        raise GameTreePathError(
            str(exc), code=GameTreeNavigationCode.INVALID_PATH
        ) from exc
    moves = _line_moves(resolve_line(game, parent_path))
    if parent_move_index >= len(moves):
        raise GameTreePathError(
            f"parent move index {parent_move_index} outside line length {len(moves)}",
            code=GameTreeNavigationCode.INVALID_PATH,
        )
    variations = _move_variations(moves[parent_move_index])
    if variation_index >= len(variations):
        raise GameTreePathError(
            f"variation index {variation_index} outside count {len(variations)}",
            code=GameTreeNavigationCode.INVALID_PATH,
        )
    child_path = parent_path + (VariationStep(parent_move_index, variation_index),)
    return BranchReturnContext(
        parent_path=parent_path,
        child_path=child_path,
        branch_from_move_index=parent_move_index,
        variation_index=variation_index,
        resume_parent_move_index=parent_move_index + 1,
    )


def validate_cursor(game: PgnGame, cursor: GameTreeCursor) -> GameTreeCursor:
    """Validate a cursor while preserving end-of-line as a legal state."""

    if not isinstance(cursor, GameTreeCursor):
        raise TypeError("cursor must be a GameTreeCursor")
    moves = _line_moves(resolve_line(game, cursor.line_path))
    if cursor.next_move_index > len(moves):
        raise GameTreeCursorError(
            f"cursor index {cursor.next_move_index} outside line length {len(moves)}",
            code=GameTreeNavigationCode.INVALID_CURSOR,
        )
    return cursor


def current_move(game: PgnGame, cursor: GameTreeCursor) -> MoveNode | None:
    """Return the next move or ``None`` at line end."""

    validate_cursor(game, cursor)
    moves = _line_moves(resolve_line(game, cursor.line_path))
    if cursor.next_move_index == len(moves):
        return None
    return moves[cursor.next_move_index]


def advance(game: PgnGame, cursor: GameTreeCursor) -> GameTreeCursor:
    """Advance once without silently crossing a branch boundary."""

    validate_cursor(game, cursor)
    moves = _line_moves(resolve_line(game, cursor.line_path))
    if cursor.next_move_index >= len(moves):
        raise GameTreeCursorError(
            "cannot advance past end of line",
            code=GameTreeNavigationCode.INVALID_CURSOR,
        )
    return GameTreeCursor(cursor.line_path, cursor.next_move_index + 1)


def enter_variation(
    game: PgnGame,
    cursor: GameTreeCursor,
    variation_index: int = 0,
) -> GameTreeCursor:
    """Enter a branch owned by the move immediately before ``cursor``."""

    validate_cursor(game, cursor)
    if cursor.next_move_index == 0:
        raise GameTreeCursorError(
            "no preceding parent move owns a variation",
            code=GameTreeNavigationCode.INVALID_CURSOR,
        )
    try:
        context = branch_context(
            game,
            cursor.line_path,
            cursor.next_move_index - 1,
            variation_index,
        )
    except GameTreePathError as exc:
        raise GameTreeCursorError(
            str(exc),
            code=(
                GameTreeNavigationCode.INVALID_CURSOR
                if exc.code is GameTreeNavigationCode.INVALID_PATH
                else exc.code
            ),
        ) from exc
    return GameTreeCursor(context.child_path, 0)


def leave_variation(game: PgnGame, cursor: GameTreeCursor) -> GameTreeCursor:
    """Leave the current branch and resume exactly after its owning move."""

    validate_cursor(game, cursor)
    if not cursor.line_path:
        raise GameTreeCursorError(
            "root line has no parent variation",
            code=GameTreeNavigationCode.INVALID_CURSOR,
        )
    step = cursor.line_path[-1]
    parent_path = cursor.line_path[:-1]
    try:
        context = branch_context(
            game,
            parent_path,
            step.parent_move_index,
            step.variation_index,
        )
    except GameTreePathError as exc:
        raise GameTreeCursorError(
            str(exc),
            code=(
                GameTreeNavigationCode.INVALID_CURSOR
                if exc.code is GameTreeNavigationCode.INVALID_PATH
                else exc.code
            ),
        ) from exc
    return GameTreeCursor(parent_path, context.resume_parent_move_index)


def iter_move_addresses(game: PgnGame) -> Iterator[MoveAddress]:
    """Yield every move once in deterministic bounded pre-order."""

    root = _root_line(game)
    active: set[int] = set()
    seen_lines: set[int] = set()
    seen_moves: set[int] = set()
    count = [0]

    def claim(value: object) -> None:
        count[0] += 1
        if count[0] > MAX_TREE_NODES:
            raise GameTreePathError(
                "GameTree navigation exceeds the node safety limit",
                code=GameTreeNavigationCode.GRAPH_NODE_LIMIT,
            )

    def walk(
        line: VariationLine,
        path: VariationPath,
        depth: int,
    ) -> Iterator[MoveAddress]:
        if depth > MAX_VARIATION_DEPTH:
            raise GameTreePathError(
                "GameTree navigation exceeds the depth safety limit",
                code=GameTreeNavigationCode.GRAPH_DEPTH_LIMIT,
            )
        identity = id(line)
        if identity in active:
            raise GameTreePathError(
                "GameTree navigation found a cycle",
                code=GameTreeNavigationCode.GRAPH_CYCLE,
            )
        if identity in seen_lines:
            raise GameTreePathError(
                "GameTree navigation found a reused line object",
                code=GameTreeNavigationCode.GRAPH_REUSE,
            )
        claim(line)
        active.add(identity)
        seen_lines.add(identity)
        try:
            for move_index, move in enumerate(_line_moves(line)):
                move_identity = id(move)
                if move_identity in seen_moves:
                    raise GameTreePathError(
                        "GameTree navigation found a reused move object",
                        code=GameTreeNavigationCode.GRAPH_REUSE,
                    )
                seen_moves.add(move_identity)
                claim(move)
                yield MoveAddress(path, move_index)
                for variation_index, variation in enumerate(
                    _move_variations(move)
                ):
                    child_path = path + (
                        VariationStep(move_index, variation_index),
                    )
                    yield from walk(variation, child_path, depth + 1)
        finally:
            active.remove(identity)

    yield from walk(root, ROOT_PATH, 0)
