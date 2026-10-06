from __future__ import annotations

"""Concrete chess/media tools exposed to the Universal Chess Agent.

The agent does not scrape Accessible Chess UI. Every tool calls the existing
canonical Board, AnalysisService, GameSearchService or media timeline boundary.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Protocol

from .agent_tools import ToolExecutor, ToolRisk, ToolSpec
from .analysis_service import AnalysisService
from .board_service import BoardCommandService
from .chesscore import Board
from .media_foundation import MediaClock, MediaContractError, MediaPositionTimeline
from .squares import square_name
from .search_service import GameSearchQuery, GameSearchService


class MediaPlaybackPort(Protocol):
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def seek(self, position_ms: int) -> None: ...


class ChessAgentToolsError(ValueError):
    pass


def _exact_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise ChessAgentToolsError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ChessAgentToolsError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _optional_text(arguments: Mapping[str, object], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if type(value) is not str:
        raise ChessAgentToolsError(f"{name} must be text")
    value = value.strip()
    return value or None


class MediaAgentBridge:
    """Bind the media timeline to agent tools without making it chess truth."""

    def __init__(
        self,
        *,
        clock: MediaClock,
        timeline: MediaPositionTimeline,
        board_set_fen: Callable[[str], None],
        playback: MediaPlaybackPort | None = None,
    ) -> None:
        if type(clock) is not MediaClock:
            raise TypeError("clock must be MediaClock")
        if type(timeline) is not MediaPositionTimeline:
            raise TypeError("timeline must be MediaPositionTimeline")
        if not callable(board_set_fen):
            raise TypeError("board_set_fen must be callable")
        self.clock = clock
        self.timeline = timeline
        self.board_set_fen = board_set_fen
        self.playback = playback

    def status(self) -> dict[str, object]:
        state = self.clock.state
        binding = self.timeline.at(state.position_ms)
        return {
            "sessionId": state.session_id,
            "sourceId": state.source_id,
            "sourceKind": state.source_kind.value,
            "positionMs": state.position_ms,
            "durationMs": state.duration_ms,
            "playbackState": state.playback_state.value,
            "playbackRate": state.playback_rate,
            "revision": state.revision,
            "synchronizedFen": None if binding is None else binding.fen,
            "synchronizedTreePath": (
                None if binding is None else list(binding.tree_path)
            ),
            "qualification": None if binding is None else binding.state.value,
        }

    def restore(self) -> dict[str, object]:
        state = self.clock.state
        fen = self.timeline.restore_fen(state.position_ms)
        canonical = Board(fen).fen()
        self.board_set_fen(canonical)
        binding = self.timeline.at(state.position_ms)
        assert binding is not None
        return {
            "restored": True,
            "positionMs": state.position_ms,
            "fen": canonical,
            "treePath": list(binding.tree_path),
            "qualification": binding.state.value,
        }

    def play(self) -> dict[str, object]:
        if self.playback is None:
            raise MediaContractError("no playback provider is attached")
        self.playback.play()
        return {"requested": "play"}

    def pause(self) -> dict[str, object]:
        if self.playback is None:
            raise MediaContractError("no playback provider is attached")
        self.playback.pause()
        return {"requested": "pause"}

    def seek(self, position_ms: int) -> dict[str, object]:
        if self.playback is None:
            raise MediaContractError("no playback provider is attached")
        self.playback.seek(position_ms)
        return {"requested": "seek", "positionMs": position_ms}


class ChessAgentToolRegistry:
    """Register typed real-product tools on an Agent ToolExecutor."""

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        board_provider: Callable[[], Board],
        board_commands_provider: Callable[[], BoardCommandService],
        analysis_service: AnalysisService | None = None,
        search_service: GameSearchService | None = None,
        media: MediaAgentBridge | None = None,
    ) -> None:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")
        if not callable(board_provider):
            raise TypeError("board_provider must be callable")
        if not callable(board_commands_provider):
            raise TypeError("board_commands_provider must be callable")
        self.executor = executor
        self.board_provider = board_provider
        self.board_commands_provider = board_commands_provider
        self.analysis_service = analysis_service
        self.search_service = search_service
        self.media = media

    def register_all(self) -> tuple[ToolSpec, ...]:
        self._register_board()
        if self.analysis_service is not None:
            self._register_engine()
        if self.search_service is not None:
            self._register_library()
        if self.media is not None:
            self._register_media()
        return self.executor.specs()

    def _board(self) -> Board:
        board = self.board_provider()
        if type(board) is not Board:
            raise TypeError(
                "board_provider must return canonical chesscore.Board"
            )
        return board

    def _board_commands(self) -> BoardCommandService:
        service = self.board_commands_provider()
        if type(service) is not BoardCommandService:
            raise TypeError(
                "board_commands_provider must return BoardCommandService"
            )
        return service

    def _register_board(self) -> None:
        async def current(_arguments: Mapping[str, object]) -> object:
            board = self._board()
            service = self._board_commands()
            last_move = service.last_move()
            return {
                "fen": board.fen(),
                "turn": service.board.turn,
                "inCheck": board.in_check(),
                "legalMoveCount": len(service.board.legal_moves),
                "lastMove": (
                    None
                    if last_move is None
                    else {
                        "from": last_move.frm,
                        "to": last_move.to,
                        "san": last_move.san,
                        "capture": last_move.is_capture,
                    }
                ),
            }

        async def square(arguments: Mapping[str, object]) -> object:
            raw = arguments.get("square")
            if type(raw) is not str:
                raise ChessAgentToolsError(
                    "square must be algebraic text"
                )
            name = raw.strip().lower()
            service = self._board_commands()
            view = service.current(name)
            return {
                "square": view.square,
                "piece": view.piece,
                "attackers": [
                    {"square": item.square, "piece": item.piece}
                    for item in service.attackers(name)
                ],
                "defenders": [
                    {"square": item.square, "piece": item.piece}
                    for item in service.defenders(name)
                ],
            }

        async def legal_moves(
            _arguments: Mapping[str, object],
        ) -> object:
            service = self._board_commands()
            moves = service.board.legal_moves
            labels = [
                move.san or f"{square_name(move.frm)}-{square_name(move.to)}"
                for move in moves
            ]
            return {
                "moves": labels,
                "count": len(moves),
            }

        async def material(
            _arguments: Mapping[str, object],
        ) -> object:
            view = self._board_commands().material()
            return {
                "white": dict(view.white),
                "black": dict(view.black),
                "whitePoints": view.white_points,
                "blackPoints": view.black_points,
                "balance": view.balance,
            }

        self.executor.register(
            ToolSpec(
                "board.current",
                "Read the current canonical board position.",
            ),
            current,
        )
        self.executor.register(
            ToolSpec(
                "board.square",
                "Describe one square using canonical board-command data.",
                input_schema={"square": "a1-h8"},
            ),
            square,
        )
        self.executor.register(
            ToolSpec(
                "board.legal_moves",
                "List canonical legal SAN moves from the current position.",
            ),
            legal_moves,
        )
        self.executor.register(
            ToolSpec(
                "board.material",
                "Read the canonical material summary.",
            ),
            material,
        )

    def _register_engine(self) -> None:
        service = self.analysis_service
        assert service is not None

        async def analyze(arguments: Mapping[str, object]) -> object:
            board = self._board()
            multipv = _exact_int(
                arguments.get("multipv", 3),
                name="multipv",
                minimum=1,
                maximum=10,
            )
            depth = _exact_int(
                arguments.get("depth", 16),
                name="depth",
                minimum=1,
                maximum=40,
            )
            result = await asyncio.to_thread(
                service.analyze,
                board.fen(),
                multipv,
                depth,
            )
            return result.as_dict()

        self.executor.register(
            ToolSpec(
                "engine.analyze",
                "Analyze the current canonical position with the configured engine.",
                timeout_seconds=120.0,
                input_schema={"multipv": "1-10", "depth": "1-40"},
            ),
            analyze,
        )

    def _register_library(self) -> None:
        service = self.search_service
        assert service is not None

        async def search(arguments: Mapping[str, object]) -> object:
            limit = _exact_int(
                arguments.get("limit", 20),
                name="limit",
                minimum=1,
                maximum=200,
            )
            query = GameSearchQuery(
                player=_optional_text(arguments, "player"),
                event=_optional_text(arguments, "event"),
                eco=_optional_text(arguments, "eco"),
                opening=_optional_text(arguments, "opening"),
                game_date=_optional_text(arguments, "game_date"),
                date_from=_optional_text(arguments, "date_from"),
                date_to=_optional_text(arguments, "date_to"),
                result=_optional_text(arguments, "result"),
                source_name=_optional_text(arguments, "source_name"),
                limit=limit,
            )
            # The injected service owns a thread-affine SQLite connection.
            # The host must create/run this registry on that service's owning
            # worker loop; moving only the query to another thread is invalid.
            page = service.search(query)
            return {
                "items": [asdict(item) for item in page.items],
                "hasMore": page.has_more,
                "nextAfterGameId": page.next_after_game_id,
            }

        self.executor.register(
            ToolSpec(
                "library.search",
                "Search canonical ACSDB/Library game metadata.",
                timeout_seconds=30.0,
                input_schema={
                    "player": "optional text",
                    "event": "optional text",
                    "eco": "optional text",
                    "opening": "optional text",
                    "game_date": "optional source date",
                    "date_from": "optional YYYY.MM.DD",
                    "date_to": "optional YYYY.MM.DD",
                    "result": "optional game result",
                    "source_name": "optional text",
                    "limit": "1-200",
                },
            ),
            search,
        )

    def _register_media(self) -> None:
        media = self.media
        assert media is not None

        async def status(_arguments: Mapping[str, object]) -> object:
            return media.status()

        async def restore(_arguments: Mapping[str, object]) -> object:
            return media.restore()

        async def play(_arguments: Mapping[str, object]) -> object:
            return media.play()

        async def pause(_arguments: Mapping[str, object]) -> object:
            return media.pause()

        async def seek(arguments: Mapping[str, object]) -> object:
            position = _exact_int(
                arguments.get("position_ms"),
                name="position_ms",
                minimum=0,
                maximum=24 * 60 * 60 * 1000,
            )
            return media.seek(position)

        self.executor.register(
            ToolSpec(
                "media.status",
                "Read media playback and synchronized-board state.",
            ),
            status,
        )
        self.executor.register(
            ToolSpec(
                "media.restore_position",
                "Restore the board to the current media timeline position.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            restore,
        )
        self.executor.register(
            ToolSpec(
                "media.play",
                "Request playback from the attached media provider.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            play,
        )
        self.executor.register(
            ToolSpec(
                "media.pause",
                "Pause the attached media provider.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            pause,
        )
        self.executor.register(
            ToolSpec(
                "media.seek",
                "Seek the attached media provider to an exact timestamp.",
                risk=ToolRisk.LOCAL_WRITE,
                input_schema={
                    "position_ms": "non-negative integer milliseconds"
                },
            ),
            seek,
        )
