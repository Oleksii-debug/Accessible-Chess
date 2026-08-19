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
from .engine_ports import (
    EngineContractError,
    EngineContractErrorCode,
    EngineMoveRequest,
    EngineMoveResult,
)
from .game_lifecycle import (
    EndReason,
    GameLifecycle,
    GameOutcome,
    GameStatus,
    LifecycleError,
    LifecycleSnapshot,
)


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

    def __post_init__(self) -> None:
        if not isinstance(self.config, ResolvedEngineGameConfig):
            raise EngineContractError(
                "engine session config must be resolved",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if not isinstance(self.side_to_move, str) or self.side_to_move not in {"w", "b"}:
            raise EngineContractError(
                "engine session side_to_move must be 'w' or 'b'",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if not isinstance(self.turn_state, EngineTurnState):
            raise EngineContractError(
                "engine session turn_state must be EngineTurnState",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if not isinstance(self.lifecycle, LifecycleSnapshot):
            raise EngineContractError(
                "engine session lifecycle must be LifecycleSnapshot",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if not isinstance(self.clock, ClockSnapshot):
            raise EngineContractError(
                "engine session clock must be ClockSnapshot",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.lifecycle.status is GameStatus.FINISHED:
            if self.turn_state is not EngineTurnState.FINISHED:
                raise EngineContractError(
                    "finished lifecycle requires finished engine turn state",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
        else:
            expected = (
                EngineTurnState.ENGINE
                if self.side_to_move == self.config.engine_side
                else EngineTurnState.HUMAN
            )
            if self.turn_state is not expected:
                raise EngineContractError(
                    "active lifecycle turn state does not match configured side",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
            if self.clock.flagged is not None:
                raise EngineContractError(
                    "active lifecycle cannot carry a flagged clock",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
            if (
                not self.config.time_control.untimed
                and self.clock.state not in {ClockState.RUNNING, ClockState.PAUSED}
            ):
                raise EngineContractError(
                    "active timed session requires a running or paused clock",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
        if self.lifecycle.status is GameStatus.FINISHED and self.clock.state in {
            ClockState.RUNNING,
            ClockState.PAUSED,
        }:
            raise EngineContractError(
                "finished lifecycle cannot carry an active clock",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.config.time_control.untimed and (
            self.clock.white_ms != 0
            or self.clock.black_ms != 0
            or self.clock.state is not ClockState.STOPPED
        ):
            raise EngineContractError(
                "untimed session requires the canonical stopped clock",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if (
            self.clock.state in {ClockState.RUNNING, ClockState.PAUSED}
            and self.clock.active != self.side_to_move
        ):
            raise EngineContractError(
                "active clock does not match session side_to_move",
                code=EngineContractErrorCode.INVALID_SESSION,
            )


@dataclass(frozen=True)
class EngineNoMoveHandoff:
    """Neutral request to resolve why an engine position has no legal move."""

    fen: str
    side_to_move: str
    history_node_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.fen, str) or not self.fen.strip():
            raise EngineContractError(
                "no-move handoff FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_HANDOFF,
            )
        if not isinstance(self.side_to_move, str) or self.side_to_move not in {"w", "b"}:
            raise EngineContractError(
                "no-move handoff side_to_move must be 'w' or 'b'",
                code=EngineContractErrorCode.INVALID_HANDOFF,
            )
        if not isinstance(self.history_node_id, str) or not self.history_node_id.strip():
            raise EngineContractError(
                "no-move handoff history_node_id must be non-empty text",
                code=EngineContractErrorCode.INVALID_HANDOFF,
            )
        object.__setattr__(self, "fen", self.fen.strip())
        object.__setattr__(self, "history_node_id", self.history_node_id.strip())


@dataclass(frozen=True)
class EngineNoMoveResolution:
    """Canonical lifecycle outcome supplied by the chess-state owner."""

    result: str
    reason: EndReason
    winner: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason, EndReason) or self.reason not in {
            EndReason.CHECKMATE,
            EndReason.STALEMATE,
        }:
            raise EngineContractError(
                "no-move resolution reason must be checkmate or stalemate",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        try:
            GameOutcome(self.result, self.reason, self.winner)
        except LifecycleError as exc:
            raise EngineContractError(
                "no-move resolution result is inconsistent",
                code=EngineContractErrorCode.INVALID_RESULT,
            ) from exc


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
        timeout_mating_capability_provider: Callable[[str], bool | None] | None = None,
        analysis_handoff: Callable[[EngineGameHandoff], None] | None = None,
        review_handoff: Callable[[EngineGameHandoff], None] | None = None,
        lifecycle: GameLifecycle | None = None,
        clock_factory: Callable[[object], ChessClock] | None = None,
    ) -> None:
        if not isinstance(play_service, EnginePlayService):
            raise TypeError("play_service must be EnginePlayService")
        required_callbacks = {
            "fen_provider": fen_provider,
            "side_to_move_provider": side_to_move_provider,
            "commit_engine_move": commit_engine_move,
            "history_node_provider": history_node_provider,
        }
        for name, callback in required_callbacks.items():
            if not callable(callback):
                raise EngineContractError(
                    f"{name} must be callable",
                    code=EngineContractErrorCode.INVALID_PROVIDER,
                )
        optional_callbacks = {
            "undo_committed_move": undo_committed_move,
            "clock_restore_provider": clock_restore_provider,
            "no_move_resolver": no_move_resolver,
            "timeout_mating_capability_provider": timeout_mating_capability_provider,
            "analysis_handoff": analysis_handoff,
            "review_handoff": review_handoff,
        }
        for name, callback in optional_callbacks.items():
            if callback is not None and not callable(callback):
                raise EngineContractError(
                    f"{name} must be callable or None",
                    code=EngineContractErrorCode.INVALID_PROVIDER,
                )
        if lifecycle is not None and not isinstance(lifecycle, GameLifecycle):
            raise EngineContractError(
                "lifecycle must be GameLifecycle or None",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if clock_factory is not None and not callable(clock_factory):
            raise EngineContractError(
                "clock_factory must be callable or None",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        self._play_service = play_service
        self._fen_provider = fen_provider
        self._side_provider = side_to_move_provider
        self._commit_engine_move = commit_engine_move
        self._history_node_provider = history_node_provider
        self._undo_committed_move = undo_committed_move
        self._clock_restore_provider = clock_restore_provider
        self._no_move_resolver = no_move_resolver
        self._timeout_mating_capability_provider = timeout_mating_capability_provider
        self._analysis_handoff = analysis_handoff
        self._review_handoff = review_handoff
        self._lifecycle = GameLifecycle() if lifecycle is None else lifecycle
        self._clock_factory = (
            (lambda control: ChessClock(control))
            if clock_factory is None
            else clock_factory
        )
        self._config: ResolvedEngineGameConfig | None = None
        self._clock: ChessClock | None = None

    def start(self, config: EngineGameConfig, *, random_choice=None) -> EngineGameSessionSnapshot:
        resolved = resolve_engine_game_config(config, random_choice=random_choice)
        clock = self._clock_factory(resolved.time_control)
        if not isinstance(clock, ChessClock):
            raise EngineContractError(
                "clock_factory must return ChessClock",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        side = self._side_to_move()
        clock_snapshot = clock.start(side)
        lifecycle = LifecycleSnapshot(GameStatus.ACTIVE, None, None, None)
        turn_state = (
            EngineTurnState.ENGINE
            if side == resolved.engine_side
            else EngineTurnState.HUMAN
        )
        snapshot = EngineGameSessionSnapshot(
            resolved,
            side,
            turn_state,
            lifecycle,
            clock_snapshot,
        )
        self._lifecycle.reset_for_new_game()
        self._config = resolved
        self._clock = clock
        return snapshot

    def reset(self) -> EngineGameSessionSnapshot:
        self._require_started()
        assert self._clock is not None and self._config is not None
        side = self._side_to_move()
        clock = self._clock.reset(side_to_move=side)
        if not self._config.time_control.untimed:
            clock = self._clock.resume()
        turn_state = (
            EngineTurnState.ENGINE
            if side == self._config.engine_side
            else EngineTurnState.HUMAN
        )
        snapshot = EngineGameSessionSnapshot(
            self._config,
            side,
            turn_state,
            LifecycleSnapshot(GameStatus.ACTIVE, None, None, None),
            clock,
        )
        self._lifecycle.reset_for_new_game()
        return snapshot

    def snapshot(self) -> EngineGameSessionSnapshot:
        self._require_started()
        assert self._config is not None and self._clock is not None
        side = self._side_to_move()
        lifecycle = self._lifecycle.snapshot()
        clock = self._clock.snapshot()
        if clock.flagged is not None and lifecycle.status is GameStatus.ACTIVE:
            self._record_timeout(clock.flagged)
            lifecycle = self._lifecycle.snapshot()
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
        if not isinstance(moved_side, str) or moved_side not in {"w", "b"}:
            raise EngineContractError(
                "moved_side must be 'w' or 'b'",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if moved_side != self._side_to_move():
            raise ValueError("moved_side does not match side to move")
        assert self._clock is not None
        clock = self._clock.snapshot()
        if clock.flagged is not None:
            self._record_timeout(clock.flagged)
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
        fen = self._current_fen()
        result = self._play_service.choose_move(EngineMoveRequest(fen, level=snap.config.level.level))
        if result.move is None:
            self._resolve_no_engine_move(fen, snap.side_to_move)
            return result
        moved_side = snap.side_to_move
        self.assert_move_allowed(moved_side)
        if self._current_fen() != fen:
            raise EngineContractError(
                "position changed while the engine move was pending",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        self._commit_engine_move(result.move)
        self._lifecycle.on_move_committed()
        assert self._clock is not None
        self._clock.switch_after_move(moved_side)
        return result

    def on_human_move_committed(self, moved_side: str) -> EngineGameSessionSnapshot:
        self._require_active()
        if not isinstance(moved_side, str) or moved_side not in {"w", "b"}:
            raise EngineContractError(
                "moved_side must be 'w' or 'b'",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        assert self._clock is not None
        clock = self._clock.snapshot()
        if clock.flagged is not None:
            self._record_timeout(clock.flagged)
            raise ValueError("clock flagged before move commit")
        if clock.state is ClockState.RUNNING and clock.active != moved_side:
            raise ValueError("active clock does not match moved side")
        self._lifecycle.on_move_committed()
        self._clock.switch_after_move(moved_side)
        return self.snapshot()

    def sync_position_outcome(self, result: str, reason: EndReason, winner: str | None = None) -> EngineGameSessionSnapshot:
        self._require_active()
        self._lifecycle.record_position_outcome(result, reason, winner=winner)
        self._stop_clock()
        return self.snapshot()

    def sync_timeout(self, *, opponent_can_mate: bool | None = None) -> EngineGameSessionSnapshot:
        self._require_started()
        assert self._clock is not None
        flagged = self._clock.snapshot().flagged
        if flagged is None:
            raise ValueError("clock has not flagged")
        if self._lifecycle.snapshot().status is GameStatus.ACTIVE:
            self._record_timeout(flagged, opponent_can_mate=opponent_can_mate)
        return self.snapshot()

    def handle_handoff(self, handoff: EngineGameHandoff) -> EngineGameSessionSnapshot:
        self._require_started()
        if not isinstance(handoff, EngineGameHandoff):
            raise TypeError("handoff must be EngineGameHandoff")
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
        handoff = EngineGameHandoff(
            EngineGameIntent.ANALYZE_CURRENT_GAME,
            fen=self._current_fen(),
        )
        self.handle_handoff(handoff)
        return handoff

    def open_final_review(self) -> EngineGameHandoff:
        handoff = EngineGameHandoff(
            EngineGameIntent.OPEN_FINAL_REVIEW,
            history_node_id=self._history_node_id(),
        )
        self.handle_handoff(handoff)
        return handoff

    def _resolve_no_engine_move(self, fen: str, side_to_move: str) -> None:
        if self._no_move_resolver is None:
            return
        handoff = EngineNoMoveHandoff(
            fen=fen,
            side_to_move=side_to_move,
            history_node_id=self._history_node_id(),
        )
        resolution = self._no_move_resolver(handoff)
        if resolution is None:
            return
        if not isinstance(resolution, EngineNoMoveResolution):
            raise EngineContractError(
                "no_move_resolver must return EngineNoMoveResolution or None",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        self._lifecycle.record_position_outcome(
            resolution.result,
            resolution.reason,
            winner=resolution.winner,
        )
        self._stop_clock()

    def _record_timeout(
        self,
        flagged_side: str,
        *,
        opponent_can_mate: bool | None = None,
    ) -> None:
        if not isinstance(flagged_side, str) or flagged_side not in {"w", "b"}:
            raise EngineContractError(
                "flagged side must be 'w' or 'b'",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        resolved = opponent_can_mate
        if resolved is not None:
            if type(resolved) is not bool:
                raise EngineContractError(
                    "opponent_can_mate must be an exact boolean",
                    code=EngineContractErrorCode.INVALID_REQUEST,
                )
        else:
            if self._timeout_mating_capability_provider is None:
                raise EngineContractError(
                    "timeout mating capability is unresolved",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
            resolved = self._timeout_mating_capability_provider(flagged_side)
            if resolved is None:
                raise EngineContractError(
                    "timeout mating capability is unresolved",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
            if type(resolved) is not bool:
                raise EngineContractError(
                    "timeout mating capability provider must return bool or None",
                    code=EngineContractErrorCode.INVALID_PROVIDER,
                )
        self._lifecycle.record_timeout(flagged_side, opponent_can_mate=resolved)

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
        side = self._side_provider()
        if not isinstance(side, str) or side not in {"w", "b"}:
            raise EngineContractError(
                "side-to-move provider must return 'w' or 'b'",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        return side

    def _current_fen(self) -> str:
        fen = self._fen_provider()
        if not isinstance(fen, str) or not fen.strip():
            raise EngineContractError(
                "fen provider must return non-empty text",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        return fen.strip()

    def _history_node_id(self) -> str:
        node_id = self._history_node_provider()
        if not isinstance(node_id, str) or not node_id.strip():
            raise EngineContractError(
                "history node provider must return non-empty text",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        return node_id.strip()
