from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from typing import Callable

from .engine_ports import RawAnalysisLine


ProcessFactory = Callable[..., subprocess.Popen]


class UCIEngine:
    """Serialized UCI adapter used by both analysis and engine play.

    One instance owns one subprocess. Calls are serialized so analysis and move
    requests cannot interleave commands on the same UCI stream.
    """

    def __init__(self, path: str, *, process_factory: ProcessFactory = subprocess.Popen):
        self.path = str(path)
        self.proc = None
        self.q: queue.Queue[str] = queue.Queue()
        self.reader = None
        self._process_factory = process_factory
        self._lock = threading.Lock()
        self._closed = False

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("Stockfish adapter is closed")
        if self.proc and self.proc.poll() is None:
            return
        try:
            self.proc = self._process_factory(
                [self.path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Unable to start Stockfish: {exc}") from exc
        if not self.proc.stdout:
            raise RuntimeError("Stockfish stdout pipe is unavailable")

        def read() -> None:
            try:
                for line in self.proc.stdout:
                    self.q.put(line.strip())
            except Exception:
                return

        self.reader = threading.Thread(target=read, daemon=True, name="acs-stockfish-reader")
        self.reader.start()
        self.send("uci")
        self._wait("uciok", 5)
        self.send("isready")
        self._wait("readyok", 5)

    def send(self, command: str) -> None:
        if self._closed:
            raise RuntimeError("Stockfish adapter is closed")
        if not self.proc or not self.proc.stdin or self.proc.poll() is not None:
            raise RuntimeError("Stockfish is not running")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def _wait(self, token: str, timeout: float) -> str:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if token in line:
                return line
        raise RuntimeError("Stockfish did not respond: " + token)

    def _drain(self) -> None:
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def _configure_request_options(self, *, multipv: int, skill_level: int) -> None:
        """Restore request-local UCI options on the shared Stockfish process.

        Stockfish options persist between searches. Analysis and engine play share
        this serialized provider, so each request must explicitly restore the
        options whose semantics differ between the two modes.
        """
        self.send(f"setoption name Skill Level value {skill_level}")
        self.send(f"setoption name MultiPV value {multipv}")
        self.send("isready")
        self._wait("readyok", 5)

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        multipv = max(1, min(10, int(multipv)))
        depth = max(1, min(40, int(depth)))
        with self._lock:
            self.start()
            self._drain()
            self._configure_request_options(multipv=multipv, skill_level=20)
            self.send("position fen " + fen)
            self.send(f"go depth {depth}")
            best: dict[int, RawAnalysisLine] = {}
            end = time.monotonic() + 60
            while time.monotonic() < end:
                try:
                    line = self.q.get(timeout=0.3)
                except queue.Empty:
                    continue
                if line.startswith("bestmove"):
                    return tuple(best[k] for k in sorted(best)[:multipv])
                if not (line.startswith("info ") and " pv " in line):
                    continue
                mp_match = re.search(r" multipv (\d+)", line)
                depth_match = re.search(r" depth (\d+)", line)
                score_match = re.search(r" score (cp|mate) (-?\d+)", line)
                mp = int(mp_match.group(1)) if mp_match else 1
                item_depth = int(depth_match.group(1)) if depth_match else 0
                score_kind = score_match.group(1) if score_match else "cp"
                score_value = int(score_match.group(2)) if score_match else 0
                pv = tuple(line.split(" pv ", 1)[1].split())
                best[mp] = RawAnalysisLine(item_depth, score_kind, score_value, pv)
            try:
                self.send("stop")
            except Exception:
                pass
            raise RuntimeError("Stockfish analysis timed out")

    def best_move(self, fen: str, skill_level: int = 10, movetime_ms: int = 500) -> str | None:
        with self._lock:
            self.start()
            self._drain()
            skill = max(0, min(20, int(skill_level)))
            movetime_ms = max(50, int(movetime_ms))
            self._configure_request_options(multipv=1, skill_level=skill)
            self.send("position fen " + fen)
            self.send(f"go movetime {movetime_ms}")
            end = time.monotonic() + max(5, movetime_ms / 1000 + 5)
            while time.monotonic() < end:
                try:
                    line = self.q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line.startswith("bestmove"):
                    parts = line.split()
                    return parts[1] if len(parts) > 1 and parts[1] != "(none)" else None
            try:
                self.send("stop")
            except Exception:
                pass
            raise RuntimeError("Stockfish did not return bestmove")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            proc = self.proc
            if proc is not None and proc.poll() is None:
                try:
                    if proc.stdin:
                        proc.stdin.write("quit\n")
                        proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            self.proc = None
            self._closed = True
