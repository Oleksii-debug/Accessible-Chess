from __future__ import annotations

"""Single-flight Windows host controller for cancellable semantic Book Open.

The worker owns no Book semantics. Preparation is injected and may only return an
opaque prepared value. Canonical application publication is injected separately
and is always invoked through the existing UI-thread poster.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import threading
from typing import Any


class BookOpenWorkerEventKind(str, Enum):
    STARTED = "started"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BookOpenWorkerEvent:
    kind: BookOpenWorkerEventKind
    focus_target: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, BookOpenWorkerEventKind):
            raise TypeError("Book Open worker event kind is invalid")
        if type(self.focus_target) is not str:
            raise TypeError("Book Open worker focus target must be text")


class Version2BookOpenWorker:
    """Prepare one Book off-thread and commit it only on the owning UI thread."""

    def __init__(
        self,
        *,
        prepare: Callable[..., object],
        commit: Callable[[object], Any],
        post_to_ui: Callable[[Callable[[], None]], Any],
        event_sink: Callable[[BookOpenWorkerEvent], Any],
    ) -> None:
        for name, callback in (
            ("prepare", prepare),
            ("commit", commit),
            ("post_to_ui", post_to_ui),
            ("event_sink", event_sink),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        self._prepare = prepare
        self._commit = commit
        self._post_to_ui = post_to_ui
        self._event_sink = event_sink
        self._ui_thread_id = threading.get_ident()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancel: threading.Event | None = None
        self._generation = 0
        self._closed = False

    def _assert_ui_thread(self) -> None:
        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("Book Open worker control requires the UI thread")

    @property
    def active(self) -> bool:
        with self._lock:
            return not self._closed and self._cancel is not None

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _emit(self, kind: BookOpenWorkerEventKind, focus_target: str) -> None:
        self._event_sink(BookOpenWorkerEvent(kind, focus_target))

    def start(self, source: Path, *, focus_target: str = "") -> bool:
        self._assert_ui_thread()
        if not isinstance(source, Path):
            raise TypeError("Book Open source must be a Path")
        if type(focus_target) is not str:
            raise TypeError("Book Open focus target must be text")

        with self._lock:
            if self._closed:
                raise RuntimeError("Book Open worker is closed")
            if self._cancel is not None:
                raise RuntimeError("Book Open is already running")
            self._generation += 1
            generation = self._generation
            cancel = threading.Event()
            self._cancel = cancel
            thread = threading.Thread(
                target=self._run,
                args=(generation, source, focus_target, cancel),
                name="AccessibleChessBookOpen",
                daemon=False,
            )
            self._thread = thread
        try:
            self._emit(BookOpenWorkerEventKind.STARTED, focus_target)
            thread.start()
        except BaseException:
            with self._lock:
                if generation == self._generation and self._thread is thread:
                    self._cancel = None
                    self._thread = None
            try:
                self._emit(BookOpenWorkerEventKind.FAILED, focus_target)
            except BaseException:
                pass
            raise
        return True

    def cancel(self, *, focus_target: str = "") -> bool:
        self._assert_ui_thread()
        with self._lock:
            if self._closed or self._cancel is None:
                return False
            self._cancel.set()
        self._emit(BookOpenWorkerEventKind.CANCELLING, focus_target)
        return True

    def _run(
        self,
        generation: int,
        source: Path,
        focus_target: str,
        cancel: threading.Event,
    ) -> None:
        try:
            prepared = self._prepare(source, cancel_check=cancel.is_set)
        except BaseException as error:
            outcome = ("cancelled" if cancel.is_set() else "failed", error)
        else:
            outcome = ("cancelled", None) if cancel.is_set() else ("prepared", prepared)

        def finish() -> None:
            self._finish(generation, focus_target, cancel, outcome)

        try:
            self._post_to_ui(finish)
        except BaseException:
            # Owner shutdown can invalidate BeginInvoke after preparation ends.
            # Never commit from the worker as a fallback. Clear only this exact
            # generation so shutdown/join and later diagnostics remain truthful.
            with self._lock:
                if generation == self._generation:
                    self._cancel = None
                    self._thread = None

    def _finish(
        self,
        generation: int,
        focus_target: str,
        cancel: threading.Event,
        outcome: tuple[str, object],
    ) -> None:
        self._assert_ui_thread()
        with self._lock:
            if generation != self._generation:
                return
            if self._closed:
                self._cancel = None
                self._thread = None
                return
            current_cancel = self._cancel
        if current_cancel is not cancel:
            return

        kind, value = outcome
        if cancel.is_set() or kind == "cancelled":
            terminal = BookOpenWorkerEventKind.CANCELLED
        elif kind == "prepared":
            try:
                self._commit(value)
            except BaseException:
                terminal = BookOpenWorkerEventKind.FAILED
            else:
                terminal = BookOpenWorkerEventKind.COMPLETED
        else:
            terminal = BookOpenWorkerEventKind.FAILED

        with self._lock:
            if generation == self._generation:
                self._cancel = None
                self._thread = None
        self._emit(terminal, focus_target)

    def shutdown(self, timeout: float | None = None) -> bool:
        self._assert_ui_thread()
        if timeout is not None and (
            type(timeout) not in {int, float} or timeout < 0
        ):
            raise ValueError("Book Open shutdown timeout must be non-negative or None")
        with self._lock:
            self._closed = True
            self._generation += 1
            cancel = self._cancel
            thread = self._thread
            if cancel is not None:
                cancel.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                return False
        with self._lock:
            self._cancel = None
            self._thread = None
        return True


__all__ = [
    "BookOpenWorkerEvent",
    "BookOpenWorkerEventKind",
    "Version2BookOpenWorker",
]
