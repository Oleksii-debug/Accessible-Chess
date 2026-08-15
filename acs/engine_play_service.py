from __future__ import annotations

"""Presentation-neutral engine-play application contracts and service.

This module owns engine-game policy (levels, side selection and game handoff
intents) while leaving the concrete UCI/Stockfish process behind
``MoveEnginePort``.  The canonical chess-clock DTO remains ``TimeControl`` from
``clock_service``; this module deliberately does not create a second clock
model.
"""

from dataclasses import dataclass
from enum import Enum
import random
from typing import Callable

from .clock_service import TimeControl
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


class EngineSideMode(str, Enum):
    WHITE = "white"
    BLACK = "black"
    RANDOM = "random"


class EngineGameIntent(str, Enum):
    """Stable application intents emitted by an engine-game presentation.

    Lifecycle intents are consumed by the existing ``GameLifecycle`` service;
    analysis and review intents are handoffs to their respective application
    services.  No intent here mutates board/history/UI state by itself.
    """

    REQUEST_TAKEBACK = "request_takeback"
    ACCEPT_TAKEBACK = "accept_takeback"
    DECLINE_TAKEBACK = "decline_takeback"
    OFFER_DRAW = "offer_draw"
    ACCEPT_DRAW = "accept_draw"
    DECLINE_DRAW = "decline_draw"
    RESIGN = "resign"
    ANALYZE_CURRENT_GAME = "analyze_current_game"
    OPEN_FINAL_REVIEW = "open_final_review"


_PLAYER_INTENTS = frozenset(
    {
        EngineGameIntent.REQUEST_TAKEBACK,
        EngineGameIntent.ACCEPT_TAKEBACK,
        EngineGameIntent.DECLINE_TAKEBACK,
        EngineGameIntent.OFFER_DRAW,
        EngineGameIntent.ACCEPT_DRAW,
        EngineGameIntent.DECLINE_DRAW,
        EngineGameIntent.RESIGN,
    }
)


@dataclass(frozen=True)
class EngineGameConfig:
    """Stable request DTO for starting a local game against an engine."""

    level: int = 5
    engine_side: EngineSideMode | str = EngineSideMode.BLACK
    time_control: TimeControl = TimeControl(0, 0)

    def __post_init__(self) -> None:
        level = int(self.level)
        if level < 1 or level > 10:
            raise ValueError("engine game level must be between 1 and 10")
        object.__setattr__(self, "level", level)
        mode = _normalize_side_mode(self.engine_side)
        object.__setattr__(self, "engine_side", mode)
        if not isinstance(self.time_control, TimeControl):
            raise TypeError("time_control must be clock_service.TimeControl")


@dataclass(frozen=True)
class ResolvedEngineGameConfig:
    """Concrete side + engine policy after resolving a start request."""

    engine_side: str
    level: EngineLevel
    time_control: TimeControl


@dataclass(frozen=True)
class EngineGameHandoff:
    """Validated neutral handoff for local engine-game secondary actions."""

    intent: EngineGameIntent
    actor: str | None = None
    fen: str | None = None
    history_node_id: str | None = None

    def __post_init__(self) -> None:
        try:
            intent = self.intent if isinstance(self.intent, EngineGameIntent) else EngineGameIntent(str(self.intent))
        except ValueError as exc:
            raise ValueError("unknown engine game intent") from exc
        object.__setattr__(self, "intent", intent)

        if intent in _PLAYER_INTENTS:
            if self.actor not in {"w", "b"}:
                raise ValueError("player lifecycle intent requires actor 'w' or 'b'")
        elif self.actor is not None and self.actor not in {"w", "b"}:
            raise ValueError("actor must be 'w', 'b', or None")

        if intent is EngineGameIntent.ANALYZE_CURRENT_GAME:
            fen = "" if self.fen is None else str(self.fen).strip()
            if not fen:
                raise ValueError("analyze-current-game handoff requires fen")
            object.__setattr__(self, "fen", fen)

        if intent is EngineGameIntent.OPEN_FINAL_REVIEW:
            node_id = "" if self.history_node_id is None else str(self.history_node_id).strip()
            if not node_id:
                raise ValueError("final-review handoff requires history_node_id")
            object.__setattr__(self, "history_node_id", node_id)


def level_policy(level: int) -> EngineLevel:
    level = max(1, min(10, int(level)))
    return _LEVELS[level - 1]


def _normalize_side_mode(mode: EngineSideMode | str) -> EngineSideMode:
    if isinstance(mode, EngineSideMode):
        return mode
    normalized = str(mode).strip().lower()
    aliases = {
        "white": EngineSideMode.WHITE,
        "w": EngineSideMode.WHITE,
        "black": EngineSideMode.BLACK,
        "b": EngineSideMode.BLACK,
        "random": EngineSideMode.RANDOM,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("engine side must be white, black, or random") from exc


def choose_engine_side(
    mode: EngineSideMode | str,
    *,
    random_choice: Callable[[tuple[str, str]], str] | None = None,
) -> str:
    """Resolve ``white``, ``black`` or ``random`` to ``w``/``b``.

    ``random_choice`` is injectable for deterministic tests.
    """

    resolved_mode = _normalize_side_mode(mode)
    if resolved_mode is EngineSideMode.WHITE:
        return "w"
    if resolved_mode is EngineSideMode.BLACK:
        return "b"
    chooser = random_choice or random.choice
    result = chooser(("w", "b"))
    if result not in {"w", "b"}:
        raise ValueError("random side chooser must return 'w' or 'b'")
    return result


def resolve_engine_game_config(
    config: EngineGameConfig,
    *,
    random_choice: Callable[[tuple[str, str]], str] | None = None,
) -> ResolvedEngineGameConfig:
    """Resolve a start request without creating an engine or mutating a game."""

    if not isinstance(config, EngineGameConfig):
        raise TypeError("config must be EngineGameConfig")
    return ResolvedEngineGameConfig(
        engine_side=choose_engine_side(config.engine_side, random_choice=random_choice),
        level=level_policy(config.level),
        time_control=config.time_control,
    )


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
