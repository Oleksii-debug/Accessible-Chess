from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class ClockErrorCode(str, Enum):
    INVALID_CONTROL = "invalid_control"
    INVALID_COMMAND = "invalid_command"
    INVALID_STATE = "invalid_state"
    INVALID_SNAPSHOT = "invalid_snapshot"
    INVALID_TIME_SOURCE = "invalid_time_source"


class ClockError(ValueError):
    """Raised when a clock operation violates the game-clock contract."""

    def __init__(
        self,
        message: str,
        *,
        code: ClockErrorCode = ClockErrorCode.INVALID_COMMAND,
    ) -> None:
        super().__init__(message)
        self.code = ClockErrorCode(code)


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
        for field_name in ("initial_ms", "increment_ms"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ClockError(
                    f"{field_name} must be a non-negative integer",
                    code=ClockErrorCode.INVALID_CONTROL,
                )
        if self.initial_ms == 0 and self.increment_ms != 0:
            raise ClockError(
                "untimed control cannot carry an increment",
                code=ClockErrorCode.INVALID_CONTROL,
            )

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

    def __post_init__(self) -> None:
        _validate_snapshot_fields(self)

    def remaining(self, side: str) -> int:
        if side == "w":
            return self.white_ms
        if side == "b":
            return self.black_ms
        raise ClockError(
            "side must be 'w' or 'b'",
            code=ClockErrorCode.INVALID_COMMAND,
        )


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
        if not isinstance(control, TimeControl):
            raise ClockError(
                "control must be a TimeControl",
                code=ClockErrorCode.INVALID_CONTROL,
            )
        if not callable(now):
            raise ClockError(
                "now must be callable",
                code=ClockErrorCode.INVALID_TIME_SOURCE,
            )
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
            raise ClockError(
                "cannot start a flagged clock; reset first",
                code=ClockErrorCode.INVALID_STATE,
            )
        self._sync()
        if self._state is not ClockState.STOPPED:
            raise ClockError(
                "clock must be stopped before start",
                code=ClockErrorCode.INVALID_STATE,
            )
        tick = self._read_now()
        self._active = side
        self._state = ClockState.RUNNING
        self._last_tick = tick
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
            raise ClockError(
                "cannot resume a flagged clock; reset first",
                code=ClockErrorCode.INVALID_STATE,
            )
        if self._active is None:
            raise ClockError(
                "cannot resume before a side has been selected",
                code=ClockErrorCode.INVALID_STATE,
            )
        if self._state == ClockState.PAUSED:
            tick = self._read_now()
            self._state = ClockState.RUNNING
            self._last_tick = tick
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
            raise ClockError(
                "clock must be running to switch after a move",
                code=ClockErrorCode.INVALID_STATE,
            )
        if self._active != moved_side:
            raise ClockError(
                "moved_side does not match the active clock",
                code=ClockErrorCode.INVALID_COMMAND,
            )

        tick = self._read_now(not_before=self._last_tick)
        self._remaining[moved_side] += self.control.increment_ms
        self._active = "b" if moved_side == "w" else "w"
        self._last_tick = tick
        return self.snapshot()

    def set_remaining(self, side: str, milliseconds: int) -> ClockSnapshot:
        """Administrative/game-restore hook; never changes whose clock is active."""
        self._validate_side(side)
        if (
            not isinstance(milliseconds, int)
            or isinstance(milliseconds, bool)
            or milliseconds < 0
        ):
            raise ClockError(
                "milliseconds must be a non-negative integer",
                code=ClockErrorCode.INVALID_COMMAND,
            )
        self._sync()
        self._remaining[side] = milliseconds
        if self._state == ClockState.FLAGGED and self._flagged == side and milliseconds > 0:
            self._flagged = None
            self._state = ClockState.PAUSED if self._active is not None else ClockState.STOPPED
        return self.snapshot()

    def restore(self, snapshot: ClockSnapshot, *, resume_running: bool = False) -> ClockSnapshot:
        """Restore a validated historical clock snapshot without owning history.

        A snapshot captured while running is restored paused by default so time
        cannot leak while a destructive undo/redo operation is still being
        coordinated. ``resume_running=True`` resumes it from the current
        monotonic instant after the restore is complete.
        """
        if not isinstance(snapshot, ClockSnapshot):
            raise ClockError(
                "snapshot must be a ClockSnapshot",
                code=ClockErrorCode.INVALID_SNAPSHOT,
            )
        if not isinstance(resume_running, bool):
            raise ClockError(
                "resume_running must be boolean",
                code=ClockErrorCode.INVALID_COMMAND,
            )
        self._validate_snapshot(snapshot)
        if self.control.untimed:
            if snapshot != ClockSnapshot(0, 0, None, ClockState.STOPPED):
                raise ClockError(
                    "untimed clock requires the canonical stopped zero snapshot",
                    code=ClockErrorCode.INVALID_SNAPSHOT,
                )
            self._remaining = {"w": 0, "b": 0}
            self._active = None
            self._flagged = None
            self._state = ClockState.STOPPED
            self._last_tick = None
            return self.snapshot()

        resume_tick = None
        if snapshot.state is ClockState.RUNNING and resume_running:
            resume_tick = self._read_now()

        self._remaining = {"w": snapshot.white_ms, "b": snapshot.black_ms}
        self._active = snapshot.active
        self._flagged = snapshot.flagged
        self._last_tick = None

        if snapshot.state is ClockState.RUNNING:
            self._state = ClockState.PAUSED
            if resume_running:
                self._state = ClockState.RUNNING
                self._last_tick = resume_tick
        else:
            self._state = snapshot.state
        return self.snapshot()

    def reset(self, *, side_to_move: str | None = None) -> ClockSnapshot:
        if side_to_move is not None:
            self._validate_side(side_to_move)
        self._remaining = {"w": self.control.initial_ms, "b": self.control.initial_ms}
        self._flagged = None
        if self.control.untimed or side_to_move is None:
            self._active = None
            self._state = ClockState.STOPPED
            self._last_tick = None
        else:
            self._active = side_to_move
            self._state = ClockState.PAUSED
            self._last_tick = None
        return self.snapshot()

    def _sync(self) -> None:
        if self._state != ClockState.RUNNING or self._active is None or self._last_tick is None:
            return
        now = self._read_now(not_before=self._last_tick)
        elapsed_ms = int((now - self._last_tick) * 1000)
        if elapsed_ms <= 0:
            return
        self._last_tick += elapsed_ms / 1000
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

    @classmethod
    def _validate_snapshot(cls, snapshot: ClockSnapshot) -> None:
        _validate_snapshot_fields(snapshot)

    @staticmethod
    def _validate_side(side: str) -> None:
        if not isinstance(side, str) or side not in ("w", "b"):
            raise ClockError(
                "side must be 'w' or 'b'",
                code=ClockErrorCode.INVALID_COMMAND,
            )

    def _read_now(self, *, not_before: float | None = None) -> float:
        value = self._now()
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ClockError(
                "monotonic time source must return a finite number",
                code=ClockErrorCode.INVALID_TIME_SOURCE,
            )
        instant = float(value)
        if not_before is not None and instant < not_before:
            raise ClockError(
                "monotonic time source moved backwards",
                code=ClockErrorCode.INVALID_TIME_SOURCE,
            )
        return instant


def _validate_snapshot_fields(snapshot: ClockSnapshot) -> None:
    for field_name in ("white_ms", "black_ms"):
        value = getattr(snapshot, field_name)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ClockError(
                "snapshot remaining time must be non-negative integers",
                code=ClockErrorCode.INVALID_SNAPSHOT,
            )
    if not isinstance(snapshot.state, ClockState):
        raise ClockError(
            "snapshot state must be a ClockState",
            code=ClockErrorCode.INVALID_SNAPSHOT,
        )
    for field_name in ("active", "flagged"):
        value = getattr(snapshot, field_name)
        if value is not None and (
            not isinstance(value, str) or value not in {"w", "b"}
        ):
            raise ClockError(
                f"snapshot {field_name} must be 'w', 'b', or None",
                code=ClockErrorCode.INVALID_SNAPSHOT,
            )
    if snapshot.state in {ClockState.RUNNING, ClockState.PAUSED}:
        if snapshot.active is None:
            raise ClockError(
                "running or paused snapshot requires an active side",
                code=ClockErrorCode.INVALID_SNAPSHOT,
            )
    elif snapshot.active is not None:
        raise ClockError(
            "stopped or flagged snapshot must not have an active side",
            code=ClockErrorCode.INVALID_SNAPSHOT,
        )
    if snapshot.state is ClockState.FLAGGED:
        if snapshot.flagged is None:
            raise ClockError(
                "flagged snapshot requires a flagged side",
                code=ClockErrorCode.INVALID_SNAPSHOT,
            )
        remaining = (
            snapshot.white_ms if snapshot.flagged == "w" else snapshot.black_ms
        )
        if remaining != 0:
            raise ClockError(
                "flagged side must have zero remaining time",
                code=ClockErrorCode.INVALID_SNAPSHOT,
            )
    elif snapshot.flagged is not None:
        raise ClockError(
            "only flagged snapshots may carry a flagged side",
            code=ClockErrorCode.INVALID_SNAPSHOT,
        )
