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
    requests cannot interleave commands on the same UCI stream. Reader output is
    tagged with a process generation so a late line from a failed/replaced
    Stockfish process can never satisfy a later handshake, analysis or bestmove.
    """

    def __init__(self, path: str, *, process_factory: ProcessFactory = subprocess.Popen):
        self.path = str(path)
        self.proc = None
        self.q: queue.Queue[object] = queue.Queue()
        self.reader = None
        self._process_factory = process_factory
        self._lock = threading.RLock()
        self._closed = False
        self._process_generation = 0

    def _shutdown_process(self, proc) -> None:
        """Best-effort bounded shutdown with escalation so no child is abandoned."""
        if proc is None:
            return
        try:
            if proc.poll() is not None:
                return
        except Exception:
            pass
        try:
            if proc.stdin:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
            return
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
            return
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass

    def _abandon_process(self) -> None:
        """Detach an unsynchronized UCI stream and force a fresh generation.

        A search that does not acknowledge ``stop`` with terminal ``bestmove``
        cannot safely be reused. A late terminal line could otherwise satisfy a
        later request and return a move/PV for the wrong position. Detaching the
        process before shutdown makes every late reader line belong to an old
        generation and therefore invisible to the next Stockfish session.
        """
        proc = self.proc
        self.proc = None
        self.reader = None
        self._process_generation += 1
        self._shutdown_process(proc)
        self._drain()

    def _stop_and_synchronize(self, generation: int, timeout: float = 2.0) -> bool:
        """Stop the current search and consume its terminal ``bestmove``.

        UCI defines ``bestmove`` as the search-completion delimiter, including
        after ``stop``. Returning to the caller before consuming that delimiter
        leaves the command stream ambiguous. If Stockfish does not produce it
        within the bounded recovery window, discard that process and let the
        next request start a clean provider generation.
        """
        try:
            self.send("stop")
        except Exception:
            self._abandon_process()
            return False

        end = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < end:
            try:
                line = self._get_line(
                    min(0.2, max(0.0, end - time.monotonic())),
                    generation=generation,
                )
            except queue.Empty:
                continue
            if line.startswith("bestmove"):
                return True

        self._abandon_process()
        return False

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Stockfish adapter is closed")
            if self.proc and self.proc.poll() is None:
                return
            try:
                proc = self._process_factory(
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

            self.proc = proc
            self._process_generation += 1
            generation = self._process_generation
            try:
                if not proc.stdout:
                    raise RuntimeError("Stockfish stdout pipe is unavailable")
                self._drain()

                def read() -> None:
                    try:
                        for line in proc.stdout:
                            self.q.put((generation, line.strip()))
                    except Exception:
                        return

                self.reader = threading.Thread(target=read, daemon=True, name="acs-stockfish-reader")
                self.reader.start()
                self.send("uci")
                self._wait("uciok", 5)
                self.send("isready")
                self._wait("readyok", 5)
            except Exception:
                self._shutdown_process(proc)
                self.proc = None
                self.reader = None
                raise

    def send(self, command: str) -> None:
        if self._closed:
            raise RuntimeError("Stockfish adapter is closed")
        if not self.proc or not self.proc.stdin or self.proc.poll() is not None:
            raise RuntimeError("Stockfish is not running")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def _get_line(self, timeout: float, *, generation: int | None = None) -> str:
        """Return one line for the expected process generation.

        Raw strings remain accepted for deterministic source tests that inject
        scripted UCI output directly. Production reader threads always enqueue
        ``(generation, line)`` records.
        """
        expected = self._process_generation if generation is None else int(generation)
        end = time.monotonic() + max(0.0, float(timeout))
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            item = self.q.get(timeout=remaining)
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], int):
                item_generation, line = item
                if item_generation != expected:
                    continue
                return str(line)
            return str(item)

    def _wait(self, token: str, timeout: float) -> str:
        end = time.monotonic() + timeout
        generation = self._process_generation
        while time.monotonic() < end:
            try:
                line = self._get_line(min(0.2, max(0.0, end - time.monotonic())), generation=generation)
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

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        multipv = max(1, min(10, int(multipv)))
        depth = max(1, min(40, int(depth)))
        with self._lock:
            self.start()
            generation = self._process_generation
            self._drain()
            self.send(f"setoption name MultiPV value {multipv}")
            self.send("isready")
            self._wait("readyok", 5)
            self.send("position fen " + fen)
            self.send(f"go depth {depth}")
            best: dict[int, RawAnalysisLine] = {}
            end = time.monotonic() + 60
            while time.monotonic() < end:
                try:
                    line = self._get_line(0.3, generation=generation)
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
            self._stop_and_synchronize(generation)
            raise RuntimeError("Stockfish analysis timed out")

    def best_move(self, fen: str, skill_level: int = 10, movetime_ms: int = 500) -> str | None:
        with self._lock:
            self.start()
            generation = self._process_generation
            self._drain()
            skill = max(0, min(20, int(skill_level)))
            movetime_ms = max(50, int(movetime_ms))
            self.send(f"setoption name Skill Level value {skill}")
            self.send("isready")
            self._wait("readyok", 5)
            self.send("position fen " + fen)
            self.send(f"go movetime {movetime_ms}")
            end = time.monotonic() + max(5, movetime_ms / 1000 + 5)
            while time.monotonic() < end:
                try:
                    line = self._get_line(0.2, generation=generation)
                except queue.Empty:
                    continue
                if line.startswith("bestmove"):
                    parts = line.split()
                    return parts[1] if len(parts) > 1 and parts[1] != "(none)" else None
            self._stop_and_synchronize(generation)
            raise RuntimeError("Stockfish did not return bestmove")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            proc = self.proc
            self.proc = None
            self.reader = None
            self._closed = True
            self._process_generation += 1
            self._shutdown_process(proc)
