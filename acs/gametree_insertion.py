from __future__ import annotations

"""Atomic copy-on-write insertion for the canonical structural GameTree.

Insertion is deliberately separate from UI/database concerns. A target is bound to
an exact semantic record digest, so an address prepared against stale state cannot
silently attach a new branch to a different move. The caller's source game and
proposed variation are never mutated.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .game_identity import GameIdentityContractError, identity_for_game
from .gametree import MAX_TREE_NODES, MoveNode, PgnGame, VariationLine
from .gametree_navigation import (
    GameTreeCursor,
    GameTreeNavigationCode,
    GameTreePathError,
    VariationPath,
    VariationStep,
    iter_move_addresses,
    resolve_line,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class VariationInsertCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    INVALID_TARGET = "invalid_target"
    INVALID_ORDER = "invalid_order"
    STALE_REVISION = "stale_revision"
    EMPTY_VARIATION = "empty_variation"
    GRAPH_CYCLE = "graph_cycle"
    GRAPH_REUSE = "graph_reuse"
    GRAPH_DEPTH_LIMIT = "graph_depth_limit"
    GRAPH_NODE_LIMIT = "graph_node_limit"


class VariationInsertError(ValueError):
    def __init__(self, message: str, *, code: VariationInsertCode) -> None:
        super().__init__(message)
        self.code = VariationInsertCode(code)


@dataclass(frozen=True, slots=True)
class VariationInsertTarget:
    parent_path: VariationPath
    parent_move_index: int
    insert_index: int
    expected_record_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.parent_path, tuple) or any(
            not isinstance(step, VariationStep) for step in self.parent_path
        ):
            raise TypeError("parent_path must be a tuple of VariationStep values")
        if type(self.parent_move_index) is not int or self.parent_move_index < 0:
            raise TypeError("parent_move_index must be a non-negative exact integer")
        if type(self.insert_index) is not int or self.insert_index < 0:
            raise TypeError("insert_index must be a non-negative exact integer")
        if (
            not isinstance(self.expected_record_digest, str)
            or _DIGEST_RE.fullmatch(self.expected_record_digest) is None
        ):
            raise ValueError("expected_record_digest must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class VariationInsertCursorRemap:
    before: GameTreeCursor
    after: GameTreeCursor


@dataclass(frozen=True, slots=True)
class VariationInsertResult:
    game: PgnGame
    target: VariationInsertTarget
    inserted_path: VariationPath
    cursor_remap: tuple[VariationInsertCursorRemap, ...]

    def remap_cursor(self, cursor: GameTreeCursor) -> GameTreeCursor:
        if not isinstance(cursor, GameTreeCursor):
            raise TypeError("cursor must be a GameTreeCursor")
        for entry in self.cursor_remap:
            if entry.before == cursor:
                return entry.after
        raise VariationInsertError(
            "cursor was not valid in the source GameTree",
            code=VariationInsertCode.INVALID_TARGET,
        )


def _map_navigation_code(code: GameTreeNavigationCode) -> VariationInsertCode:
    return {
        GameTreeNavigationCode.GRAPH_CYCLE: VariationInsertCode.GRAPH_CYCLE,
        GameTreeNavigationCode.GRAPH_REUSE: VariationInsertCode.GRAPH_REUSE,
        GameTreeNavigationCode.GRAPH_DEPTH_LIMIT: VariationInsertCode.GRAPH_DEPTH_LIMIT,
        GameTreeNavigationCode.GRAPH_NODE_LIMIT: VariationInsertCode.GRAPH_NODE_LIMIT,
    }.get(code, VariationInsertCode.INVALID_INPUT)


def _validated_digest(game: object) -> str:
    if not isinstance(game, PgnGame):
        raise VariationInsertError(
            "variation insertion requires a PgnGame",
            code=VariationInsertCode.INVALID_INPUT,
        )
    try:
        for _ in iter_move_addresses(game):
            pass
        return identity_for_game(game).record_digest
    except GameTreePathError as exc:
        raise VariationInsertError(str(exc), code=_map_navigation_code(exc.code)) from exc
    except GameIdentityContractError as exc:
        code = (
            VariationInsertCode.GRAPH_CYCLE
            if exc.code.value == "cyclic_tree"
            else VariationInsertCode.GRAPH_DEPTH_LIMIT
            if exc.code.value == "tree_limit_exceeded"
            else VariationInsertCode.INVALID_INPUT
        )
        raise VariationInsertError(str(exc), code=code) from exc


def _iter_graph_objects(line: VariationLine) -> Iterable[object]:
    stack: list[VariationLine] = [line]
    seen_lines: set[int] = set()
    seen_moves: set[int] = set()
    count = 0
    while stack:
        current = stack.pop()
        line_id = id(current)
        if line_id in seen_lines:
            raise VariationInsertError(
                "variation graph reuses or cycles a VariationLine",
                code=VariationInsertCode.GRAPH_REUSE,
            )
        seen_lines.add(line_id)
        yield current
        count += 1
        if count > MAX_TREE_NODES:
            raise VariationInsertError(
                "variation graph exceeds the node safety limit",
                code=VariationInsertCode.GRAPH_NODE_LIMIT,
            )
        if type(current.moves) is not list:
            raise VariationInsertError(
                "variation moves must be a list",
                code=VariationInsertCode.INVALID_INPUT,
            )
        for move in current.moves:
            if not isinstance(move, MoveNode):
                raise VariationInsertError(
                    "variation moves must contain MoveNode values",
                    code=VariationInsertCode.INVALID_INPUT,
                )
            move_id = id(move)
            if move_id in seen_moves:
                raise VariationInsertError(
                    "variation graph reuses a MoveNode",
                    code=VariationInsertCode.GRAPH_REUSE,
                )
            seen_moves.add(move_id)
            yield move
            count += 1
            if count > MAX_TREE_NODES:
                raise VariationInsertError(
                    "variation graph exceeds the node safety limit",
                    code=VariationInsertCode.GRAPH_NODE_LIMIT,
                )
            if type(move.variations) is not list:
                raise VariationInsertError(
                    "move variations must be a list",
                    code=VariationInsertCode.INVALID_INPUT,
                )
            stack.extend(reversed(move.variations))


def _line_paths(root: VariationLine) -> list[tuple[VariationPath, VariationLine]]:
    out: list[tuple[VariationPath, VariationLine]] = []
    stack: list[tuple[VariationPath, VariationLine]] = [((), root)]
    while stack:
        path, line = stack.pop()
        out.append((path, line))
        for move_index in range(len(line.moves) - 1, -1, -1):
            move = line.moves[move_index]
            for variation_index in range(len(move.variations) - 1, -1, -1):
                stack.append(
                    (
                        path + (VariationStep(move_index, variation_index),),
                        move.variations[variation_index],
                    )
                )
    return out


def _shift_path(path: VariationPath, target: VariationInsertTarget) -> VariationPath:
    prefix_len = len(target.parent_path)
    if len(path) <= prefix_len or path[:prefix_len] != target.parent_path:
        return path
    step = path[prefix_len]
    if (
        step.parent_move_index != target.parent_move_index
        or step.variation_index < target.insert_index
    ):
        return path
    shifted = VariationStep(step.parent_move_index, step.variation_index + 1)
    return path[:prefix_len] + (shifted,) + path[prefix_len + 1 :]


def variation_insert_target(
    game: PgnGame,
    parent_path: VariationPath,
    parent_move_index: int,
    insert_index: int | None = None,
) -> VariationInsertTarget:
    """Bind an insertion point to the exact current semantic revision."""

    digest = _validated_digest(game)
    if not isinstance(parent_path, tuple) or any(
        not isinstance(step, VariationStep) for step in parent_path
    ):
        raise VariationInsertError(
            "parent_path must be a tuple of VariationStep values",
            code=VariationInsertCode.INVALID_TARGET,
        )
    if type(parent_move_index) is not int or parent_move_index < 0:
        raise VariationInsertError(
            "parent_move_index must be a non-negative exact integer",
            code=VariationInsertCode.INVALID_TARGET,
        )
    try:
        parent = resolve_line(game, parent_path)
    except GameTreePathError as exc:
        raise VariationInsertError(
            str(exc), code=VariationInsertCode.INVALID_TARGET
        ) from exc
    if parent_move_index >= len(parent.moves):
        raise VariationInsertError(
            "parent move index is out of range",
            code=VariationInsertCode.INVALID_TARGET,
        )
    sibling_count = len(parent.moves[parent_move_index].variations)
    if insert_index is None:
        insert_index = sibling_count
    if type(insert_index) is not int or insert_index < 0 or insert_index > sibling_count:
        raise VariationInsertError(
            "variation insertion index is out of range",
            code=VariationInsertCode.INVALID_ORDER,
        )
    return VariationInsertTarget(
        parent_path,
        parent_move_index,
        insert_index,
        digest,
    )


def add_variation(
    game: PgnGame,
    target: VariationInsertTarget,
    variation: VariationLine,
) -> VariationInsertResult:
    """Insert a detached variation atomically without mutating either input."""

    if not isinstance(target, VariationInsertTarget):
        raise TypeError("target must be a VariationInsertTarget")
    if not isinstance(variation, VariationLine):
        raise VariationInsertError(
            "variation must be a VariationLine",
            code=VariationInsertCode.INVALID_INPUT,
        )
    if not variation.moves:
        raise VariationInsertError(
            "an inserted variation must contain at least one move",
            code=VariationInsertCode.EMPTY_VARIATION,
        )

    current_digest = _validated_digest(game)
    if current_digest != target.expected_record_digest:
        raise VariationInsertError(
            "GameTree changed after the insertion target was created",
            code=VariationInsertCode.STALE_REVISION,
        )

    try:
        parent = resolve_line(game, target.parent_path)
    except GameTreePathError as exc:
        raise VariationInsertError(
            str(exc), code=VariationInsertCode.INVALID_TARGET
        ) from exc
    if target.parent_move_index >= len(parent.moves):
        raise VariationInsertError(
            "parent move index is out of range",
            code=VariationInsertCode.INVALID_TARGET,
        )
    siblings = parent.moves[target.parent_move_index].variations
    if target.insert_index > len(siblings):
        raise VariationInsertError(
            "variation insertion index is out of range",
            code=VariationInsertCode.INVALID_ORDER,
        )

    source_ids = {id(obj) for obj in _iter_graph_objects(game.line)}
    proposed_objects = list(_iter_graph_objects(variation))
    if any(id(obj) in source_ids for obj in proposed_objects):
        raise VariationInsertError(
            "inserted variation must be detached from the source GameTree",
            code=VariationInsertCode.GRAPH_REUSE,
        )

    # Validate the proposed subtree independently before cloning the source.
    _validated_digest(PgnGame(line=variation))

    source_paths = _line_paths(game.line)
    edited = deepcopy(game)
    inserted = deepcopy(variation)
    edited_parent = resolve_line(edited, target.parent_path)
    edited_parent.moves[target.parent_move_index].variations.insert(
        target.insert_index,
        inserted,
    )
    _validated_digest(edited)

    remap: list[VariationInsertCursorRemap] = []
    for path, line in source_paths:
        after_path = _shift_path(path, target)
        for next_index in range(len(line.moves) + 1):
            remap.append(
                VariationInsertCursorRemap(
                    GameTreeCursor(path, next_index),
                    GameTreeCursor(after_path, next_index),
                )
            )
            if len(remap) > MAX_TREE_NODES:
                raise VariationInsertError(
                    "cursor remap exceeds the node safety limit",
                    code=VariationInsertCode.GRAPH_NODE_LIMIT,
                )

    inserted_path = target.parent_path + (
        VariationStep(target.parent_move_index, target.insert_index),
    )
    return VariationInsertResult(edited, target, inserted_path, tuple(remap))
