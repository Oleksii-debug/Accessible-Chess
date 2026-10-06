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


_INVALID_PGN_SESSION = object()


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

        # The production Windows runtime is a trusted application boundary. A
        # PgnDocumentSession subclass is an active object: it may override
        # properties such as ``dirty``/``document_revision`` or methods used by
        # the file delegate. Never execute such caller-controlled hooks merely
        # because ``isinstance`` accepts the object. Convert every non-canonical
        # session to a passive sentinel before it reaches the delegate; the
        # delegate then emits its existing path-free ``pgn_session_invalid``
        # terminal without touching the foreign object. The lower-level direct
        # delegate keeps its historical structural seam for non-Windows tests
        # and embeddings.
        def canonical_pgn_session():
            session = get_pgn_session()
            if session is None or type(session) is PgnDocumentSession:
                return session
            return _INVALID_PGN_SESSION

        self._file_delegate = Version2WindowsStreamingFileActionDelegate(
            dialogs=self._file_dialogs,
            get_pgn_session=canonical_pgn_session,
            set_pgn_session=set_pgn_session,
            import_services_factory=import_services_factory,
            event_sink=self._pump,
            next_delegate=self._export_delegate,
            current_focus_provider=current_focus_provider,
            post_to_ui=self._pump.post_owner_callback,
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
        # The runtime now makes one action-id decision before delegation, so
        # preserve the delegate's exact passive-input boundary here as well.
        # Never execute __eq__ on an active str subclass before fail-closed
        # validation or before deciding whether retained owner state may run.
        if type(action_id) is not str:
            raise TypeError("file action id must be exact text")
        with self._lock:
            if self._closed:
                raise RuntimeError("Version 2 Windows file workflow runtime is closed")
        delegate_was_fenced = self._file_delegate.shutdown_requested
        # Cancellation owns the matching pre-publication decision itself. If an
        # owner callback is retained after UI-post failures, running it before a
        # matching Cancel would publish/commit the pending result first and make
        # that cancellation observe only "no ... running". Skip owner-callback
        # recovery only while the corresponding worker authority is still live;
        # a mismatched Cancel must retain the normal pre-action recovery behavior.
        cancel_owns_pending = (
            action_id == "pgn.cancel_open" and self._file_delegate.pgn_open_running
        ) or (
            action_id == "pgn.cancel_save" and self._file_delegate.pgn_save_running
        )
        if not cancel_owns_pending:
            self._pump.request_pending_owner_callback()

        # Retained mailbox events are accessibility truth, not background
        # telemetry. A presentation failure can exhaust its one automatic retry;
        # the next real owner-thread command is therefore a deterministic recovery
        # opportunity before any newer command result can overtake that terminal.
        # Application-side mailbox delivery is transactional, so any remaining
        # event after this owner-thread attempt means presentation did not commit.
        if self._mailbox.pending_count:
            self._pump.request_pending_wakeup()
            if self._mailbox.pending_count:
                raise RuntimeError(
                    "Version 2 Windows file workflow UI recovery is still pending"
                )

        # Either recovery callback above is an owner boundary and can re-enter
        # native shutdown. Never dispatch the command against a runtime that was
        # synchronously closed, or through a delegate that became newly fenced
        # during this exact recovery transaction.
        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "Version 2 Windows file workflow runtime closed during UI recovery"
                )
        if not delegate_was_fenced and self._file_delegate.shutdown_requested:
            raise RuntimeError(
                "Version 2 Windows file workflow runtime fenced during UI recovery"
            )
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
        owner_recovered = self._pump.request_pending_owner_callback()
        mailbox_recovered = self._pump.request_pending_wakeup()
        with self._lock:
            if self._closed:
                return False
        # UI delivery is an owner boundary and may re-enter a bounded native
        # shutdown that cannot close this outer runtime while a worker drains.
        # In that case the delegate is fenced even though _closed is still False.
        # Do not report wakeup recovery while file actions are no longer live.
        if self._file_delegate.shutdown_requested:
            return False
        return owner_recovered or mailbox_recovered

    def resume_after_refused_shutdown(self) -> bool:
        """Restore file actions atomically after the owning Form refused to close.

        Application shutdown retires the canonical file delegate and closes its
        UI pump before durable progress/database publication. If that later
        publication fails, the still-visible product must recover both halves of
        this runtime; reopening only the delegate or only the pump would advertise
        file commands that cannot complete or cannot reach keyboard/NVDA users.
        """

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError(
                "Version 2 Windows file workflow recovery requires UI thread"
            )
        with self._lock:
            runtime_was_closed = self._closed

        if runtime_was_closed:
            pump_restored = self._pump.resume_after_refused_shutdown()
            if pump_restored is not True:
                return False
            # The delegate may synchronously publish an owner-async recovery
            # terminal (for example PGN Open cancellation). Make the outer
            # runtime live before that callback can run so presentation/focus
            # recovery never observes a mixed "pump open, runtime closed" state.
            # A failed delegate recovery rolls this boundary back below.
            with self._lock:
                self._closed = False

        try:
            delegate_restored = self._file_delegate.resume_after_refused_shutdown()
        except BaseException:
            if runtime_was_closed:
                with self._lock:
                    self._closed = True
                try:
                    self._pump.close()
                except BaseException:
                    # The delegate recovery failure remains authoritative. A
                    # secondary pump-close abort is only diagnostic; leaving
                    # the outer runtime closed is the safe fail-closed state.
                    pass
            raise
        if delegate_restored is not True:
            if runtime_was_closed:
                with self._lock:
                    self._closed = True
                try:
                    self._pump.close()
                except BaseException:
                    # Do not replace the delegate's explicit refusal with an
                    # unrelated UI-pump rollback failure.
                    pass
            return False

        # Import terminals are canonical mailbox state, not disposable UI work.
        # A close attempt can retire the pump after the worker stored such an
        # event. Re-deliver it only after both runtime halves are live again.
        self._pump.request_pending_wakeup()
        # UI-ready delivery is synchronous on the owner thread. A retained
        # terminal can therefore re-enter native shutdown before this recovery
        # boundary returns. Never report the runtime as recovered after that
        # re-entrant close has fenced it again.
        with self._lock:
            if self._closed:
                return False
        # A synchronous UI-ready callback can re-enter bounded shutdown. When
        # that retry times out, the outer runtime remains open but the delegate
        # has been fenced again. Treat that state as not recovered.
        if self._file_delegate.shutdown_requested:
            return False
        return True

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

        # Cross this outer closed-state boundary before closing the UI pump.
        # If pump.close() aborts, application-level recovery must restore both
        # the pump and file delegate rather than observing a half-closed runtime.
        with self._lock:
            self._closed = True
        self._pump.close()
        return True


__all__ = ["Version2WindowsFileWorkflowRuntime"]
