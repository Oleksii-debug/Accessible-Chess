from __future__ import annotations

"""Presentation-only bridge from semantic WebView2 UI to engine analysis services.

This module deliberately knows nothing about Stockfish subprocesses, executable
paths, packaging, or UCI.  It accepts a presentation-neutral continuous
analysis service supplied by the composition root and projects its state for the
WebView API.  The adapter is also responsible for suppressing stale results so
NVDA never reads analysis for an older position.
"""

from dataclasses import dataclass
from typing import Any

from .analysis_service import AnalysisLine
from .engine_ports import EngineContractError, EngineContractErrorCode


@dataclass(frozen=True)
class AnalysisPresentationLine:
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
                "presentation multipv must be an integer between 1 and 10",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if (
            not isinstance(self.depth, int)
            or isinstance(self.depth, bool)
            or self.depth < 0
        ):
            raise EngineContractError(
                "presentation depth must be a non-negative integer",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.score_kind, str):
            raise EngineContractError(
                "presentation score kind must be text",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        score_kind = self.score_kind.strip()
        if score_kind not in {"cp", "mate"}:
            raise EngineContractError(
                "presentation score kind must be 'cp' or 'mate'",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.score_value, int) or isinstance(
            self.score_value,
            bool,
        ):
            raise EngineContractError(
                "presentation score value must be an integer",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        if not isinstance(self.pv, tuple):
            raise EngineContractError(
                "presentation PV must be a tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        moves: list[str] = []
        for move in self.pv:
            if not isinstance(move, str) or not move.strip():
                raise EngineContractError(
                    "presentation PV moves must be non-empty text",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            moves.append(move.strip())
        object.__setattr__(self, "score_kind", score_kind)
        object.__setattr__(self, "pv", tuple(moves))

    def as_dict(self) -> dict[str, Any]:
        return {
            "multipv": self.multipv,
            "depth": self.depth,
            "scoreKind": self.score_kind,
            "scoreValue": self.score_value,
            "pv": list(self.pv),
        }


@dataclass(frozen=True)
class AnalysisPresentation:
    enabled: bool
    fen: str | None
    running: bool
    multipv: int
    depth: int
    lines: tuple[AnalysisPresentationLine, ...]
    error: str | None
    stale: bool

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool) or not isinstance(self.running, bool):
            raise EngineContractError(
                "presentation enabled/running flags must be boolean",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.fen is not None and (
            not isinstance(self.fen, str) or not self.fen.strip()
        ):
            raise EngineContractError(
                "presentation FEN must be non-empty text or None",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if (
            not isinstance(self.multipv, int)
            or isinstance(self.multipv, bool)
            or not 1 <= self.multipv <= 10
        ):
            raise EngineContractError(
                "presentation multipv must be between 1 and 10",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if (
            not isinstance(self.depth, int)
            or isinstance(self.depth, bool)
            or not 1 <= self.depth <= 40
        ):
            raise EngineContractError(
                "presentation depth must be between 1 and 40",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if not isinstance(self.lines, tuple) or any(
            not isinstance(line, AnalysisPresentationLine) for line in self.lines
        ):
            raise EngineContractError(
                "presentation lines must be an AnalysisPresentationLine tuple",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.error is not None:
            if not isinstance(self.error, str) or not self.error.strip():
                raise EngineContractError(
                    "presentation error must be non-empty text or None",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
            object.__setattr__(self, "error", self.error.strip())
        if not isinstance(self.stale, bool):
            raise EngineContractError(
                "presentation stale flag must be boolean",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if not self.enabled and (
            self.fen is not None or self.running or self.lines or self.stale
        ):
            raise EngineContractError(
                "disabled presentation cannot carry active analysis state",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.enabled and self.fen is None:
            raise EngineContractError(
                "enabled presentation requires a FEN",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.running and not self.enabled:
            raise EngineContractError(
                "running presentation must be enabled",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.lines and (self.stale or self.error is not None):
            raise EngineContractError(
                "stale or failed presentation cannot carry lines",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if len(self.lines) > self.multipv or tuple(
            line.multipv for line in self.lines
        ) != tuple(range(1, len(self.lines) + 1)):
            raise EngineContractError(
                "presentation lines must be ordered within the MultiPV limit",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.fen is not None:
            object.__setattr__(self, "fen", self.fen.strip())

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "fen": self.fen,
            "running": self.running,
            "multipv": self.multipv,
            "depth": self.depth,
            "lines": [line.as_dict() for line in self.lines],
            "error": self.error,
            "stale": self.stale,
        }


class AnalysisPresentationAdapter:
    """Thin UI adapter around a ContinuousAnalysisService-compatible object."""

    def __init__(
        self,
        service: Any | None,
        *,
        multipv: int = 5,
        depth: int = 16,
    ) -> None:
        if service is not None:
            required = ("start", "update_position", "stop", "close", "state")
            if isinstance(service, type) or any(
                not callable(getattr(service, name, None)) for name in required
            ):
                raise EngineContractError(
                    "analysis presentation service is incompatible",
                    code=EngineContractErrorCode.INVALID_PROVIDER,
                )
        multipv, depth = self._normalize_limits(multipv, depth)
        self._service = service
        self._enabled = False
        self._fen: str | None = None
        self._multipv = multipv
        self._depth = depth
        self._last_error: str | None = None

    @property
    def available(self) -> bool:
        return self._service is not None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self, fen: str) -> None:
        if self._service is None:
            raise RuntimeError("analysis service is not configured")
        fen = self._normalize_fen(fen)
        self._service.start(fen, multipv=self._multipv, depth=self._depth)
        self._fen = fen
        self._enabled = True
        self._last_error = None

    def disable(self) -> None:
        if self._service is not None:
            self._service.stop()
        self._enabled = False
        self._fen = None
        self._last_error = None

    def sync_position(self, fen: str) -> None:
        """Feed the newest displayed FEN without ever restarting the UI layer."""
        if not self._enabled or self._service is None:
            return
        fen = self._normalize_fen(fen)
        if fen == self._fen:
            return
        self._service.update_position(fen)
        self._fen = fen
        self._last_error = None

    def close(self) -> None:
        service = self._service
        self._service = None
        self._enabled = False
        self._fen = None
        self._last_error = None
        if service is not None:
            service.close()

    @staticmethod
    def _line(line: Any) -> AnalysisPresentationLine:
        if isinstance(line, AnalysisLine):
            return AnalysisPresentationLine(
                line.multipv,
                line.depth,
                line.score_kind,
                line.score_value,
                line.pv,
            )
        if isinstance(line, dict):
            required = {"multipv", "depth", "scoreKind", "scoreValue", "pv"}
            if set(line) != required:
                raise EngineContractError(
                    "analysis line dictionary fields are invalid",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            multipv = line["multipv"]
            depth = line["depth"]
            score_kind = line["scoreKind"]
            score_value = line["scoreValue"]
            pv = line["pv"]
        else:
            required = ("multipv", "depth", "score_kind", "score_value", "pv")
            if isinstance(line, type) or any(
                not hasattr(line, name) for name in required
            ):
                raise EngineContractError(
                    "analysis line projection is incompatible",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            multipv = line.multipv
            depth = line.depth
            score_kind = line.score_kind
            score_value = line.score_value
            pv = line.pv
        if not isinstance(pv, (list, tuple)):
            raise EngineContractError(
                "analysis line PV must be a list or tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        return AnalysisPresentationLine(
            multipv,
            depth,
            score_kind,
            score_value,
            tuple(pv),
        )

    @staticmethod
    def _normalize_fen(
        fen: str,
        *,
        code: EngineContractErrorCode = EngineContractErrorCode.INVALID_REQUEST,
    ) -> str:
        if not isinstance(fen, str) or not fen.strip():
            raise EngineContractError(
                "presentation FEN must be non-empty text",
                code=code,
            )
        return fen.strip()

    @staticmethod
    def _normalize_limits(
        multipv: int,
        depth: int,
        *,
        code: EngineContractErrorCode = EngineContractErrorCode.INVALID_CONFIG,
    ) -> tuple[int, int]:
        for name, value in (("multipv", multipv), ("depth", depth)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise EngineContractError(
                    f"presentation {name} must be an integer",
                    code=code,
                )
        return max(1, min(10, multipv)), max(1, min(40, depth))

    @staticmethod
    def _language(lang: str) -> str:
        if not isinstance(lang, str) or lang not in {"uk", "en"}:
            raise EngineContractError(
                "analysis language must be 'uk' or 'en'",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return lang

    def snapshot(self, displayed_fen: str) -> AnalysisPresentation:
        displayed_fen = self._normalize_fen(displayed_fen)
        if self._service is None:
            return AnalysisPresentation(
                False,
                None,
                False,
                self._multipv,
                self._depth,
                (),
                "analysis service is not configured",
                False,
            )
        if not self._enabled:
            return AnalysisPresentation(
                False,
                None,
                False,
                self._multipv,
                self._depth,
                (),
                None,
                False,
            )

        state = self._service.state()
        required_state = ("running", "fen", "multipv", "depth", "last_result")
        if any(not hasattr(state, name) for name in required_state):
            raise EngineContractError(
                "analysis presentation state is incompatible",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        state_fen = (
            self._fen
            if state.fen is None
            else self._normalize_fen(
                state.fen,
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        )
        running = state.running
        multipv = state.multipv
        depth = state.depth
        if not isinstance(running, bool):
            raise EngineContractError(
                "analysis presentation running state must be boolean",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        normalized_limits = self._normalize_limits(
            multipv,
            depth,
            code=EngineContractErrorCode.INVALID_SESSION,
        )
        if normalized_limits != (multipv, depth):
            raise EngineContractError(
                "analysis presentation state limits are outside canonical bounds",
                code=EngineContractErrorCode.INVALID_SESSION,
            )

        result = state.last_result
        lines: tuple[AnalysisPresentationLine, ...] = ()
        error = self._last_error
        stale = state_fen != displayed_fen
        if result is not None:
            required_result = ("fen", "stale", "error", "lines")
            if any(not hasattr(result, name) for name in required_result):
                raise EngineContractError(
                    "analysis presentation result is incompatible",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            result_fen = self._normalize_fen(
                result.fen,
                code=EngineContractErrorCode.INVALID_RESULT,
            )
            if not isinstance(result.stale, bool):
                raise EngineContractError(
                    "analysis result stale flag must be boolean",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            stale = stale or result.stale or result_fen != displayed_fen
            if not stale:
                if result.error is not None and (
                    not isinstance(result.error, str) or not result.error.strip()
                ):
                    raise EngineContractError(
                        "analysis result error must be non-empty text or None",
                        code=EngineContractErrorCode.INVALID_RESULT,
                    )
                error = None if result.error is None else result.error.strip()
                if error is None:
                    if not isinstance(result.lines, (list, tuple)):
                        raise EngineContractError(
                            "analysis result lines must be a list or tuple",
                            code=EngineContractErrorCode.INVALID_RESULT,
                        )
                    lines = tuple(self._line(line) for line in result.lines)
        return AnalysisPresentation(
            True,
            state_fen,
            running,
            multipv,
            depth,
            lines,
            error,
            stale,
        )

    def read_pv(self, index: int, displayed_fen: str, *, lang: str = "uk") -> str:
        if not isinstance(index, int) or isinstance(index, bool):
            raise EngineContractError(
                "analysis PV index must be an integer",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        lang = self._language(lang)
        snap = self.snapshot(displayed_fen)
        if not snap.enabled:
            return "Аналіз Stockfish вимкнено." if lang == "uk" else "Stockfish analysis is disabled."
        if snap.error:
            prefix = "Помилка Stockfish: " if lang == "uk" else "Stockfish error: "
            return prefix + snap.error
        if snap.stale:
            return "Очікую аналіз поточної позиції." if lang == "uk" else "Waiting for analysis of the current position."
        if index < 1 or index > len(snap.lines):
            return "Варіант ще недоступний." if lang == "uk" else "Variation is not available yet."
        line = snap.lines[index - 1]
        pv = " ".join(line.pv)
        score = f"{line.score_kind} {line.score_value}"
        depth = line.depth
        if lang == "uk":
            return f"Варіант {index}. Глибина {depth}. Оцінка {score}. {pv}".strip()
        return f"Variation {index}. Depth {depth}. Evaluation {score}. {pv}".strip()

    def evaluation_text(self, displayed_fen: str, *, lang: str = "uk") -> str:
        lang = self._language(lang)
        snap = self.snapshot(displayed_fen)
        if not snap.lines or snap.stale:
            return self.read_pv(1, displayed_fen, lang=lang)
        line = snap.lines[0]
        if lang == "uk":
            return f"Оцінка: {line.score_kind} {line.score_value}, глибина {line.depth}."
        return f"Evaluation: {line.score_kind} {line.score_value}, depth {line.depth}."

    def best_move_text(self, displayed_fen: str, *, lang: str = "uk") -> str:
        lang = self._language(lang)
        snap = self.snapshot(displayed_fen)
        if not snap.lines or snap.stale:
            return self.read_pv(1, displayed_fen, lang=lang)
        pv = snap.lines[0].pv
        if not pv:
            return "Найкращий хід ще недоступний." if lang == "uk" else "Best move is not available yet."
        prefix = "Найкращий хід: " if lang == "uk" else "Best move: "
        return prefix + pv[0]
