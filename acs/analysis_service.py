from __future__ import annotations

"""Presentation-neutral engine analysis coordinator.

The UI must never announce analysis that belongs to an older position. This
service gives every request a generation and discards the result when the
position has changed while an engine provider was thinking.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock, RLock
from typing import Any, Callable

from .engine_ports import (
    AnalysisEnginePort,
    EngineContractError,
    EngineContractErrorCode,
    RawAnalysisLine,
)


@dataclass(frozen=True)
class AnalysisLine:
    multipv: int
    depth: int
    score_kind: str
    score_value: int
    pv: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.multipv, int)
            or isinstance(self.multipv, bool)
            or not 1 <= self.multipv <= 10
        ):
            raise EngineContractError(
                "analysis multipv index must be an integer between 1 and 10",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        raw = RawAnalysisLine(
            self.depth,
            self.score_kind,
            self.score_value,
            self.pv,
        )
        object.__setattr__(self, "score_kind", raw.score_kind)
        object.__setattr__(self, "pv", raw.pv)

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

    def __post_init__(self) -> None:
        if not isinstance(self.fen, str) or not self.fen.strip():
            raise EngineContractError(
                "analysis result FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if (
            not isinstance(self.generation, int)
            or isinstance(self.generation, bool)
            or self.generation < 0
        ):
            raise EngineContractError(
                "analysis generation must be a non-negative integer",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.stale, bool):
            raise EngineContractError(
                "analysis stale flag must be boolean",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.lines, tuple) or any(
            not isinstance(line, AnalysisLine) for line in self.lines
        ):
            raise EngineContractError(
                "analysis result lines must be an AnalysisLine tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if self.error is not None:
            if not isinstance(self.error, str) or not self.error.strip():
                raise EngineContractError(
                    "analysis error must be non-empty text or None",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            object.__setattr__(self, "error", self.error.strip())
        if self.lines and (self.stale or self.error is not None):
            raise EngineContractError(
                "stale or failed analysis cannot carry lines",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        object.__setattr__(self, "fen", self.fen.strip())

    def as_dict(self) -> dict[str, Any]:
        return {
            "fen": self.fen,
            "generation": self.generation,
            "stale": self.stale,
            "lines": [line.as_dict() for line in self.lines],
            "error": self.error,
        }


class AnalysisService:
    """Coordinates one engine provider and invalidates stale results.

    ``engine_factory`` is injectable so source tests never need a Stockfish
    binary. ``owns_engine=False`` is used by the production shared runtime: the
    runtime then owns provider shutdown and multiple services cannot close each
    other's subprocess.

    Engine construction, analysis calls and owned-provider shutdown are
    serialized. This matters even though stale-result generations are
    presentation-neutral: a single UCI provider is a stateful command stream and
    must never receive concurrent requests or be closed while a request is using
    it.
    """

    CLOSED_ERROR = "analysis service is closed"

    def __init__(
        self,
        engine_factory: Callable[[], AnalysisEnginePort],
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
        self._engine: AnalysisEnginePort | None = None
        self._owns_engine = owns_engine
        self._generation = 0
        self._current_fen: str | None = None
        self._closed = False
        self._state_lock = Lock()
        self._engine_lock = RLock()

    def invalidate(self, fen: str | None = None) -> int:
        """Invalidate in-flight analysis after any board/position change."""
        normalized_fen = None if fen is None else self._normalize_fen(fen)
        with self._state_lock:
            self._generation += 1
            self._current_fen = normalized_fen
            return self._generation

    def _begin(self, fen: str) -> tuple[int, bool]:
        with self._state_lock:
            if self._closed:
                return self._generation, True
            self._generation += 1
            self._current_fen = fen
            return self._generation, False

    def _is_stale(self, generation: int, fen: str) -> bool:
        with self._state_lock:
            return generation != self._generation or fen != self._current_fen

    @staticmethod
    def _normalize_line(item: object, multipv: int) -> AnalysisLine:
        if isinstance(item, RawAnalysisLine):
            return AnalysisLine(
                multipv=multipv,
                depth=item.depth,
                score_kind=item.score_kind,
                score_value=item.score_value,
                pv=item.pv,
            )

        if not isinstance(item, tuple) or len(item) != 3:
            raise EngineContractError(
                "legacy analysis line must be a three-item tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        item_depth, score, pv = item
        if not isinstance(score, tuple) or len(score) != 2:
            raise EngineContractError(
                "legacy analysis score must be a two-item tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if isinstance(pv, (str, bytes, bytearray)) or not isinstance(pv, Sequence):
            raise EngineContractError(
                "legacy analysis PV must be a move sequence",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        score_kind, score_value = score
        raw = RawAnalysisLine(
            item_depth,
            score_kind,
            score_value,
            tuple(pv),
        )
        return AnalysisLine(
            multipv=multipv,
            depth=raw.depth,
            score_kind=raw.score_kind,
            score_value=raw.score_value,
            pv=raw.pv,
        )

    @staticmethod
    def _normalize_fen(fen: str) -> str:
        if not isinstance(fen, str) or not fen.strip():
            raise EngineContractError(
                "analysis FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return fen.strip()

    @staticmethod
    def _normalize_limits(multipv: int, depth: int) -> tuple[int, int]:
        for name, value in (("multipv", multipv), ("depth", depth)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise EngineContractError(
                    f"analysis {name} must be an integer",
                    code=EngineContractErrorCode.INVALID_REQUEST,
                )
        return max(1, min(10, multipv)), max(1, min(40, depth))

    @classmethod
    def _snapshot_provider_result(
        cls,
        raw: object,
        multipv: int,
    ) -> tuple[AnalysisLine, ...]:
        if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
            raise EngineContractError(
                "analysis provider must return a sequence",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        items = tuple(raw)
        if len(items) > multipv:
            raise EngineContractError(
                "analysis provider returned more lines than requested",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        return tuple(
            cls._normalize_line(item, index)
            for index, item in enumerate(items, start=1)
        )

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16) -> AnalysisResult:
        fen = self._normalize_fen(fen)
        multipv, depth = self._normalize_limits(multipv, depth)
        generation, closed = self._begin(fen)
        if closed:
            return AnalysisResult(fen, generation, False, (), self.CLOSED_ERROR)

        try:
            with self._engine_lock:
                # close() marks the service closed before waiting on this lock.
                # If shutdown won the race, do not create or reuse a provider.
                with self._state_lock:
                    if self._closed:
                        return AnalysisResult(
                            fen, generation, True, (), self.CLOSED_ERROR
                        )
                if self._engine is None:
                    engine = self._engine_factory()
                    if (
                        isinstance(engine, type)
                        or not isinstance(engine, AnalysisEnginePort)
                        or not callable(getattr(engine, "analyze", None))
                        or not callable(getattr(engine, "close", None))
                    ):
                        raise EngineContractError(
                            "engine factory returned an incompatible analysis provider",
                            code=EngineContractErrorCode.INVALID_PROVIDER,
                        )
                    self._engine = engine
                raw = self._engine.analyze(fen, multipv=multipv, depth=depth)
                lines = self._snapshot_provider_result(raw, multipv)

            if self._is_stale(generation, fen):
                return AnalysisResult(fen, generation, True, ())
            return AnalysisResult(fen, generation, False, lines)
        except Exception as exc:
            if self._is_stale(generation, fen):
                return AnalysisResult(fen, generation, True, ())
            error = str(exc).strip() or type(exc).__name__
            return AnalysisResult(fen, generation, False, (), error)

    def close(self) -> None:
        # Publish shutdown to all request threads before waiting for the
        # stateful provider. This prevents any late analyze() from resurrecting
        # a fresh engine after application shutdown has begun.
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            self._current_fen = None

        with self._engine_lock:
            engine = self._engine
            self._engine = None
            if self._owns_engine and engine is not None:
                try:
                    engine.close()
                except Exception:
                    pass
