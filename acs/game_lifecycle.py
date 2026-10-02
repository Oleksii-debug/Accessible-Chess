from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LifecycleErrorCode(str, Enum):
    INVALID_COMMAND = "invalid_command"
    INVALID_OUTCOME = "invalid_outcome"
    INVALID_STATE = "invalid_state"
    NO_PENDING_INTERACTION = "no_pending_interaction"
    SELF_RESPONSE = "self_response"
    ALREADY_PENDING = "already_pending"


class LifecycleError(ValueError):
    """Raised when a game-lifecycle command is invalid for the current state."""

    def __init__(
        self,
        message: str,
        *,
        code: LifecycleErrorCode = LifecycleErrorCode.INVALID_COMMAND,
    ) -> None:
        super().__init__(message)
        self.code = LifecycleErrorCode(code)


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

DRAW_ONLY_REASONS = frozenset({
    EndReason.DRAW_AGREEMENT,
    EndReason.STALEMATE,
    EndReason.INSUFFICIENT_MATERIAL,
    EndReason.THREEFOLD_REPETITION,
    EndReason.FIFTY_MOVE_RULE,
})

DECISIVE_ONLY_REASONS = frozenset({
    EndReason.RESIGNATION,
    EndReason.CHECKMATE,
})


@dataclass(frozen=True)
class GameOutcome:
    result: str
    reason: EndReason
    winner: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.result, str)
            or self.result not in {"1-0", "0-1", "1/2-1/2"}
        ):
            raise LifecycleError(
                "result must be 1-0, 0-1, or 1/2-1/2",
                code=LifecycleErrorCode.INVALID_OUTCOME,
            )
        if not isinstance(self.reason, EndReason):
            raise LifecycleError(
                "reason must be an EndReason",
                code=LifecycleErrorCode.INVALID_OUTCOME,
            )
        if self.winner is not None and (
            not isinstance(self.winner, str) or self.winner not in {"w", "b"}
        ):
            raise LifecycleError(
                "winner must be 'w', 'b', or None",
                code=LifecycleErrorCode.INVALID_OUTCOME,
            )
        expected = {"1-0": "w", "0-1": "b", "1/2-1/2": None}[self.result]
        if self.winner != expected:
            raise LifecycleError(
                "winner does not match result",
                code=LifecycleErrorCode.INVALID_OUTCOME,
            )
        if self.reason in DRAW_ONLY_REASONS and self.result != "1/2-1/2":
            raise LifecycleError(
                "draw reason requires a drawn result",
                code=LifecycleErrorCode.INVALID_OUTCOME,
            )
        if self.reason in DECISIVE_ONLY_REASONS and self.result == "1/2-1/2":
            raise LifecycleError(
                "decisive reason requires a winning result",
                code=LifecycleErrorCode.INVALID_OUTCOME,
            )


@dataclass(frozen=True)
class LifecycleSnapshot:
    status: GameStatus
    outcome: GameOutcome | None
    draw_offered_by: str | None
    takeback_requested_by: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GameStatus):
            raise LifecycleError(
                "lifecycle status must be a GameStatus",
                code=LifecycleErrorCode.INVALID_STATE,
            )
        if self.outcome is not None and not isinstance(self.outcome, GameOutcome):
            raise LifecycleError(
                "lifecycle outcome must be a GameOutcome or None",
                code=LifecycleErrorCode.INVALID_STATE,
            )
        for field_name in ("draw_offered_by", "takeback_requested_by"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str) or value not in {"w", "b"}
            ):
                raise LifecycleError(
                    f"{field_name} must be 'w', 'b', or None",
                    code=LifecycleErrorCode.INVALID_STATE,
                )
        if self.status is GameStatus.ACTIVE and self.outcome is not None:
            raise LifecycleError(
                "active lifecycle snapshot cannot have an outcome",
                code=LifecycleErrorCode.INVALID_STATE,
            )
        if self.status is GameStatus.FINISHED and self.outcome is None:
            raise LifecycleError(
                "finished lifecycle snapshot requires an outcome",
                code=LifecycleErrorCode.INVALID_STATE,
            )
        if self.status is GameStatus.FINISHED and (
            self.draw_offered_by is not None
            or self.takeback_requested_by is not None
        ):
            raise LifecycleError(
                "finished lifecycle snapshot cannot have pending interactions",
                code=LifecycleErrorCode.INVALID_STATE,
            )


class GameLifecycle:
    """Presentation-neutral draw/resign/takeback/result state."""

    def __init__(self) -> None:
        self._status = GameStatus.ACTIVE
        self._outcome: GameOutcome | None = None
        self._draw_offered_by: str | None = None
        self._takeback_requested_by: str | None = None

    def snapshot(self) -> LifecycleSnapshot:
        return LifecycleSnapshot(
            self._status,
            self._outcome,
            self._draw_offered_by,
            self._takeback_requested_by,
        )

    def offer_draw(self, side: str) -> LifecycleSnapshot:
        self._require_active()
        self._validate_side(side)
        if self._draw_offered_by is not None:
            raise LifecycleError(
                "a draw offer is already pending",
                code=LifecycleErrorCode.ALREADY_PENDING,
            )
        self._draw_offered_by = side
        return self.snapshot()

    def accept_draw(self, side: str) -> LifecycleSnapshot:
        self._require_active()
        self._validate_side(side)
        if self._draw_offered_by is None:
            raise LifecycleError(
                "there is no pending draw offer",
                code=LifecycleErrorCode.NO_PENDING_INTERACTION,
            )
        if self._draw_offered_by == side:
            raise LifecycleError(
                "a side cannot accept its own draw offer",
                code=LifecycleErrorCode.SELF_RESPONSE,
            )
        return self._finish(GameOutcome("1/2-1/2", EndReason.DRAW_AGREEMENT))

    def decline_draw(self, side: str) -> LifecycleSnapshot:
        self._require_active()
        self._validate_side(side)
        if self._draw_offered_by is None:
            raise LifecycleError(
                "there is no pending draw offer",
                code=LifecycleErrorCode.NO_PENDING_INTERACTION,
            )
        if self._draw_offered_by == side:
            raise LifecycleError(
                "a side cannot decline its own draw offer",
                code=LifecycleErrorCode.SELF_RESPONSE,
            )
        self._draw_offered_by = None
        return self.snapshot()

    def request_takeback(self, side: str) -> LifecycleSnapshot:
        self._require_active()
        self._validate_side(side)
        if self._takeback_requested_by is not None:
            raise LifecycleError(
                "a takeback request is already pending",
                code=LifecycleErrorCode.ALREADY_PENDING,
            )
        self._takeback_requested_by = side
        return self.snapshot()

    def preflight_accept_takeback(self, side: str) -> LifecycleSnapshot:
        """Validate takeback acceptance without mutating lifecycle state.

        Coordinators that must invoke external canonical-history callbacks use
        this before the destructive callback so a callback failure cannot leave
        the lifecycle claiming that the request was already accepted.
        """
        self._require_active()
        self._validate_side(side)
        if self._takeback_requested_by is None:
            raise LifecycleError(
                "there is no pending takeback request",
                code=LifecycleErrorCode.NO_PENDING_INTERACTION,
            )
        if self._takeback_requested_by == side:
            raise LifecycleError(
                "a side cannot accept its own takeback request",
                code=LifecycleErrorCode.SELF_RESPONSE,
            )
        return self.snapshot()

    def accept_takeback(self, side: str) -> LifecycleSnapshot:
        self.preflight_accept_takeback(side)
        self._takeback_requested_by = None
        return self.snapshot()

    def decline_takeback(self, side: str) -> LifecycleSnapshot:
        self._require_active()
        self._validate_side(side)
        if self._takeback_requested_by is None:
            raise LifecycleError(
                "there is no pending takeback request",
                code=LifecycleErrorCode.NO_PENDING_INTERACTION,
            )
        if self._takeback_requested_by == side:
            raise LifecycleError(
                "a side cannot decline its own takeback request",
                code=LifecycleErrorCode.SELF_RESPONSE,
            )
        self._takeback_requested_by = None
        return self.snapshot()

    def resign(self, side: str) -> LifecycleSnapshot:
        self._require_active()
        self._validate_side(side)
        winner = self._other(side)
        return self._finish(
            GameOutcome(
                "1-0" if winner == "w" else "0-1",
                EndReason.RESIGNATION,
                winner,
            )
        )

    def record_timeout(
        self,
        flagged_side: str,
        *,
        opponent_can_mate: bool = True,
    ) -> LifecycleSnapshot:
        self._require_active()
        self._validate_side(flagged_side)
        if not isinstance(opponent_can_mate, bool):
            raise LifecycleError(
                "opponent_can_mate must be boolean",
                code=LifecycleErrorCode.INVALID_COMMAND,
            )
        if opponent_can_mate:
            winner = self._other(flagged_side)
            outcome = GameOutcome(
                "1-0" if winner == "w" else "0-1",
                EndReason.TIMEOUT,
                winner,
            )
        else:
            outcome = GameOutcome("1/2-1/2", EndReason.TIMEOUT)
        return self._finish(outcome)

    def record_position_outcome(
        self,
        result: str,
        reason: EndReason,
        *,
        winner: str | None = None,
    ) -> LifecycleSnapshot:
        self._require_active()
        if not isinstance(reason, EndReason) or reason not in POSITION_DERIVED_REASONS:
            raise LifecycleError(
                "reason is not position-derived",
                code=LifecycleErrorCode.INVALID_OUTCOME,
            )
        return self._finish(GameOutcome(result, reason, winner))

    def invalidate_position_outcome(self) -> LifecycleSnapshot:
        if self._outcome is None or self._outcome.reason not in POSITION_DERIVED_REASONS:
            return self.snapshot()
        self._status = GameStatus.ACTIVE
        self._outcome = None
        self._draw_offered_by = None
        self._takeback_requested_by = None
        return self.snapshot()

    def on_move_committed(self) -> LifecycleSnapshot:
        self._require_active()
        self._draw_offered_by = None
        self._takeback_requested_by = None
        return self.snapshot()

    def reset_for_new_game(self) -> LifecycleSnapshot:
        self._status = GameStatus.ACTIVE
        self._outcome = None
        self._draw_offered_by = None
        self._takeback_requested_by = None
        return self.snapshot()

    def _finish(self, outcome: GameOutcome) -> LifecycleSnapshot:
        if not isinstance(outcome, GameOutcome):
            raise LifecycleError(
                "outcome must be a GameOutcome",
                code=LifecycleErrorCode.INVALID_OUTCOME,
            )
        self._status = GameStatus.FINISHED
        self._outcome = outcome
        self._draw_offered_by = None
        self._takeback_requested_by = None
        return self.snapshot()

    def _require_active(self) -> None:
        if self._status != GameStatus.ACTIVE:
            raise LifecycleError(
                "game is already finished",
                code=LifecycleErrorCode.INVALID_STATE,
            )

    @staticmethod
    def _validate_side(side: str) -> None:
        if not isinstance(side, str) or side not in {"w", "b"}:
            raise LifecycleError(
                "side must be 'w' or 'b'",
                code=LifecycleErrorCode.INVALID_COMMAND,
            )

    @staticmethod
    def _other(side: str) -> str:
        return "b" if side == "w" else "w"
