from __future__ import annotations

"""Passive structural safety for PGN presentation graph traversal.

This boundary deliberately does not validate chess legality, SAN grammar, or
PGN exportability.  The presenter is a recovery/read surface, so damaged but
representable historical text must remain readable.  The guard only proves that
recursive presentation will traverse exact passive containers within the
canonical GameTree graph bounds.
"""

from .gametree import (
    MAX_TREE_NODES,
    MAX_VARIATION_DEPTH,
    Comment,
    GameTreeContractError,
    GameTreeErrorCode,
    MoveNode,
    PgnGame,
    VariationLine,
)


def snapshot_pgn_presentation_games(games: object) -> tuple[PgnGame, ...]:
    """Snapshot a passive built-in game collection without invoking user hooks."""
    if type(games) not in {list, tuple}:
        raise TypeError("PGN presenter games must be a built-in list or tuple")
    for game in games:
        if type(game) is not PgnGame:
            raise GameTreeContractError(
                "PGN presenter game must be PgnGame",
                code=GameTreeErrorCode.INVALID_GAME,
            )
    return tuple(games)


def _contract_error(message: str, code: GameTreeErrorCode) -> GameTreeContractError:
    return GameTreeContractError(message, code=code)


def _require_exact_text(value: object, *, field: str) -> None:
    if type(value) is not str:
        raise _contract_error(
            f"{field} must be built-in text",
            GameTreeErrorCode.INVALID_CONTAINER,
        )


def _require_comment_list(value: object, *, field: str) -> None:
    if type(value) is not list:
        raise _contract_error(
            f"{field} must be a built-in list",
            GameTreeErrorCode.INVALID_CONTAINER,
        )
    for comment in value:
        if type(comment) is not Comment:
            raise _contract_error(
                f"{field} items must be Comment",
                GameTreeErrorCode.INVALID_CONTAINER,
            )
        _require_exact_text(comment.text, field=f"{field} text")


def _validate_game_shell(game: object) -> PgnGame:
    if type(game) is not PgnGame:
        raise _contract_error(
            "PGN presenter game must be PgnGame",
            GameTreeErrorCode.INVALID_GAME,
        )
    if type(game.tags) is not dict:
        raise _contract_error(
            "PGN presenter tags must be a built-in dict",
            GameTreeErrorCode.INVALID_CONTAINER,
        )
    for key, value in game.tags.items():
        _require_exact_text(key, field="PGN tag name")
        _require_exact_text(value, field="PGN tag value")
    if type(game.source_index) is not int:
        raise _contract_error(
            "PGN source index must be an exact integer",
            GameTreeErrorCode.INVALID_GAME,
        )
    if type(game.warnings) is not list:
        raise _contract_error(
            "PGN warnings must be a built-in list",
            GameTreeErrorCode.INVALID_CONTAINER,
        )
    for warning in game.warnings:
        _require_exact_text(warning, field="PGN warning")
    if type(game.line) is not VariationLine:
        raise _contract_error(
            "PGN root must be VariationLine",
            GameTreeErrorCode.INVALID_LINE,
        )
    return game


def validate_pgn_presentation_graph(game: object) -> None:
    """Prove recursive presenter traversal is passive, acyclic, and bounded.

    The traversal is iterative so the validation itself cannot hit Python's
    recursion limit on hostile input.  Line and move identity are tracked across
    the current game: active-line reuse is a cycle; completed-node reuse is an
    aliasing graph that the tree presenter cannot represent canonically.
    """
    canonical_game = _validate_game_shell(game)
    claimed: set[int] = set()
    active_lines: set[int] = set()
    node_count = 0
    stack: list[tuple[str, VariationLine, int]] = [("enter", canonical_game.line, 0)]

    while stack:
        phase, line, depth = stack.pop()
        line_id = id(line)
        if phase == "exit":
            active_lines.remove(line_id)
            continue

        if type(line) is not VariationLine:
            raise _contract_error(
                "PGN variation must be VariationLine",
                GameTreeErrorCode.INVALID_LINE,
            )
        if depth > MAX_VARIATION_DEPTH:
            raise _contract_error(
                "PGN presentation graph exceeds canonical variation depth",
                GameTreeErrorCode.GRAPH_DEPTH_LIMIT,
            )
        if line_id in active_lines:
            raise _contract_error(
                "PGN presentation graph contains a cycle",
                GameTreeErrorCode.GRAPH_CYCLE,
            )
        if line_id in claimed:
            raise _contract_error(
                "PGN presentation graph reuses a variation node",
                GameTreeErrorCode.GRAPH_REUSE,
            )
        claimed.add(line_id)
        active_lines.add(line_id)
        node_count += 1
        if node_count > MAX_TREE_NODES:
            raise _contract_error(
                "PGN presentation graph exceeds canonical node limit",
                GameTreeErrorCode.GRAPH_NODE_LIMIT,
            )

        if type(line.moves) is not list:
            raise _contract_error(
                "PGN variation moves must be a built-in list",
                GameTreeErrorCode.INVALID_CONTAINER,
            )
        _require_comment_list(line.leading_comments, field="PGN leading comments")
        _require_comment_list(line.trailing_comments, field="PGN trailing comments")
        if line.result is not None:
            _require_exact_text(line.result, field="PGN variation result")

        child_lines: list[VariationLine] = []
        for move in line.moves:
            if type(move) is not MoveNode:
                raise _contract_error(
                    "PGN variation move must be MoveNode",
                    GameTreeErrorCode.INVALID_MOVE,
                )
            move_id = id(move)
            if move_id in claimed:
                raise _contract_error(
                    "PGN presentation graph reuses a move node",
                    GameTreeErrorCode.GRAPH_REUSE,
                )
            claimed.add(move_id)
            node_count += 1
            if node_count > MAX_TREE_NODES:
                raise _contract_error(
                    "PGN presentation graph exceeds canonical node limit",
                    GameTreeErrorCode.GRAPH_NODE_LIMIT,
                )

            _require_exact_text(move.san, field="PGN SAN text")
            if move.move_number is not None:
                _require_exact_text(move.move_number, field="PGN move number")
            if type(move.nags) is not list:
                raise _contract_error(
                    "PGN NAGs must be a built-in list",
                    GameTreeErrorCode.INVALID_CONTAINER,
                )
            for nag in move.nags:
                _require_exact_text(nag, field="PGN NAG")
            _require_comment_list(move.comments_before, field="PGN comments before move")
            _require_comment_list(move.comments_after, field="PGN comments after move")
            if type(move.variations) is not list:
                raise _contract_error(
                    "PGN move variations must be a built-in list",
                    GameTreeErrorCode.INVALID_CONTAINER,
                )
            for variation in move.variations:
                if type(variation) is not VariationLine:
                    raise _contract_error(
                        "PGN move variation must be VariationLine",
                        GameTreeErrorCode.INVALID_LINE,
                    )
                child_lines.append(variation)

        stack.append(("exit", line, depth))
        for child in reversed(child_lines):
            stack.append(("enter", child, depth + 1))
