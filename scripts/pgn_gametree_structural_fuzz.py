from __future__ import annotations

"""Deterministic evidence-only fuzz for canonical GameTree structural editing.

The oracle does not implement PGN, chess rules, or a second GameTree. Product
mutations go only through canonical D06 editing/insertion/workspace APIs. Every
move receives an opaque marker so the QA layer can independently locate the
same semantic cursor boundary after structural churn.
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
INSERT_SAN = (
    ("a3", "a6", "Ra2"),
    ("h3", "h6", "Rh2"),
    ("d4", "d5", "Nd2"),
    ("c4", "c5", "Nc3"),
    ("g3", "g6", "Bg2"),
    ("b3", "b6", "Bb2"),
)


def walk_lines(game: PgnGame):
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


def all_cursors(game: PgnGame) -> tuple[GameTreeCursor, ...]:
    out: list[GameTreeCursor] = []
    for path, line in walk_lines(game):
        if not line.moves:
            raise AssertionError("PGN-04 oracle requires non-empty lines")
        out.extend(GameTreeCursor(path, index) for index in range(len(line.moves) + 1))
    if len(out) != len(set(out)):
        raise AssertionError("source cursor enumeration contains duplicates")
    return tuple(out)


def move_marker(move: MoveNode) -> str:
    values = [c.text for c in move.comments_after if c.text.startswith(MARKER_PREFIX)]
    if len(values) != 1:
        raise AssertionError(f"move marker cardinality {len(values)} != 1")
    return values[0]


def marker_index(game: PgnGame):
    out = {}
    for path, line in walk_lines(game):
        for move_index, move in enumerate(line.moves):
            marker = move_marker(move)
            if marker in out:
                raise AssertionError(f"duplicate marker {marker}")
            out[marker] = (path, move_index)
    return out


def cursor_key(game: PgnGame, cursor: GameTreeCursor):
    line = resolve_line(game, cursor.line_path)
    validate_cursor(game, cursor)
    if cursor.next_move_index < len(line.moves):
        return "before", move_marker(line.moves[cursor.next_move_index])
    return "after", move_marker(line.moves[-1])


def locate_key(index, key):
    side, marker = key
    found = index.get(marker)
    if found is None:
        return None
    path, move_index = found
    return GameTreeCursor(path, move_index if side == "before" else move_index + 1)


def next_marker(counter: list[int]) -> str:
    counter[0] += 1
    return f"{MARKER_PREFIX}{counter[0]:06d}"


def mark_seed(game: PgnGame, counter: list[int]) -> None:
    for _, line in walk_lines(game):
        for move in line.moves:
            move.comments_after.append(Comment(next_marker(counter)))


def new_variation(counter: list[int], rng: random.Random) -> VariationLine:
    first_san, second_san, nested_san = rng.choice(INSERT_SAN)
    first = MoveNode(first_san, comments_after=[Comment(next_marker(counter))])
    second = MoveNode(second_san, comments_after=[Comment(next_marker(counter))])
    nested = MoveNode(nested_san, comments_after=[Comment(next_marker(counter))])
    first.variations = [VariationLine(moves=[nested])]
    return VariationLine(moves=[first, second])


def strict_roundtrip(game: PgnGame) -> PgnGame:
    text = serialize_pgn_text((game,))
    reparsed = parse_pgn_text(text, strict=True)
    if len(reparsed) != 1 or reparsed[0] != game:
        raise AssertionError("GameTree changed under strict PGN round-trip")
    if serialize_pgn_text(reparsed) != text:
        raise AssertionError("strict PGN serialization is nondeterministic")
    return reparsed[0]


def targets(game: PgnGame):
    variations = []
    insertions = []
    for path, line in walk_lines(game):
        for move_index, move in enumerate(line.moves):
            sibling_count = len(move.variations)
            insertions.append((path, move_index, sibling_count))
            for variation_index in range(sibling_count):
                variations.append((path, move_index, variation_index, sibling_count))
    return variations, insertions


def verify_remap(
    source: PgnGame,
    edited: PgnGame,
    result,
    operation: str,
    parent_path=None,
    parent_move_index=None,
) -> int:
    source_cursors = all_cursors(source)
    if len(result.cursor_remap) != len(source_cursors):
        raise AssertionError(
            f"{operation}: remap cardinality {len(result.cursor_remap)} != {len(source_cursors)}"
        )
    if len({entry.before for entry in result.cursor_remap}) != len(source_cursors):
        raise AssertionError(f"{operation}: duplicate source cursor in remap")

    edited_markers = marker_index(edited)
    for cursor in source_cursors:
        if (
            operation == "promote"
            and cursor.line_path == parent_path
            and cursor.next_move_index == parent_move_index
        ):
            # This boundary identifies the branch point, not the old owner move.
            expected = GameTreeCursor(parent_path, parent_move_index)
        else:
            expected = locate_key(edited_markers, cursor_key(source, cursor))
        actual = result.remap_cursor(cursor)
        if actual != expected:
            raise AssertionError(
                f"{operation}: {cursor!r} -> {actual!r}, expected {expected!r}"
            )
        if actual is not None:
            validate_cursor(edited, actual)
    return len(source_cursors)


def verify_workspace(
    source: PgnGame,
    direct_result,
    operation: str,
    target,
    active: GameTreeCursor,
    proposed=None,
    new_index=None,
) -> None:
    workspace = PgnWorkspace([source])
    workspace.set_cursor(active)
    before_revision = workspace.content_revision
    before_digest = workspace.content_digest

    if operation == "insert":
        wrapped = workspace.add_variation(target, deepcopy(proposed))
        expected_cursor = direct_result.remap_cursor(active)
    elif operation == "reorder":
        wrapped = workspace.reorder_variation(target, new_index)
        expected_cursor = direct_result.remap_cursor(active)
    elif operation == "delete":
        wrapped = workspace.delete_variation(target)
        expected_cursor = direct_result.remap_cursor(active)
        if expected_cursor is None:
            expected_cursor = GameTreeCursor(target.parent_path, target.parent_move_index + 1)
    elif operation == "promote":
        wrapped = workspace.promote_variation(target)
        expected_cursor = direct_result.remap_cursor(active)
    else:
        raise AssertionError(f"unknown operation {operation}")

    if wrapped.game != direct_result.game or workspace.current_game() != direct_result.game:
        raise AssertionError(f"{operation}: workspace/direct Product results differ")
    if workspace.cursor != expected_cursor:
        raise AssertionError(
            f"{operation}: workspace cursor {workspace.cursor!r} != {expected_cursor!r}"
        )
    validate_cursor(workspace.current_game(), workspace.cursor)
    if workspace.content_revision != before_revision + 1:
        raise AssertionError(f"{operation}: workspace revision did not increment once")
    if not workspace.dirty or workspace.content_digest == before_digest:
        raise AssertionError(f"{operation}: workspace mutation did not become dirty")


def verify_stale(edited: PgnGame, operation: str, target) -> None:
    before = deepcopy(edited)
    if operation == "insert":
        try:
            add_variation(edited, target, VariationLine(moves=[MoveNode("a4")]))
        except VariationInsertError as exc:
            if exc.code != VariationInsertCode.STALE_REVISION:
                raise AssertionError(f"insert stale target returned {exc.code}") from exc
        else:
            raise AssertionError("insert stale target unexpectedly succeeded")
    else:
        try:
            delete_variation(edited, target)
        except GameTreeEditError as exc:
            if exc.code != GameTreeEditCode.STALE_REVISION:
                raise AssertionError(f"edit stale target returned {exc.code}") from exc
        else:
            raise AssertionError("edit stale target unexpectedly succeeded")
    if edited != before:
        raise AssertionError(f"{operation}: stale failure partially mutated source")


def apply_operation(game: PgnGame, desired: str, rng: random.Random, counter: list[int]):
    variations, insertions = targets(game)
    reorderable = [item for item in variations if item[3] > 1]
    line_count = sum(1 for _ in walk_lines(game))

    if desired == "reorder" and not reorderable:
        desired = "insert"
    if desired in {"delete", "promote"} and not variations:
        desired = "insert"
    if desired == "insert" and line_count >= 80:
        desired = "reorder" if reorderable else "delete"

    if desired == "insert":
        parent_path, move_index, sibling_count = rng.choice(insertions)
        insert_index = rng.randrange(sibling_count + 1)
        target = variation_insert_target(game, parent_path, move_index, insert_index)
        proposed = new_variation(counter, rng)
        proposed_before = deepcopy(proposed)
        result = add_variation(game, target, proposed)
        if proposed != proposed_before:
            raise AssertionError("insert mutated caller-owned proposed variation")
        return desired, result, target, proposed, None, parent_path, move_index

    pool = reorderable if desired == "reorder" else variations
    parent_path, move_index, variation_index, sibling_count = rng.choice(pool)
    target = variation_edit_target(game, parent_path, move_index, variation_index)
    if desired == "reorder":
        choices = [index for index in range(sibling_count) if index != variation_index]
        if not choices:
            raise AssertionError("reorder selected a non-reorderable target")
        new_index = rng.choice(choices)
        result = reorder_variation(game, target, new_index)
    elif desired == "delete":
        new_index = None
        result = delete_variation(game, target)
    elif desired == "promote":
        new_index = None
        result = promote_variation(game, target)
    else:
        raise AssertionError(f"unknown desired operation {desired}")
    return desired, result, target, None, new_index, parent_path, move_index


def exercise_seed(seed: int, steps: int):
    rng = random.Random(seed)
    counter = [seed * 100_000]
    game = parse_pgn_text(BASE_PGN, strict=True)[0]
    mark_seed(game, counter)
    game = strict_roundtrip(game)

    counts = Counter()
    cursor_checks = 0
    roundtrips = 1
    workspace_checks = 0
    max_depth = 0
    max_lines = 0
    operation_cycle = ("insert", "reorder", "promote", "delete")

    for step in range(steps):
        source = game
        source_before = deepcopy(source)
        max_depth = max(max_depth, max(len(path) for path, _ in walk_lines(source)))
        max_lines = max(max_lines, sum(1 for _ in walk_lines(source)))
        active = rng.choice(all_cursors(source))

        operation, result, target, proposed, new_index, parent_path, move_index = apply_operation(
            source, operation_cycle[step % 4], rng, counter
        )
        cursor_checks += verify_remap(
            source,
            result.game,
            result,
            operation,
            parent_path,
            move_index,
        )
        verify_workspace(
            source,
            result,
            operation,
            target,
            active,
            proposed,
            new_index,
        )
        verify_stale(result.game, operation, target)
        if source != source_before:
            raise AssertionError(f"{operation}: Product mutated caller source")

        game = strict_roundtrip(result.game)
        roundtrips += 1
        workspace_checks += 1
        counts[operation] += 1

    max_depth = max(max_depth, max(len(path) for path, _ in walk_lines(game)))
    max_lines = max(max_lines, sum(1 for _ in walk_lines(game)))
    return counts, cursor_checks, roundtrips, workspace_checks, max_depth, max_lines


def run(seeds: int, steps: int) -> int:
    aggregate = Counter()
    cursor_checks = roundtrips = workspace_checks = 0
    max_depth = max_lines = 0
    for seed in range(seeds):
        counts, checked, trips, wrapped, depth, lines = exercise_seed(seed, steps)
        aggregate.update(counts)
        cursor_checks += checked
        roundtrips += trips
        workspace_checks += wrapped
        max_depth = max(max_depth, depth)
        max_lines = max(max_lines, lines)

    required = ("insert", "reorder", "delete", "promote")
    missing = [name for name in required if aggregate[name] == 0]
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
    return run(2, 8) if args.selftest else run(args.seeds, args.steps)


if __name__ == "__main__":
    raise SystemExit(main())
