from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable
import time


class ClockError(ValueError):
    """Raised when a clock operation violates the game-clock contract."""


class ClockState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    FLAGGED = "flagged"


@dataclass(frozen=True)
class TimeControl:
    """Presentation-neutral chess time control in milliseconds."""

    initial_ms: int
    increment_ms: int = 0

    def __post_init__(self) -> None:
        if self.initial_ms < 0:
            raise ClockError("initial_ms must not be negative")
        if self.increment_ms < 0:
            raise ClockError("increment_ms must not be negative")

    @property
    def untimed(self) -> bool:
        return self.initial_ms == 0


@dataclass(frozen=True)
class ClockSnapshot:
    white_ms: int
    black_ms: int
    active: str | None
    state: ClockState
    flagged: str | None = None

    def remaining(self, side: str) -> int:
        if side == "w":
            return self.white_ms
        if side == "b":
            return self.black_ms
        raise ClockError("side must be 'w' or 'b'")


class ChessClock:
    """Deterministic two-player chess clock.

    Time is charged lazily whenever a snapshot or state-changing operation is
    requested. The service does not own move legality or UI timers.
    """

    def __init__(
        self,
        control: TimeControl,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.control = control
        self._now = now
        self._remaining = {"w": control.initial_ms, "b": control.initial_ms}
        self._active: str | None = None
        self._state = ClockState.STOPPED
        self._flagged: str | None = None
        self._last_tick: float | None = None

    @property
    def state(self) -> ClockState:
        self._sync()
        return self._state

    @property
    def active(self) -> str | None:
        self._sync()
        return self._active

    @property
    def flagged(self) -> str | None:
        self._sync()
        return self._flagged

    def snapshot(self) -> ClockSnapshot:
        self._sync()
        return ClockSnapshot(
            white_ms=self._remaining["w"],
            black_ms=self._remaining["b"],
            active=self._active,
            state=self._state,
            flagged=self._flagged,
        )

    def start(self, side: str = "w") -> ClockSnapshot:
        self._validate_side(side)
        if self.control.untimed:
            self._active = None
            self._state = ClockState.STOPPED
            self._last_tick = None
            return self.snapshot()
        if self._state == ClockState.FLAGGED:
            raise ClockError("cannot start a flagged clock; reset first")
        self._sync()
        self._active = side
        self._state = ClockState.RUNNING
        self._last_tick = self._now()
        return self.snapshot()

    def pause(self) -> ClockSnapshot:
        self._sync()
        if self._state == ClockState.RUNNING:
            self._state = ClockState.PAUSED
            self._last_tick = None
        return self.snapshot()

    def resume(self) -> ClockSnapshot:
        if self.control.untimed:
            return self.snapshot()
        if self._state == ClockState.FLAGGED:
            raise ClockError("cannot resume a flagged clock; reset first")
        if self._active is None:
            raise ClockError("cannot resume before a side has been selected")
        if self._state == ClockState.PAUSED:
            self._state = ClockState.RUNNING
            self._last_tick = self._now()
        return self.snapshot()

    def stop(self) -> ClockSnapshot:
        self._sync()
        if self._state != ClockState.FLAGGED:
            self._state = ClockState.STOPPED
        self._active = None
        self._last_tick = None
        return self.snapshot()

    def switch_after_move(self, moved_side: str) -> ClockSnapshot:
        """Charge the mover, award increment, then start the opponent clock."""
        self._validate_side(moved_side)
        self._sync()
        if self.control.untimed:
            return self.snapshot()
        if self._state == ClockState.FLAGGED:
            return self.snapshot()
        if self._state != ClockState.RUNNING:
            raise ClockError("clock must be running to switch after a move")
        if self._active != moved_side:
            raise ClockError("moved_side does not match the active clock")

        self._remaining[moved_side] += self.control.increment_ms
        self._active = "b" if moved_side == "w" else "w"
        self._last_tick = self._now()
        return self.snapshot()

    def set_remaining(self, side: str, milliseconds: int) -> ClockSnapshot:
        """Administrative/game-restore hook; never changes whose clock is active."""
        self._validate_side(side)
        if milliseconds < 0:
            raise ClockError("milliseconds must not be negative")
        self._sync()
        self._remaining[side] = int(milliseconds)
        if self._state == ClockState.FLAGGED and self._flagged == side and milliseconds > 0:
            self._flagged = None
            self._state = ClockState.PAUSED if self._active is not None else ClockState.STOPPED
        return self.snapshot()

    def reset(self, *, side_to_move: str | None = None) -> ClockSnapshot:
        if side_to_move is not None:
            self._validate_side(side_to_move)
        self._remaining = {"w": self.control.initial_ms, "b": self.control.initial_ms}
        self._flagged = None
        self._active = side_to_move
        if self.control.untimed or side_to_move is None:
            self._state = ClockState.STOPPED
            self._last_tick = None
        else:
            self._state = ClockState.PAUSED
            self._last_tick = None
        return self.snapshot()

    def _sync(self) -> None:
        if self._state != ClockState.RUNNING or self._active is None or self._last_tick is None:
            return
        now = self._now()
        elapsed_ms = max(0, int(round((now - self._last_tick) * 1000)))
        self._last_tick = now
        if elapsed_ms <= 0:
            return
        side = self._active
        remaining = self._remaining[side] - elapsed_ms
        if remaining <= 0:
            self._remaining[side] = 0
            self._flagged = side
            self._state = ClockState.FLAGGED
            self._active = None
            self._last_tick = None
        else:
            self._remaining[side] = remaining

    @staticmethod
    def _validate_side(side: str) -> None:
        if side not in ("w", "b"):
            raise ClockError("side must be 'w' or 'b'")
