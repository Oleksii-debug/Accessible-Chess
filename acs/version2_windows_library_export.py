from __future__ import annotations

"""Trusted Windows host seam for canonical D07 Library PGN export.

The browser supplies only a selection/filter identity. Native Save selection remains
on the owning UI thread. Production may then hand destination binding plus canonical
Library export to one cancellable worker; the worker owns no Library/PGN semantics.

The legacy synchronous service injection remains supported for focused tests and
non-Windows embedders. The real Windows composition uses worker-local ACSDB state
and marshals only path-free terminal events back to the owner thread.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path
import threading
from typing import Any

from .library_export_service import (
    LibraryExportCancelledError,
    LibraryExportRequest,
    LibraryExportResult,
    LibraryExportService,
)
from .version2_windows_native_dialog_ownership import Version2OwnedWindowsPgnExportDialogs


_LOG = logging.getLogger(__name__)
_LIBRARY_EXPORT_ACTION = "library.export"
_AUTO_RETRY_DELAY_SECONDS = 0.05


class LibraryExportHostEventKind(str, Enum):
    STARTED = "export_started"
    CANCELLING = "export_cancelling"
    EXPORTED = "exported"
    DIALOG_CANCELLED = "dialog_cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LibraryExportHostEvent:
    """Path-free status event safe for accessible presentation."""

    kind: LibraryExportHostEventKind
    action_id: str = _LIBRARY_EXPORT_ACTION
    focus_target: str = ""
    error_code: str = ""
    game_count: int = 0

    def __post_init__(self) -> None:
        if type(self.kind) is not LibraryExportHostEventKind:
            raise TypeError("Library export event kind is invalid")
        if type(self.action_id) is not str or self.action_id != _LIBRARY_EXPORT_ACTION:
            raise ValueError("Library export event action is invalid")
        if type(self.focus_target) is not str or type(self.error_code) is not str:
            raise TypeError("Library export event text fields must be text")
        if type(self.game_count) is not int or self.game_count < 0:
            raise ValueError("Library export event game count is invalid")
        if self.kind is LibraryExportHostEventKind.EXPORTED and self.game_count < 1:
            raise ValueError("successful Library export requires a positive game count")
        if self.kind is not LibraryExportHostEventKind.EXPORTED and self.game_count != 0:
            raise ValueError("non-successful Library export cannot claim games")


@dataclass(frozen=True, slots=True)
class LibraryExportWorkerServices:
    """Worker-local canonical export service and exact resource cleanup."""

    library: LibraryExportService
    close: Callable[[], Any]

    def __post_init__(self) -> None:
        if not isinstance(self.library, LibraryExportService):
            raise TypeError("Library export worker requires LibraryExportService")
        if not callable(self.close):
            raise TypeError("Library export worker cleanup must be callable")


class Version2WindowsLibraryExportDelegate:
    """Chainable trusted-host owner of ``library.export``.

    With ``service`` this preserves the historical synchronous embedding seam.
    With ``worker_services_factory`` plus ``post_to_ui`` it keeps the native Save
    dialog on the owner thread, then runs all destination hashing/streaming off
    that thread. Exactly one export remains in flight through terminal UI commit.
    """

    OWNED_ACTIONS = frozenset({_LIBRARY_EXPORT_ACTION})

    def __init__(
        self,
        *,
        dialogs: object,
        event_sink: Callable[[LibraryExportHostEvent], Any],
        next_delegate: Callable[[str, Mapping[str, object]], Any],
        current_focus_provider: Callable[[], str] | None = None,
        service: LibraryExportService | None = None,
        worker_services_factory: Callable[[], LibraryExportWorkerServices] | None = None,
        post_to_ui: Callable[[Callable[[], None]], Any] | None = None,
    ) -> None:
        if not callable(getattr(dialogs, "export_selection", None)):
            raise TypeError("Windows Library export dialogs must expose export_selection")
        for name, callback in (("event_sink", event_sink), ("next_delegate", next_delegate)):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("current_focus_provider must be callable")

        synchronous = service is not None
        asynchronous = worker_services_factory is not None or post_to_ui is not None
        if synchronous == asynchronous:
            raise ValueError(
                "Library export requires exactly one service mode: synchronous service "
                "or worker_services_factory + post_to_ui"
            )
        if synchronous and not isinstance(service, LibraryExportService):
            raise TypeError("service must be LibraryExportService")
        if asynchronous:
            if not callable(worker_services_factory):
                raise TypeError("worker_services_factory must be callable")
            if not callable(post_to_ui):
                raise TypeError("post_to_ui must be callable")

        self._dialogs = dialogs
        self._service = service
        self._worker_services_factory = worker_services_factory
        self._post_to_ui = post_to_ui
        self._event_sink = event_sink
        self._next_delegate = next_delegate
        self._focus_provider = current_focus_provider or (lambda: "")
        self._ui_thread_id = threading.get_ident()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancel: threading.Event | None = None
        self._terminal_pending: tuple[int, LibraryExportHostEvent] | None = None
        self._retry_timer: threading.Timer | None = None
        self._generation = 0
        self._closed = False
        self._shutdown_recovery_requested = False
        self._shutdown_recovery_terminal: LibraryExportHostEvent | None = None

    @property
    def asynchronous(self) -> bool:
        return self._worker_services_factory is not None

    def _assert_ui_thread(self) -> None:
        if self.asynchronous and threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("Library export control requires the UI thread")

    @property
    def export_running(self) -> bool:
        with self._lock:
            return (
                self.asynchronous
                and not self._closed
                and (self._cancel is not None or self._terminal_pending is not None)
            )

    def _focus(self) -> str:
        try:
            value = self._focus_provider()
        except BaseException:
            return ""
        return value if type(value) is str else ""

    def _emit(self, event: LibraryExportHostEvent) -> LibraryExportHostEvent:
        try:
            self._event_sink(event)
        except BaseException:
            _LOG.warning("Version 2 Library export event sink failed", exc_info=True)
        return event

    def _failed(self, error_code: str, focus_target: str) -> LibraryExportHostEvent:
        return self._emit(
            LibraryExportHostEvent(
                LibraryExportHostEventKind.FAILED,
                focus_target=focus_target,
                error_code=error_code,
            )
        )

    def __call__(self, action_id: str, payload: Mapping[str, object]) -> Any:
        # Action routing is a passive-data boundary. Reject active str subclasses
        # before equality can dispatch arbitrary Python code through __eq__/__ne__.
        if type(action_id) is not str:
            raise TypeError("Library export action id must be text")
        if action_id != _LIBRARY_EXPORT_ACTION:
            return self._next_delegate(action_id, payload)

        self._assert_ui_thread()
        previous_focus = self._focus()
        try:
            request = LibraryExportRequest.from_payload(payload)
        except BaseException:
            return self._failed("invalid_export_request", previous_focus)

        if self.asynchronous:
            with self._lock:
                if self._closed:
                    return self._failed("library_export_unavailable", previous_focus)
                if self._cancel is not None or self._terminal_pending is not None:
                    return self._failed("library_export_busy", previous_focus)

        try:
            destination = self._dialogs.export_selection("library-export.pgn")
        except BaseException:
            return self._failed("file_dialog_failed", previous_focus)
        if destination is None:
            return self._emit(
                LibraryExportHostEvent(
                    LibraryExportHostEventKind.DIALOG_CANCELLED,
                    focus_target=previous_focus,
                )
            )
        if not isinstance(destination, Path):
            return self._failed("file_dialog_failed", previous_focus)

        if not self.asynchronous:
            return self._export_synchronously(destination, request, previous_focus)
        return self._start_export(destination, request, previous_focus)

    def _export_synchronously(
        self,
        destination: Path,
        request: LibraryExportRequest,
        previous_focus: str,
    ) -> LibraryExportHostEvent:
        assert self._service is not None
        try:
            expected_sha256 = self._service.expected_destination_sha256(destination)
            result = self._service.export_to(
                destination,
                request,
                expected_sha256=expected_sha256,
            )
            if type(result) is not LibraryExportResult:
                raise TypeError("Library export service returned an invalid result")
            terminal = LibraryExportHostEvent(
                LibraryExportHostEventKind.EXPORTED,
                focus_target=previous_focus,
                game_count=result.game_count,
            )
        except BaseException:
            return self._failed("library_export_failed", previous_focus)
        return self._emit(terminal)

    def _start_export(
        self,
        destination: Path,
        request: LibraryExportRequest,
        previous_focus: str,
    ) -> LibraryExportHostEvent:
        self._assert_ui_thread()
        with self._lock:
            if self._closed:
                return self._failed("library_export_unavailable", previous_focus)
            if self._cancel is not None or self._terminal_pending is not None:
                return self._failed("library_export_busy", previous_focus)
            self._generation += 1
            generation = self._generation
            cancel = threading.Event()
            thread = threading.Thread(
                target=self._run_export,
                args=(generation, destination, request, previous_focus, cancel),
                name="AccessibleChessLibraryExport",
                daemon=False,
            )
            self._cancel = cancel
            self._thread = thread

        started = self._emit(
            LibraryExportHostEvent(
                LibraryExportHostEventKind.STARTED,
                focus_target=previous_focus,
            )
        )
        shutdown_before_start = False
        cancelled_before_start = False
        try:
            # STARTED observers run on the owner thread and may re-enter shutdown
            # or cancellation. Linearize those decisions with Thread.start() so
            # work accepted as cancelled never opens worker-local database state.
            with self._lock:
                current = (
                    generation == self._generation
                    and self._thread is thread
                    and self._cancel is cancel
                )
                if self._closed or not current:
                    shutdown_before_start = self._closed
                    if not shutdown_before_start:
                        raise RuntimeError(
                            "Library export worker ownership changed before start"
                        )
                elif cancel.is_set():
                    self._cancel = None
                    self._thread = None
                    cancelled_before_start = True
                else:
                    thread.start()
        except BaseException:
            with self._lock:
                if generation == self._generation and self._thread is thread:
                    self._cancel = None
                    self._thread = None
            return self._failed("library_export_worker_failed", previous_focus)
        if shutdown_before_start:
            return self._failed("library_export_unavailable", previous_focus)
        if cancelled_before_start:
            return self._emit(
                LibraryExportHostEvent(
                    LibraryExportHostEventKind.DIALOG_CANCELLED,
                    focus_target=previous_focus,
                )
            )
        return started

    def _run_export(
        self,
        generation: int,
        destination: Path,
        request: LibraryExportRequest,
        previous_focus: str,
        cancel: threading.Event,
    ) -> None:
        services: LibraryExportWorkerServices | None = None
        terminal: LibraryExportHostEvent
        try:
            assert self._worker_services_factory is not None
            candidate_services = self._worker_services_factory()
            if type(candidate_services) is not LibraryExportWorkerServices:
                raise TypeError("Library export worker factory returned invalid services")
            services = candidate_services
            expected_sha256 = services.library.expected_destination_sha256(
                destination,
                cancel_check=cancel.is_set,
            )
            result = services.library.export_to(
                destination,
                request,
                expected_sha256=expected_sha256,
                cancel_check=cancel.is_set,
            )
            if type(result) is not LibraryExportResult:
                raise TypeError("Library export worker returned an invalid result")
            terminal = LibraryExportHostEvent(
                LibraryExportHostEventKind.EXPORTED,
                focus_target=previous_focus,
                game_count=result.game_count,
            )
        except LibraryExportCancelledError:
            terminal = LibraryExportHostEvent(
                LibraryExportHostEventKind.DIALOG_CANCELLED,
                focus_target=previous_focus,
            )
        except BaseException:
            terminal = LibraryExportHostEvent(
                LibraryExportHostEventKind.FAILED,
                focus_target=previous_focus,
                error_code="library_export_failed",
            )
        finally:
            if services is not None:
                try:
                    services.close()
                except BaseException:
                    # Cleanup is secondary to the already selected bounded
                    # terminal. A provider callback must not strand single-flight
                    # ownership by aborting this worker before UI publication.
                    _LOG.warning("Library export worker cleanup failed", exc_info=True)

        with self._lock:
            if generation != self._generation or self._closed:
                return
            self._terminal_pending = (generation, terminal)

        self._post_terminal(generation, terminal)

    def _post_terminal(
        self,
        generation: int,
        terminal: LibraryExportHostEvent,
        *,
        schedule_retry: bool = True,
    ) -> None:
        with self._lock:
            if (
                generation != self._generation
                or self._closed
                or self._terminal_pending != (generation, terminal)
            ):
                return

        def finish() -> None:
            self._finish_export(generation, terminal)

        try:
            assert self._post_to_ui is not None
            self._post_to_ui(finish)
        except BaseException:
            if schedule_retry:
                self._schedule_terminal_retry(generation, terminal)
            else:
                # Keep the exact terminal event pending. The existing
                # Ctrl+Shift+X Library cancel authority can consume it on the
                # UI thread without changing the already chosen durable result.
                _LOG.warning(
                    "Version 2 Library export terminal UI retry failed",
                    exc_info=True,
                )

    def _schedule_terminal_retry(
        self,
        generation: int,
        terminal: LibraryExportHostEvent,
    ) -> None:
        with self._lock:
            if (
                generation != self._generation
                or self._closed
                or self._terminal_pending != (generation, terminal)
                or self._retry_timer is not None
            ):
                return
            timer = threading.Timer(
                _AUTO_RETRY_DELAY_SECONDS,
                self._retry_terminal,
                args=(generation, terminal),
            )
            timer.daemon = True
            self._retry_timer = timer
        try:
            timer.start()
        except BaseException:
            with self._lock:
                if self._retry_timer is timer:
                    self._retry_timer = None
            _LOG.warning(
                "Version 2 Library export terminal UI retry could not start",
                exc_info=True,
            )

    def _retry_terminal(
        self,
        generation: int,
        terminal: LibraryExportHostEvent,
    ) -> None:
        with self._lock:
            self._retry_timer = None
            if (
                generation != self._generation
                or self._closed
                or self._terminal_pending != (generation, terminal)
            ):
                return
        self._post_terminal(generation, terminal, schedule_retry=False)

    def _finish_export(
        self,
        generation: int,
        terminal: LibraryExportHostEvent,
    ) -> None:
        self._assert_ui_thread()
        with self._lock:
            if generation != self._generation or self._closed:
                return
            pending = self._terminal_pending
            if pending != (generation, terminal):
                return
            retry_timer = self._retry_timer
            self._retry_timer = None
            self._terminal_pending = None
            self._cancel = None
            self._thread = None
            self._shutdown_recovery_requested = False
        if retry_timer is not None:
            retry_timer.cancel()
        self._emit(terminal)

    def recover_pending_terminal(self) -> bool:
        """Publish an already-chosen terminal on the owner thread, if any."""

        self._assert_ui_thread()
        with self._lock:
            if self._closed or self._terminal_pending is None:
                return False
            generation, terminal = self._terminal_pending
        self._finish_export(generation, terminal)
        return True

    def cancel_export(self) -> LibraryExportHostEvent:
        """Request cooperative cancellation without racing a chosen terminal result."""

        self._assert_ui_thread()
        focus = self._focus()
        with self._lock:
            if self._closed:
                return self._failed("library_export_unavailable", focus)
            pending = self._terminal_pending
            if pending is not None:
                generation, terminal = pending
            else:
                generation = 0
                terminal = None
                cancel = self._cancel
                if cancel is None:
                    return self._failed("no_library_export_running", focus)
                cancel.set()
        if terminal is not None:
            # The worker already chose a durable terminal result. Consume that
            # exact result on the owner thread; never overwrite it with a late
            # cancellation and never emit it twice if a queued callback follows.
            self._finish_export(generation, terminal)
            return terminal
        return self._emit(
            LibraryExportHostEvent(
                LibraryExportHostEventKind.CANCELLING,
                focus_target=focus,
            )
        )

    def wait_for_export(self, timeout: float | None = None) -> bool:
        if timeout is not None and (
            type(timeout) not in {int, float} or timeout < 0
        ):
            raise ValueError("Library export wait timeout must be non-negative or None")
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def resume_after_refused_shutdown(self) -> bool:
        """Reopen a retired owner and replay one retained truthful terminal.

        Successful shutdown increments the generation before retiring queued UI
        work, so callbacks from the pre-close generation stay stale. When close
        is later refused, a terminal explicitly retained for recovery is emitted
        once on the owner thread after all worker/retry authority is quiescent.
        """

        self._assert_ui_thread()
        with self._lock:
            if not self._closed:
                return True
            if (
                self._thread is not None
                or self._cancel is not None
                or self._terminal_pending is not None
                or self._retry_timer is not None
            ):
                return False
            recovery_terminal = self._shutdown_recovery_terminal
            self._shutdown_recovery_terminal = None
            self._shutdown_recovery_requested = False
            self._closed = False
        if recovery_terminal is not None:
            self._emit(recovery_terminal)
        return True

    def shutdown(
        self,
        timeout: float | None = None,
        *,
        retain_terminal_for_recovery: bool = False,
    ) -> bool:
        """Cancel/join worker; fence stale callbacks and optionally retain truth."""

        self._assert_ui_thread()
        if timeout is not None and (
            type(timeout) not in {int, float} or timeout < 0
        ):
            raise ValueError("Library export shutdown timeout must be non-negative or None")
        if type(retain_terminal_for_recovery) is not bool:
            raise TypeError("retain_terminal_for_recovery must be bool")
        with self._lock:
            if self._closed:
                return True
            cancel = self._cancel
            thread = self._thread
            worker_was_live = thread is not None and thread.is_alive()
            if cancel is not None:
                cancel.set()
            if worker_was_live:
                # A close attempt that interrupts live work may be refused by a
                # later application owner. Preserve whichever truthful terminal
                # the worker ultimately chooses until that decision is known.
                self._shutdown_recovery_requested = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                return False
        with self._lock:
            retry_timer = self._retry_timer
            self._retry_timer = None
            pending = self._terminal_pending
            retain_terminal = (
                retain_terminal_for_recovery
                or self._shutdown_recovery_requested
            )
            self._shutdown_recovery_terminal = (
                pending[1] if retain_terminal and pending is not None else None
            )
            self._shutdown_recovery_requested = False
            self._closed = True
            self._generation += 1
            self._terminal_pending = None
            self._cancel = None
            self._thread = None
        if retry_timer is not None:
            retry_timer.cancel()
        return True


def build_version2_windows_library_file_runtime(
    *,
    owner_control: object,
    library_service: LibraryExportService,
    library_export_event_sink: Callable[[LibraryExportHostEvent], Any],
    get_pgn_session: Callable[[], object],
    set_pgn_session: Callable[[object], Any],
    import_services_factory: Callable[[], object],
    export_selected: Callable[[object, object], Any],
    import_ui_ready: Callable[[object], Any],
    pgn_export_event_sink: Callable[[object], Any],
    next_delegate: Callable[[str, Mapping[str, object]], Any],
    current_focus_provider: Callable[[], str] | None = None,
    dialog_language_provider: Callable[[], object] | None = None,
    mailbox_max_events: int = 64,
    ui_delegate_factory: Callable[[Callable[[], None]], object] | None = None,
    file_forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]] | None = None,
    export_forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]] | None = None,
):
    """Compatibility builder retaining the historical injected-service seam.

    Production ``Version2WindowsFileWorkflowRuntime`` now composes its own
    worker-local Library export. This builder deliberately injects the supplied
    synchronous delegate so existing focused embedders keep their exact contract.
    """

    if not isinstance(library_service, LibraryExportService):
        raise TypeError("library_service must be LibraryExportService")
    if dialog_language_provider is not None and not callable(dialog_language_provider):
        raise TypeError("dialog_language_provider must be callable")
    library_dialogs = Version2OwnedWindowsPgnExportDialogs(
        lambda: owner_control,
        forms_loader=export_forms_loader,
        language_provider=dialog_language_provider,
    )
    library_delegate = Version2WindowsLibraryExportDelegate(
        dialogs=library_dialogs,
        service=library_service,
        event_sink=library_export_event_sink,
        next_delegate=next_delegate,
        current_focus_provider=current_focus_provider,
    )

    from .version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime

    return Version2WindowsFileWorkflowRuntime(
        owner_control=owner_control,
        get_pgn_session=get_pgn_session,  # type: ignore[arg-type]
        set_pgn_session=set_pgn_session,  # type: ignore[arg-type]
        import_services_factory=import_services_factory,  # type: ignore[arg-type]
        export_selected=export_selected,
        import_ui_ready=import_ui_ready,  # type: ignore[arg-type]
        pgn_export_event_sink=pgn_export_event_sink,
        next_delegate=next_delegate,
        library_export_delegate=library_delegate,
        current_focus_provider=current_focus_provider,
        dialog_language_provider=dialog_language_provider,
        mailbox_max_events=mailbox_max_events,
        ui_delegate_factory=ui_delegate_factory,
        file_forms_loader=file_forms_loader,
        export_forms_loader=export_forms_loader,
    )


__all__ = [
    "LibraryExportHostEvent",
    "LibraryExportHostEventKind",
    "LibraryExportWorkerServices",
    "Version2WindowsLibraryExportDelegate",
    "build_version2_windows_library_file_runtime",
]
