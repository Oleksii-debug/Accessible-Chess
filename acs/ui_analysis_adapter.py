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
from .chesscore import Board
from .engine_ports import EngineContractError, EngineContractErrorCode
from .notation import NotationError, format_san

MAX_ANALYSIS_PV_PLIES = 256


@dataclass(frozen=True)
class AnalysisPresentationLine:
    multipv: int
    depth: int
    score_kind: str
    score_value: int
    pv: tuple[str, ...]
    position_fens: tuple[str, ...] = ()

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
        if not isinstance(self.position_fens, tuple):
            raise EngineContractError(
                "presentation PV positions must be a tuple",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        positions: list[str] = []
        for fen in self.position_fens:
            if not isinstance(fen, str) or not fen.strip():
                raise EngineContractError(
                    "presentation PV positions must be non-empty FEN text",
                    code=EngineContractErrorCode.INVALID_RESULT,
                )
            positions.append(fen.strip())
        if positions and len(positions) != len(moves):
            raise EngineContractError(
                "presentation PV moves and positions must have equal length",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        object.__setattr__(self, "score_kind", score_kind)
        object.__setattr__(self, "pv", tuple(moves))
        object.__setattr__(self, "position_fens", tuple(positions))

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
    target_locked: bool = False
    selected_pv: int = 1
    exploring: bool = False
    exploration_ply: int = 0
    exploration_length: int = 0
    exploration_fen: str | None = None

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
        if not isinstance(self.target_locked, bool) or not isinstance(self.exploring, bool):
            raise EngineContractError(
                "presentation lock/exploration flags must be boolean",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        for name, value in (
            ("selected_pv", self.selected_pv),
            ("exploration_ply", self.exploration_ply),
            ("exploration_length", self.exploration_length),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise EngineContractError(
                    f"presentation {name} must be an exact integer",
                    code=EngineContractErrorCode.INVALID_SESSION,
                )
        if not 1 <= self.selected_pv <= self.multipv:
            raise EngineContractError(
                "presentation selected PV must be within the MultiPV limit",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if (
            self.exploration_ply < 0
            or self.exploration_length < 0
            or self.exploration_ply > self.exploration_length
        ):
            raise EngineContractError(
                "presentation exploration range is invalid",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.exploration_fen is not None and (
            not isinstance(self.exploration_fen, str) or not self.exploration_fen.strip()
        ):
            raise EngineContractError(
                "presentation exploration FEN must be non-empty text or None",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.exploring != (self.exploration_fen is not None):
            raise EngineContractError(
                "presentation exploration flag and FEN disagree",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.exploring and (
            not self.enabled
            or not self.target_locked
            or self.exploration_length == 0
            or self.exploration_ply == 0
        ):
            raise EngineContractError(
                "active exploration requires enabled locked analysis and a PV position",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if not self.exploring and (
            self.exploration_ply != 0
            or self.exploration_length != 0
            or self.exploration_fen is not None
        ):
            raise EngineContractError(
                "inactive exploration cannot carry temporary position state",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if not self.enabled and (
            self.fen is not None
            or self.running
            or self.lines
            or self.stale
            or self.target_locked
            or self.exploring
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
        if self.exploration_fen is not None:
            object.__setattr__(self, "exploration_fen", self.exploration_fen.strip())

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "fen": self.fen,
            "running": self.running,
            "multipv": self.multipv,
            "depth": self.depth,
            "lines": [line.as_dict() for line in self.lines],
            # Provider exception/path details are diagnostic-only and never cross
            # the WebView bridge.  The UI needs one stable, non-sensitive state.
            "error": None if self.error is None else "engine_error",
            "stale": self.stale,
            "targetLocked": self.target_locked,
            "selectedPv": self.selected_pv,
            "exploring": self.exploring,
            "explorationPly": self.exploration_ply,
            "explorationLength": self.exploration_length,
            "explorationFen": self.exploration_fen,
        }


@dataclass(frozen=True)
class AnalysisExploration:
    """Frozen temporary view of one already validated engine PV."""

    line: AnalysisPresentationLine
    ply: int

    def __post_init__(self) -> None:
        if not isinstance(self.line, AnalysisPresentationLine):
            raise EngineContractError(
                "analysis exploration requires a presentation line",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if (
            not isinstance(self.ply, int)
            or isinstance(self.ply, bool)
            or not 1 <= self.ply <= len(self.line.pv)
            or len(self.line.position_fens) != len(self.line.pv)
        ):
            raise EngineContractError(
                "analysis exploration ply is outside the validated PV",
                code=EngineContractErrorCode.INVALID_SESSION,
            )

    @property
    def fen(self) -> str:
        return self.line.position_fens[self.ply - 1]

    @property
    def san(self) -> str:
        return self.line.pv[self.ply - 1]


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
        self._follow_position = True
        self._selected_pv = 1
        self._exploration: AnalysisExploration | None = None

    @property
    def available(self) -> bool:
        return self._service is not None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def target_locked(self) -> bool:
        return self._enabled and not self._follow_position

    @property
    def target_fen(self) -> str | None:
        return self._fen

    @property
    def selected_pv(self) -> int:
        return self._selected_pv

    @property
    def multipv(self) -> int:
        return self._multipv

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def exploration(self) -> AnalysisExploration | None:
        return self._exploration

    def enable(self, fen: str) -> None:
        if self._service is None:
            raise RuntimeError("analysis service is not configured")
        fen = self._normalize_fen(fen)
        self._service.start(fen, multipv=self._multipv, depth=self._depth)
        self._fen = fen
        self._enabled = True
        self._last_error = None
        self._follow_position = True
        self._selected_pv = 1
        self._exploration = None

    def disable(self) -> None:
        if self._service is not None:
            self._service.stop()
        self._enabled = False
        self._fen = None
        self._last_error = None
        self._follow_position = True
        self._selected_pv = 1
        self._exploration = None

    def sync_position(self, fen: str) -> None:
        """Feed the newest displayed FEN without ever restarting the UI layer."""
        if not self._enabled or self._service is None or not self._follow_position:
            return
        fen = self._normalize_fen(fen)
        if fen == self._fen:
            return
        self._service.update_position(fen)
        self._fen = fen
        self._last_error = None
        self._exploration = None

    def configure(self, *, multipv: int, depth: int) -> None:
        """Apply bounded settings atomically and invalidate the old result."""

        multipv, depth = self._normalize_limits(multipv, depth)
        service = self._service
        if service is not None:
            configure = getattr(service, "configure", None)
            if callable(configure):
                configure(multipv=multipv, depth=depth)
            elif self._enabled and self._fen is not None:
                # Compatibility services can restart through the original
                # lifecycle boundary.  Publish settings only after success.
                service.start(self._fen, multipv=multipv, depth=depth)
        self._multipv = multipv
        self._depth = depth
        self._selected_pv = min(self._selected_pv, multipv)
        self._last_error = None
        self._exploration = None

    def restart(self, displayed_fen: str) -> None:
        if self._service is None:
            raise RuntimeError("analysis service is not configured")
        displayed_fen = self._normalize_fen(displayed_fen)
        target = self._fen if self.target_locked and self._fen is not None else displayed_fen
        self._service.start(target, multipv=self._multipv, depth=self._depth)
        self._fen = target
        self._enabled = True
        self._last_error = None
        self._exploration = None

    def lock_target(self) -> None:
        if not self._enabled or self._fen is None:
            raise EngineContractError(
                "analysis must be enabled before its target can be locked",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        self._follow_position = False

    def unlock_target(self, displayed_fen: str) -> None:
        if not self._enabled or self._service is None:
            raise EngineContractError(
                "analysis must be enabled before its target can follow",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        displayed_fen = self._normalize_fen(displayed_fen)
        if displayed_fen != self._fen:
            self._service.update_position(displayed_fen)
        self._fen = displayed_fen
        self._follow_position = True
        self._last_error = None
        self._exploration = None

    def select_pv(self, index: int, displayed_fen: str) -> AnalysisPresentationLine:
        index = self._normalize_pv_index(index)
        snap = self.snapshot(displayed_fen)
        if snap.stale or snap.error is not None or index > len(snap.lines):
            raise EngineContractError(
                "requested analysis PV is not currently available",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        self._selected_pv = index
        self._exploration = None
        return snap.lines[index - 1]

    def select_relative_pv(self, delta: int, displayed_fen: str) -> AnalysisPresentationLine:
        if type(delta) is not int or delta not in {-1, 1}:
            raise EngineContractError(
                "analysis PV selection delta must be exactly -1 or 1",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        snap = self.snapshot(displayed_fen)
        if not snap.lines or snap.stale or snap.error is not None:
            raise EngineContractError(
                "analysis PV selection is not currently available",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        selected = max(1, min(len(snap.lines), self._selected_pv + delta))
        self._selected_pv = selected
        self._exploration = None
        return snap.lines[selected - 1]

    def begin_exploration(self, displayed_fen: str) -> AnalysisExploration:
        line = self.select_pv(self._selected_pv, displayed_fen)
        if not line.pv or len(line.position_fens) != len(line.pv):
            raise EngineContractError(
                "selected analysis PV has no validated moves",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        self._follow_position = False
        self._exploration = AnalysisExploration(line, 1)
        return self._exploration

    def step_exploration(self, delta: int) -> AnalysisExploration:
        if type(delta) is not int or delta not in {-1, 1}:
            raise EngineContractError(
                "analysis exploration delta must be exactly -1 or 1",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        current = self._exploration
        if current is None:
            raise EngineContractError(
                "analysis PV exploration is not active",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        ply = max(1, min(len(current.line.pv), current.ply + delta))
        self._exploration = AnalysisExploration(current.line, ply)
        return self._exploration

    def return_from_exploration(self) -> None:
        self._exploration = None

    def selected_line(self, displayed_fen: str) -> AnalysisPresentationLine:
        if self._exploration is not None:
            return self._exploration.line
        return self.select_pv(self._selected_pv, displayed_fen)

    def close(self) -> None:
        service = self._service
        self._service = None
        self._enabled = False
        self._fen = None
        self._last_error = None
        self._follow_position = True
        self._selected_pv = 1
        self._exploration = None
        if service is not None:
            service.close()

    @staticmethod
    def _line(line: Any, fen: str) -> AnalysisPresentationLine:
        if isinstance(line, AnalysisLine):
            multipv = line.multipv
            depth = line.depth
            score_kind = line.score_kind
            score_value = line.score_value
            pv = line.pv
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
        elif not isinstance(line, AnalysisLine):
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
        raw_pv = tuple(pv)
        if len(raw_pv) > MAX_ANALYSIS_PV_PLIES:
            raise EngineContractError(
                "analysis provider PV exceeds the presentation safety limit",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        sans: list[str] = []
        positions: list[str] = []
        try:
            board = Board(fen)
            for token in raw_pv:
                if not isinstance(token, str) or not token.strip():
                    raise ValueError("PV token must be non-empty text")
                san = board.push_text(token.strip())
                sans.append(san)
                positions.append(board.fen())
        except (IndexError, TypeError, ValueError) as exc:
            raise EngineContractError(
                "analysis provider returned an illegal PV for its target position",
                code=EngineContractErrorCode.INVALID_RESULT,
            ) from exc
        return AnalysisPresentationLine(
            multipv,
            depth,
            score_kind,
            score_value,
            tuple(sans),
            tuple(positions),
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
    def _normalize_pv_index(index: int) -> int:
        if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= 10:
            raise EngineContractError(
                "analysis PV index must be an integer between 1 and 10",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return index

    @staticmethod
    def _language(lang: str) -> str:
        if not isinstance(lang, str) or lang not in {"uk", "en"}:
            raise EngineContractError(
                "analysis language must be 'uk' or 'en'",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return lang

    @staticmethod
    def score_text(line: AnalysisPresentationLine, *, lang: str = "uk") -> str:
        lang = AnalysisPresentationAdapter._language(lang)
        if line.score_kind == "mate":
            distance = abs(line.score_value)
            if lang == "uk":
                return (
                    f"мат за {distance}"
                    if line.score_value >= 0
                    else f"загроза мату за {distance}"
                )
            return (
                f"mate in {distance}"
                if line.score_value >= 0
                else f"mated in {distance}"
            )
        return f"{line.score_value / 100:+.2f}"

    @staticmethod
    def _spoken_moves(moves: tuple[str, ...], lang: str) -> str:
        profile = "uk_literal" if lang == "uk" else "en_literal"
        spoken: list[str] = []
        for move in moves:
            try:
                spoken.append(format_san(move, profile))
            except NotationError:
                spoken.append(move)
        return " ".join(spoken)

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
                False,
                self._selected_pv,
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
                False,
                self._selected_pv,
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
        target_fen = self._fen
        if target_fen is None:
            raise EngineContractError(
                "enabled analysis lost its target FEN",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        stale = state_fen != target_fen or (
            self._follow_position and target_fen != displayed_fen
        )
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
            stale = stale or result.stale or result_fen != target_fen
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
                    lines = tuple(self._line(line, target_fen) for line in result.lines)
        selected_pv = min(self._selected_pv, max(1, len(lines) or multipv))
        self._selected_pv = selected_pv
        exploration = self._exploration
        return AnalysisPresentation(
            True,
            state_fen,
            running,
            multipv,
            depth,
            lines,
            error,
            stale,
            self.target_locked,
            selected_pv,
            exploration is not None,
            0 if exploration is None else exploration.ply,
            0 if exploration is None else len(exploration.line.pv),
            None if exploration is None else exploration.fen,
        )

    def read_pv(self, index: int, displayed_fen: str, *, lang: str = "uk") -> str:
        index = self._normalize_pv_index(index)
        lang = self._language(lang)
        snap = self.snapshot(displayed_fen)
        if not snap.enabled:
            return "Аналіз Stockfish вимкнено." if lang == "uk" else "Stockfish analysis is disabled."
        if snap.error:
            return "Помилка Stockfish." if lang == "uk" else "Stockfish error."
        if snap.stale:
            return "Очікую аналіз поточної позиції." if lang == "uk" else "Waiting for analysis of the current position."
        if index < 1 or index > len(snap.lines):
            return "Варіант ще недоступний." if lang == "uk" else "Variation is not available yet."
        self._selected_pv = index
        line = snap.lines[index - 1]
        pv = self._spoken_moves(line.pv, lang)
        score = self.score_text(line, lang=lang)
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
        score = self.score_text(line, lang=lang)
        if lang == "uk":
            return f"Оцінка для сторони, що ходить: {score}, глибина {line.depth}."
        return f"Side-to-move evaluation: {score}, depth {line.depth}."

    def best_move_text(self, displayed_fen: str, *, lang: str = "uk") -> str:
        lang = self._language(lang)
        snap = self.snapshot(displayed_fen)
        if not snap.lines or snap.stale:
            return self.read_pv(1, displayed_fen, lang=lang)
        pv = snap.lines[0].pv
        if not pv:
            return "Найкращий хід ще недоступний." if lang == "uk" else "Best move is not available yet."
        prefix = "Найкращий хід: " if lang == "uk" else "Best move: "
        return prefix + self._spoken_moves((pv[0],), lang)
