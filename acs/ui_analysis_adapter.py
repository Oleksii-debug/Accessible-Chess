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


@dataclass(frozen=True)
class AnalysisPresentation:
    enabled: bool
    fen: str | None
    running: bool
    multipv: int
    depth: int
    lines: tuple[dict[str, Any], ...]
    error: str | None
    stale: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "fen": self.fen,
            "running": self.running,
            "multipv": self.multipv,
            "depth": self.depth,
            "lines": [dict(line) for line in self.lines],
            "error": self.error,
            "stale": self.stale,
        }


class AnalysisPresentationAdapter:
    """Thin UI adapter around a ContinuousAnalysisService-compatible object."""

    def __init__(self, service: Any | None, *, multipv: int = 5, depth: int = 16) -> None:
        self._service = service
        self._enabled = False
        self._fen: str | None = None
        self._multipv = max(1, min(10, int(multipv)))
        self._depth = max(1, min(40, int(depth)))
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
        self._fen = str(fen)
        self._last_error = None
        self._service.start(self._fen, multipv=self._multipv, depth=self._depth)
        self._enabled = True

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
        fen = str(fen)
        if fen == self._fen:
            return
        self._fen = fen
        self._last_error = None
        self._service.update_position(fen)

    def close(self) -> None:
        service = self._service
        self._service = None
        self._enabled = False
        self._fen = None
        if service is not None:
            service.close()

    @staticmethod
    def _line_dict(line: Any) -> dict[str, Any]:
        if hasattr(line, "as_dict"):
            return dict(line.as_dict())
        if isinstance(line, dict):
            return dict(line)
        return {
            "multipv": int(getattr(line, "multipv", 0)),
            "depth": int(getattr(line, "depth", 0)),
            "scoreKind": str(getattr(line, "score_kind", "cp")),
            "scoreValue": int(getattr(line, "score_value", 0)),
            "pv": [str(move) for move in getattr(line, "pv", ())],
        }

    def snapshot(self, displayed_fen: str) -> AnalysisPresentation:
        if self._service is None:
            return AnalysisPresentation(False, None, False, self._multipv, self._depth, (), "analysis service is not configured", False)
        if not self._enabled:
            return AnalysisPresentation(False, None, False, self._multipv, self._depth, (), None, False)

        state = self._service.state()
        result = getattr(state, "last_result", None)
        lines: tuple[dict[str, Any], ...] = ()
        error = self._last_error
        stale = False
        if result is not None:
            result_fen = str(getattr(result, "fen", ""))
            stale = bool(getattr(result, "stale", False)) or result_fen != str(displayed_fen)
            if not stale:
                error = getattr(result, "error", None)
                lines = tuple(self._line_dict(line) for line in getattr(result, "lines", ()))
        return AnalysisPresentation(
            True,
            str(getattr(state, "fen", self._fen)) if getattr(state, "fen", None) is not None else self._fen,
            bool(getattr(state, "running", self._enabled)),
            int(getattr(state, "multipv", self._multipv)),
            int(getattr(state, "depth", self._depth)),
            lines,
            error,
            stale,
        )

    def read_pv(self, index: int, displayed_fen: str, *, lang: str = "uk") -> str:
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
        pv = " ".join(str(move) for move in line.get("pv", ()))
        score = f"{line.get('scoreKind', 'cp')} {line.get('scoreValue', 0)}"
        depth = line.get("depth", 0)
        if lang == "uk":
            return f"Варіант {index}. Глибина {depth}. Оцінка {score}. {pv}".strip()
        return f"Variation {index}. Depth {depth}. Evaluation {score}. {pv}".strip()

    def evaluation_text(self, displayed_fen: str, *, lang: str = "uk") -> str:
        snap = self.snapshot(displayed_fen)
        if not snap.lines or snap.stale:
            return self.read_pv(1, displayed_fen, lang=lang)
        line = snap.lines[0]
        if lang == "uk":
            return f"Оцінка: {line.get('scoreKind', 'cp')} {line.get('scoreValue', 0)}, глибина {line.get('depth', 0)}."
        return f"Evaluation: {line.get('scoreKind', 'cp')} {line.get('scoreValue', 0)}, depth {line.get('depth', 0)}."

    def best_move_text(self, displayed_fen: str, *, lang: str = "uk") -> str:
        snap = self.snapshot(displayed_fen)
        if not snap.lines or snap.stale:
            return self.read_pv(1, displayed_fen, lang=lang)
        pv = list(snap.lines[0].get("pv", ()))
        if not pv:
            return "Найкращий хід ще недоступний." if lang == "uk" else "Best move is not available yet."
        prefix = "Найкращий хід: " if lang == "uk" else "Best move: "
        return prefix + str(pv[0])
