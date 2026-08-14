from __future__ import annotations

"""Presentation-neutral engine contracts for Accessible Chess.

Core/application code depends on these protocols and DTOs, never on the
Stockfish subprocess implementation.  A Stockfish adapter, another UCI engine,
or a deterministic test double can implement the same ports.
"""

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class RawAnalysisLine:
    depth: int
    score_kind: str
    score_value: int
    pv: tuple[str, ...]


@dataclass(frozen=True)
class EngineMoveRequest:
    fen: str
    level: int = 5
    movetime_ms: int | None = None


@dataclass(frozen=True)
class EngineMoveResult:
    move: str | None
    level: int
    movetime_ms: int


@runtime_checkable
class AnalysisEnginePort(Protocol):
    def analyze(self, fen: str, multipv: int = 5, depth: int = 16) -> Sequence[object]:
        """Return one raw analysis item per PV.

        Existing UCIEngine compatibility is preserved: each item may be the
        legacy tuple ``(depth, (score_kind, score_value), pv_moves)``.
        Adapters may later return ``RawAnalysisLine`` directly.
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
