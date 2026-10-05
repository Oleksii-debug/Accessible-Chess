from __future__ import annotations

"""Concrete Accessible Chess tool composition for the Universal Chess Agent.

The handlers reuse existing presentation-neutral BoardCommandService rather than
creating duplicate chess logic. Media tools delegate to MediaApplicationService.
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict

from .agent_tools import (
    ChessToolCall,
    ChessToolExecutor,
    ChessToolResult,
    ChessToolRisk,
    ChessToolSpec,
)
from .analysis_service import AnalysisService
from .board_service import BoardCommandService
from .media_application import MediaApplicationService
from .search_service import GameSearchQuery, GameSearchService


BoardServiceProvider = Callable[[], BoardCommandService]
FenProvider = Callable[[], str]
AnalysisServiceProvider = Callable[[], AnalysisService]
SearchServiceProvider = Callable[[], GameSearchService]


def _required_text(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text")
    return value.strip()


class UniversalChessAgentTools:
    """Registers real Accessible Chess application tools on one executor."""

    def __init__(
        self,
        board_service: BoardServiceProvider,
        *,
        media_service: MediaApplicationService | None = None,
        analysis_service: AnalysisServiceProvider | None = None,
        fen_provider: FenProvider | None = None,
        search_service: SearchServiceProvider | None = None,
        executor: ChessToolExecutor | None = None,
    ) -> None:
        if not callable(board_service):
            raise TypeError("board_service must be callable")
        if media_service is not None and not isinstance(media_service, MediaApplicationService):
            raise TypeError("media_service must be MediaApplicationService or None")
        if analysis_service is not None and not callable(analysis_service):
            raise TypeError("analysis_service must be callable or None")
        if (analysis_service is None) != (fen_provider is None):
            raise ValueError("analysis_service and fen_provider must be supplied together")
        if fen_provider is not None and not callable(fen_provider):
            raise TypeError("fen_provider must be callable or None")
        if search_service is not None and not callable(search_service):
            raise TypeError("search_service must be callable or None")
        self._board_service = board_service
        self._media_service = media_service
        self._analysis_service = analysis_service
        self._fen_provider = fen_provider
        self._search_service = search_service
        self.executor = executor or ChessToolExecutor()
        self._register()

    def _board(self) -> BoardCommandService:
        service = self._board_service()
        if not isinstance(service, BoardCommandService):
            raise TypeError("board service provider returned an invalid value")
        return service

    def _register(self) -> None:
        self.executor.register(
            ChessToolSpec(
                "board.square",
                "Read the canonical piece currently on one square.",
                input_schema={"square": "canonical algebraic square"},
            ),
            self._board_square,
        )
        self.executor.register(
            ChessToolSpec(
                "board.material",
                "Read canonical material counts and balance.",
            ),
            self._board_material,
        )
        self.executor.register(
            ChessToolSpec(
                "board.legal_moves",
                "Read canonical legal moves for the piece on one square.",
                input_schema={"square": "canonical algebraic square"},
            ),
            self._board_legal_moves,
        )
        if self._analysis_service is not None:
            self.executor.register(
                ChessToolSpec(
                    "engine.analyze",
                    "Analyze the current canonical FEN through the existing AnalysisService.",
                    input_schema={
                        "multipv": "optional integer 1..10",
                        "depth": "optional integer 1..40",
                    },
                ),
                self._engine_analyze,
            )
        if self._search_service is not None:
            self.executor.register(
                ChessToolSpec(
                    "library.search_games",
                    "Search the canonical ACSDB Library through GameSearchService.",
                    input_schema={
                        "player": "optional text",
                        "event": "optional text",
                        "eco": "optional text",
                        "opening": "optional text",
                        "result": "optional canonical result",
                        "source_name": "optional text",
                        "limit": "optional integer",
                    },
                ),
                self._library_search_games,
            )
        if self._media_service is not None:
            self.executor.register(
                ChessToolSpec(
                    "media.status",
                    "Read current synchronized media state.",
                ),
                self._media_status,
            )
            self.executor.register(
                ChessToolSpec(
                    "media.restore_position",
                    "Restore the canonical board to the current media position.",
                    risk=ChessToolRisk.LOCAL_WRITE,
                ),
                self._media_restore,
            )
            self.executor.register(
                ChessToolSpec(
                    "media.seek",
                    "Seek the media synchronization cursor to a timestamp.",
                    risk=ChessToolRisk.LOCAL_WRITE,
                    input_schema={"timestamp_ms": "non-negative integer"},
                ),
                self._media_seek,
            )

    async def execute(self, call: ChessToolCall) -> ChessToolResult:
        return await self.executor.execute(call)

    async def _board_square(self, arguments: Mapping[str, object]) -> object:
        square = _required_text(arguments, "square")
        view = self._board().current(square)
        return {"square": view.square, "piece": view.piece}

    async def _board_material(self, arguments: Mapping[str, object]) -> object:
        if arguments:
            raise ValueError("board.material accepts no arguments")
        view = self._board().material()
        return {
            "white": dict(view.white),
            "black": dict(view.black),
            "white_points": view.white_points,
            "black_points": view.black_points,
            "balance": view.balance,
        }

    async def _board_legal_moves(self, arguments: Mapping[str, object]) -> object:
        square = _required_text(arguments, "square")
        moves = self._board().legal_moves(square)
        return {
            "square": square,
            "moves": [
                {
                    "from": move.frm,
                    "to": move.to,
                    "san": move.san,
                    "is_capture": move.is_capture,
                }
                for move in moves
            ],
        }

    async def _engine_analyze(self, arguments: Mapping[str, object]) -> object:
        assert self._analysis_service is not None
        assert self._fen_provider is not None
        service = self._analysis_service()
        if not isinstance(service, AnalysisService):
            raise TypeError("analysis service provider returned an invalid value")
        fen = self._fen_provider()
        if not isinstance(fen, str) or not fen.strip():
            raise ValueError("fen provider returned invalid text")
        multipv = arguments.get("multipv", 5)
        depth = arguments.get("depth", 16)
        if type(multipv) is not int or type(depth) is not int:
            raise ValueError("multipv and depth must be integers")
        unknown = set(arguments) - {"multipv", "depth"}
        if unknown:
            raise ValueError("engine.analyze received unsupported arguments")
        result = service.analyze(fen, multipv=multipv, depth=depth)
        return result.as_dict()

    async def _library_search_games(self, arguments: Mapping[str, object]) -> object:
        assert self._search_service is not None
        service = self._search_service()
        if not isinstance(service, GameSearchService):
            raise TypeError("search service provider returned an invalid value")
        allowed = {
            "player",
            "event",
            "eco",
            "opening",
            "result",
            "source_name",
            "limit",
            "after_game_id",
        }
        unknown = set(arguments) - allowed
        if unknown:
            raise ValueError("library.search_games received unsupported arguments")
        query = GameSearchQuery(
            player=arguments.get("player"),
            event=arguments.get("event"),
            eco=arguments.get("eco"),
            opening=arguments.get("opening"),
            result=arguments.get("result"),
            source_name=arguments.get("source_name"),
            limit=arguments.get("limit", 20),
            after_game_id=arguments.get("after_game_id"),
        )
        page = service.search(query)
        return {
            "items": [asdict(item) for item in page.items],
            "next_after_game_id": page.next_after_game_id,
            "has_more": page.has_more,
        }

    async def _media_status(self, arguments: Mapping[str, object]) -> object:
        if arguments:
            raise ValueError("media.status accepts no arguments")
        assert self._media_service is not None
        return self._media_service.status()

    async def _media_restore(self, arguments: Mapping[str, object]) -> object:
        if arguments:
            raise ValueError("media.restore_position accepts no arguments")
        assert self._media_service is not None
        entry = await self._media_service.restore_media_position()
        return {
            "position_id": entry.position_id,
            "gametree_node_id": entry.gametree_node_id,
            "start_ms": entry.start_ms,
        }

    async def _media_seek(self, arguments: Mapping[str, object]) -> object:
        value = arguments.get("timestamp_ms")
        if type(value) is not int or value < 0:
            raise ValueError("timestamp_ms must be a non-negative integer")
        assert self._media_service is not None
        entry = await self._media_service.seek(value)
        return {
            "timestamp_ms": value,
            "position_id": None if entry is None else entry.position_id,
            "gametree_node_id": None if entry is None else entry.gametree_node_id,
        }


__all__ = [
    "AnalysisServiceProvider",
    "BoardServiceProvider",
    "FenProvider",
    "SearchServiceProvider",
    "UniversalChessAgentTools",
]
