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

from .clock_service import ChessClock, ClockSnapshot, ClockState
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


@dataclass(frozen=True)
class EngineNoMoveHandoff:
    """Neutral request to resolve why an engine position has no legal move."""

    fen: str
    side_to_move: str
    history_node_id: str


@dataclass(frozen=True)
class EngineNoMoveResolution:
    """Canonical lifecycle outcome supplied by the chess-state owner."""

    result: str
    reason: EndReason
    winner: str | None = None


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
        clock_restore_provider: Callable[[], ClockSnapshot] | None = None,
        no_move_resolver: Callable[[EngineNoMoveHandoff], EngineNoMoveResolution | None] | None = None,
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
        self._clock_restore_provider = clock_restore_provider
        self._no_move_resolver = no_move_resolver
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
        assert self._clock is not None and self._config is not None
        self._lifecycle.reset_for_new_game()
        self._clock.reset(side_to_move=self._side_to_move())
        if not self._config.time_control.untimed:
            self._clock.resume()
        return self.snapshot()

    def snapshot(self) -> EngineGameSessionSnapshot:
        self._require_started()
        assert self._config is not None and self._clock is not None
        lifecycle = self._lifecycle.snapshot()
        clock = self._clock.snapshot()
        if clock.flagged is not None and lifecycle.status is GameStatus.ACTIVE:
            self._lifecycle.record_timeout(clock.flagged, opponent_can_mate=True)
            lifecycle = self._lifecycle.snapshot()
        side = self._side_to_move()
        if lifecycle.status is GameStatus.FINISHED:
            turn_state = EngineTurnState.FINISHED
        elif side == self._config.engine_side:
            turn_state = EngineTurnState.ENGINE
        else:
            turn_state = EngineTurnState.HUMAN
        return EngineGameSessionSnapshot(self._config, side, turn_state, lifecycle, clock)

    def assert_move_allowed(self, moved_side: str) -> ClockSnapshot:
        """Pre-commit guard for integrations that own the canonical Board."""
        self._require_active()
        if moved_side not in {"w", "b"}:
            raise ValueError("moved_side must be 'w' or 'b'")
        if moved_side != self._side_to_move():
            raise ValueError("moved_side does not match side to move")
        assert self._clock is not None
        clock = self._clock.snapshot()
        if clock.flagged is not None:
            self._lifecycle.record_timeout(clock.flagged, opponent_can_mate=True)
            raise ValueError("clock flagged before move commit")
        if clock.state is ClockState.RUNNING and clock.active != moved_side:
            raise ValueError("active clock does not match moved side")
        return clock

    def request_engine_move(self) -> EngineMoveResult:
        snap = self.snapshot()
        if snap.turn_state is EngineTurnState.FINISHED:
            raise ValueError("engine game session is finished")
        if snap.turn_state is not EngineTurnState.ENGINE:
            raise ValueError("engine move requested when it is not the engine turn")
        self.assert_move_allowed(snap.side_to_move)
        fen = str(self._fen_provider()).strip()
        if not fen:
            raise ValueError("fen provider returned empty position")
        result = self._play_service.choose_move(EngineMoveRequest(fen, level=snap.config.level.level))
        if result.move is None:
            self._resolve_no_engine_move(fen, snap.side_to_move)
            return result
        moved_side = snap.side_to_move
        self._commit_engine_move(result.move)
        self._assert_canonical_turn_advanced(moved_side, source="engine move commit")
        self._lifecycle.on_move_committed()
        assert self._clock is not None
        self._clock.switch_after_move(moved_side)
        return result

    def on_human_move_committed(self, moved_side: str) -> EngineGameSessionSnapshot:
        self._require_active()
        if moved_side not in {"w", "b"}:
            raise ValueError("moved_side must be 'w' or 'b'")
        self._assert_canonical_turn_advanced(moved_side, source="human move commit")
        assert self._clock is not None
        clock = self._clock.snapshot()
        if clock.flagged is not None:
            self._lifecycle.record_timeout(clock.flagged, opponent_can_mate=True)
            raise ValueError("clock flagged before move commit")
        if clock.state is ClockState.RUNNING and clock.active != moved_side:
            raise ValueError("active clock does not match moved side")
        self._lifecycle.on_move_committed()
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
        if self._lifecycle.snapshot().status is GameStatus.ACTIVE:
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
        if handoff.intent is EngineGameIntent.ACCEPT_TAKEBACK and self._undo_committed_move is None:
            raise ValueError("takeback undo hook is not configured")

        before = self._lifecycle.snapshot()
        after = dispatch_lifecycle_handoff(self._lifecycle, handoff)
        if handoff.intent is EngineGameIntent.ACCEPT_TAKEBACK:
            assert self._undo_committed_move is not None
            self._undo_committed_move()
            self._lifecycle.invalidate_position_outcome()
            self._restore_clock_after_takeback()
            after = self._lifecycle.snapshot()
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

    def _resolve_no_engine_move(self, fen: str, side_to_move: str) -> None:
        if self._no_move_resolver is None:
            return
        handoff = EngineNoMoveHandoff(
            fen=fen,
            side_to_move=side_to_move,
            history_node_id=str(self._history_node_provider()),
        )
        resolution = self._no_move_resolver(handoff)
        if resolution is None:
            return
        self._lifecycle.record_position_outcome(
            resolution.result,
            resolution.reason,
            winner=resolution.winner,
        )
        self._stop_clock()

    def _restore_clock_after_takeback(self) -> None:
        if self._clock_restore_provider is None or self._clock is None:
            return
        restored = self._clock_restore_provider()
        resume = self._lifecycle.snapshot().status is GameStatus.ACTIVE
        self._clock.restore(restored, resume_running=resume)

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

    def _assert_canonical_turn_advanced(self, moved_side: str, *, source: str) -> None:
        """Require a committed move to be visible in the canonical board state.

        The coordinator deliberately does not own Board mutation. A callback may
        therefore fail silently, or an integration may call the post-commit hook
        before the canonical state was actually updated. Advancing lifecycle or
        clocks in that state would create a second, contradictory notion of whose
        turn it is. Fail before touching lifecycle/clock state unless the canonical
        side-to-move has advanced exactly once to the opponent.
        """
        expected = "b" if moved_side == "w" else "w"
        actual = self._side_to_move()
        if actual != expected:
            raise ValueError(
                f"canonical side to move did not advance after {source}: "
                f"expected {expected}, got {actual}"
            )
