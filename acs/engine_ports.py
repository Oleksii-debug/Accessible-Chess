from __future__ import annotations

"""Presentation-neutral engine contracts for Accessible Chess.

Core/application code depends on these protocols and DTOs, never on the
Stockfish subprocess implementation.  A Stockfish adapter, another UCI engine,
or a deterministic test double can implement the same ports.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence, runtime_checkable


ENGINE_FEN_MAX_LENGTH = 512
ENGINE_MOVE_MAX_MOVETIME_MS = 60_000


class EngineContractErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    INVALID_RESULT = "invalid_result"
    INVALID_CONFIG = "invalid_config"
    INVALID_HANDOFF = "invalid_handoff"
    INVALID_PROVIDER = "invalid_provider"
    INVALID_SESSION = "invalid_session"


class EngineContractError(ValueError):
    """Stable failure at a presentation-neutral engine contract boundary."""

    def __init__(self, message: str, *, code: EngineContractErrorCode) -> None:
        super().__init__(message)
        self.code = EngineContractErrorCode(code)


@dataclass(frozen=True)
class RawAnalysisLine:
    depth: int
    score_kind: str
    score_value: int
    pv: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.depth, int)
            or isinstance(self.depth, bool)
            or self.depth < 0
        ):
            raise EngineContractError(
                "analysis depth must be a non-negative integer",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.score_kind, str):
            raise EngineContractError(
                "analysis score kind must be text",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        score_kind = self.score_kind.strip()
        if score_kind not in {"cp", "mate"}:
            raise EngineContractError(
                "analysis score kind must be 'cp' or 'mate'",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.score_value, int) or isinstance(
            self.score_value,
            bool,
        ):
            raise EngineContractError(
                "analysis score value must be an integer",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.pv, tuple):
            raise EngineContractError(
                "analysis PV must be a tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        moves: list[str] = []
        for move in self.pv:
            if not isinstance(move, str) or not move.strip():
                raise EngineContractError(
                    "analysis PV moves must be non-empty text",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            moves.append(move.strip())
        object.__setattr__(self, "score_kind", score_kind)
        object.__setattr__(self, "pv", tuple(moves))


LegacyAnalysisLine = tuple[int, tuple[str, int], Sequence[str]]
AnalysisProviderLine = RawAnalysisLine | LegacyAnalysisLine


@dataclass(frozen=True)
class EngineMoveRequest:
    fen: str
    level: int = 5
    movetime_ms: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.fen, str):
            raise EngineContractError(
                "engine move request FEN must be bounded non-empty text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        normalized_fen = self.fen.strip()
        if not normalized_fen or len(normalized_fen) > ENGINE_FEN_MAX_LENGTH:
            raise EngineContractError(
                "engine move request FEN must be bounded non-empty text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if not isinstance(self.level, int) or isinstance(self.level, bool):
            raise EngineContractError(
                "engine move request level must be an integer",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if self.movetime_ms is not None and (
            not isinstance(self.movetime_ms, int)
            or isinstance(self.movetime_ms, bool)
        ):
            raise EngineContractError(
                "engine move request movetime_ms must be an integer or None",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if (
            self.movetime_ms is not None
            and self.movetime_ms > ENGINE_MOVE_MAX_MOVETIME_MS
        ):
            raise EngineContractError(
                "engine move request movetime_ms exceeds supported bound",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        object.__setattr__(self, "fen", normalized_fen)


@dataclass(frozen=True)
class EngineMoveResult:
    move: str | None
    level: int
    movetime_ms: int

    def __post_init__(self) -> None:
        if self.move is not None:
            if not isinstance(self.move, str) or not self.move.strip():
                raise EngineContractError(
                    "engine move result must contain non-empty move text or None",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            object.__setattr__(self, "move", self.move.strip())
        if (
            not isinstance(self.level, int)
            or isinstance(self.level, bool)
            or not 1 <= self.level <= 10
        ):
            raise EngineContractError(
                "engine move result level must be an integer between 1 and 10",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if (
            not isinstance(self.movetime_ms, int)
            or isinstance(self.movetime_ms, bool)
            or not 50 <= self.movetime_ms <= ENGINE_MOVE_MAX_MOVETIME_MS
        ):
            raise EngineContractError(
                "engine move result movetime_ms must be between 50 and 60000",
                code=EngineContractErrorCode.INVALID_RESULT,
            )


@runtime_checkable
class AnalysisEnginePort(Protocol):
    def analyze(
        self,
        fen: str,
        multipv: int = 5,
        depth: int = 16,
    ) -> Sequence[AnalysisProviderLine]:
        """Return one raw analysis item per PV.

        Existing UCIEngine compatibility is preserved: each item may be the
        bounded legacy tuple ``(depth, (score_kind, score_value), pv_moves)``.
        New adapters should return ``RawAnalysisLine`` directly.
        """

    def close(self) -> None:
        """Release engine resources. Implementations should be idempotent."""


@runtime_checkable
class MoveEnginePort(Protocol):
    def best_move(self, fen: str, skill_level: int = 10, movetime_ms: int = 500) -> str | None:
        """Return a UCI move or None when the position has no legal move."""

    def close(self) -> None:
        """Release engine resources. Implementations should be idempotent."""


@runtime_checkable
class ChessEnginePort(AnalysisEnginePort, MoveEnginePort, Protocol):
    """Combined port implemented by a full engine adapter."""
