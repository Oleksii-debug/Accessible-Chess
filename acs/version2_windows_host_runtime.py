from __future__ import annotations

"""Lifecycle-safe composition of Version 2 trusted Windows file-workflow ports.

This module does not register actions and does not own PGN, Library, ChessBase or
projection semantics. It assembles the already-owned host primitives into one
object that a production Windows composition root can inject behind the
canonical action router without reimplementing dialog, threading or shutdown
rules.
"""

from collections.abc import Callable, Mapping
import threading
from typing import Any

from .pgn_document import PgnDocumentSession
from .version2_windows_file_workflows import Version2ImportWorkerServices
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
from .version2_windows_pgn_streaming_host import Version2WindowsStreamingFileActionDelegate


class _Version2RecoverableOwnerCallbackPoster:
    """Retain one file-worker owner callback when ``BeginInvoke`` rejects it.

    PGN Open/Save share one worker slot, so at most one deferred owner callback can
    be authoritative at a time.  The file delegate already generation-fences every
    callback.  Retaining a rejected callback here therefore lets the next trusted
    UI-thread file action complete a durable Save owner commit instead of leaving
    the shared worker permanently busy, while a stale Open callback remains a
    harmless no-op after its delegate-side post-failure fence cleared ownership.

    This seam does not retry domain work and does not swallow the original posting
    error: the delegate still observes exactly the same ``BeginInvoke`` failure and
    applies its existing Open/Save failure semantics.  Only the already-built owner
    callback is retained for bounded recovery.
    """

    def __init__(
        self,
        poster: Callable[[Callable[[], None]], Any],
        *,
        ui_thread_id: int,
    ) -> None:
        if not callable(poster):
            raise TypeError("owner callback poster must be callable")
        if type(ui_thread_id) is not int:
            raise TypeError("ui_thread_id must be an integer")
        self._poster = poster
        self._ui_thread_id = ui_thread_id
        self._lock = threading.RLock()
        self._pending: Callable[[], None] | None = None
        self._closed = False

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._pending is not None

    def __call__(self, callback: Callable[[], None]) -> Any:
        if not callable(callback):
            raise TypeError("owner callback must be callable")
        with self._lock:
            if self._closed:
                raise RuntimeError("owner callback recovery is closed")
            if self._pending is not None:
                raise RuntimeError("previous owner callback is pending recovery")
        try:
            return self._poster(callback)
        except Exception:
            with self._lock:
                if not self._closed and self._pending is None:
                    self._pending = callback
            raise

    def recover_on_owner(self) -> bool:
        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("owner callback recovery requires UI thread")
        with self._lock:
            if self._closed or self._pending is None:
                return False
            callback = self._pending
            self._pending = None
        # Once execution begins, the delegate's own generation/session fences own
        # retry safety. Re-queueing an unexpectedly failing callback here could
        # replay a partially completed domain effect, so failures propagate once.
        callback()
        return True

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending = None


class Version2WindowsFileWorkflowRuntime:
    """Compose trusted file actions, async UI handoff and orderly shutdown.

    The runtime is created on the WinForms UI thread. ``owner_control`` is the
    exact application Form/Control used both for native dialog ownership and
    ``BeginInvoke`` marshalling. ``import_ui_ready`` receives the bounded mailbox
    on that same UI thread; the Library presentation owner remains responsible for
    interpreting/draining its path-free canonical events.

    ``dialog_language_provider`` is presentation-only and resolved lazily by each
    native dialog. It may therefore follow the live V2 shell language without
    rebuilding this runtime or creating a second language state.
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
        dialog_language_provider: Callable[[], object] | None = None,
        mailbox_max_events: int = 64,
        ui_delegate_factory: Callable[[Callable[[], None]], object] | None = None,
        file_forms_loader: Callable[
            [], tuple[object, Callable[[], object], Callable[[], object]]
        ]
        | None = None,
        export_forms_loader: Callable[
            [], tuple[object, Callable[[], object], Callable[[], object]]
        ]
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
        if dialog_language_provider is not None and not callable(dialog_language_provider):
            raise TypeError("dialog_language_provider must be callable")

        self._ui_thread_id = threading.get_ident()
        self._lock = threading.RLock()
        self._closed = False

        self._mailbox = Version2ImportUiEventMailbox(max_events=mailbox_max_events)
        self._poster = Version2WinFormsUiPoster(
            owner_control,
            delegate_factory=ui_delegate_factory,
        )
        self._owner_callback_poster = _Version2RecoverableOwnerCallbackPoster(
            self._poster,
            ui_thread_id=self._ui_thread_id,
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
            language_provider=dialog_language_provider,
        )
        self._export_dialogs = Version2OwnedWindowsPgnExportDialogs(
            lambda: owner_control,
            forms_loader=export_forms_loader,
            language_provider=dialog_language_provider,
        )
        self._export_delegate = Version2WindowsPgnExportDelegate(
            dialogs=self._export_dialogs,
            export_selected=export_selected,
            event_sink=pgn_export_event_sink,
            next_delegate=next_delegate,
            current_focus_provider=current_focus_provider,
        )
        self._file_delegate = Version2WindowsStreamingFileActionDelegate(
            dialogs=self._file_dialogs,
            get_pgn_session=get_pgn_session,
            set_pgn_session=set_pgn_session,
            import_services_factory=import_services_factory,
            event_sink=self._pump,
            next_delegate=self._export_delegate,
            current_focus_provider=current_focus_provider,
            post_to_ui=self._owner_callback_poster,
            owner_async_event_sink=self._pump.owner_async_event_sink,
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
    def pgn_open_running(self) -> bool:
        return self._file_delegate.pgn_open_running

    @property
    def pgn_save_running(self) -> bool:
        return self._file_delegate.pgn_save_running

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
        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("Version 2 Windows file workflow actions require UI thread")
        with self._lock:
            if self._closed:
                raise RuntimeError("Version 2 Windows file workflow runtime is closed")
        # A failed BeginInvoke after durable PGN Save publication must not strand
        # the one shared file worker forever. The next trusted file action is an
        # owner-thread recovery point for that exact generation-fenced callback.
        self._owner_callback_poster.recover_on_owner()
        return self._file_delegate(action_id, payload)

    def wait_for_import(self, timeout: float | None = None) -> bool:
        return self._file_delegate.wait_for_import(timeout)

    def wait_for_pgn_open(self, timeout: float | None = None) -> bool:
        return self._file_delegate.wait_for_pgn_open(timeout)

    def wait_for_pgn_save(self, timeout: float | None = None) -> bool:
        return self._file_delegate.wait_for_pgn_save(timeout)

    def request_pending_import_wakeup(self) -> bool:
        with self._lock:
            if self._closed:
                return False
        recovered = False
        if threading.get_ident() == self._ui_thread_id:
            recovered = self._owner_callback_poster.recover_on_owner()
        return self._pump.request_pending_wakeup() or recovered

    def shutdown(self, timeout: float | None = None) -> bool:
        """Cancel/join active file worker before closing the UI pump."""

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("Version 2 Windows file workflow shutdown requires UI thread")
        with self._lock:
            if self._closed:
                return True

        stopped = self._file_delegate.shutdown(timeout)
        if not stopped:
            # Keep the pump/runtime live so a still-running worker can terminate;
            # caller may retry shutdown. PGN Open publication is already fenced.
            return False

        # Shutdown owns pending-save commit recovery inside the file delegate.
        # Any callback retained only because BeginInvoke failed is stale now.
        self._owner_callback_poster.close()
        self._pump.close()
        with self._lock:
            self._closed = True
        return True


__all__ = ["Version2WindowsFileWorkflowRuntime"]
