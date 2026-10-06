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
    ANALYSIS_MAX_MOVETIME_MS,
    ANALYSIS_MIN_MOVETIME_MS,
    AnalysisEnginePort,
    EngineContractError,
    EngineContractErrorCode,
    RawAnalysisLine,
)
from .input_limits import MAX_FEN_CHARS


ANALYSIS_MAX_LINES = 10
ANALYSIS_MAX_PV_PLIES = 256
ANALYSIS_MAX_ERROR_CHARS = 180


@dataclass(frozen=True)
class AnalysisLine:
    multipv: int
    depth: int
    score_kind: str
    score_value: int
    pv: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.multipv) is not int
            or not 1 <= self.multipv <= ANALYSIS_MAX_LINES
        ):
            raise EngineContractError(
                "analysis multipv index must be an integer between 1 and 10",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if type(self.pv) is not tuple:
            raise EngineContractError(
                "analysis PV must be a tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if len(self.pv) > ANALYSIS_MAX_PV_PLIES:
            raise EngineContractError(
                "analysis PV exceeds supported bound",
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
        # Keep result publication behind the same raw representation budget as
        # canonical Board FEN ingress. Reject active str subclasses and oversized
        # exact text before strip() can execute or scan unbounded input.
        if type(self.fen) is not str or len(self.fen) > MAX_FEN_CHARS:
            raise EngineContractError(
                "analysis result FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        normalized_fen = self.fen.strip()
        if not normalized_fen:
            raise EngineContractError(
                "analysis result FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if (
            type(self.generation) is not int
            or self.generation < 0
        ):
            raise EngineContractError(
                "analysis generation must be a non-negative integer",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if type(self.stale) is not bool:
            raise EngineContractError(
                "analysis stale flag must be boolean",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if type(self.lines) is not tuple:
            raise EngineContractError(
                "analysis result lines must be an AnalysisLine tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if len(self.lines) > ANALYSIS_MAX_LINES:
            raise EngineContractError(
                "analysis result contains too many lines",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if any(type(line) is not AnalysisLine for line in self.lines):
            raise EngineContractError(
                "analysis result lines must be an AnalysisLine tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if self.error is not None:
            if (
                type(self.error) is not str
                or len(self.error) > ANALYSIS_MAX_ERROR_CHARS
                or "\n" in self.error
                or "\r" in self.error
                or not self.error.strip()
            ):
                raise EngineContractError(
                    "analysis error must be bounded non-empty text or None",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            object.__setattr__(self, "error", self.error.strip())
        if self.lines and (self.stale or self.error is not None):
            raise EngineContractError(
                "stale or failed analysis cannot carry lines",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        object.__setattr__(self, "fen", normalized_fen)

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
        if type(owns_engine) is not bool:
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
    def _safe_error_text(exc: Exception) -> str:
        fallback = type(exc).__name__[:ANALYSIS_MAX_ERROR_CHARS] or "Exception"
        try:
            text = str(exc).strip()
        except Exception:
            return fallback
        if (
            not text
            or len(text) > ANALYSIS_MAX_ERROR_CHARS
            or "\n" in text
            or "\r" in text
        ):
            return fallback
        return text

    @staticmethod
    def _normalize_line(item: object, multipv: int) -> AnalysisLine:
        if type(item) is RawAnalysisLine:
            return AnalysisLine(
                multipv=multipv,
                depth=item.depth,
                score_kind=item.score_kind,
                score_value=item.score_value,
                pv=item.pv,
            )

        if type(item) is not tuple or len(item) != 3:
            raise EngineContractError(
                "legacy analysis line must be a three-item tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        item_depth, score, pv = item
        if type(score) is not tuple or len(score) != 2:
            raise EngineContractError(
                "legacy analysis score must be a two-item tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if isinstance(pv, (str, bytes, bytearray)) or not isinstance(pv, Sequence):
            raise EngineContractError(
                "legacy analysis PV must be a move sequence",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if len(pv) > ANALYSIS_MAX_PV_PLIES:
            raise EngineContractError(
                "legacy analysis PV exceeds supported bound",
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
        # This is a representation/resource boundary, not a chess-rules parser.
        # Match canonical Board's shared FEN budget before any normalization.
        if type(fen) is not str or len(fen) > MAX_FEN_CHARS:
            raise EngineContractError(
                "analysis FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        normalized = fen.strip()
        if not normalized:
            raise EngineContractError(
                "analysis FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return normalized

    @staticmethod
    def _normalize_movetime(movetime_ms: int | None) -> int | None:
        if movetime_ms is None:
            return None
        if type(movetime_ms) is not int:
            raise EngineContractError(
                "analysis movetime_ms must be an integer or None",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        if not ANALYSIS_MIN_MOVETIME_MS <= movetime_ms <= ANALYSIS_MAX_MOVETIME_MS:
            raise EngineContractError(
                "analysis movetime_ms is outside the supported range",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return movetime_ms

    @staticmethod
    def _normalize_limits(multipv: int, depth: int) -> tuple[int, int]:
        for name, value in (("multipv", multipv), ("depth", depth)):
            if type(value) is not int:
                raise EngineContractError(
                    f"analysis {name} must be an integer",
                    code=EngineContractErrorCode.INVALID_REQUEST,
                )
        return max(1, min(ANALYSIS_MAX_LINES, multipv)), max(1, min(40, depth))

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
        # Sequence is the provider protocol. Reject an advertised over-width
        # result before tuple() can materialize provider-controlled elements.
        if len(raw) > multipv:
            raise EngineContractError(
                "analysis provider returned more lines than requested",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        items = tuple(raw)
        if len(items) > multipv:
            # Preserve the post-materialization check for unstable provider
            # sequences whose reported size changes while being read.
            raise EngineContractError(
                "analysis provider returned more lines than requested",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        return tuple(
            cls._normalize_line(item, index)
            for index, item in enumerate(items, start=1)
        )

    def analyze(
        self,
        fen: str,
        multipv: int = 5,
        depth: int = 16,
        movetime_ms: int | None = None,
    ) -> AnalysisResult:
        fen = self._normalize_fen(fen)
        multipv, depth = self._normalize_limits(multipv, depth)
        movetime_ms = self._normalize_movetime(movetime_ms)
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
                if movetime_ms is None:
                    raw = self._engine.analyze(fen, multipv=multipv, depth=depth)
                else:
                    raw = self._engine.analyze(
                        fen,
                        multipv=multipv,
                        depth=depth,
                        movetime_ms=movetime_ms,
                    )
                lines = self._snapshot_provider_result(raw, multipv)

            if self._is_stale(generation, fen):
                return AnalysisResult(fen, generation, True, ())
            return AnalysisResult(fen, generation, False, lines)
        except Exception as exc:
            if self._is_stale(generation, fen):
                return AnalysisResult(fen, generation, True, ())
            error = self._safe_error_text(exc)
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
