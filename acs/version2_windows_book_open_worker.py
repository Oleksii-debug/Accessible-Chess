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
        self._focus_target = ""
        self._pending_outcome_kind: str | None = None
        self._recovery_focus: str | None = None
        self._recovery_terminal_kind: BookOpenWorkerEventKind | None = None

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

    def _publish_pending_recovery_terminal(self) -> None:
        """Publish one owner-thread terminal retained by a refused close."""
        self._assert_ui_thread()
        with self._lock:
            if self._closed or self._thread is not None or self._cancel is not None:
                return
            focus_target = self._recovery_focus
            terminal_kind = self._recovery_terminal_kind
        if focus_target is None or terminal_kind is None:
            return
        self._emit(terminal_kind, focus_target)
        with self._lock:
            if (
                self._thread is None
                and self._cancel is None
                and self._recovery_focus == focus_target
                and self._recovery_terminal_kind is terminal_kind
            ):
                self._recovery_focus = None
                self._recovery_terminal_kind = None

    def start(self, source: Path, *, focus_target: str = "") -> bool:
        self._assert_ui_thread()
        if not isinstance(source, Path):
            raise TypeError("Book Open source must be a Path")
        if type(focus_target) is not str:
            raise TypeError("Book Open focus target must be text")

        # A refused close can retire an already-finished generation after its
        # owner callback was invalidated. Clear that accessible busy state before
        # a new Book Open is allowed to announce another STARTED terminal.
        self._publish_pending_recovery_terminal()

        with self._lock:
            if self._closed:
                raise RuntimeError("Book Open worker is closed")
            if self._cancel is not None:
                raise RuntimeError("Book Open is already running")
            self._generation += 1
            generation = self._generation
            cancel = threading.Event()
            self._cancel = cancel
            self._focus_target = focus_target
            self._pending_outcome_kind = None
            thread = threading.Thread(
                target=self._run,
                args=(generation, source, focus_target, cancel),
                name="AccessibleChessBookOpen",
                daemon=False,
            )
            self._thread = thread
        try:
            self._emit(BookOpenWorkerEventKind.STARTED, focus_target)
            # STARTED is an observer boundary and may re-enter native FormClosing.
            # Revalidate exact ownership after the callback before launching the
            # non-daemon thread; shutdown may already have fenced this generation.
            with self._lock:
                may_start = (
                    generation == self._generation
                    and not self._closed
                    and self._thread is thread
                    and self._cancel is cancel
                )
            if not may_start:
                return False
            thread.start()
        except BaseException:
            with self._lock:
                if generation == self._generation and self._thread is thread:
                    self._cancel = None
                    self._thread = None
                    self._focus_target = ""
                    self._pending_outcome_kind = None
                    self._pending_outcome_kind = None
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

        # Publish the fixed preparation outcome before owner posting. Shutdown
        # can then preserve a failure that was already authoritative, while a
        # later cancellation still discards a merely prepared candidate.
        with self._lock:
            if (
                generation == self._generation
                and self._cancel is cancel
                and self._thread is threading.current_thread()
            ):
                self._pending_outcome_kind = outcome[0]

        def finish() -> None:
            self._finish(generation, focus_target, cancel, outcome)

        try:
            self._post_to_ui(finish)
        except BaseException:
            # Owner shutdown can invalidate BeginInvoke after preparation ends.
            # Never commit from the worker as a fallback. A refused close may
            # already have advanced the generation fence and re-opened control
            # while this cancelled thread drains; clear only the exact retained
            # cancel/thread ownership so the visible application cannot remain
            # permanently busy after the stale generation exits.
            with self._lock:
                if self._cancel is cancel and self._thread is threading.current_thread():
                    self._cancel = None
                    self._thread = None
                    self._focus_target = ""

    def _finish(
        self,
        generation: int,
        focus_target: str,
        cancel: threading.Event,
        outcome: tuple[str, object],
    ) -> None:
        self._assert_ui_thread()
        stale_reopened = False
        with self._lock:
            if generation != self._generation:
                # A bounded shutdown can fence this generation but still refuse
                # the native close while its cancelled thread drains. If recovery
                # has re-opened the worker, consume only this exact stale owner
                # and publish one cancelled terminal; this returns keyboard/NVDA
                # state to idle without allowing the prepared result to commit.
                if self._cancel is cancel:
                    self._cancel = None
                    self._thread = None
                    self._focus_target = ""
                    self._pending_outcome_kind = None
                    stale_reopened = not self._closed
                else:
                    return
            elif self._closed:
                self._cancel = None
                self._thread = None
                self._focus_target = ""
                self._pending_outcome_kind = None
                return
            current_cancel = self._cancel
        if stale_reopened:
            with self._lock:
                recovery_terminal = self._recovery_terminal_kind
            terminal = recovery_terminal or BookOpenWorkerEventKind.CANCELLED
            self._emit(terminal, focus_target)
            with self._lock:
                if self._recovery_focus == focus_target:
                    self._recovery_focus = None
                    self._recovery_terminal_kind = None
            return
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
                self._focus_target = ""
                self._pending_outcome_kind = None
        self._emit(terminal, focus_target)

    def resume_after_refused_shutdown(self) -> bool:
        """Re-open control after the native close was refused.

        A fully retired worker can reopen immediately. A bounded shutdown may
        instead have fenced and cancelled a generation whose thread is still
        draining. That generation can no longer commit because shutdown()
        advanced the generation fence, so it is safe to re-open control while
        retaining its exact busy lease until the stale terminal callback (or
        post-failure cleanup) clears it. New Book Open work remains blocked by
        _cancel until that cleanup completes.
        """
        self._assert_ui_thread()
        fully_retired = False
        with self._lock:
            if not self._closed:
                return True
            if self._thread is None and self._cancel is None:
                self._closed = False
                fully_retired = True
            elif (
                self._thread is None
                or self._cancel is None
                or not self._cancel.is_set()
            ):
                return False
            else:
                self._closed = False
        if fully_retired:
            # If shutdown retired an in-flight Book after its preparation had
            # already finished, the stale posted callback can no longer publish
            # a terminal. Reconcile the visible/NVDA busy state now, on the UI
            # owner thread, before reporting recovery success.
            self._publish_pending_recovery_terminal()
            # Terminal delivery is itself an observer boundary and may re-enter
            # FormClosing. Do not claim recovery if that callback already fenced
            # this worker again.
            with self._lock:
                if self._closed:
                    return False
        return True

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
                if self._recovery_focus is None:
                    self._recovery_focus = self._focus_target
                    self._recovery_terminal_kind = (
                        BookOpenWorkerEventKind.FAILED
                        if self._pending_outcome_kind == "failed"
                        else BookOpenWorkerEventKind.CANCELLED
                    )
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                return False
        with self._lock:
            self._cancel = None
            self._thread = None
            self._focus_target = ""
            self._pending_outcome_kind = None
        return True


__all__ = [
    "BookOpenWorkerEvent",
    "BookOpenWorkerEventKind",
    "Version2BookOpenWorker",
]
