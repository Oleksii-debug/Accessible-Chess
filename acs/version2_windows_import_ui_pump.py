from __future__ import annotations

"""Windows UI-thread wakeup seam for Version 2 asynchronous Library imports.

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

    def _request_wakeup(self) -> None:
        with self._lock:
            if self._closed or self._wakeup_pending:
                return
            self._wakeup_pending = True

        try:
            self._post_to_ui(self._run_ui_ready)
        except Exception as exc:
            with self._lock:
                self._wakeup_pending = False
                self._post_failures += 1
            # The exact event is still retained in the bounded mailbox. Raising
            # here is safe: Version2WindowsFileActionDelegate isolates event_sink
            # observer failures from canonical import/storage completion.
            raise RuntimeError("failed to post Library import event to UI thread") from exc

    def _run_ui_ready(self) -> None:
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
        except Exception:
            with self._lock:
                self._ready_failures += 1
            # Presentation delivery is an observer boundary. Pending mailbox
            # events remain available for explicit UI recovery/retry.
            _LOG.warning("Version 2 Library UI-ready callback failed", exc_info=True)

    def request_pending_wakeup(self) -> bool:
        """Request a UI wakeup for already-pending events after recoverable failure."""

        if self._mailbox.pending_count == 0:
            return False
        if threading.get_ident() == self._ui_thread_id:
            self._run_ui_ready()
            return True
        self._request_wakeup()
        return True

    def close(self) -> None:
        """Stop future wakeup scheduling; caller must stop the import worker first."""

        with self._lock:
            self._closed = True
            self._wakeup_pending = False


__all__ = [
    "Version2ImportUiWakeupPump",
    "Version2WinFormsUiPoster",
]
