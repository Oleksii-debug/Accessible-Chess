from __future__ import annotations

"""Deterministic, presentation-neutral navigation for structural PGN GameTrees.

The PGN parser preserves recursive RAV lines but deliberately does not own a
UI cursor.  This module provides stable addresses and exact branch/return
semantics so book readers, database viewers and later accessible presentation
layers can all navigate the same tree without inventing their own rules.

No chess legality or proprietary-format semantics are inferred here.  A
variation is addressed exactly where the structural parser attached it: to the
preceding move node.  Leaving that variation resumes at the move immediately
after that parent move in the parent line.
"""

from dataclasses import dataclass
from typing import Iterator

from .gametree import MoveNode, PgnGame, VariationLine


class GameTreeNavigationError(ValueError):
    """Base error for invalid structural GameTree navigation."""


class GameTreePathError(GameTreeNavigationError):
    """Raised when a variation path cannot be resolved exactly."""


class GameTreeCursorError(GameTreeNavigationError):
    """Raised when a requested cursor transition is not valid."""


@dataclass(frozen=True, slots=True)
class VariationStep:
    """One descent from a parent line into one variation of one parent move."""

    parent_move_index: int
    variation_index: int

    def __post_init__(self) -> None:
        if self.parent_move_index < 0:
            raise ValueError("parent_move_index must be >= 0")
        if self.variation_index < 0:
            raise ValueError("variation_index must be >= 0")


VariationPath = tuple[VariationStep, ...]
ROOT_PATH: VariationPath = ()


@dataclass(frozen=True, slots=True)
class MoveAddress:
    """Stable structural address of a move inside one parsed game."""

    line_path: VariationPath
    move_index: int

    def __post_init__(self) -> None:
        if self.move_index < 0:
            raise ValueError("move_index must be >= 0")


@dataclass(frozen=True, slots=True)
class BranchReturnContext:
    """Exact structural context for entering and leaving one RAV branch.

    ``branch_from_move_index`` is the move node that owns the RAV in the
    structural model.  ``resume_parent_move_index`` is therefore the next move
    to read in the parent line after finishing the branch.  It may equal the
    parent line length, which means "return to end of line".
    """

    parent_path: VariationPath
    child_path: VariationPath
    branch_from_move_index: int
    variation_index: int
    resume_parent_move_index: int


@dataclass(frozen=True, slots=True)
class GameTreeCursor:
    """Immutable reading cursor expressed as the next move to consume.

    ``next_move_index == len(line.moves)`` is a valid end-of-line cursor.  This
    makes branch return deterministic even when the variation is attached to
    the final move of its parent line.
    """

    line_path: VariationPath = ROOT_PATH
    next_move_index: int = 0

    def __post_init__(self) -> None:
        if self.next_move_index < 0:
            raise ValueError("next_move_index must be >= 0")


def resolve_line(game: PgnGame, path: VariationPath = ROOT_PATH) -> VariationLine:
    """Resolve ``path`` from the game root or fail without fallback."""

    line = game.line
    traversed: list[VariationStep] = []
    for step in path:
        if step.parent_move_index >= len(line.moves):
            raise GameTreePathError(
                "variation path references parent move "
                f"{step.parent_move_index} outside line length {len(line.moves)} "
                f"after path {tuple(traversed)!r}"
            )
        parent_move = line.moves[step.parent_move_index]
        if step.variation_index >= len(parent_move.variations):
            raise GameTreePathError(
                "variation path references variation "
                f"{step.variation_index} outside count {len(parent_move.variations)} "
                f"at parent move {step.parent_move_index} after path {tuple(traversed)!r}"
            )
        line = parent_move.variations[step.variation_index]
        traversed.append(step)
    return line


def resolve_move(game: PgnGame, address: MoveAddress) -> MoveNode:
    """Resolve an exact move address or fail explicitly."""

    line = resolve_line(game, address.line_path)
    if address.move_index >= len(line.moves):
        raise GameTreePathError(
            f"move index {address.move_index} outside line length {len(line.moves)}"
        )
    return line.moves[address.move_index]


def branch_context(
    game: PgnGame,
    parent_path: VariationPath,
    parent_move_index: int,
    variation_index: int,
) -> BranchReturnContext:
    """Return the exact enter/return context for one existing variation."""

    if parent_move_index < 0 or variation_index < 0:
        raise GameTreePathError("branch indices must be >= 0")
    parent_line = resolve_line(game, parent_path)
    if parent_move_index >= len(parent_line.moves):
        raise GameTreePathError(
            f"parent move index {parent_move_index} outside line length {len(parent_line.moves)}"
        )
    parent_move = parent_line.moves[parent_move_index]
    if variation_index >= len(parent_move.variations):
        raise GameTreePathError(
            f"variation index {variation_index} outside count {len(parent_move.variations)}"
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

    line = resolve_line(game, cursor.line_path)
    if cursor.next_move_index > len(line.moves):
        raise GameTreeCursorError(
            f"cursor index {cursor.next_move_index} outside line length {len(line.moves)}"
        )
    return cursor


def current_move(game: PgnGame, cursor: GameTreeCursor) -> MoveNode | None:
    """Return the next move or ``None`` when the cursor is at line end."""

    validate_cursor(game, cursor)
    line = resolve_line(game, cursor.line_path)
    if cursor.next_move_index == len(line.moves):
        return None
    return line.moves[cursor.next_move_index]


def advance(game: PgnGame, cursor: GameTreeCursor) -> GameTreeCursor:
    """Advance by one move without silently crossing a variation boundary."""

    validate_cursor(game, cursor)
    line = resolve_line(game, cursor.line_path)
    if cursor.next_move_index >= len(line.moves):
        raise GameTreeCursorError("cannot advance past end of line")
    return GameTreeCursor(cursor.line_path, cursor.next_move_index + 1)


def enter_variation(
    game: PgnGame,
    cursor: GameTreeCursor,
    variation_index: int = 0,
) -> GameTreeCursor:
    """Enter a variation attached to the move immediately before the cursor.

    A caller normally consumes a parent move with :func:`advance` and then
    chooses one of that move's RAV branches.  Requiring the parent move to be
    immediately before the cursor prevents ambiguous branch ownership.
    """

    validate_cursor(game, cursor)
    if cursor.next_move_index == 0:
        raise GameTreeCursorError("no preceding parent move owns a variation")
    context = branch_context(
        game,
        cursor.line_path,
        cursor.next_move_index - 1,
        variation_index,
    )
    return GameTreeCursor(context.child_path, 0)


def leave_variation(game: PgnGame, cursor: GameTreeCursor) -> GameTreeCursor:
    """Leave the current variation and resume exactly after its parent move."""

    validate_cursor(game, cursor)
    if not cursor.line_path:
        raise GameTreeCursorError("root line has no parent variation")
    step = cursor.line_path[-1]
    parent_path = cursor.line_path[:-1]
    context = branch_context(
        game,
        parent_path,
        step.parent_move_index,
        step.variation_index,
    )
    return GameTreeCursor(parent_path, context.resume_parent_move_index)


def iter_move_addresses(game: PgnGame) -> Iterator[MoveAddress]:
    """Yield every move once in deterministic pre-order structural order."""

    def walk(line: VariationLine, path: VariationPath) -> Iterator[MoveAddress]:
        for move_index, node in enumerate(line.moves):
            yield MoveAddress(path, move_index)
            for variation_index, variation in enumerate(node.variations):
                child_path = path + (VariationStep(move_index, variation_index),)
                yield from walk(variation, child_path)

    yield from walk(game.line, ROOT_PATH)
