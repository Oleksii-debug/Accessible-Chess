from __future__ import annotations

"""Windows UI-thread wakeup seam for Version 2 asynchronous file workflows.

The import worker must never call WebView/NVDA presentation code directly.
``Version2ImportUiEventMailbox`` owns the bounded worker->UI queue; this module
owns only scheduling a single UI-thread wakeup when worker events are pending.

Projection semantics remain outside this host seam. The injected ``ui_ready``
callback runs on the captured UI thread and is expected to drain the mailbox
through the exact owner projection contract.
"""

from collections.abc import Callable
import logging
import os
import threading
from typing import Any

from .version2_windows_file_workflows import FileWorkflowEvent
from .version2_windows_import_event_mailbox import Version2ImportUiEventMailbox


_LOG = logging.getLogger(__name__)
_AUTO_RETRY_DELAY_SECONDS = 0.05


def _safe_warning(message: str) -> None:
    """Best-effort telemetry that can never own UI delivery authority."""

    try:
        _LOG.warning(message)
    except BaseException:
        pass


class Version2WinFormsUiPoster:
    """Adapt a WinForms Control.BeginInvoke boundary to a Python callback.

    ``delegate_factory`` exists only as a composition/test seam. Production uses
    ``System.Action`` and therefore requires Windows + pythonnet.
    """

    def __init__(
        self,
        control: object,
        *,
        delegate_factory: Callable[[Callable[[], None]], object] | None = None,
    ) -> None:
        if not callable(getattr(control, "BeginInvoke", None)):
            raise TypeError("WinForms UI poster requires a control with BeginInvoke")
        if delegate_factory is not None and not callable(delegate_factory):
            raise TypeError("delegate_factory must be callable")
        self._control = control
        self._delegate_factory = delegate_factory or self._system_action

    @staticmethod
    def _system_action(callback: Callable[[], None]) -> object:
        if not callable(callback):
            raise TypeError("UI callback must be callable")
        if os.name != "nt":
            raise RuntimeError("WinForms UI posting requires Windows")
        import clr  # type: ignore

        clr.AddReference("System")
        from System import Action  # type: ignore

        return Action(callback)

    def __call__(self, callback: Callable[[], None]) -> Any:
        if not callable(callback):
            raise TypeError("UI callback must be callable")
        if bool(getattr(self._control, "IsDisposed", False)) or bool(
            getattr(self._control, "Disposing", False)
        ):
            raise RuntimeError("WinForms UI owner is closing")
        delegate = self._delegate_factory(callback)
        return self._control.BeginInvoke(delegate)


class Version2ImportUiWakeupPump:
    """Coalesce worker wakeups and marshal pending mailbox work to the UI thread.

    Use this object as the trusted file delegate's ``event_sink``. Events emitted
    synchronously on the UI thread are intentionally not posted again: the action
    caller already receives those exact events. Worker events are first placed in
    the bounded mailbox, then at most one UI wakeup is outstanding.

    ``ui_ready`` owns no domain authority here. It is expected to drain the
    mailbox and hand the resulting path-free events to the existing Library
    presentation owner on the UI thread.
    """

    def __init__(
        self,
        mailbox: Version2ImportUiEventMailbox,
        post_to_ui: Callable[[Callable[[], None]], Any],
        ui_ready: Callable[[], Any],
    ) -> None:
        if not isinstance(mailbox, Version2ImportUiEventMailbox):
            raise TypeError("mailbox must be Version2ImportUiEventMailbox")
        if mailbox.ui_thread_id != threading.get_ident():
            raise RuntimeError("UI wakeup pump must be created on the mailbox UI thread")
        if not callable(post_to_ui) or not callable(ui_ready):
            raise TypeError("UI wakeup callbacks must be callable")
        self._mailbox = mailbox
        self._post_to_ui = post_to_ui
        self._ui_ready = ui_ready
        self._ui_thread_id = mailbox.ui_thread_id
        self._lock = threading.RLock()
        self._wakeup_pending = False
        self._closed = False
        self._post_failures = 0
        self._ready_failures = 0
        self._retry_timer: threading.Timer | None = None
        self._owner_callback: Callable[[], None] | None = None
        self._owner_wakeup_pending = False
        self._owner_post_failures = 0
        self._owner_retry_timer: threading.Timer | None = None

    @property
    def wakeup_pending(self) -> bool:
        with self._lock:
            return self._wakeup_pending

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def post_failure_count(self) -> int:
        with self._lock:
            return self._post_failures

    @property
    def ready_failure_count(self) -> int:
        with self._lock:
            return self._ready_failures

    @property
    def owner_callback_pending(self) -> bool:
        with self._lock:
            return self._owner_callback is not None

    @property
    def owner_post_failure_count(self) -> int:
        with self._lock:
            return self._owner_post_failures

    def __call__(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        return self.event_sink(event)

    def event_sink(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        if not isinstance(event, FileWorkflowEvent):
            raise TypeError("UI wakeup pump accepts FileWorkflowEvent only")

        with self._lock:
            if self._closed:
                return event

        returned = self._mailbox.put(event)
        if threading.get_ident() == self._ui_thread_id:
            return returned

        self._request_wakeup()
        return returned

    def owner_async_event_sink(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        """Deliver an asynchronous completion that is already on the UI thread."""

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("owner asynchronous file events require the UI thread")
        if not isinstance(event, FileWorkflowEvent):
            raise TypeError("UI wakeup pump accepts FileWorkflowEvent only")
        with self._lock:
            if self._closed:
                return event
        returned = self._mailbox.put_async_owner(event)
        # Unlike a synchronous user command, an owner callback has no caller
        # waiting to consume its return value. Drain the exact queued terminal
        # through the existing presentation callback before returning.
        self._run_ui_ready()
        return returned

    def post_owner_callback(self, callback: Callable[[], None]) -> None:
        """Retain one canonical owner callback until it runs on the UI thread."""
        if not callable(callback):
            raise TypeError("owner callback must be callable")
        with self._lock:
            if self._closed:
                raise RuntimeError("UI wakeup pump is closed")
            if self._owner_callback is not None:
                raise RuntimeError("owner callback is already pending")
            self._owner_callback = callback
        self._request_owner_callback_wakeup()

    def _request_owner_callback_wakeup(self, *, schedule_retry: bool = True) -> bool:
        with self._lock:
            if self._closed or self._owner_callback is None:
                return False
            if self._owner_wakeup_pending:
                return True
            self._owner_wakeup_pending = True
        try:
            self._post_to_ui(self._run_owner_callback)
        except BaseException:
            with self._lock:
                self._owner_wakeup_pending = False
                self._owner_post_failures += 1
            if schedule_retry:
                self._schedule_owner_retry()
            return False
        return True

    def _schedule_owner_retry(self) -> None:
        with self._lock:
            if self._closed or self._owner_retry_timer is not None or self._owner_callback is None:
                return
            timer = threading.Timer(_AUTO_RETRY_DELAY_SECONDS, self._retry_pending_owner_callback)
            timer.daemon = True
            self._owner_retry_timer = timer
        timer.start()

    def _retry_pending_owner_callback(self) -> None:
        with self._lock:
            self._owner_retry_timer = None
            if self._closed or self._owner_callback is None:
                return
        if not self._request_owner_callback_wakeup(schedule_retry=False):
            _safe_warning("Version 2 owner callback UI wake-up retry failed")

    def _run_owner_callback(self) -> None:
        if threading.get_ident() != self._ui_thread_id:
            with self._lock:
                self._owner_wakeup_pending = False
            raise RuntimeError("owner callback UI wakeup ran on the wrong thread")
        with self._lock:
            self._owner_wakeup_pending = False
            if self._closed:
                return
            callback = self._owner_callback
            self._owner_callback = None
        if callback is not None:
            callback()

    def request_pending_owner_callback(self) -> bool:
        """Recover a retained owner completion after UI posting failed."""
        with self._lock:
            if self._closed or self._owner_callback is None:
                return False
        if threading.get_ident() == self._ui_thread_id:
            self._run_owner_callback()
            return True
        return self._request_owner_callback_wakeup()

    def _request_wakeup(self, *, schedule_retry: bool = True) -> None:
        with self._lock:
            if self._closed or self._wakeup_pending:
                return
            self._wakeup_pending = True

        ready_callback = (
            self._run_ui_ready
            if schedule_retry
            else lambda: self._run_ui_ready(schedule_retry=False)
        )
        try:
            self._post_to_ui(ready_callback)
        except BaseException:
            with self._lock:
                self._wakeup_pending = False
                self._post_failures += 1
            # The exact event is still retained in the bounded mailbox. Raising
            # a fresh path-free control error is safe: the file delegate isolates
            # event-sink observer failures from canonical storage completion.
            # Never chain the arbitrary poster exception into that control error.
            if schedule_retry:
                self._schedule_retry()
            raise RuntimeError(
                "failed to post Library import event to UI thread"
            ) from None

    def _schedule_retry(self) -> None:
        with self._lock:
            if (
                self._closed
                or self._retry_timer is not None
                or self._mailbox.pending_count == 0
            ):
                return
            timer = threading.Timer(_AUTO_RETRY_DELAY_SECONDS, self._retry_pending_wakeup)
            timer.daemon = True
            self._retry_timer = timer
        timer.start()

    def _retry_pending_wakeup(self) -> None:
        with self._lock:
            self._retry_timer = None
            if self._closed or self._mailbox.pending_count == 0:
                return
        try:
            # One automatic attempt only. A second posting failure remains
            # observable and the mailbox retains the event for explicit recovery.
            self._request_wakeup(schedule_retry=False)
        except BaseException:
            _safe_warning("Version 2 Library UI wake-up retry failed")

    def _run_ui_ready(self, *, schedule_retry: bool = True) -> None:
        if threading.get_ident() != self._ui_thread_id:
            with self._lock:
                self._wakeup_pending = False
            raise RuntimeError("Library import UI wakeup ran on the wrong thread")

        with self._lock:
            self._wakeup_pending = False
            if self._closed:
                return

        try:
            self._ui_ready()
        except BaseException:
            with self._lock:
                self._ready_failures += 1
            # Presentation delivery is an observer boundary. Keep the exact
            # mailbox batch authoritative and make one bounded automatic retry;
            # a repeated presentation failure remains retained for explicit
            # recovery without creating an infinite UI-post loop.
            _safe_warning("Version 2 Library UI-ready callback failed")
            if schedule_retry:
                self._schedule_retry()

    def request_pending_wakeup(self) -> bool:
        """Request a UI wakeup for already-pending events after recoverable failure."""

        if self._mailbox.pending_count == 0:
            return False
        if threading.get_ident() == self._ui_thread_id:
            self._run_ui_ready()
            return True
        self._request_wakeup()
        return True

    def resume_after_refused_shutdown(self) -> bool:
        """Re-open UI delivery after an application close attempt was refused.

        The owning file delegate has already retired its worker before the pump is
        closed. close() cancels retry timers and drops owner callbacks that became
        stale at that retirement boundary, but it deliberately leaves the
        canonical mailbox intact. A refused native close may therefore re-open
        this pump and deliver retained path-free mailbox events through the same
        trusted UI owner.
        """

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("UI wakeup pump recovery requires the UI thread")
        with self._lock:
            if not self._closed:
                return True
            if (
                self._retry_timer is not None
                or self._owner_retry_timer is not None
                or self._owner_callback is not None
                or self._wakeup_pending
                or self._owner_wakeup_pending
            ):
                return False
            self._closed = False
        return True

    def close(self) -> None:
        """Stop future wakeup scheduling; caller must stop the import worker first."""

        with self._lock:
            self._closed = True
            self._wakeup_pending = False
            self._owner_wakeup_pending = False
            self._owner_callback = None
            retry_timer = self._retry_timer
            owner_retry_timer = self._owner_retry_timer
            self._retry_timer = None
            self._owner_retry_timer = None
        if retry_timer is not None:
            retry_timer.cancel()
        if owner_retry_timer is not None:
            owner_retry_timer.cancel()


__all__ = [
    "Version2ImportUiWakeupPump",
    "Version2WinFormsUiPoster",
]
