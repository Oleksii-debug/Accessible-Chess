from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LifecycleError(ValueError):
    """Raised when a game-lifecycle command is invalid for the current state."""


class GameStatus(str, Enum):
    ACTIVE = "active"
    FINISHED = "finished"


class EndReason(str, Enum):
    RESIGNATION = "resignation"
    DRAW_AGREEMENT = "draw_agreement"
    TIMEOUT = "timeout"
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    INSUFFICIENT_MATERIAL = "insufficient_material"
    THREEFOLD_REPETITION = "threefold_repetition"
    FIFTY_MOVE_RULE = "fifty_move_rule"


POSITION_DERIVED_REASONS = frozenset({
    EndReason.CHECKMATE,
    EndReason.STALEMATE,
    EndReason.INSUFFICIENT_MATERIAL,
    EndReason.THREEFOLD_REPETITION,
    EndReason.FIFTY_MOVE_RULE,
})


@dataclass(frozen=True)
class GameOutcome:
    result: str
    reason: EndReason
    winner: str | None = None

    def __post_init__(self) -> None:
        if self.result not in {"1-0", "0-1", "1/2-1/2"}:
            raise LifecycleError("result must be 1-0, 0-1, or 1/2-1/2")
        if self.winner not in {None, "w", "b"}:
            raise LifecycleError("winner must be 'w', 'b', or None")
        expected = {"1-0": "w", "0-1": "b", "1/2-1/2": None}[self.result]
        if self.winner != expected:
            raise LifecycleError("winner does not match result")


@dataclass(frozen=True)
class LifecycleSnapshot:
    status: GameStatus
    outcome: GameOutcome | None
    draw_offered_by: str | None
    takeback_requested_by: str | None


class GameLifecycle:
    """Presentation-neutral draw/resign/takeback/result state."""

    def __init__(self) -> None:
        self._status = GameStatus.ACTIVE
        self._outcome: GameOutcome | None = None
        self._draw_offered_by: str | None = None
        self._takeback_requested_by: str | None = None

    def snapshot(self) -> LifecycleSnapshot:
        return LifecycleSnapshot(self._status, self._outcome, self._draw_offered_by, self._takeback_requested_by)

    def offer_draw(self, side: str) -> LifecycleSnapshot:
        self._require_active(); self._validate_side(side); self._draw_offered_by = side; return self.snapshot()

    def accept_draw(self, side: str) -> LifecycleSnapshot:
        self._require_active(); self._validate_side(side)
        if self._draw_offered_by is None:
            raise LifecycleError("there is no pending draw offer")
        if self._draw_offered_by == side:
            raise LifecycleError("a side cannot accept its own draw offer")
        return self._finish(GameOutcome("1/2-1/2", EndReason.DRAW_AGREEMENT))

    def decline_draw(self, side: str) -> LifecycleSnapshot:
        self._require_active(); self._validate_side(side)
        if self._draw_offered_by is None:
            raise LifecycleError("there is no pending draw offer")
        if self._draw_offered_by == side:
            raise LifecycleError("a side cannot decline its own draw offer")
        self._draw_offered_by = None
        return self.snapshot()

    def request_takeback(self, side: str) -> LifecycleSnapshot:
        self._require_active(); self._validate_side(side); self._takeback_requested_by = side; return self.snapshot()

    def accept_takeback(self, side: str) -> LifecycleSnapshot:
        self._require_active(); self._validate_side(side)
        if self._takeback_requested_by is None:
            raise LifecycleError("there is no pending takeback request")
        if self._takeback_requested_by == side:
            raise LifecycleError("a side cannot accept its own takeback request")
        self._takeback_requested_by = None
        return self.snapshot()

    def decline_takeback(self, side: str) -> LifecycleSnapshot:
        self._require_active(); self._validate_side(side)
        if self._takeback_requested_by is None:
            raise LifecycleError("there is no pending takeback request")
        if self._takeback_requested_by == side:
            raise LifecycleError("a side cannot decline its own takeback request")
        self._takeback_requested_by = None
        return self.snapshot()

    def resign(self, side: str) -> LifecycleSnapshot:
        self._require_active(); self._validate_side(side)
        winner = self._other(side)
        return self._finish(GameOutcome("1-0" if winner == "w" else "0-1", EndReason.RESIGNATION, winner))

    def record_timeout(self, flagged_side: str, *, opponent_can_mate: bool = True) -> LifecycleSnapshot:
        self._require_active(); self._validate_side(flagged_side)
        if opponent_can_mate:
            winner = self._other(flagged_side)
            outcome = GameOutcome("1-0" if winner == "w" else "0-1", EndReason.TIMEOUT, winner)
        else:
            outcome = GameOutcome("1/2-1/2", EndReason.TIMEOUT)
        return self._finish(outcome)

    def record_position_outcome(self, result: str, reason: EndReason, *, winner: str | None = None) -> LifecycleSnapshot:
        self._require_active()
        if reason not in POSITION_DERIVED_REASONS:
            raise LifecycleError("reason is not position-derived")
        return self._finish(GameOutcome(result, reason, winner))

    def invalidate_position_outcome(self) -> LifecycleSnapshot:
        if self._outcome is None or self._outcome.reason not in POSITION_DERIVED_REASONS:
            return self.snapshot()
        self._status = GameStatus.ACTIVE
        self._outcome = None
        return self.snapshot()

    def on_move_committed(self) -> LifecycleSnapshot:
        self._require_active(); self._draw_offered_by = None; self._takeback_requested_by = None; return self.snapshot()

    def reset_for_new_game(self) -> LifecycleSnapshot:
        self._status = GameStatus.ACTIVE; self._outcome = None; self._draw_offered_by = None; self._takeback_requested_by = None; return self.snapshot()

    def _finish(self, outcome: GameOutcome) -> LifecycleSnapshot:
        self._status = GameStatus.FINISHED; self._outcome = outcome; self._draw_offered_by = None; self._takeback_requested_by = None; return self.snapshot()

    def _require_active(self) -> None:
        if self._status != GameStatus.ACTIVE:
            raise LifecycleError("game is already finished")

    @staticmethod
    def _validate_side(side: str) -> None:
        if side not in {"w", "b"}:
            raise LifecycleError("side must be 'w' or 'b'")

    @staticmethod
    def _other(side: str) -> str:
        return "b" if side == "w" else "w"
