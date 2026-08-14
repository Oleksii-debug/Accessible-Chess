from __future__ import annotations

"""Presentation-neutral engine-play application service.

This module owns policy (levels, side selection and move-time defaults) while
leaving the concrete UCI/Stockfish process behind ``MoveEnginePort``.
"""

from dataclasses import dataclass
import random
from typing import Callable

from .engine_ports import EngineMoveRequest, EngineMoveResult, MoveEnginePort


@dataclass(frozen=True)
class EngineLevel:
    level: int
    skill_level: int
    movetime_ms: int


# User-facing levels 1..10 map to Stockfish/UCI skill 0..20 and bounded think
# times.  The policy is centralized here so UI code never embeds engine tuning.
_LEVELS: tuple[EngineLevel, ...] = (
    EngineLevel(1, 0, 100),
    EngineLevel(2, 2, 150),
    EngineLevel(3, 4, 225),
    EngineLevel(4, 6, 325),
    EngineLevel(5, 8, 450),
    EngineLevel(6, 11, 650),
    EngineLevel(7, 14, 900),
    EngineLevel(8, 16, 1250),
    EngineLevel(9, 18, 1750),
    EngineLevel(10, 20, 2500),
)


def level_policy(level: int) -> EngineLevel:
    level = max(1, min(10, int(level)))
    return _LEVELS[level - 1]


def choose_engine_side(mode: str, *, random_choice: Callable[[tuple[str, str]], str] | None = None) -> str:
    """Resolve ``white``, ``black`` or ``random`` to ``w``/``b``.

    ``random_choice`` is injectable for deterministic tests.
    """

    normalized = str(mode).strip().lower()
    if normalized in {"white", "w"}:
        return "w"
    if normalized in {"black", "b"}:
        return "b"
    if normalized == "random":
        chooser = random_choice or random.choice
        result = chooser(("w", "b"))
        if result not in {"w", "b"}:
            raise ValueError("random side chooser must return 'w' or 'b'")
        return result
    raise ValueError("engine side must be white, black, or random")


class EnginePlayService:
    def __init__(self, engine_factory: Callable[[], MoveEnginePort]) -> None:
        self._engine_factory = engine_factory
        self._engine: MoveEnginePort | None = None

    def choose_move(self, request: EngineMoveRequest) -> EngineMoveResult:
        if not str(request.fen).strip():
            raise ValueError("fen must not be empty")
        policy = level_policy(request.level)
        movetime_ms = policy.movetime_ms if request.movetime_ms is None else max(50, int(request.movetime_ms))
        if self._engine is None:
            self._engine = self._engine_factory()
        move = self._engine.best_move(
            str(request.fen).strip(),
            skill_level=policy.skill_level,
            movetime_ms=movetime_ms,
        )
        return EngineMoveResult(move=move, level=policy.level, movetime_ms=movetime_ms)

    def close(self) -> None:
        engine = self._engine
        self._engine = None
        if engine is not None:
            try:
                engine.close()
            except Exception:
                pass
