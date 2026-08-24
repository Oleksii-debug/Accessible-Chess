from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from typing import Callable

from .engine_ports import (
    EngineContractError,
    EngineContractErrorCode,
    RawAnalysisLine,
)


ProcessFactory = Callable[..., subprocess.Popen]
_UCI_MOVE_RE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
_UCI_OUTPUT_MAX_LINE_CHARS = 16_384
_UCI_OUTPUT_MAX_PENDING_LINES = 256


class UCIEngine:
    """Serialized UCI adapter used by both analysis and engine play.

    One instance owns one subprocess. Calls are serialized so analysis and move
    requests cannot interleave commands on the same UCI stream.
    """

    def __init__(
        self,
        path: str,
        *,
        process_factory: ProcessFactory = subprocess.Popen,
    ):
        if (
            not isinstance(path, str)
            or not path.strip()
            or "\n" in path
            or "\r" in path
        ):
            raise EngineContractError(
                "Stockfish path must be non-empty single-line text",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if not callable(process_factory):
            raise EngineContractError(
                "process_factory must be callable",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        self.path = path.strip()
        self.proc = None
        self.q: queue.Queue[str] = queue.Queue(
            maxsize=_UCI_OUTPUT_MAX_PENDING_LINES
        )
        self.reader = None
        self._process_factory = process_factory
        self._lock = threading.RLock()
        self._reader_state_lock = threading.Lock()
        self._reader_fault: tuple[object, str] | None = None
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Stockfish adapter is closed")
            if self.proc and self.proc.poll() is None:
                return
            previous_reader = self.reader
            self.proc = None
            self.reader = None
            if (
                previous_reader is not None
                and previous_reader is not threading.current_thread()
            ):
                previous_reader.join(timeout=0.2)
            self._drain()
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
            if not self._compatible_process(proc):
                self._terminate_process(proc)
                raise EngineContractError(
                    "process_factory returned an incompatible process",
                    code=EngineContractErrorCode.INVALID_PROVIDER,
                )

            stdout = proc.stdout
            self.proc = proc
            with self._reader_state_lock:
                self._reader_fault = None

            def read() -> None:
                try:
                    for line in stdout:
                        if not isinstance(line, str):
                            continue
                        if len(line) > _UCI_OUTPUT_MAX_LINE_CHARS:
                            self._record_reader_fault(proc, "line")
                            return
                        try:
                            self.q.put_nowait(line.strip())
                        except queue.Full:
                            self._record_reader_fault(proc, "queue")
                            return
                except Exception:
                    return

            self.reader = threading.Thread(
                target=read,
                daemon=True,
                name="acs-stockfish-reader",
            )
            self.reader.start()
            try:
                self.send("uci")
                self._wait("uciok", 5)
                self.send("isready")
                self._wait("readyok", 5)
            except Exception:
                self._discard_process(proc)
                raise

    def send(self, command: str) -> None:
        if (
            not isinstance(command, str)
            or not command.strip()
            or "\n" in command
            or "\r" in command
        ):
            raise EngineContractError(
                "UCI command must be non-empty single-line text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        command = command.strip()
        with self._lock:
            if self._closed:
                raise RuntimeError("Stockfish adapter is closed")
            if not self.proc or not self.proc.stdin or self.proc.poll() is not None:
                raise RuntimeError("Stockfish is not running")
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()

    def _wait(self, token: str, timeout: float) -> str:
        proc = self.proc
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self._raise_if_reader_fault(proc)
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                self._raise_if_reader_fault(proc)
                continue
            self._raise_if_reader_fault(proc)
            if line.strip() == token:
                return line
        self._raise_if_reader_fault(proc)
        raise RuntimeError("Stockfish did not respond: " + token)

    def _record_reader_fault(self, proc: object, reason: str) -> None:
        with self._reader_state_lock:
            if self.proc is proc:
                self._reader_fault = (proc, reason)

    def _raise_if_reader_fault(self, proc: object | None) -> None:
        if proc is None:
            return
        with self._reader_state_lock:
            fault = self._reader_fault
        if fault is not None and fault[0] is proc:
            raise EngineContractError(
                "Engine response exceeded safe limits",
                code=EngineContractErrorCode.INVALID_RESULT,
            )

    @staticmethod
    def _compatible_process(proc: object) -> bool:
        if isinstance(proc, type):
            return False
        if not all(
            callable(getattr(proc, name, None))
            for name in ("poll", "wait", "terminate")
        ):
            return False
        stdin = getattr(proc, "stdin", None)
        stdout = getattr(proc, "stdout", None)
        return (
            stdin is not None
            and callable(getattr(stdin, "write", None))
            and callable(getattr(stdin, "flush", None))
            and stdout is not None
            and hasattr(stdout, "__iter__")
        )

    @staticmethod
    def _terminate_process(proc: object) -> None:
        """Best-effort terminate, then hard-kill and reap a stubborn child."""
        try:
            poll = getattr(proc, "poll", None)
            if callable(poll) and poll() is None:
                terminate = getattr(proc, "terminate", None)
                if callable(terminate):
                    terminate()
        except Exception:
            pass
        try:
            wait = getattr(proc, "wait", None)
            if callable(wait):
                wait(timeout=2)
                return
        except Exception:
            pass

        try:
            poll = getattr(proc, "poll", None)
            still_running = not callable(poll) or poll() is None
        except Exception:
            still_running = True
        if not still_running:
            return

        try:
            kill = getattr(proc, "kill", None)
            if callable(kill):
                kill()
        except Exception:
            pass
        try:
            wait = getattr(proc, "wait", None)
            if callable(wait):
                wait(timeout=2)
        except Exception:
            pass

    def _discard_process(self, proc: object) -> None:
        self._terminate_process(proc)
        reader = self.reader
        self.proc = None
        self.reader = None
        with self._reader_state_lock:
            if self._reader_fault is not None and self._reader_fault[0] is proc:
                self._reader_fault = None
        self._drain()
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=0.2)

    def _discard_failed_transaction(self, proc: object | None) -> None:
        """Discard only the subprocess used by a failed UCI transaction.

        The adapter itself stays open so the next request can start a fresh
        Stockfish process. This prevents malformed/late output from a failed
        search leaking into a retry while preserving application-level recovery.
        """
        if proc is not None and self.proc is proc:
            self._discard_process(proc)

    @staticmethod
    def _raise_if_process_exited(proc: object | None, operation: str) -> None:
        if proc is None:
            return
        poll = getattr(proc, "poll", None)
        if callable(poll) and poll() is not None:
            raise RuntimeError(f"Stockfish exited during {operation}")

    @staticmethod
    def _normalize_fen(fen: str) -> str:
        if (
            not isinstance(fen, str)
            or not fen.strip()
            or "\n" in fen
            or "\r" in fen
        ):
            raise EngineContractError(
                "engine FEN must be non-empty single-line text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return fen.strip()

    @staticmethod
    def _bounded_integer(
        name: str,
        value: int,
        minimum: int,
        maximum: int,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise EngineContractError(
                f"{name} must be an integer",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return max(minimum, min(maximum, value))

    @staticmethod
    def _minimum_integer(name: str, value: int, minimum: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise EngineContractError(
                f"{name} must be an integer",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return max(minimum, value)

    @staticmethod
    def _bestmove_token(parts: list[str]) -> str | None:
        if len(parts) < 2 or parts[0] != "bestmove":
            raise EngineContractError(
                "Stockfish returned an invalid bestmove response",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        move = parts[1]
        if move in {"(none)", "0000"}:
            return None
        if _UCI_MOVE_RE.fullmatch(move) is None:
            raise EngineContractError(
                "Stockfish returned an invalid bestmove token",
                code=EngineContractErrorCode.INVALID_RESULT,
            )
        return move

    def _drain(self) -> None:
        for _ in range(_UCI_OUTPUT_MAX_PENDING_LINES):
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

    def analyze(
        self,
        fen: str,
        multipv: int = 5,
        depth: int = 16,
    ) -> tuple[RawAnalysisLine, ...]:
        fen = self._normalize_fen(fen)
        multipv = self._bounded_integer("multipv", multipv, 1, 10)
        depth = self._bounded_integer("depth", depth, 1, 40)
        with self._lock:
            self.start()
            proc = self.proc
            try:
                self._drain()
                self._raise_if_reader_fault(proc)
                self._configure_request_options(multipv=multipv, skill_level=20)
                self.send("position fen " + fen)
                self.send(f"go depth {depth}")
                best: dict[int, RawAnalysisLine] = {}
                end = time.monotonic() + 60
                while time.monotonic() < end:
                    self._raise_if_reader_fault(proc)
                    try:
                        line = self.q.get(timeout=0.3)
                    except queue.Empty:
                        self._raise_if_reader_fault(proc)
                        self._raise_if_process_exited(proc, "analysis")
                        continue
                    self._raise_if_reader_fault(proc)
                    tokens = line.split()
                    if tokens and tokens[0] == "bestmove":
                        self._bestmove_token(tokens)
                        return tuple(best[k] for k in sorted(best)[:multipv])
                    if not (line.startswith("info ") and " pv " in line):
                        continue
                    mp_match = re.search(r" multipv (\d+)", line)
                    depth_match = re.search(r" depth (\d+)", line)
                    score_match = re.search(r" score (cp|mate) (-?\d+)", line)
                    if not (mp_match and depth_match and score_match):
                        continue
                    try:
                        mp = int(mp_match.group(1))
                        item_depth = int(depth_match.group(1))
                        score_value = int(score_match.group(2))
                    except ValueError:
                        continue
                    if not 1 <= mp <= multipv:
                        continue
                    score_kind = score_match.group(1)
                    pv = tuple(line.split(" pv ", 1)[1].split())
                    if not pv or any(_UCI_MOVE_RE.fullmatch(move) is None for move in pv):
                        continue
                    best[mp] = RawAnalysisLine(item_depth, score_kind, score_value, pv)
                self._raise_if_reader_fault(proc)
                raise RuntimeError("Stockfish analysis timed out")
            except Exception:
                self._discard_failed_transaction(proc)
                raise

    def best_move(
        self,
        fen: str,
        skill_level: int = 10,
        movetime_ms: int = 500,
    ) -> str | None:
        fen = self._normalize_fen(fen)
        skill = self._bounded_integer("skill_level", skill_level, 0, 20)
        movetime_ms = self._minimum_integer(
            "movetime_ms",
            movetime_ms,
            50,
        )
        with self._lock:
            self.start()
            proc = self.proc
            try:
                self._drain()
                self._raise_if_reader_fault(proc)
                self._configure_request_options(multipv=1, skill_level=skill)
                self.send("position fen " + fen)
                self.send(f"go movetime {movetime_ms}")
                end = time.monotonic() + max(5, movetime_ms / 1000 + 5)
                while time.monotonic() < end:
                    self._raise_if_reader_fault(proc)
                    try:
                        line = self.q.get(timeout=0.2)
                    except queue.Empty:
                        self._raise_if_reader_fault(proc)
                        self._raise_if_process_exited(proc, "bestmove search")
                        continue
                    self._raise_if_reader_fault(proc)
                    parts = line.split()
                    if not parts or parts[0] != "bestmove":
                        continue
                    return self._bestmove_token(parts)
                self._raise_if_reader_fault(proc)
                raise RuntimeError("Stockfish did not return bestmove")
            except Exception:
                self._discard_failed_transaction(proc)
                raise

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
                    self._terminate_process(proc)
            self.proc = None
            reader = self.reader
            self.reader = None
            with self._reader_state_lock:
                self._reader_fault = None
            self._closed = True
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=0.2)
