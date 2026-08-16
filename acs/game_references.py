from __future__ import annotations

"""Stable presentation-neutral references into the canonical PGN GameTree.

The references in this module are selectors only. They do not copy or own game
state, do not validate chess legality, and do not persist proprietary database
addresses.  Adapters can store or exchange them to return to an exact game,
variation, move, or logical position without inventing a second tree model.
"""

from dataclasses import dataclass

from .gametree import MoveNode, PgnGame, VariationLine


class GameReferenceError(ValueError):
    """Raised when a neutral reference cannot be resolved in the supplied game."""


@dataclass(frozen=True, slots=True, order=True)
class VariationStep:
    """One descent from a variation to a child RAV attached to a move."""

    move_index: int
    variation_index: int

    def __post_init__(self) -> None:
        if self.move_index < 0:
            raise ValueError("move_index must be non-negative")
        if self.variation_index < 0:
            raise ValueError("variation_index must be non-negative")


@dataclass(frozen=True, slots=True, order=True)
class VariationRef:
    source_index: int
    path: tuple[VariationStep, ...] = ()

    def __post_init__(self) -> None:
        if self.source_index < 0:
            raise ValueError("source_index must be non-negative")


@dataclass(frozen=True, slots=True, order=True)
class MoveRef:
    variation: VariationRef
    move_index: int

    def __post_init__(self) -> None:
        if self.move_index < 0:
            raise ValueError("move_index must be non-negative")


@dataclass(frozen=True, slots=True, order=True)
class PositionRef:
    """Logical position inside a variation after ``ply_index`` local moves.

    ``ply_index=0`` means the position from which the variation starts.  For a
    child RAV this is the position before its attachment move on the parent
    line.  This is a structural reference only; the actual board/FEN remains
    owned by chess Core.
    """

    variation: VariationRef
    ply_index: int

    def __post_init__(self) -> None:
        if self.ply_index < 0:
            raise ValueError("ply_index must be non-negative")


@dataclass(frozen=True, slots=True)
class BranchContext:
    """Exact structural branch/return semantics for a child variation."""

    variation: VariationRef
    attached_to: MoveRef
    branch_base: PositionRef
    return_position: PositionRef
    resume_move: MoveRef | None


def _check_game(ref: VariationRef, game: PgnGame) -> None:
    if ref.source_index != game.source_index:
        raise GameReferenceError(
            f"reference source_index {ref.source_index} does not match game {game.source_index}"
        )


def resolve_variation(game: PgnGame, ref: VariationRef) -> VariationLine:
    _check_game(ref, game)
    line = game.line
    for depth, step in enumerate(ref.path):
        if step.move_index >= len(line.moves):
            raise GameReferenceError(
                f"path step {depth} move_index {step.move_index} out of range"
            )
        move = line.moves[step.move_index]
        if step.variation_index >= len(move.variations):
            raise GameReferenceError(
                f"path step {depth} variation_index {step.variation_index} out of range"
            )
        line = move.variations[step.variation_index]
    return line


def resolve_move(game: PgnGame, ref: MoveRef) -> MoveNode:
    line = resolve_variation(game, ref.variation)
    if ref.move_index >= len(line.moves):
        raise GameReferenceError(f"move_index {ref.move_index} out of range")
    return line.moves[ref.move_index]


def resolve_position(game: PgnGame, ref: PositionRef) -> PositionRef:
    line = resolve_variation(game, ref.variation)
    if ref.ply_index > len(line.moves):
        raise GameReferenceError(f"ply_index {ref.ply_index} out of range")
    return ref


def child_variation(parent: VariationRef, move_index: int, variation_index: int) -> VariationRef:
    return VariationRef(
        source_index=parent.source_index,
        path=parent.path + (VariationStep(move_index, variation_index),),
    )


def branch_context(game: PgnGame, ref: VariationRef) -> BranchContext:
    """Describe where a nested RAV branches and where reading returns.

    PGN RAV semantics branch from the position *before* the move to which the
    variation is attached.  After finishing the RAV, navigation returns to the
    parent line immediately *after* that attachment move and resumes at the
    next parent move when one exists.
    """

    resolve_variation(game, ref)
    if not ref.path:
        raise GameReferenceError("main line has no parent branch context")

    last = ref.path[-1]
    parent = VariationRef(ref.source_index, ref.path[:-1])
    parent_line = resolve_variation(game, parent)
    if last.move_index >= len(parent_line.moves):
        raise GameReferenceError(f"attachment move_index {last.move_index} out of range")
    parent_move = parent_line.moves[last.move_index]
    if last.variation_index >= len(parent_move.variations):
        raise GameReferenceError(
            f"attachment variation_index {last.variation_index} out of range"
        )

    attached_to = MoveRef(parent, last.move_index)
    branch_base = PositionRef(parent, last.move_index)
    return_position = PositionRef(parent, last.move_index + 1)
    resume_index = last.move_index + 1
    resume_move = (
        MoveRef(parent, resume_index) if resume_index < len(parent_line.moves) else None
    )
    return BranchContext(
        variation=ref,
        attached_to=attached_to,
        branch_base=branch_base,
        return_position=return_position,
        resume_move=resume_move,
    )
