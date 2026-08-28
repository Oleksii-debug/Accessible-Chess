from __future__ import annotations

"""Lifecycle-safe composition of Version 2 trusted Windows file-workflow ports.

This module does not register actions and does not own PGN, Library, ChessBase or
projection semantics.  It assembles the already-owned #300 host primitives into
one object that a production Windows composition root can inject behind the
canonical action router without reimplementing dialog, threading or shutdown
rules.
"""

from collections.abc import Callable, Mapping
import threading
from typing import Any

from .pgn_document import PgnDocumentSession
from .version2_windows_file_workflows import (
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)
from .version2_windows_import_event_mailbox import Version2ImportUiEventMailbox
from .version2_windows_import_ui_pump import (
    Version2ImportUiWakeupPump,
    Version2WinFormsUiPoster,
)
from .version2_windows_native_dialog_ownership import (
    Version2OwnedWindowsFileDialogs,
    Version2OwnedWindowsPgnExportDialogs,
)
from .version2_windows_pgn_export import Version2WindowsPgnExportDelegate


class Version2WindowsFileWorkflowRuntime:
    """Compose trusted file actions, async UI handoff and orderly shutdown.

    The runtime is created on the WinForms UI thread.  ``owner_control`` is the
    exact application Form/Control used both for native dialog ownership and
    ``BeginInvoke`` marshalling.  ``import_ui_ready`` receives the bounded mailbox
    on that same UI thread; the Library presentation owner remains responsible for
    interpreting/draining its path-free canonical events.
    """

    def __init__(
        self,
        *,
        owner_control: object,
        get_pgn_session: Callable[[], PgnDocumentSession | None],
        set_pgn_session: Callable[[PgnDocumentSession], Any],
        import_services_factory: Callable[[], Version2ImportWorkerServices],
        export_selected: Callable[[object, object], Any],
        import_ui_ready: Callable[[Version2ImportUiEventMailbox], Any],
        pgn_export_event_sink: Callable[[object], Any],
        next_delegate: Callable[[str, Mapping[str, object]], Any],
        current_focus_provider: Callable[[], str] | None = None,
        mailbox_max_events: int = 64,
        ui_delegate_factory: Callable[[Callable[[], None]], object] | None = None,
        file_forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]]
        | None = None,
        export_forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]]
        | None = None,
    ) -> None:
        for name, callback in (
            ("get_pgn_session", get_pgn_session),
            ("set_pgn_session", set_pgn_session),
            ("import_services_factory", import_services_factory),
            ("export_selected", export_selected),
            ("import_ui_ready", import_ui_ready),
            ("pgn_export_event_sink", pgn_export_event_sink),
            ("next_delegate", next_delegate),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("current_focus_provider must be callable")

        self._ui_thread_id = threading.get_ident()
        self._lock = threading.RLock()
        self._closed = False

        self._mailbox = Version2ImportUiEventMailbox(max_events=mailbox_max_events)
        self._poster = Version2WinFormsUiPoster(
            owner_control,
            delegate_factory=ui_delegate_factory,
        )

        def ui_ready() -> Any:
            return import_ui_ready(self._mailbox)

        self._pump = Version2ImportUiWakeupPump(
            self._mailbox,
            self._poster,
            ui_ready,
        )
        self._file_dialogs = Version2OwnedWindowsFileDialogs(
            lambda: owner_control,
            forms_loader=file_forms_loader,
        )
        self._export_dialogs = Version2OwnedWindowsPgnExportDialogs(
            lambda: owner_control,
            forms_loader=export_forms_loader,
        )
        self._export_delegate = Version2WindowsPgnExportDelegate(
            dialogs=self._export_dialogs,
            export_selected=export_selected,
            event_sink=pgn_export_event_sink,
            next_delegate=next_delegate,
            current_focus_provider=current_focus_provider,
        )
        self._file_delegate = Version2WindowsFileActionDelegate(
            dialogs=self._file_dialogs,
            get_pgn_session=get_pgn_session,
            set_pgn_session=set_pgn_session,
            import_services_factory=import_services_factory,
            event_sink=self._pump,
            next_delegate=self._export_delegate,
            current_focus_provider=current_focus_provider,
        )

    @property
    def ui_thread_id(self) -> int:
        return self._ui_thread_id

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def import_running(self) -> bool:
        return self._file_delegate.import_running

    @property
    def import_mailbox(self) -> Version2ImportUiEventMailbox:
        return self._mailbox

    @property
    def file_dialogs(self) -> Version2OwnedWindowsFileDialogs:
        return self._file_dialogs

    @property
    def export_dialogs(self) -> Version2OwnedWindowsPgnExportDialogs:
        return self._export_dialogs

    def __call__(self, action_id: str, payload: Mapping[str, object]) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError("Version 2 Windows file workflow runtime is closed")
        return self._file_delegate(action_id, payload)

    def wait_for_import(self, timeout: float | None = None) -> bool:
        return self._file_delegate.wait_for_import(timeout)

    def request_pending_import_wakeup(self) -> bool:
        with self._lock:
            if self._closed:
                return False
        return self._pump.request_pending_wakeup()

    def shutdown(self, timeout: float | None = None) -> bool:
        """Cancel/join import before closing the UI pump; retryable on timeout."""

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("Version 2 Windows file workflow shutdown requires UI thread")
        with self._lock:
            if self._closed:
                return True

        stopped = self._file_delegate.shutdown(timeout)
        if not stopped:
            # Keep the pump/runtime live so the still-running worker can finish and
            # its terminal event can be observed; caller may retry shutdown.
            return False

        self._pump.close()
        with self._lock:
            self._closed = True
        return True


__all__ = ["Version2WindowsFileWorkflowRuntime"]
