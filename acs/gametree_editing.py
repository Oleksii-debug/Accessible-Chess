from __future__ import annotations

"""Copy-on-write structural editing for the canonical PGN GameTree.

Every request carries the expected versioned record digest, so an address made
against an older tree cannot silently edit a different sibling after concurrent
or intervening mutation.  Operations clone the complete bounded source before
changing it, preserve all untouched DTO fields, and return an immutable map for
every valid source cursor.  The caller's ``PgnGame`` is never mutated.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Callable, Mapping

from .game_identity import GameIdentityContractError, identity_for_game
from .gametree import (
    MAX_TREE_NODES,
    MoveNode,
    PgnGame,
    PgnRecoveryIssue,
    VariationLine,
)
from .gametree_navigation import (
    GameTreeCursor,
    GameTreeNavigationCode,
    GameTreePathError,
    VariationPath,
    VariationStep,
    branch_context,
    iter_move_addresses,
    resolve_line,
)


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class GameTreeEditCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    INVALID_TARGET = "invalid_target"
    STALE_REVISION = "stale_revision"
    INVALID_ORDER = "invalid_order"
    EMPTY_VARIATION = "empty_variation"
    CURSOR_NOT_IN_SOURCE = "cursor_not_in_source"
    GRAPH_CYCLE = "graph_cycle"
    GRAPH_REUSE = "graph_reuse"
    GRAPH_DEPTH_LIMIT = "graph_depth_limit"
    GRAPH_NODE_LIMIT = "graph_node_limit"


class GameTreeEditError(ValueError):
    """Stable failure for an atomic GameTree edit request."""

    def __init__(self, message: str, *, code: GameTreeEditCode) -> None:
        super().__init__(message)
        self.code = GameTreeEditCode(code)


class GameTreeEditOperation(str, Enum):
    PROMOTE_VARIATION = "promote_variation"
    REORDER_VARIATION = "reorder_variation"
    DELETE_VARIATION = "delete_variation"


def _exact_nonnegative(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class VariationEditTarget:
    """One exact branch address bound to an expected semantic revision."""

    parent_path: VariationPath
    parent_move_index: int
    variation_index: int
    expected_record_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.parent_path, tuple) or any(
            not isinstance(step, VariationStep) for step in self.parent_path
        ):
            raise TypeError("parent_path must be a tuple of VariationStep values")
        _exact_nonnegative(self.parent_move_index, "parent_move_index")
        _exact_nonnegative(self.variation_index, "variation_index")
        if (
            not isinstance(self.expected_record_digest, str)
            or _DIGEST_RE.fullmatch(self.expected_record_digest) is None
        ):
            raise ValueError("expected_record_digest must be a lowercase SHA-256 digest")

    @property
    def child_path(self) -> VariationPath:
        return self.parent_path + (
            VariationStep(self.parent_move_index, self.variation_index),
        )


@dataclass(frozen=True, slots=True)
class CursorRemapEntry:
    before: GameTreeCursor
    after: GameTreeCursor | None

    def __post_init__(self) -> None:
        if not isinstance(self.before, GameTreeCursor):
            raise TypeError("before must be a GameTreeCursor")
        if self.after is not None and not isinstance(self.after, GameTreeCursor):
            raise TypeError("after must be a GameTreeCursor or None")


@dataclass(frozen=True, slots=True)
class GameTreeEditResult:
    game: PgnGame
    operation: GameTreeEditOperation
    target: VariationEditTarget
    cursor_remap: tuple[CursorRemapEntry, ...]
    _cursor_lookup: Mapping[GameTreeCursor, GameTreeCursor | None] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.game, PgnGame):
            raise TypeError("game must be a PgnGame")
        object.__setattr__(self, "operation", GameTreeEditOperation(self.operation))
        if not isinstance(self.target, VariationEditTarget):
            raise TypeError("target must be a VariationEditTarget")
        if (
            not isinstance(self.cursor_remap, tuple)
            or any(
                not isinstance(entry, CursorRemapEntry)
                for entry in self.cursor_remap
            )
            or len(self.cursor_remap) > MAX_TREE_NODES
        ):
            raise TypeError("cursor_remap must be a bounded CursorRemapEntry tuple")
        lookup: dict[GameTreeCursor, GameTreeCursor | None] = {}
        for entry in self.cursor_remap:
            if entry.before in lookup:
                raise ValueError("cursor_remap contains a duplicate source cursor")
            lookup[entry.before] = entry.after
        object.__setattr__(self, "_cursor_lookup", MappingProxyType(lookup))

    def remap_cursor(self, cursor: GameTreeCursor) -> GameTreeCursor | None:
        """Return the exact post-edit cursor, or ``None`` for deleted context."""

        if not isinstance(cursor, GameTreeCursor):
            raise TypeError("cursor must be a GameTreeCursor")
        if cursor not in self._cursor_lookup:
            raise GameTreeEditError(
                "cursor was not valid in the source GameTree",
                code=GameTreeEditCode.CURSOR_NOT_IN_SOURCE,
            )
        return self._cursor_lookup[cursor]


@dataclass(frozen=True, slots=True)
class _LineRecord:
    path: VariationPath
    line: VariationLine


def _map_navigation_code(code: GameTreeNavigationCode) -> GameTreeEditCode:
    return {
        GameTreeNavigationCode.GRAPH_CYCLE: GameTreeEditCode.GRAPH_CYCLE,
        GameTreeNavigationCode.GRAPH_REUSE: GameTreeEditCode.GRAPH_REUSE,
        GameTreeNavigationCode.GRAPH_DEPTH_LIMIT: GameTreeEditCode.GRAPH_DEPTH_LIMIT,
        GameTreeNavigationCode.GRAPH_NODE_LIMIT: GameTreeEditCode.GRAPH_NODE_LIMIT,
    }.get(code, GameTreeEditCode.INVALID_INPUT)


def _validate_outer_game(game: object) -> PgnGame:
    if not isinstance(game, PgnGame):
        raise GameTreeEditError(
            "editing requires a PgnGame",
            code=GameTreeEditCode.INVALID_INPUT,
        )
    if type(game.source_index) is not int or game.source_index < 0:
        raise GameTreeEditError(
            "source_index must be a non-negative exact integer",
            code=GameTreeEditCode.INVALID_INPUT,
        )
    if not isinstance(game.warnings, list) or any(
        not isinstance(item, str) for item in game.warnings
    ):
        raise GameTreeEditError(
            "warnings must be a list of text values",
            code=GameTreeEditCode.INVALID_INPUT,
        )
    if not isinstance(game.recovery_issues, list) or any(
        not isinstance(item, PgnRecoveryIssue) for item in game.recovery_issues
    ):
        raise GameTreeEditError(
            "recovery_issues must be a list of PgnRecoveryIssue values",
            code=GameTreeEditCode.INVALID_INPUT,
        )
    return game


def _validated_digest(game: object) -> str:
    game = _validate_outer_game(game)
    try:
        for _ in iter_move_addresses(game):
            pass
    except GameTreePathError as exc:
        raise GameTreeEditError(
            str(exc), code=_map_navigation_code(exc.code)
        ) from exc
    try:
        return identity_for_game(game).record_digest
    except GameIdentityContractError as exc:
        code = (
            GameTreeEditCode.GRAPH_CYCLE
            if exc.code.value == "cyclic_tree"
            else GameTreeEditCode.GRAPH_DEPTH_LIMIT
            if exc.code.value == "tree_limit_exceeded"
            else GameTreeEditCode.INVALID_INPUT
        )
        raise GameTreeEditError(str(exc), code=code) from exc


def _resolve_target(game: PgnGame, target: VariationEditTarget) -> VariationLine:
    try:
        context = branch_context(
            game,
            target.parent_path,
            target.parent_move_index,
            target.variation_index,
        )
        return resolve_line(game, context.child_path)
    except GameTreePathError as exc:
        raise GameTreeEditError(
            str(exc), code=GameTreeEditCode.INVALID_TARGET
        ) from exc


def variation_edit_target(
    game: PgnGame,
    parent_path: VariationPath,
    parent_move_index: int,
    variation_index: int,
) -> VariationEditTarget:
    """Bind one current branch address to the complete record revision."""

    digest = _validated_digest(game)
    try:
        provisional = VariationEditTarget(
            parent_path,
            parent_move_index,
            variation_index,
            digest,
        )
    except (TypeError, ValueError) as exc:
        raise GameTreeEditError(
            str(exc), code=GameTreeEditCode.INVALID_TARGET
        ) from exc
    _resolve_target(game, provisional)
    return provisional


def _prepare(
    game: PgnGame,
    target: VariationEditTarget,
) -> tuple[PgnGame, list[_LineRecord], dict[int, object], VariationLine]:
    if not isinstance(target, VariationEditTarget):
        raise TypeError("target must be a VariationEditTarget")
    digest = _validated_digest(game)
    if digest != target.expected_record_digest:
        raise GameTreeEditError(
            "GameTree changed after the variation target was created",
            code=GameTreeEditCode.STALE_REVISION,
        )
    selected = _resolve_target(game, target)
    records = _collect_lines(game.line)
    memo: dict[int, object] = {}
    cloned = deepcopy(game, memo)
    assert isinstance(cloned, PgnGame)
    return cloned, records, memo, selected


def _collect_lines(root: VariationLine) -> list[_LineRecord]:
    records: list[_LineRecord] = []

    def walk(line: VariationLine, path: VariationPath) -> None:
        records.append(_LineRecord(path, line))
        for move_index, move in enumerate(line.moves):
            for variation_index, variation in enumerate(move.variations):
                walk(
                    variation,
                    path + (VariationStep(move_index, variation_index),),
                )

    walk(root, ())
    return records


def _new_paths(game: PgnGame) -> dict[int, VariationPath]:
    return {id(record.line): record.path for record in _collect_lines(game.line)}


def _cursor_remap(
    records: list[_LineRecord],
    memo: dict[int, object],
    edited: PgnGame,
    overrides: Mapping[
        int,
        Callable[[int], GameTreeCursor | None],
    ] | None = None,
) -> tuple[CursorRemapEntry, ...]:
    overrides = {} if overrides is None else overrides
    paths = _new_paths(edited)
    entries: list[CursorRemapEntry] = []
    for record in records:
        override = overrides.get(id(record.line))
        cloned_line = memo.get(id(record.line))
        new_path = paths.get(id(cloned_line)) if cloned_line is not None else None
        for next_index in range(len(record.line.moves) + 1):
            before = GameTreeCursor(record.path, next_index)
            after = (
                override(next_index)
                if override is not None
                else GameTreeCursor(new_path, next_index)
                if new_path is not None
                else None
            )
            entries.append(CursorRemapEntry(before, after))
            if len(entries) > MAX_TREE_NODES:
                raise GameTreeEditError(
                    "cursor remap exceeds the node safety limit",
                    code=GameTreeEditCode.GRAPH_NODE_LIMIT,
                )
    return tuple(entries)


def _finish(
    edited: PgnGame,
    operation: GameTreeEditOperation,
    target: VariationEditTarget,
    records: list[_LineRecord],
    memo: dict[int, object],
    overrides: Mapping[int, Callable[[int], GameTreeCursor | None]] | None = None,
) -> GameTreeEditResult:
    _validated_digest(edited)
    return GameTreeEditResult(
        edited,
        operation,
        target,
        _cursor_remap(records, memo, edited, overrides),
    )


def reorder_variation(
    game: PgnGame,
    target: VariationEditTarget,
    new_index: int,
) -> GameTreeEditResult:
    """Move one sibling RAV to ``new_index`` without changing its content."""

    if type(new_index) is not int:
        raise GameTreeEditError(
            "new_index must be an exact integer",
            code=GameTreeEditCode.INVALID_ORDER,
        )
    edited, records, memo, _ = _prepare(game, target)
    parent = resolve_line(edited, target.parent_path)
    variations = parent.moves[target.parent_move_index].variations
    if new_index < 0 or new_index >= len(variations):
        raise GameTreeEditError(
            "new variation index is out of range",
            code=GameTreeEditCode.INVALID_ORDER,
        )
    selected = variations.pop(target.variation_index)
    variations.insert(new_index, selected)
    return _finish(
        edited,
        GameTreeEditOperation.REORDER_VARIATION,
        target,
        records,
        memo,
    )


def delete_variation(
    game: PgnGame,
    target: VariationEditTarget,
) -> GameTreeEditResult:
    """Remove exactly one addressed RAV; deleted cursors map to ``None``."""

    edited, records, memo, _ = _prepare(game, target)
    parent = resolve_line(edited, target.parent_path)
    parent.moves[target.parent_move_index].variations.pop(target.variation_index)
    return _finish(
        edited,
        GameTreeEditOperation.DELETE_VARIATION,
        target,
        records,
        memo,
    )


def promote_variation(
    game: PgnGame,
    target: VariationEditTarget,
) -> GameTreeEditResult:
    """Promote one RAV to its parent continuation and demote the old mainline."""

    edited, records, memo, selected_source = _prepare(game, target)
    if not selected_source.moves:
        raise GameTreeEditError(
            "an empty variation cannot become a mainline",
            code=GameTreeEditCode.EMPTY_VARIATION,
        )

    parent_source = resolve_line(game, target.parent_path)
    parent = resolve_line(edited, target.parent_path)
    owner_index = target.parent_move_index
    old_moves = parent.moves
    old_result = parent.result
    old_trailing = parent.trailing_comments
    old_suffix = old_moves[owner_index:]
    old_owner = old_suffix[0]
    selected = old_owner.variations.pop(target.variation_index)
    selected_first = selected.moves[0]

    remaining_siblings = list(old_owner.variations)
    selected_first_siblings = list(selected_first.variations)
    old_owner.variations = []
    demoted = VariationLine(
        moves=old_suffix,
        leading_comments=[],
        trailing_comments=old_trailing,
        result=old_result,
    )
    selected_first.comments_before = (
        list(selected.leading_comments) + list(selected_first.comments_before)
    )
    selected_first.variations = (
        [demoted] + remaining_siblings + selected_first_siblings
    )
    parent.moves = old_moves[:owner_index] + list(selected.moves)
    parent.trailing_comments = list(selected.trailing_comments)
    parent.result = selected.result if selected.result is not None else old_result
    if not target.parent_path and "Result" in edited.tags and parent.result is not None:
        edited.tags["Result"] = parent.result

    demoted_path = target.parent_path + (VariationStep(owner_index, 0),)
    selected_source_id = id(selected_source)
    parent_source_id = id(parent_source)

    def remap_parent(next_index: int) -> GameTreeCursor:
        if next_index <= owner_index:
            return GameTreeCursor(target.parent_path, next_index)
        return GameTreeCursor(demoted_path, next_index - owner_index)

    def remap_selected(next_index: int) -> GameTreeCursor:
        return GameTreeCursor(target.parent_path, owner_index + next_index)

    return _finish(
        edited,
        GameTreeEditOperation.PROMOTE_VARIATION,
        target,
        records,
        memo,
        {
            parent_source_id: remap_parent,
            selected_source_id: remap_selected,
        },
    )
