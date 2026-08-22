from __future__ import annotations

"""Presentation-neutral continuous engine analysis lifecycle.

This coordinator owns no UI, Stockfish process, filesystem, or persistence
concerns. It continuously feeds the newest requested position to AnalysisService
and only publishes a result when it still belongs to the active request.
"""

from dataclasses import dataclass
from threading import Condition, Thread, current_thread
from typing import Callable

from .analysis_service import AnalysisResult, AnalysisService
from .engine_ports import EngineContractError, EngineContractErrorCode


@dataclass(frozen=True)
class ContinuousAnalysisState:
    running: bool
    fen: str | None
    multipv: int
    depth: int
    revision: int
    last_result: AnalysisResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.running, bool):
            raise EngineContractError(
                "continuous-analysis running flag must be boolean",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.fen is not None and (
            not isinstance(self.fen, str) or not self.fen.strip()
        ):
            raise EngineContractError(
                "continuous-analysis FEN must be non-empty text or None",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.running and self.fen is None:
            raise EngineContractError(
                "running continuous analysis requires a FEN",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if (
            not isinstance(self.multipv, int)
            or isinstance(self.multipv, bool)
            or not 1 <= self.multipv <= 10
        ):
            raise EngineContractError(
                "continuous-analysis multipv must be between 1 and 10",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if (
            not isinstance(self.depth, int)
            or isinstance(self.depth, bool)
            or not 1 <= self.depth <= 40
        ):
            raise EngineContractError(
                "continuous-analysis depth must be between 1 and 40",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 0
        ):
            raise EngineContractError(
                "continuous-analysis revision must be non-negative",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.last_result is not None and not isinstance(
            self.last_result,
            AnalysisResult,
        ):
            raise EngineContractError(
                "continuous-analysis last_result must be AnalysisResult or None",
                code=EngineContractErrorCode.INVALID_SESSION,
            )
        if self.fen is not None:
            object.__setattr__(self, "fen", self.fen.strip())


class ContinuousAnalysisService:
    """Coalescing continuous-analysis session around ``AnalysisService``.

    Position changes supersede in-flight work. Intermediate positions are
    intentionally coalesced: after a slow engine returns, the worker analyzes
    the newest pending FEN rather than replaying obsolete requests.
    """

    def __init__(
        self,
        analysis: AnalysisService,
        on_result: Callable[[AnalysisResult], None] | None = None,
    ) -> None:
        if not isinstance(analysis, AnalysisService):
            raise TypeError("analysis must be AnalysisService")
        if on_result is not None and not callable(on_result):
            raise EngineContractError(
                "on_result must be callable or None",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        self._analysis = analysis
        self._on_result = on_result
        self._condition = Condition()
        self._running = False
        self._closed = False
        self._fen: str | None = None
        self._multipv = 5
        self._depth = 16
        self._revision = 0
        self._pending: tuple[int, str, int, int] | None = None
        self._last_result: AnalysisResult | None = None
        self._worker: Thread | None = None

    @staticmethod
    def _normalize(multipv: int, depth: int) -> tuple[int, int]:
        for name, value in (("multipv", multipv), ("depth", depth)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise EngineContractError(
                    f"continuous-analysis {name} must be an integer",
                    code=EngineContractErrorCode.INVALID_REQUEST,
                )
        return max(1, min(10, multipv)), max(1, min(40, depth))

    @staticmethod
    def _normalize_fen(fen: str) -> str:
        if not isinstance(fen, str) or not fen.strip():
            raise EngineContractError(
                "continuous-analysis FEN must be non-empty text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return fen.strip()

    def state(self) -> ContinuousAnalysisState:
        with self._condition:
            return ContinuousAnalysisState(self._running, self._fen, self._multipv, self._depth, self._revision, self._last_result)

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = Thread(target=self._run, name="acs-continuous-analysis", daemon=True)
        self._worker.start()

    def start(self, fen: str, multipv: int = 5, depth: int = 16) -> int:
        fen = self._normalize_fen(fen)
        multipv, depth = self._normalize(multipv, depth)
        with self._condition:
            if self._closed:
                raise RuntimeError("continuous analysis is closed")
            self._ensure_worker()
            self._analysis.invalidate(fen)
            self._running = True
            self._fen = fen
            self._multipv = multipv
            self._depth = depth
            self._last_result = None
            self._revision += 1
            revision = self._revision
            self._pending = (revision, self._fen, multipv, depth)
            self._condition.notify_all()
            return revision

    def update_position(self, fen: str) -> int:
        fen = self._normalize_fen(fen)
        with self._condition:
            if self._closed:
                raise RuntimeError("continuous analysis is closed")
            if not self._running:
                raise RuntimeError("continuous analysis is not running")
            self._analysis.invalidate(fen)
            self._fen = fen
            self._last_result = None
            self._revision += 1
            revision = self._revision
            self._pending = (revision, self._fen, self._multipv, self._depth)
            self._condition.notify_all()
            return revision

    def configure(self, *, multipv: int | None = None, depth: int | None = None) -> int:
        with self._condition:
            if self._closed:
                raise RuntimeError("continuous analysis is closed")
            new_multipv = self._multipv if multipv is None else multipv
            new_depth = self._depth if depth is None else depth
            new_multipv, new_depth = self._normalize(new_multipv, new_depth)
            if self._running and self._fen is not None:
                self._analysis.invalidate(self._fen)
            self._multipv = new_multipv
            self._depth = new_depth
            self._last_result = None
            self._revision += 1
            revision = self._revision
            if self._running and self._fen is not None:
                self._pending = (revision, self._fen, self._multipv, self._depth)
                self._condition.notify_all()
            return revision

    def stop(self) -> int:
        with self._condition:
            if self._closed:
                return self._revision
            self._running = False
            self._pending = None
            self._last_result = None
            self._revision += 1
            revision = self._revision
            self._analysis.invalidate(None)
            self._condition.notify_all()
            return revision

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._running = False
            self._pending = None
            self._last_result = None
            self._revision += 1
            self._analysis.invalidate(None)
            self._condition.notify_all()
            worker = self._worker
        if (
            worker is not None
            and worker is not current_thread()
            and worker.is_alive()
        ):
            worker.join(timeout=2)
        self._analysis.close()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._closed and (not self._running or self._pending is None):
                    self._condition.wait()
                if self._closed:
                    return
                request = self._pending
                self._pending = None
            assert request is not None
            revision, fen, multipv, depth = request
            result = self._analysis.analyze(fen, multipv=multipv, depth=depth)
            callback: Callable[[AnalysisResult], None] | None = None
            with self._condition:
                current = self._running and revision == self._revision and fen == self._fen and not result.stale
                if current:
                    self._last_result = result
                    callback = self._on_result
            if callback is not None:
                try:
                    callback(result)
                except Exception:
                    pass
