from __future__ import annotations

"""Deterministic evidence-only fuzz for canonical GameTree structural editing.

This tool deliberately does not implement PGN, chess rules, or a second GameTree.
It mutates only through the existing canonical D06 insertion/editing/workspace
APIs.  The independent oracle gives every move an opaque marker and verifies
that every valid source cursor is remapped to the same semantic move boundary,
including nested sibling movement, deletion, insertion, and promotion.
"""

import argparse
from collections import Counter
from copy import deepcopy
import json
import random

from acs.gametree import Comment, MoveNode, PgnGame, VariationLine
from acs.gametree_editing import (
    GameTreeEditCode,
    GameTreeEditError,
    delete_variation,
    promote_variation,
    reorder_variation,
    variation_edit_target,
)
from acs.gametree_insertion import (
    VariationInsertCode,
    VariationInsertError,
    add_variation,
    variation_insert_target,
)
from acs.gametree_navigation import GameTreeCursor, VariationStep, resolve_line, validate_cursor
from acs.pgn_roundtrip import parse_pgn_text, serialize_pgn_text
from acs.pgn_workspace import PgnWorkspace


PRODUCT_BASE = "d706eb93b9a4df3c6e99ab1af584a9cfe6b6f5ea"
MARKER_PREFIX = "PGN04-M"

BASE_PGN = '''[Event "PGN-04 structural fuzz seed"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 {root e4} e5
(1... c5 $1 {sicilian} 2. Nf3 (2... d6 $2 {nested}) 2... Nc6)
(1... e6 {french} 2. d4 d5)
2. Nf3 {main knight} Nc6 *
'''

_INSERT_SAN = (
    ("a3", "a6", "Ra2"),
    ("h3", "h6", "Rh2"),
    ("d4", "d5", "Nd2"),
    ("c4", "c5", "Nc3"),
    ("g3", "g6", "Bg2"),
    ("b3", "b6", "Bb2"),
)


def _walk_lines(game: PgnGame):
    stack = [((), game.line)]
    while stack:
        path, line = stack.pop()
        yield path, line
        for move_index in range(len(line.moves) - 1, -1, -1):
            move = line.moves[move_index]
            for variation_index in range(len(move.variations) - 1, -1, -1):
                stack.append(
                    (
                        path + (VariationStep(move_index, variation_index),),
                        move.variations[variation_index],
                    )
                )


def _all_cursors(game: PgnGame) -> tuple[GameTreeCursor, ...]:
    out: list[GameTreeCursor] = []
    for path, line in _walk_lines(game):
        if not line.moves:
            raise AssertionError("PGN-04 oracle requires non-empty lines")
        out.extend(GameTreeCursor(path, index) for index in range(len(line.moves) + 1))
    if len(out) != len(set(out)):
        raise AssertionError("source cursor enumeration contains duplicates")
    return tuple(out)


def _marker(move: MoveNode) -> str:
    found = [
        comment.text
        for comment in move.comments_after
        if comment.text.startswith(MARKER_PREFIX)
    ]
    if len(found) != 1:
        raise AssertionError(f"move marker cardinality is {len(found)}, expected 1")
    return found[0]


def _marker_index(game: PgnGame) -> dict[str, tuple[tuple[VariationStep, ...], int]]:
    out: dict[str, tuple[tuple[VariationStep, ...], int]] = {}
    for path, line in _walk_lines(game):
        for index, move in enumerate(line.moves):
            marker = _marker(move)
            if marker in out:
                raise AssertionError(f"duplicate move marker {marker}")
            out[marker] = (path, index)
    return out


def _cursor_marker_key(game: PgnGame, cursor: GameTreeCursor) -> tuple[str, str]:
    line = resolve_line(game, cursor.line_path)
    validate_cursor(game, cursor)
    if cursor.next_move_index < len(line.moves):
        return "before", _marker(line.moves[cursor.next_move_index])
    return "after", _marker(line.moves[-1])


def _cursor_from_key(
    marker_index: dict[str, tuple[tuple[VariationStep, ...], int]],
    key: tuple[str, str],
) -> GameTreeCursor | None:
    side, marker = key
    address = marker_index.get(marker)
    if address is None:
        return None
    path, move_index = address
    return GameTreeCursor(path, move_index if side == "before" else move_index + 1)


def _next_marker(counter: list[int]) -> str:
    counter[0] += 1
    return f"{MARKER_PREFIX}{counter[0]:06d}"


def _mark_seed(game: PgnGame, counter: list[int]) -> None:
    for _, line in _walk_lines(game):
        for move in line.moves:
            move.comments_after.append(Comment(_next_marker(counter)))


def _new_variation(counter: list[int], rng: random.Random) -> VariationLine:
    san_a, san_b, san_c = rng.choice(_INSERT_SAN)
    first = MoveNode(san_a, comments_after=[Comment(_next_marker(counter))])
    second = MoveNode(san_b, comments_after=[Comment(_next_marker(counter))])
    nested = MoveNode(san_c, comments_after=[Comment(_next_marker(counter))])
    first.variations = [VariationLine(moves=[nested])]
    return VariationLine(moves=[first, second])


def _strict_roundtrip(game: PgnGame) -> PgnGame:
    text = serialize_pgn_text((game,))
    reparsed = parse_pgn_text(text, strict=True)
    if len(reparsed) != 1 or reparsed[0] != game:
        raise AssertionError("GameTree changed under strict PGN round-trip")
    if serialize_pgn_text(reparsed) != text:
        raise AssertionError("strict PGN serialization is nondeterministic")
    return reparsed[0]


def _targets(game: PgnGame):
    variations: list[tuple[tuple[VariationStep, ...], int, int, int]] = []
    insertions: list[tuple[tuple[VariationStep, ...], int, int]] = []
    for path, line in _walk_lines(game):
        for move_index, move in enumerate(line.moves):
            sibling_count = len(move.variations)
            insertions.append((path, move_index, sibling_count))
            for variation_index in range(sibling_count):
                variations.append((path, move_index, variation_index, sibling_count))
    return variations, insertions


def _assert_complete_remap(
    source: PgnGame,
    edited: PgnGame,
    result,
    *,
    operation: str,
    parent_path: tuple[VariationStep, ...] | None = None,
    parent_move_index: int | None = None,
) -> int:
    source_cursors = _all_cursors(source)
    if len(result.cursor_remap) != len(source_cursors):
        raise AssertionError(
            f"{operation}: remap cardinality {len(result.cursor_remap)} != {len(source_cursors)}"
        )
    if len({entry.before for entry in result.cursor_remap}) != len(source_cursors):
        raise AssertionError(f"{operation}: duplicate source cursor in remap")

    edited_markers = _marker_index(edited)
    checked = 0
    for cursor in source_cursors:
        if (
            operation == "promote"
            and cursor.line_path == parent_path
            and cursor.next_move_index == parent_move_index
        ):
            # Promotion preserves the branch point itself.  The old owner move
            # is demoted, so marker identity is intentionally not the semantic
            # identity of this one cursor boundary.
            expected = GameTreeCursor(parent_path, parent_move_index)
        else:
            expected = _cursor_from_key(edited_markers, _cursor_marker_key(source, cursor))
        actual = result.remap_cursor(cursor)
        if actual != expected:
            raise AssertionError(
                f"{operation}: cursor {cursor!r} remapped to {actual!r}, expected {expected!r}"
            )
        if actual is not None:
            validate_cursor(edited, actual)
        checked += 1
    return checked


def _assert_workspace_wrapper(
    source: PgnGame,
    direct_result,
    *,
    operation: str,
    target,
    active_cursor: GameTreeCursor,
    proposed: VariationLine | None = None,
    new_index: int | None = None,
) -> None:
    workspace = PgnWorkspace([source])
    workspace.set_cursor(active_cursor)
    before_revision = workspace.content_revision
    before_digest = workspace.content_digest

    if operation == "insert":
        wrapped = workspace.add_variation(target, deepcopy(proposed))
        expected_cursor = direct_result.remap_cursor(active_cursor)
    elif operation == "reorder":
        wrapped = workspace.reorder_variation(target, new_index)
        expected_cursor = direct_result.remap_cursor(active_cursor)
    elif operation == "delete":
        wrapped = workspace.delete_variation(target)
        expected_cursor = direct_result.remap_cursor(active_cursor)
        if expected_cursor is None:
            expected_cursor = GameTreeCursor(
                target.parent_path,
                target.parent_move_index + 1,
            )
    elif operation == "promote":
        wrapped = workspace.promote_variation(target)
        expected_cursor = direct_result.remap_cursor(active_cursor)
    else:
        raise AssertionError(f"unknown workspace operation {operation}")

    if wrapped.game != direct_result.game:
        raise AssertionError(f"{operation}: workspace and direct Product result differ")
    if workspace.current_game() != direct_result.game:
        raise AssertionError(f"{operation}: workspace did not commit direct canonical result")
    if workspace.cursor != expected_cursor:
        raise AssertionError(
            f"{operation}: workspace cursor {workspace.cursor!r} != {expected_cursor!r}"
        )
    validate_cursor(workspace.current_game(), workspace.cursor)
    if workspace.content_revision != before_revision + 1:
        raise AssertionError(f"{operation}: workspace revision did not increment exactly once")
    if not workspace.dirty or workspace.content_digest == before_digest:
        raise AssertionError(f"{operation}: workspace mutation did not become dirty")


def _assert_stale_fails(source_after: PgnGame, *, operation: str, target) -> None:
    before = deepcopy(source_after)
    if operation == "insert":
        try:
            add_variation(
                source_after,
                target,
                VariationLine(moves=[MoveNode("a4")]),
            )
        except VariationInsertError as exc:
            if exc.code != VariationInsertCode.STALE_REVISION:
                raise AssertionError(f"insert stale target returned {exc.code}") from exc
        else:
            raise AssertionError("insert stale target unexpectedly succeeded")
    else:
        try:
            delete_variation(source_after, target)
        except GameTreeEditError as exc:
            if exc.code != GameTreeEditCode.STALE_REVISION:
                raise AssertionError(f"edit stale target returned {exc.code}") from exc
        else:
            raise AssertionError("edit stale target unexpectedly succeeded")
    if source_after != before:
        raise AssertionError(f"{operation}: stale-target failure partially mutated source")


def _exercise_seed(seed: int, steps: int) -> dict[str, object]:
    rng = random.Random(seed)
    marker_counter = [seed * 100_000]
    game = parse_pgn_text(BASE_PGN, strict=True)[0]
    _mark_seed(game, marker_counter)
    game = _strict_roundtrip(game)

    counts: Counter[str] = Counter()
    cursor_checks = 0
    roundtrips = 1
    workspace_checks = 0
    max_depth = 0
    max_lines = 0

    cycle = ("insert", "reorder", "promote", "delete")
    for step in range(steps):
        variations, insertions = _targets(game)
        max_depth = max(max_depth, max((len(path) for path, _ in _walk_lines(game)), default=0))
        max_lines = max(max_lines, sum(1 for _ in _walk_lines(game)))

        desired = cycle[step % len(cycle)]
        if desired == "reorder":
            eligible = [item for item in variations if item[3] > 1]
            if not eligible:
                desired = "insert"
        if desired in {"delete", "promote"} and not variations:
            desired = "insert"
        if desired == "insert" and max_lines >= 80:
            desired = "reorder" if any(item[3] > 1 for item in variations) else "delete"

        source = game
        source_before = deepcopy(source)
        source_cursors = _all_cursors(source)
        active_cursor = rng.choice(source_cursors)

        if desired == "insert":
            parent_path, move_index, sibling_count = rng.choice(insertions)
            insert_index = rng.randrange(sibling_count + 1)
            target = variation_insert_target(source, parent_path, move_index, insert_index)
            proposed = _new_variation(marker_counter, rng)
            proposed_before = deepcopy(proposed)
            result = add_variation(source, target, proposed)
            if proposed != proposed_before:
                raise AssertionError("insert mutated caller-owned proposed variation")
            cursor_checks += _assert_complete_remap(source, result.game, result, operation="insert")
            _assert_workspace_wrapper(
                source,
                result,
                operation="insert",
                target=target,
                active_cursor=active_cursor,
                proposed=proposed,
            )
            _assert_stale_fails(result.game, operation="insert", target=target)
        else:
            parent_path, move_index, variation_index, sibling_count = rng.choice(variations)
            target = variation_edit_target(source, parent_path, move_index, variation_index)
            if desired == "reorder":
                choices = [index for index in range(sibling_count) if index != variation_index]
                if not choices:
                    # Availability can change after the desired-operation check
                    # only through our local selection; fall back deterministically.
                    desired = "promote"
                else:
                    new_index = rng.choice(choices)
                    result = reorder_variation(source, target, new_index)
                    cursor_checks += _assert_complete_remap(
                        source, result.game, result, operation="reorder"
                    )
                    _assert_workspace_wrapper(
                        source,
                        result,
                        operation="reorder",
                        target=target,
                        active_cursor=active_cursor,
                        new_index=new_index,
                    )
            if desired == "delete":
                result = delete_variation(source, target)
                cursor_checks += _assert_complete_remap(source, result.game, result, operation="delete")
                _assert_workspace_wrapper(
                    source,
                    result,
                    operation="delete",
                    target=target,
                    active_cursor=active_cursor,
                )
            elif desired == "promote":
                result = promote_variation(source, target)
                cursor_checks += _assert_complete_remap(
                    source,
                    result.game,
                    result,
                    operation="promote",
                    parent_path=parent_path,
                    parent_move_index=move_index,
                )
                _assert_workspace_wrapper(
                    source,
                    result,
                    operation="promote",
                    target=target,
                    active_cursor=active_cursor,
                )
            _assert_stale_fails(result.game, operation=desired, target=target)

        if source != source_before:
            raise AssertionError(f"{desired}: Product operation mutated caller source")
        game = _strict_roundtrip(result.game)
        roundtrips += 1
        counts[desired] += 1
        workspace_checks += 1

    max_depth = max(max_depth, max((len(path) for path, _ in _walk_lines(game)), default=0))
    max_lines = max(max_lines, sum(1 for _ in _walk_lines(game)))
    return {
        "seed": seed,
        "operations": dict(counts),
        "cursor_checks": cursor_checks,
        "roundtrips": roundtrips,
        "workspace_checks": workspace_checks,
        "max_depth": max_depth,
        "max_lines": max_lines,
    }


def run(*, seeds: int, steps: int) -> int:
    aggregate: Counter[str] = Counter()
    cursor_checks = 0
    roundtrips = 0
    workspace_checks = 0
    max_depth = 0
    max_lines = 0
    results = []

    for seed in range(seeds):
        result = _exercise_seed(seed, steps)
        results.append(result)
        aggregate.update(result["operations"])
        cursor_checks += int(result["cursor_checks"])
        roundtrips += int(result["roundtrips"])
        workspace_checks += int(result["workspace_checks"])
        max_depth = max(max_depth, int(result["max_depth"]))
        max_lines = max(max_lines, int(result["max_lines"]))

    missing = [name for name in ("insert", "reorder", "delete", "promote") if aggregate[name] == 0]
    if missing:
        raise AssertionError(f"fuzz campaign missed required operations: {missing}")

    report = {
        "schema": 1,
        "product_base": PRODUCT_BASE,
        "seeds": seeds,
        "steps_per_seed": steps,
        "operations_total": sum(aggregate.values()),
        "operation_counts": dict(sorted(aggregate.items())),
        "cursor_remap_assertions": cursor_checks,
        "strict_roundtrips": roundtrips,
        "workspace_wrapper_checks": workspace_checks,
        "max_variation_depth_observed": max_depth,
        "max_lines_observed": max_lines,
        "product_mutation": "NONE",
        "oracle": "opaque move-marker semantic boundary + canonical cursor validation",
    }
    print("PGN04_STRUCTURAL_FUZZ_REPORT=" + json.dumps(report, sort_keys=True))
    print("PGN-04 GAMETREE STRUCTURAL FUZZ PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=32)
    parser.add_argument("--steps", type=int, default=28)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.seeds <= 0 or args.steps <= 0:
        parser.error("--seeds and --steps must be positive")
    if args.selftest:
        return run(seeds=2, steps=8)
    return run(seeds=args.seeds, steps=args.steps)


if __name__ == "__main__":
    raise SystemExit(main())
