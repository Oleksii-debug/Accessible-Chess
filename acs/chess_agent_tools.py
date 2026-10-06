from __future__ import annotations

"""Concrete chess/media tools exposed to the Universal Chess Agent.

The agent does not scrape Accessible Chess UI. Every tool calls the existing
canonical Board, AnalysisService, GameSearchService or Media application boundary.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Protocol

from .agent_tools import ToolExecutor, ToolRisk, ToolSpec
from .analysis_service import AnalysisService
from .board_service import BoardCommandService
from .chesscore import Board
from .media_application import MediaApplicationService
from .media_foundation import MediaClock, MediaContractError
from .squares import square_name
from .search_service import GameSearchQuery, GameSearchService


class MediaPlaybackPort(Protocol):
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def seek(self, position_ms: int) -> None: ...
    def set_rate(self, playback_rate: float) -> None: ...


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


def _bounded_float(
    value: object,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if type(value) not in (int, float):
        raise ChessAgentToolsError(f"{name} must be an exact numeric value")
    candidate = float(value)
    if (
        candidate != candidate
        or candidate in (float("inf"), float("-inf"))
        or not minimum <= candidate <= maximum
    ):
        raise ChessAgentToolsError(
            f"{name} must be finite and between {minimum:g} and {maximum:g}"
        )
    return candidate


def _require_argument_keys(
    arguments: Mapping[str, object],
    *,
    tool_id: str,
    expected: frozenset[str],
) -> None:
    actual = frozenset(arguments)
    if actual != expected:
        raise ChessAgentToolsError(
            f"{tool_id} requires exactly {sorted(expected)!r} arguments"
        )


def _optional_text(arguments: Mapping[str, object], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if type(value) is not str:
        raise ChessAgentToolsError(f"{name} must be text")
    value = value.strip()
    return value or None


class MediaAgentBridge:
    """Expose canonical Media application behavior to Agent tools.

    The Agent does not resolve media timelines, parse FEN, reconstruct GameTree
    paths, or call a chess mutation callback directly. Provider time comes from
    MediaClock; all synchronization, navigation and Restore Media Position
    semantics are owned by MediaApplicationService.
    """

    def __init__(
        self,
        *,
        clock: MediaClock,
        application: MediaApplicationService,
        playback: MediaPlaybackPort | None = None,
    ) -> None:
        if type(clock) is not MediaClock:
            raise TypeError("clock must be MediaClock")
        if type(application) is not MediaApplicationService:
            raise TypeError("application must be MediaApplicationService")
        clock_state = clock.state
        if application.source.source_id != clock_state.source_id:
            raise ChessAgentToolsError(
                "media clock and Media application source IDs differ"
            )
        application_duration = application.source.duration_ms
        if (
            application_duration is not None
            and clock_state.duration_ms is not None
            and application_duration != clock_state.duration_ms
        ):
            raise ChessAgentToolsError(
                "media clock and Media application durations differ"
            )
        self.clock = clock
        self.application = application
        self.playback = playback

    def status(self) -> dict[str, object]:
        state = self.clock.state
        snapshot = self.application.snapshot_at(state.position_ms)
        return {
            "sessionId": state.session_id,
            "sourceId": state.source_id,
            "sourceKind": state.source_kind.value,
            "positionMs": state.position_ms,
            "durationMs": state.duration_ms,
            "playbackState": state.playback_state.value,
            "playbackRate": state.playback_rate,
            "revision": state.revision,
            "applicationRevision": snapshot.revision,
            "analysisChessRef": snapshot.analysis_chess_ref,
            "synchronizedChessRef": snapshot.synchronized_chess_ref,
            "synchronizedAnchorMs": snapshot.anchor_timestamp_ms,
            "synchronizationAmbiguous": snapshot.qualification == "ambiguous",
            "canRestore": snapshot.can_restore,
            "qualification": snapshot.qualification,
            "statusText": snapshot.status_text,
        }

    def current_position(self) -> dict[str, object]:
        state = self.clock.state
        snapshot = self.application.snapshot_at(state.position_ms)
        return {
            "positionMs": state.position_ms,
            "anchorPositionMs": snapshot.anchor_timestamp_ms,
            "chessRef": snapshot.synchronized_chess_ref,
            "qualification": snapshot.qualification,
            "canRestore": snapshot.can_restore,
            "applicationRevision": snapshot.revision,
            "accessibleText": snapshot.status_text,
        }

    def restore(self) -> dict[str, object]:
        state = self.clock.state
        result = self.application.restore_media_position(state.position_ms)
        return {
            "restored": True,
            "positionMs": result.position_ms,
            "anchorPositionMs": result.anchor_timestamp_ms,
            "chessRef": result.chess_ref,
            "changed": result.changed,
            "applicationRevision": result.revision,
            "accessibleText": result.accessible_text,
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
        snapshot = self.application.snapshot_at(position_ms)
        self.playback.seek(position_ms)
        return {
            "requested": "seek",
            "positionMs": position_ms,
            "anchorPositionMs": snapshot.anchor_timestamp_ms,
            "chessRef": snapshot.synchronized_chess_ref,
            "qualification": snapshot.qualification,
            "canRestore": snapshot.can_restore,
            "applicationRevision": snapshot.revision,
            "accessibleText": snapshot.status_text,
        }

    def set_rate(self, playback_rate: object) -> dict[str, object]:
        if self.playback is None:
            raise MediaContractError("no playback provider is attached")
        rate = _bounded_float(
            playback_rate,
            name="playback_rate",
            minimum=0.1,
            maximum=8.0,
        )
        self.playback.set_rate(rate)
        return {
            "requested": "set_rate",
            "playbackRate": rate,
            "accessibleText": f"Requested media playback rate {rate:g}x.",
        }

    def next_move(self) -> dict[str, object]:
        if self.playback is None:
            raise MediaContractError("no playback provider is attached")
        state = self.clock.state
        target = self.application.next_media_position(state.position_ms)
        self.playback.seek(target.target_position_ms)
        return {
            "requested": "seek",
            "direction": target.direction,
            "fromPositionMs": target.from_position_ms,
            "positionMs": target.target_position_ms,
            "chessRef": target.chess_ref,
            "applicationRevision": target.revision,
            "accessibleText": target.accessible_text,
        }

    def previous_move(self) -> dict[str, object]:
        if self.playback is None:
            raise MediaContractError("no playback provider is attached")
        state = self.clock.state
        target = self.application.previous_media_position(state.position_ms)
        self.playback.seek(target.target_position_ms)
        return {
            "requested": "seek",
            "direction": target.direction,
            "fromPositionMs": target.from_position_ms,
            "positionMs": target.target_position_ms,
            "chessRef": target.chess_ref,
            "applicationRevision": target.revision,
            "accessibleText": target.accessible_text,
        }


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
            # GameSearchService owns a thread-affine ACSDB connection. The host
            # must create and execute this registry on the service owner thread;
            # moving only the query to a worker thread violates that contract.
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

        async def status(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments, tool_id="media.status", expected=frozenset()
            )
            return media.status()

        async def current_position(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments,
                tool_id="media.current_position",
                expected=frozenset(),
            )
            return media.current_position()

        async def restore(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments,
                tool_id="media.restore_position",
                expected=frozenset(),
            )
            return media.restore()

        async def play(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments, tool_id="media.play", expected=frozenset()
            )
            return media.play()

        async def pause(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments, tool_id="media.pause", expected=frozenset()
            )
            return media.pause()

        async def seek(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments,
                tool_id="media.seek",
                expected=frozenset({"position_ms"}),
            )
            position = _exact_int(
                arguments.get("position_ms"),
                name="position_ms",
                minimum=0,
                maximum=24 * 60 * 60 * 1000,
            )
            return media.seek(position)

        async def set_rate(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments,
                tool_id="media.set_rate",
                expected=frozenset({"playback_rate"}),
            )
            return media.set_rate(arguments.get("playback_rate"))

        async def next_move(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments, tool_id="media.next_move", expected=frozenset()
            )
            return media.next_move()

        async def previous_move(arguments: Mapping[str, object]) -> object:
            _require_argument_keys(
                arguments,
                tool_id="media.previous_move",
                expected=frozenset(),
            )
            return media.previous_move()

        self.executor.register(
            ToolSpec(
                "media.status",
                "Read media playback and canonical synchronization-reference state.",
            ),
            status,
        )
        self.executor.register(
            ToolSpec(
                "media.current_position",
                "Read the canonical synchronization reference at current provider time.",
            ),
            current_position,
        )
        self.executor.register(
            ToolSpec(
                "media.restore_position",
                "Restore canonical application chess state from the current media reference.",
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
                "Seek the attached media provider to an exact application-validated timestamp.",
                risk=ToolRisk.LOCAL_WRITE,
                input_schema={
                    "position_ms": "non-negative integer milliseconds"
                },
            ),
            seek,
        )
        self.executor.register(
            ToolSpec(
                "media.set_rate",
                "Request a bounded playback-rate change from the attached media provider.",
                risk=ToolRisk.LOCAL_WRITE,
                input_schema={"playback_rate": "number from 0.1 through 8.0"},
            ),
            set_rate,
        )
        self.executor.register(
            ToolSpec(
                "media.next_move",
                "Seek to the nearest later timeline anchor when it is confirmed.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            next_move,
        )
        self.executor.register(
            ToolSpec(
                "media.previous_move",
                "Seek to the nearest earlier timeline anchor when it is confirmed.",
                risk=ToolRisk.LOCAL_WRITE,
            ),
            previous_move,
        )
