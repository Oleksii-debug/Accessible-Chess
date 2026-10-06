from __future__ import annotations

"""Universal Agent adapter for the canonical Library -> PGN open command.

The Agent supplies only provenance returned by Library search. This module never
queries ACSDB, parses PGN, constructs a GameTree, or changes document state on
its own. The host callback must be the existing application command boundary,
which remains responsible for stale-row checks, dirty-document confirmation,
route changes, and detached-session creation.
"""

from collections.abc import Callable, Mapping

from .agent_tools import ToolExecutor, ToolRisk, ToolSpec


_SQLITE_INTEGER_MAX = (1 << 63) - 1
_REQUIRED_FIELDS = frozenset({"game_id", "source_id", "source_index"})


class AgentLibraryOpenError(ValueError):
    pass


def _exact_integer(
    value: object,
    *,
    name: str,
    minimum: int,
) -> int:
    if type(value) is not int:
        raise AgentLibraryOpenError(f"{name} must be an integer")
    if value < minimum or value > _SQLITE_INTEGER_MAX:
        raise AgentLibraryOpenError(
            f"{name} must be between {minimum} and {_SQLITE_INTEGER_MAX}"
        )
    return value


def register_library_open_game_tool(
    executor: ToolExecutor,
    open_game_command: Callable[[Mapping[str, int]], object],
) -> ToolSpec:
    """Register one stale-safe Library open intent on the existing executor."""

    if type(executor) is not ToolExecutor:
        raise TypeError("executor must be ToolExecutor")
    if not callable(open_game_command):
        raise TypeError("open_game_command must be callable")

    async def open_game(arguments: Mapping[str, object]) -> object:
        for key in arguments:
            if type(key) is not str:
                raise AgentLibraryOpenError("tool argument keys must be text")
        if frozenset(arguments) != _REQUIRED_FIELDS:
            raise AgentLibraryOpenError(
                "library.open_game requires exactly game_id, source_id, source_index"
            )
        payload = {
            "game_id": _exact_integer(
                arguments["game_id"], name="game_id", minimum=1
            ),
            "source_id": _exact_integer(
                arguments["source_id"], name="source_id", minimum=1
            ),
            "source_index": _exact_integer(
                arguments["source_index"], name="source_index", minimum=0
            ),
        }

        # Intentionally synchronous. Version2Application is native-UI-thread
        # affine; moving this command to a worker would violate its authority.
        open_game_command(payload)
        return {
            "opened": True,
            "gameId": payload["game_id"],
            "sourceId": payload["source_id"],
            "sourceIndex": payload["source_index"],
        }

    spec = ToolSpec(
        "library.open_game",
        "Open one canonical Library search result using its exact provenance triplet.",
        risk=ToolRisk.LOCAL_WRITE,
        input_schema={
            "game_id": "positive SQLite integer",
            "source_id": "positive SQLite integer",
            "source_index": "non-negative SQLite integer",
        },
    )
    executor.register(spec, open_game)
    return spec
