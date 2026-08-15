from __future__ import annotations

"""Presentation-neutral orchestration for a local game against an engine.

The coordinator owns scheduling/state transitions only. It never owns a Board,
ReviewHistory, UI object, filesystem path, engine process, or persistence model.
Those remain behind injected callbacks/services so one canonical source of truth
is preserved for chess state and history.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .clock_service import ChessClock, ClockSnapshot
from .engine_play_service import (
    EngineGameConfig,
    EngineGameHandoff,
    EngineGameIntent,
    EnginePlayService,
    ResolvedEngineGameConfig,
    dispatch_lifecycle_handoff,
    resolve_engine_game_config,
)
from .engine_ports import EngineMoveRequest, EngineMoveResult
from .game_lifecycle import EndReason, GameLifecycle, GameStatus, LifecycleSnapshot


class EngineTurnState(str, Enum):
    IDLE = "idle"
    HUMAN = "human"
    ENGINE = "engine"
    FINISHED = "finished"


@dataclass(frozen=True)
class EngineGameSessionSnapshot:
    config: ResolvedEngineGameConfig
    side_to_move: str
    turn_state: EngineTurnState
    lifecycle: LifecycleSnapshot
    clock: ClockSnapshot


class EngineGameSessionCoordinator:
    """Coordinate engine-game flow without taking ownership of board/history."""

    def __init__(
        self,
        play_service: EnginePlayService,
        *,
        fen_provider: Callable[[], str],
        side_to_move_provider: Callable[[], str],
        commit_engine_move: Callable[[str], None],
        history_node_provider: Callable[[], str],
        undo_committed_move: Callable[[], None] | None = None,
        analysis_handoff: Callable[[EngineGameHandoff], None] | None = None,
        review_handoff: Callable[[EngineGameHandoff], None] | None = None,
        lifecycle: GameLifecycle | None = None,
        clock_factory: Callable[[object], ChessClock] | None = None,
    ) -> None:
        self._play_service = play_service
        self._fen_provider = fen_provider
        self._side_provider = side_to_move_provider
        self._commit_engine_move = commit_engine_move
        self._history_node_provider = history_node_provider
        self._undo_committed_move = undo_committed_move
        self._analysis_handoff = analysis_handoff
        self._review_handoff = review_handoff
        self._lifecycle = lifecycle or GameLifecycle()
        self._clock_factory = clock_factory or (lambda control: ChessClock(control))
        self._config: ResolvedEngineGameConfig | None = None
        self._clock: ChessClock | None = None

    def start(self, config: EngineGameConfig, *, random_choice=None) -> EngineGameSessionSnapshot:
        self._config = resolve_engine_game_config(config, random_choice=random_choice)
        self._lifecycle.reset_for_new_game()
        self._clock = self._clock_factory(self._config.time_control)
        side = self._side_to_move()
        self._clock.start(side)
        return self.snapshot()

    def reset(self) -> EngineGameSessionSnapshot:
        self._require_started()
        assert self._clock is not None
        self._lifecycle.reset_for_new_game()
        self._clock.reset(side_to_move=self._side_to_move())
        if not self._config.time_control.untimed:
            self._clock.resume()
        return self.snapshot()

    def snapshot(self) -> EngineGameSessionSnapshot:
        self._require_started()
        assert self._config is not None and self._clock is not None
        lifecycle = self._lifecycle.snapshot()
        side = self._side_to_move()
        if lifecycle.status is GameStatus.FINISHED:
            turn_state = EngineTurnState.FINISHED
        elif side == self._config.engine_side:
            turn_state = EngineTurnState.ENGINE
        else:
            turn_state = EngineTurnState.HUMAN
        return EngineGameSessionSnapshot(self._config, side, turn_state, lifecycle, self._clock.snapshot())

    def request_engine_move(self) -> EngineMoveResult:
        snap = self.snapshot()
        if snap.turn_state is not EngineTurnState.ENGINE:
            raise ValueError("engine move requested when it is not the engine turn")
        fen = str(self._fen_provider()).strip()
        if not fen:
            raise ValueError("fen provider returned empty position")
        result = self._play_service.choose_move(EngineMoveRequest(fen, level=snap.config.level.level))
        if result.move is None:
            return result
        moved_side = snap.side_to_move
        self._commit_engine_move(result.move)
        self._lifecycle.on_move_committed()
        assert self._clock is not None
        self._clock.switch_after_move(moved_side)
        return result

    def on_human_move_committed(self, moved_side: str) -> EngineGameSessionSnapshot:
        self._require_active()
        if moved_side not in {"w", "b"}:
            raise ValueError("moved_side must be 'w' or 'b'")
        self._lifecycle.on_move_committed()
        assert self._clock is not None
        self._clock.switch_after_move(moved_side)
        return self.snapshot()

    def sync_position_outcome(self, result: str, reason: EndReason, winner: str | None = None) -> EngineGameSessionSnapshot:
        self._lifecycle.record_position_outcome(result, reason, winner=winner)
        self._stop_clock()
        return self.snapshot()

    def sync_timeout(self, *, opponent_can_mate: bool = True) -> EngineGameSessionSnapshot:
        self._require_started()
        assert self._clock is not None
        flagged = self._clock.snapshot().flagged
        if flagged is None:
            raise ValueError("clock has not flagged")
        self._lifecycle.record_timeout(flagged, opponent_can_mate=opponent_can_mate)
        return self.snapshot()

    def handle_handoff(self, handoff: EngineGameHandoff) -> EngineGameSessionSnapshot:
        self._require_started()
        if handoff.intent is EngineGameIntent.ANALYZE_CURRENT_GAME:
            if self._analysis_handoff is None:
                raise ValueError("analysis handoff is not configured")
            self._analysis_handoff(handoff)
            return self.snapshot()
        if handoff.intent is EngineGameIntent.OPEN_FINAL_REVIEW:
            if self._review_handoff is None:
                raise ValueError("review handoff is not configured")
            self._review_handoff(handoff)
            return self.snapshot()

        before = self._lifecycle.snapshot()
        after = dispatch_lifecycle_handoff(self._lifecycle, handoff)
        if handoff.intent is EngineGameIntent.ACCEPT_TAKEBACK:
            if self._undo_committed_move is None:
                raise ValueError("takeback undo hook is not configured")
            self._undo_committed_move()
            self._lifecycle.invalidate_position_outcome()
        if after.status is GameStatus.FINISHED and before.status is GameStatus.ACTIVE:
            self._stop_clock()
        return self.snapshot()

    def analyze_current_game(self) -> EngineGameHandoff:
        handoff = EngineGameHandoff(EngineGameIntent.ANALYZE_CURRENT_GAME, fen=self._fen_provider())
        self.handle_handoff(handoff)
        return handoff

    def open_final_review(self) -> EngineGameHandoff:
        handoff = EngineGameHandoff(EngineGameIntent.OPEN_FINAL_REVIEW, history_node_id=self._history_node_provider())
        self.handle_handoff(handoff)
        return handoff

    def _stop_clock(self) -> None:
        if self._clock is not None:
            self._clock.stop()

    def _require_started(self) -> None:
        if self._config is None or self._clock is None:
            raise ValueError("engine game session has not started")

    def _require_active(self) -> None:
        self._require_started()
        if self._lifecycle.snapshot().status is not GameStatus.ACTIVE:
            raise ValueError("engine game session is finished")

    def _side_to_move(self) -> str:
        side = str(self._side_provider()).strip().lower()
        if side not in {"w", "b"}:
            raise ValueError("side-to-move provider must return 'w' or 'b'")
        return side
