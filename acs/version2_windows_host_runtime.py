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
from types import MethodType
from typing import Any

from .acsdb import AcsDatabase
from .library_export_service import LibraryExportService
from .pgn_document import PgnDocumentSession
from .version2_windows_file_workflows import Version2ImportWorkerServices
from .version2_windows_import_event_mailbox import Version2ImportUiEventMailbox
from .version2_windows_import_ui_pump import (
    Version2ImportUiWakeupPump,
    Version2WinFormsUiPoster,
)
from .version2_windows_library_export import (
    LibraryExportWorkerServices,
    Version2WindowsLibraryExportDelegate,
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
        library_export_event_sink: Callable[[object], Any] | None = None,
        library_export_delegate: Version2WindowsLibraryExportDelegate | None = None,
        library_export_worker_services_factory: Callable[
            [], LibraryExportWorkerServices
        ]
        | None = None,
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
        if library_export_event_sink is not None and not callable(
            library_export_event_sink
        ):
            raise TypeError("library_export_event_sink must be callable")
        if library_export_delegate is not None and not isinstance(
            library_export_delegate, Version2WindowsLibraryExportDelegate
        ):
            raise TypeError(
                "library_export_delegate must be Version2WindowsLibraryExportDelegate"
            )
        if library_export_worker_services_factory is not None and not callable(
            library_export_worker_services_factory
        ):
            raise TypeError("library_export_worker_services_factory must be callable")
        if (
            library_export_delegate is not None
            and library_export_worker_services_factory is not None
        ):
            raise ValueError(
                "inject either library_export_delegate or worker services factory, not both"
            )
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("current_focus_provider must be callable")
        if dialog_language_provider is not None and not callable(
            dialog_language_provider
        ):
            raise TypeError("dialog_language_provider must be callable")

        self._ui_thread_id = threading.get_ident()
        self._lock = threading.RLock()
        self._closed = False
        # Native file dialogs pump the owner message loop. Reserve the exact
        # Library operation during modal pre-worker setup so a re-entrant
        # Import/Export command cannot slip past the counterpart busy check
        # before either delegate has published its worker-running state.
        self._library_modal_operation = ""

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
        if library_export_delegate is None:
            worker_factory = (
                library_export_worker_services_factory
                or self._library_export_worker_factory(import_services_factory)
            )
            library_export_delegate = Version2WindowsLibraryExportDelegate(
                dialogs=self._export_dialogs,
                worker_services_factory=worker_factory,
                post_to_ui=self._poster,
                event_sink=(
                    pgn_export_event_sink
                    if library_export_event_sink is None
                    else library_export_event_sink
                ),
                next_delegate=next_delegate,
                current_focus_provider=current_focus_provider,
            )
        self._library_export_delegate = library_export_delegate

        self._export_delegate = Version2WindowsPgnExportDelegate(
            dialogs=self._export_dialogs,
            export_selected=export_selected,
            event_sink=pgn_export_event_sink,
            next_delegate=self._library_export_delegate,
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

    @staticmethod
    def _library_export_worker_factory(
        import_services_factory: Callable[[], Version2ImportWorkerServices],
    ) -> Callable[[], LibraryExportWorkerServices]:
        """Derive worker-local Library export ownership from canonical ACSDB services."""

        def create() -> LibraryExportWorkerServices:
            services = import_services_factory()
            if type(services) is not Version2ImportWorkerServices:
                raise TypeError("import services factory returned an invalid bundle")
            close = services.close
            if (
                type(close) is not MethodType
                or close.__func__ is not AcsDatabase.close
                or type(close.__self__) is not AcsDatabase
            ):
                raise TypeError(
                    "worker services do not expose their canonical AcsDatabase owner"
                )
            database = close.__self__
            try:
                library = LibraryExportService(database)
                return LibraryExportWorkerServices(library, close)
            except BaseException:
                try:
                    close()
                except BaseException:
                    pass
                raise

        return create

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
    def export_running(self) -> bool:
        return self._library_export_delegate.export_running

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
        if type(action_id) is not str:
            raise TypeError("file action id must be exact text")

        library_start = action_id in {"library.import", "library.export"}
        with self._lock:
            if self._closed:
                raise RuntimeError("Version 2 Windows file workflow runtime is closed")
            modal_operation = self._library_modal_operation
            if library_start and modal_operation:
                if modal_operation == "library.import":
                    raise RuntimeError("Library import is already active")
                raise RuntimeError("Library export is already active")

        if library_start:
            # A terminal retained after bounded UI-post failure owns chronology.
            # Recover it before any newer Library operation can open a dialog.
            self._library_export_delegate.recover_pending_terminal()
            with self._lock:
                if self._closed:
                    raise RuntimeError(
                        "Version 2 Windows file workflow runtime closed during Library recovery"
                    )

        delegate_was_fenced = self._file_delegate.shutdown_requested

        def cancellation_owns_live_worker() -> bool:
            if action_id == "pgn.cancel_open":
                return self._file_delegate.pgn_open_running
            if action_id == "pgn.cancel_save":
                return self._file_delegate.pgn_save_running
            if action_id == "library.cancel_import":
                return self._file_delegate.import_running
            return False

        cancel_owns_pending = cancellation_owns_live_worker()
        if not cancel_owns_pending:
            self._pump.request_pending_owner_callback()
            if self._pump.owner_callback_pending:
                raise RuntimeError(
                    "Version 2 Windows file workflow owner UI recovery is still pending"
                )

        if self._mailbox.pending_count:
            self._pump.request_pending_wakeup()
            if self._mailbox.pending_count and not cancellation_owns_live_worker():
                raise RuntimeError(
                    "Version 2 Windows file workflow UI recovery is still pending"
                )

        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "Version 2 Windows file workflow runtime closed during UI recovery"
                )
        if not delegate_was_fenced and self._file_delegate.shutdown_requested:
            raise RuntimeError(
                "Version 2 Windows file workflow runtime fenced during UI recovery"
            )

        # Import and export share worker-local Library/ACSDB ownership and one
        # accessible Cancel command. They cannot overlap, including the re-entrant
        # window while a native dialog pumps the WinForms owner loop.
        if action_id == "library.export" and self.import_running:
            raise RuntimeError("Library import is already active")
        if action_id == "library.import" and self.export_running:
            raise RuntimeError("Library export is already active")
        if action_id == "library.cancel_import" and self.export_running:
            if payload is not None and not (type(payload) is dict and not payload):
                raise ValueError("Library cancellation accepts no payload")
            if self._file_delegate.shutdown_requested:
                raise RuntimeError(
                    "Version 2 Windows file workflow runtime is fenced"
                )
            return self._library_export_delegate.cancel_export()

        if library_start:
            with self._lock:
                if self._closed:
                    raise RuntimeError("Version 2 Windows file workflow runtime is closed")
                if self._library_modal_operation:
                    if self._library_modal_operation == "library.import":
                        raise RuntimeError("Library import is already active")
                    raise RuntimeError("Library export is already active")
                if action_id == "library.export" and self.import_running:
                    raise RuntimeError("Library import is already active")
                if action_id == "library.import" and self.export_running:
                    raise RuntimeError("Library export is already active")
                self._library_modal_operation = action_id
            try:
                return self._file_delegate(action_id, payload)
            finally:
                with self._lock:
                    if self._library_modal_operation == action_id:
                        self._library_modal_operation = ""

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
        # A recovery attempt is not recovery authority. Owner callback execution
        # and mailbox delivery are transactional and may retain their exact work
        # after a presentation failure. Report success only when that retained
        # accessibility state has actually committed.
        if self._pump.owner_callback_pending or self._mailbox.pending_count:
            return False
        return owner_recovered or mailbox_recovered

    def resume_after_refused_shutdown(self) -> bool:
        """Restore all native file owners after the owning Form refused to close."""

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
            with self._lock:
                self._closed = False

        def rollback_recovery() -> None:
            for owner in (self._library_export_delegate, self._file_delegate):
                try:
                    owner.shutdown(timeout=0.0)
                except BaseException:
                    pass
            if runtime_was_closed:
                with self._lock:
                    self._closed = True
                try:
                    self._pump.close()
                except BaseException:
                    pass

        try:
            delegate_restored = self._file_delegate.resume_after_refused_shutdown()
        except BaseException:
            rollback_recovery()
            raise
        if delegate_restored is not True:
            rollback_recovery()
            return False

        try:
            export_restored = self._library_export_delegate.resume_after_refused_shutdown()
        except BaseException:
            rollback_recovery()
            raise
        if export_restored is not True:
            rollback_recovery()
            return False

        # Retained import terminals are canonical accessibility state. Re-deliver
        # only after all owners are live; any observer failure makes recovery
        # incomplete and re-fences the native worker boundary.
        self._pump.request_pending_wakeup()
        if self._mailbox.pending_count:
            rollback_recovery()
            return False
        with self._lock:
            if self._closed:
                return False
        if self._file_delegate.shutdown_requested:
            return False
        return True

    def shutdown(self, timeout: float | None = None) -> bool:
        """Cancel/join all native file workers before closing the UI pump."""

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("Version 2 Windows file workflow shutdown requires UI thread")
        with self._lock:
            if self._closed:
                return True
            if self._library_modal_operation:
                return False

        # Retire the retryable import/PGN owner first. If it times out, Library
        # Export remains live and the still-visible product can recover intact.
        stopped = self._file_delegate.shutdown(timeout)
        if not stopped:
            return False
        export_stopped = self._library_export_delegate.shutdown(timeout)
        if not export_stopped:
            return False

        # Preserve shipping's recoverable outer boundary: mark closed before the
        # pump close so a pump exception is repaired through the same refused-close
        # recovery transaction rather than leaving an untracked half-close.
        with self._lock:
            self._closed = True
        self._pump.close()
        return True


__all__ = ["Version2WindowsFileWorkflowRuntime"]
