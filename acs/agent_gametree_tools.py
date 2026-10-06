from __future__ import annotations

"""Universal Agent adapters over the canonical PGN/GameTree workspace.

This adapter owns no PGN parser, GameTree, legality, or chess rules. It exposes
only the bounded session navigation already owned by PgnWorkspace and
gametree_navigation. Navigation changes cursor/game selection and never edits
the PGN document.
"""

from collections.abc import Callable, Mapping

from .agent_tools import ToolExecutor, ToolRisk, ToolSpec
from .gametree import MAX_TREE_NODES, MoveNode
from .gametree_navigation import GameTreeCursor, resolve_line
from .pgn_workspace import PgnWorkspace


class AgentGameTreeError(ValueError):
    pass


def _exact_index(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise AgentGameTreeError(f"{name} must be an integer")
    if value < 0 or value >= MAX_TREE_NODES:
        raise AgentGameTreeError(
            f"{name} must be between 0 and {MAX_TREE_NODES - 1}"
        )
    return value



def _require_fields(
    arguments: Mapping[str, object],
    allowed: frozenset[str],
) -> None:
    for key in arguments:
        if type(key) is not str:
            raise AgentGameTreeError("tool argument keys must be text")
        if key not in allowed:
            raise AgentGameTreeError(f"unknown tool argument: {key}")


def _move_payload(move: MoveNode | None) -> dict[str, object] | None:
    if move is None:
        return None
    if type(move) is not MoveNode:
        raise TypeError("canonical workspace returned a non-MoveNode value")
    return {
        "san": move.san,
        "moveNumber": move.move_number,
        "nags": list(move.nags),
        "variationCount": len(move.variations),
    }


def _cursor_payload(cursor: GameTreeCursor) -> dict[str, object]:
    if type(cursor) is not GameTreeCursor:
        raise TypeError("canonical workspace returned a non-GameTreeCursor value")
    return {
        "linePath": [
            {
                "parentMoveIndex": step.parent_move_index,
                "variationIndex": step.variation_index,
            }
            for step in cursor.line_path
        ],
        "nextMoveIndex": cursor.next_move_index,
    }


def _workspace_payload(workspace: PgnWorkspace) -> dict[str, object]:
    if type(workspace) is not PgnWorkspace:
        raise TypeError("workspace_provider must return PgnWorkspace")

    view = workspace.view()
    game = workspace.current_game()
    line = resolve_line(game, view.cursor.line_path)
    index = view.cursor.next_move_index
    current = line.moves[index] if index < len(line.moves) else None
    previous = line.moves[index - 1] if index > 0 else None

    available_variations = len(previous.variations) if previous is not None else 0
    sibling_count = 0
    active_variation_index: int | None = None
    if view.cursor.line_path:
        step = view.cursor.line_path[-1]
        parent = resolve_line(game, view.cursor.line_path[:-1])
        owner = parent.moves[step.parent_move_index]
        sibling_count = len(owner.variations)
        active_variation_index = step.variation_index

    summary = workspace.summaries()[view.selected_game_index]
    return {
        "gameCount": view.game_count,
        "selectedGameIndex": view.selected_game_index,
        "game": {
            "sourceIndex": summary.source_index,
            "event": summary.event,
            "white": summary.white,
            "black": summary.black,
            "result": summary.result,
        },
        "cursor": _cursor_payload(view.cursor),
        "lineLength": len(line.moves),
        "atLineStart": index == 0,
        "atLineEnd": index == len(line.moves),
        "currentMove": _move_payload(current),
        "previousMove": _move_payload(previous),
        "availableVariations": available_variations,
        "insideVariation": bool(view.cursor.line_path),
        "activeVariationIndex": active_variation_index,
        "siblingVariationCount": sibling_count,
        "contentRevision": view.content_revision,
        "dirty": view.dirty,
        "currentRecordDigest": view.current_record_digest,
    }


def register_gametree_tools(
    executor: ToolExecutor,
    workspace_provider: Callable[[], PgnWorkspace],
) -> tuple[ToolSpec, ...]:
    """Register typed GameTree navigation on the existing Agent executor."""

    if type(executor) is not ToolExecutor:
        raise TypeError("executor must be ToolExecutor")
    if not callable(workspace_provider):
        raise TypeError("workspace_provider must be callable")

    def workspace() -> PgnWorkspace:
        value = workspace_provider()
        if type(value) is not PgnWorkspace:
            raise TypeError("workspace_provider must return PgnWorkspace")
        return value

    async def current(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset())
        return _workspace_payload(workspace())

    async def next_move(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset())
        value = workspace()
        value.next_move()
        return _workspace_payload(value)

    async def previous_move(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset())
        value = workspace()
        value.previous_move()
        return _workspace_payload(value)

    async def enter_variation(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset({"variation_index"}))
        value = workspace()
        variation_index = _exact_index(
            arguments.get("variation_index", 0),
            name="variation_index",
        )
        value.enter_variation(variation_index)
        return _workspace_payload(value)

    async def leave_variation(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset())
        value = workspace()
        value.leave_variation()
        return _workspace_payload(value)

    async def sibling_variation(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset({"direction"}))
        direction = arguments.get("direction")
        if direction not in {"previous", "next"}:
            raise AgentGameTreeError(
                "direction must be exactly 'previous' or 'next'"
            )
        value = workspace()
        value.sibling_variation(-1 if direction == "previous" else 1)
        return _workspace_payload(value)

    async def select_game(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset({"index"}))
        value = workspace()
        index = _exact_index(arguments.get("index"), name="index")
        value.select_game(index)
        return _workspace_payload(value)

    async def next_game(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset())
        value = workspace()
        value.next_game()
        return _workspace_payload(value)

    async def previous_game(arguments: Mapping[str, object]) -> object:
        _require_fields(arguments, frozenset())
        value = workspace()
        value.previous_game()
        return _workspace_payload(value)

    registrations = (
        (
            ToolSpec(
                "gametree.current",
                "Read canonical PGN workspace cursor and branch state.",
            ),
            current,
        ),
        (
            ToolSpec(
                "gametree.next_move",
                "Advance one move in the current canonical GameTree line.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            next_move,
        ),
        (
            ToolSpec(
                "gametree.previous_move",
                "Move one step backward in the current canonical GameTree line.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            previous_move,
        ),
        (
            ToolSpec(
                "gametree.enter_variation",
                "Enter an existing variation owned by the preceding move.",
                risk=ToolRisk.LOCAL_WRITE,
                input_schema={"variation_index": f"0-{MAX_TREE_NODES - 1}"},
            ),
            enter_variation,
        ),
        (
            ToolSpec(
                "gametree.leave_variation",
                "Leave the current variation and resume after its owner move.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            leave_variation,
        ),
        (
            ToolSpec(
                "gametree.sibling_variation",
                "Move to the previous or next sibling variation.",
                risk=ToolRisk.LOCAL_WRITE,
                input_schema={"direction": "previous|next"},
            ),
            sibling_variation,
        ),
        (
            ToolSpec(
                "gametree.select_game",
                "Select a game in the current canonical multi-game PGN workspace.",
                risk=ToolRisk.LOCAL_WRITE,
                input_schema={"index": f"0-{MAX_TREE_NODES - 1}"},
            ),
            select_game,
        ),
        (
            ToolSpec(
                "gametree.next_game",
                "Select the next game in the canonical PGN workspace.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            next_game,
        ),
        (
            ToolSpec(
                "gametree.previous_game",
                "Select the previous game in the canonical PGN workspace.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            previous_game,
        ),
    )
    for spec, handler in registrations:
        executor.register(spec, handler)
    return tuple(spec for spec, _handler in registrations)
