from __future__ import annotations

"""Presentation-neutral engine-play application contracts and service.

This module owns engine-game policy (levels, side selection and game handoff
intents) while leaving the concrete UCI/Stockfish process behind
``MoveEnginePort``. The canonical chess-clock DTO remains ``TimeControl`` from
``clock_service``; this module deliberately does not create a second clock
model.
"""

from dataclasses import dataclass
from enum import Enum
import random
import threading
from typing import Callable

from .clock_service import TimeControl
from .engine_ports import (
    ENGINE_MAX_FEN_LENGTH,
    EngineContractError,
    EngineContractErrorCode,
    EngineMoveRequest,
    EngineMoveResult,
    MoveEnginePort,
)
from .game_lifecycle import GameLifecycle, LifecycleSnapshot


@dataclass(frozen=True)
class EngineLevel:
    level: int
    skill_level: int
    movetime_ms: int

    def __post_init__(self) -> None:
        fields = (self.level, self.skill_level, self.movetime_ms)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in fields):
            raise EngineContractError(
                "engine level policy fields must be integers",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if not 1 <= self.level <= 10 or not 0 <= self.skill_level <= 20:
            raise EngineContractError(
                "engine level policy is outside supported bounds",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if self.movetime_ms < 50:
            raise EngineContractError(
                "engine level movetime_ms must be at least 50",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )


_LEVELS: tuple[EngineLevel, ...] = (
    EngineLevel(1, 0, 100), EngineLevel(2, 2, 150), EngineLevel(3, 4, 225),
    EngineLevel(4, 6, 325), EngineLevel(5, 8, 450), EngineLevel(6, 11, 650),
    EngineLevel(7, 14, 900), EngineLevel(8, 16, 1250), EngineLevel(9, 18, 1750),
    EngineLevel(10, 20, 2500),
)


class EngineSideMode(str, Enum):
    WHITE = "white"
    BLACK = "black"
    RANDOM = "random"


class EngineGameIntent(str, Enum):
    REQUEST_TAKEBACK = "request_takeback"
    ACCEPT_TAKEBACK = "accept_takeback"
    DECLINE_TAKEBACK = "decline_takeback"
    OFFER_DRAW = "offer_draw"
    ACCEPT_DRAW = "accept_draw"
    DECLINE_DRAW = "decline_draw"
    RESIGN = "resign"
    ANALYZE_CURRENT_GAME = "analyze_current_game"
    OPEN_FINAL_REVIEW = "open_final_review"


_PLAYER_INTENTS = frozenset({
    EngineGameIntent.REQUEST_TAKEBACK, EngineGameIntent.ACCEPT_TAKEBACK,
    EngineGameIntent.DECLINE_TAKEBACK, EngineGameIntent.OFFER_DRAW,
    EngineGameIntent.ACCEPT_DRAW, EngineGameIntent.DECLINE_DRAW,
    EngineGameIntent.RESIGN,
})


@dataclass(frozen=True)
class EngineGameConfig:
    level: int = 5
    engine_side: EngineSideMode | str = EngineSideMode.BLACK
    time_control: TimeControl = TimeControl(0, 0)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.level, int)
            or isinstance(self.level, bool)
            or not 1 <= self.level <= 10
        ):
            raise EngineContractError(
                "engine game level must be an integer between 1 and 10",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        object.__setattr__(self, "engine_side", _normalize_side_mode(self.engine_side))
        if not isinstance(self.time_control, TimeControl):
            raise EngineContractError(
                "time_control must be clock_service.TimeControl",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )


@dataclass(frozen=True)
class ResolvedEngineGameConfig:
    engine_side: str
    level: EngineLevel
    time_control: TimeControl

    def __post_init__(self) -> None:
        if not isinstance(self.engine_side, str) or self.engine_side not in {"w", "b"}:
            raise EngineContractError(
                "resolved engine side must be 'w' or 'b'",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if not isinstance(self.level, EngineLevel):
            raise EngineContractError(
                "resolved level must be an EngineLevel",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if not isinstance(self.time_control, TimeControl):
            raise EngineContractError(
                "resolved time_control must be a TimeControl",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )


@dataclass(frozen=True)
class EngineGameHandoff:
    intent: EngineGameIntent
    actor: str | None = None
    fen: str | None = None
    history_node_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.intent, (EngineGameIntent, str)):
            raise EngineContractError(
                "engine game intent must be EngineGameIntent or text",
                code=EngineContractErrorCode.INVALID_HANDOFF,
            )
        try:
            intent = (
                self.intent
                if isinstance(self.intent, EngineGameIntent)
                else EngineGameIntent(self.intent.strip())
            )
        except ValueError as exc:
            raise EngineContractError(
                "unknown engine game intent",
                code=EngineContractErrorCode.INVALID_HANDOFF,
            ) from exc
        object.__setattr__(self, "intent", intent)
        if intent in _PLAYER_INTENTS:
            if not isinstance(self.actor, str) or self.actor not in {"w", "b"}:
                raise EngineContractError(
                    "player lifecycle intent requires actor 'w' or 'b'",
                    code=EngineContractErrorCode.INVALID_HANDOFF,
                )
            if self.fen is not None or self.history_node_id is not None:
                raise EngineContractError(
                    "player lifecycle handoff cannot carry position or history data",
                    code=EngineContractErrorCode.INVALID_HANDOFF,
                )
        if intent is EngineGameIntent.ANALYZE_CURRENT_GAME:
            if self.actor is not None or self.history_node_id is not None:
                raise EngineContractError(
                    "analysis handoff cannot carry actor or history data",
                    code=EngineContractErrorCode.INVALID_HANDOFF,
                )
            if not isinstance(self.fen, str):
                raise EngineContractError(
                    "analyze-current-game handoff requires fen text within bounds",
                    code=EngineContractErrorCode.INVALID_HANDOFF,
                )
            fen = self.fen.strip()
            if not fen or len(fen) > ENGINE_MAX_FEN_LENGTH:
                raise EngineContractError(
                    "analyze-current-game handoff requires fen text within bounds",
                    code=EngineContractErrorCode.INVALID_HANDOFF,
                )
            object.__setattr__(self, "fen", fen)
        if intent is EngineGameIntent.OPEN_FINAL_REVIEW:
            if self.actor is not None or self.fen is not None:
                raise EngineContractError(
                    "final-review handoff cannot carry actor or position data",
                    code=EngineContractErrorCode.INVALID_HANDOFF,
                )
            if (
                not isinstance(self.history_node_id, str)
                or not self.history_node_id.strip()
            ):
                raise EngineContractError(
                    "final-review handoff requires history_node_id text",
                    code=EngineContractErrorCode.INVALID_HANDOFF,
                )
            node_id = self.history_node_id.strip()
            object.__setattr__(self, "history_node_id", node_id)


def level_policy(level: int) -> EngineLevel:
    if not isinstance(level, int) or isinstance(level, bool):
        raise EngineContractError(
            "engine level must be an integer",
            code=EngineContractErrorCode.INVALID_CONFIG,
        )
    level = max(1, min(10, level))
    return _LEVELS[level - 1]


def _normalize_side_mode(mode: EngineSideMode | str) -> EngineSideMode:
    if isinstance(mode, EngineSideMode):
        return mode
    if not isinstance(mode, str):
        raise EngineContractError(
            "engine side must be white, black, or random",
            code=EngineContractErrorCode.INVALID_CONFIG,
        )
    aliases = {"white": EngineSideMode.WHITE, "w": EngineSideMode.WHITE,
               "black": EngineSideMode.BLACK, "b": EngineSideMode.BLACK,
               "random": EngineSideMode.RANDOM}
    try:
        return aliases[mode.strip().lower()]
    except KeyError as exc:
        raise EngineContractError(
            "engine side must be white, black, or random",
            code=EngineContractErrorCode.INVALID_CONFIG,
        ) from exc


def choose_engine_side(
    mode: EngineSideMode | str,
    *,
    random_choice: Callable[[tuple[str, str]], str] | None = None,
) -> str:
    if random_choice is not None and not callable(random_choice):
        raise EngineContractError(
            "random side chooser must be callable",
            code=EngineContractErrorCode.INVALID_PROVIDER,
        )
    resolved_mode = _normalize_side_mode(mode)
    if resolved_mode is EngineSideMode.WHITE:
        return "w"
    if resolved_mode is EngineSideMode.BLACK:
        return "b"
    chooser = random.choice if random_choice is None else random_choice
    result = chooser(("w", "b"))
    if not isinstance(result, str) or result not in {"w", "b"}:
        raise EngineContractError(
            "random side chooser must return 'w' or 'b'",
            code=EngineContractErrorCode.INVALID_PROVIDER,
        )
    return result


def resolve_engine_game_config(
    config: EngineGameConfig,
    *,
    random_choice: Callable[[tuple[str, str]], str] | None = None,
) -> ResolvedEngineGameConfig:
    if not isinstance(config, EngineGameConfig):
        raise TypeError("config must be EngineGameConfig")
    return ResolvedEngineGameConfig(
        engine_side=choose_engine_side(config.engine_side, random_choice=random_choice),
        level=level_policy(config.level), time_control=config.time_control,
    )


def dispatch_lifecycle_handoff(
    lifecycle: GameLifecycle,
    handoff: EngineGameHandoff,
) -> LifecycleSnapshot:
    if not isinstance(lifecycle, GameLifecycle):
        raise TypeError("lifecycle must be GameLifecycle")
    if not isinstance(handoff, EngineGameHandoff):
        raise TypeError("handoff must be EngineGameHandoff")
    if handoff.intent not in _PLAYER_INTENTS:
        raise ValueError("handoff is not a lifecycle intent")
    actor = handoff.actor
    assert actor in {"w", "b"}
    operations = {
        EngineGameIntent.REQUEST_TAKEBACK: lifecycle.request_takeback,
        EngineGameIntent.ACCEPT_TAKEBACK: lifecycle.accept_takeback,
        EngineGameIntent.DECLINE_TAKEBACK: lifecycle.decline_takeback,
        EngineGameIntent.OFFER_DRAW: lifecycle.offer_draw,
        EngineGameIntent.ACCEPT_DRAW: lifecycle.accept_draw,
        EngineGameIntent.DECLINE_DRAW: lifecycle.decline_draw,
        EngineGameIntent.RESIGN: lifecycle.resign,
    }
    return operations[handoff.intent](actor)


class EnginePlayService:
    """Serialized, terminal-close coordinator for one move-engine provider."""

    def __init__(
        self,
        engine_factory: Callable[[], MoveEnginePort],
        *,
        owns_engine: bool = True,
    ) -> None:
        if not callable(engine_factory):
            raise EngineContractError(
                "engine_factory must be callable",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        if not isinstance(owns_engine, bool):
            raise EngineContractError(
                "owns_engine must be boolean",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        self._engine_factory = engine_factory
        self._engine: MoveEnginePort | None = None
        self._owns_engine = owns_engine
        self._lock = threading.RLock()
        self._closed = False

    def choose_move(self, request: EngineMoveRequest) -> EngineMoveResult:
        if not isinstance(request, EngineMoveRequest):
            raise TypeError("request must be EngineMoveRequest")
        policy = level_policy(request.level)
        movetime_ms = (
            policy.movetime_ms
            if request.movetime_ms is None
            else max(50, request.movetime_ms)
        )

        # Provider creation and the complete stateful best-move transaction are
        # serialized. close() takes the same lock, so it cannot close a provider
        # while an in-flight request is using it and no request can resurrect a
        # provider after terminal close.
        with self._lock:
            if self._closed:
                raise EngineContractError(
                    "engine play service is closed",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
            if self._engine is None:
                engine = self._engine_factory()
                if (
                    isinstance(engine, type)
                    or not isinstance(engine, MoveEnginePort)
                    or not callable(getattr(engine, "best_move", None))
                    or not callable(getattr(engine, "close", None))
                ):
                    raise EngineContractError(
                        "engine factory returned an incompatible move provider",
                        code=EngineContractErrorCode.INVALID_PROVIDER,
                    )
                self._engine = engine
            move = self._engine.best_move(
                request.fen,
                skill_level=policy.skill_level,
                movetime_ms=movetime_ms,
            )
            return EngineMoveResult(
                move=move,
                level=policy.level,
                movetime_ms=movetime_ms,
            )

    def close(self) -> None:
        # Terminal close is deliberately monotonic. Holding the same lock used
        # by choose_move means close waits for any in-flight provider operation,
        # then prevents all future factory/provider use. An owned provider is
        # retained until cleanup succeeds so a transient close failure can be
        # retried without reopening the service or recreating the provider.
        with self._lock:
            if self._closed and self._engine is None:
                return
            self._closed = True
            engine = self._engine
            if not self._owns_engine or engine is None:
                self._engine = None
                return
            try:
                engine.close()
            except Exception as exc:
                raise EngineContractError(
                    "engine provider cleanup failed",
                    code=EngineContractErrorCode.INVALID_PROVIDER,
                ) from exc
            self._engine = None
