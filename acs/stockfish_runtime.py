from __future__ import annotations

"""Production composition contract for the packaged Stockfish runtime.

Core services consume the presentation-neutral ChessEnginePort.  This module is
only the composition boundary that resolves the executable and owns exactly one
engine adapter instance for a packaged application lifetime.
"""

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable

from .engine import UCIEngine
from .engine_ports import ChessEnginePort


PACKAGED_STOCKFISH_RELATIVE_PATH = Path("engines") / "stockfish" / "stockfish.exe"


class StockfishRuntimeError(RuntimeError):
    """Base error for production Stockfish composition failures."""


class StockfishNotFoundError(StockfishRuntimeError):
    """Raised when the configured or packaged engine executable is missing."""


class StockfishInvalidExecutableError(StockfishRuntimeError):
    """Raised when the resolved engine path is not a usable executable file."""


@dataclass(frozen=True)
class StockfishRuntimeConfig:
    configured_path: str | Path | None = None
    application_dir: str | Path | None = None


def resolve_stockfish_path(config: StockfishRuntimeConfig) -> Path:
    """Resolve an explicit path or the stable packaged application-relative path.

    An explicit configured path is authoritative: a bad explicit configuration
    never silently falls back to a packaged binary.  When no explicit path is
    supplied, ``application_dir`` is required so presentation code never guesses
    filesystem layout.
    """

    if config.configured_path is not None and str(config.configured_path).strip():
        candidate = Path(config.configured_path).expanduser()
        source = "configured"
    else:
        if config.application_dir is None or not str(config.application_dir).strip():
            raise StockfishNotFoundError(
                "Stockfish path is not configured and application_dir was not supplied"
            )
        candidate = Path(config.application_dir) / PACKAGED_STOCKFISH_RELATIVE_PATH
        source = "packaged"

    try:
        candidate = candidate.resolve(strict=False)
    except OSError as exc:
        raise StockfishInvalidExecutableError(f"Cannot resolve {source} Stockfish path: {exc}") from exc

    if not candidate.exists():
        raise StockfishNotFoundError(f"Stockfish executable not found: {candidate}")
    if not candidate.is_file():
        raise StockfishInvalidExecutableError(f"Stockfish path is not a file: {candidate}")
    try:
        size = candidate.stat().st_size
    except OSError as exc:
        raise StockfishInvalidExecutableError(f"Cannot inspect Stockfish executable: {candidate}") from exc
    if size <= 0:
        raise StockfishInvalidExecutableError(f"Stockfish executable is empty or corrupt: {candidate}")
    return candidate


EngineBuilder = Callable[[str], ChessEnginePort]


class StockfishRuntime:
    """Own exactly one production engine provider for the application lifetime.

    Analysis, continuous analysis and engine play may all receive ``provider()``;
    they therefore reuse one serialized UCI adapter instead of spawning competing
    Stockfish subprocesses.  The runtime is the sole owner and closes it once.
    """

    def __init__(
        self,
        config: StockfishRuntimeConfig,
        *,
        engine_builder: EngineBuilder | None = None,
    ) -> None:
        self._config = config
        self._engine_builder = engine_builder or (lambda path: UCIEngine(path))
        self._engine: ChessEnginePort | None = None
        self._lock = Lock()
        self._closed = False

    @property
    def expected_packaged_relative_path(self) -> Path:
        return PACKAGED_STOCKFISH_RELATIVE_PATH

    def provider(self) -> ChessEnginePort:
        with self._lock:
            if self._closed:
                raise StockfishRuntimeError("Stockfish runtime is closed")
            if self._engine is None:
                path = resolve_stockfish_path(self._config)
                engine = self._engine_builder(str(path))
                if not isinstance(engine, ChessEnginePort):
                    raise TypeError("Stockfish engine builder returned an incompatible adapter")
                self._engine = engine
            return self._engine

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            engine = self._engine
            self._engine = None
        if engine is not None:
            engine.close()

    def __enter__(self) -> "StockfishRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
