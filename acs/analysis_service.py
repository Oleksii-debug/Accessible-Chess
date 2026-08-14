from __future__ import annotations

"""Presentation-neutral Stockfish analysis coordinator for the 0.4 UI.

The WebView document must never announce analysis that belongs to an older
position.  This service gives every request a generation and discards the
result when the position has changed while Stockfish was thinking.
"""

from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable


@dataclass(frozen=True)
class AnalysisLine:
    multipv: int
    depth: int
    score_kind: str
    score_value: int
    pv: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "multipv": self.multipv,
            "depth": self.depth,
            "scoreKind": self.score_kind,
            "scoreValue": self.score_value,
            "pv": list(self.pv),
        }


@dataclass(frozen=True)
class AnalysisResult:
    fen: str
    generation: int
    stale: bool
    lines: tuple[AnalysisLine, ...]
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "fen": self.fen,
            "generation": self.generation,
            "stale": self.stale,
            "lines": [line.as_dict() for line in self.lines],
            "error": self.error,
        }


class AnalysisService:
    """Coordinates one Stockfish instance and invalidates stale results.

    ``engine_factory`` is intentionally injectable so source tests never need
    a Stockfish binary.  The real application supplies ``UCIEngine``.
    """

    def __init__(self, engine_factory: Callable[[], Any]) -> None:
        self._engine_factory = engine_factory
        self._engine: Any | None = None
        self._generation = 0
        self._current_fen: str | None = None
        self._state_lock = Lock()

    def invalidate(self, fen: str | None = None) -> int:
        """Invalidate in-flight analysis after any board/position change."""
        with self._state_lock:
            self._generation += 1
            self._current_fen = fen
            return self._generation

    def _begin(self, fen: str) -> int:
        with self._state_lock:
            self._generation += 1
            self._current_fen = fen
            return self._generation

    def _is_stale(self, generation: int, fen: str) -> bool:
        with self._state_lock:
            return generation != self._generation or fen != self._current_fen

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16) -> AnalysisResult:
        multipv = max(1, min(10, int(multipv)))
        depth = max(1, min(40, int(depth)))
        generation = self._begin(fen)
        try:
            if self._engine is None:
                self._engine = self._engine_factory()
            raw = self._engine.analyze(fen, multipv=multipv, depth=depth)
            if self._is_stale(generation, fen):
                return AnalysisResult(fen, generation, True, ())
            lines: list[AnalysisLine] = []
            for index, item in enumerate(raw, start=1):
                item_depth, score, pv = item
                score_kind, score_value = score
                lines.append(
                    AnalysisLine(
                        multipv=index,
                        depth=int(item_depth),
                        score_kind=str(score_kind),
                        score_value=int(score_value),
                        pv=tuple(str(move) for move in pv),
                    )
                )
            return AnalysisResult(fen, generation, False, tuple(lines))
        except Exception as exc:
            if self._is_stale(generation, fen):
                return AnalysisResult(fen, generation, True, ())
            return AnalysisResult(fen, generation, False, (), str(exc))

    def close(self) -> None:
        engine = self._engine
        self._engine = None
        if engine is not None:
            try:
                engine.close()
            except Exception:
                pass
