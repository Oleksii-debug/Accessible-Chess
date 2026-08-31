from __future__ import annotations

"""Composition of the trusted Version 2 Windows file host with Library PGN export.

This is glue only.  It reuses the existing #300 Windows file runtime for
Open/Save/Save As/PGN-selection export and appends the canonical Library subset
export delegate as its next trusted-host action.  Filesystem paths remain inside
the Windows host and no PGN/database/chess semantics are duplicated here.
"""

from collections.abc import Callable, Mapping
import threading
from typing import Any

from .pgn_document import PgnDocumentSession
from .version2_windows_file_workflows import Version2ImportWorkerServices
from .version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime
from .version2_windows_import_event_mailbox import Version2ImportUiEventMailbox
from .version2_windows_library_export import (
    Version2OwnedWindowsLibraryExportDialogs,
    Version2WindowsLibraryExportDelegate,
)


class Version2WindowsSaveExportRuntime:
    """One chainable host runtime for PGN Save/Export and Library subset export."""

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
        library_selection_provider: Callable[[], tuple[int, ...]],
        library_export_subset: Callable[[tuple[int, ...], object], Any],
        library_export_event_sink: Callable[[object], Any],
        next_delegate: Callable[[str, Mapping[str, object]], Any],
        current_focus_provider: Callable[[], str] | None = None,
        mailbox_max_events: int = 64,
        ui_delegate_factory: Callable[[Callable[[], None]], object] | None = None,
        file_forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]]
        | None = None,
        export_forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]]
        | None = None,
        library_export_dialogs: object | None = None,
    ) -> None:
        for name, callback in (
            ("library_selection_provider", library_selection_provider),
            ("library_export_subset", library_export_subset),
            ("library_export_event_sink", library_export_event_sink),
            ("next_delegate", next_delegate),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        self._ui_thread_id = threading.get_ident()
        self._library_dialogs = (
            library_export_dialogs
            if library_export_dialogs is not None
            else Version2OwnedWindowsLibraryExportDialogs(
                lambda: owner_control,
                forms_loader=export_forms_loader,
            )
        )
        self._library_delegate = Version2WindowsLibraryExportDelegate(
            dialogs=self._library_dialogs,
            selection_provider=library_selection_provider,
            export_subset=library_export_subset,
            event_sink=library_export_event_sink,
            next_delegate=next_delegate,
            current_focus_provider=current_focus_provider,
        )
        self._file_runtime = Version2WindowsFileWorkflowRuntime(
            owner_control=owner_control,
            get_pgn_session=get_pgn_session,
            set_pgn_session=set_pgn_session,
            import_services_factory=import_services_factory,
            export_selected=export_selected,
            import_ui_ready=import_ui_ready,
            pgn_export_event_sink=pgn_export_event_sink,
            next_delegate=self._library_delegate,
            current_focus_provider=current_focus_provider,
            mailbox_max_events=mailbox_max_events,
            ui_delegate_factory=ui_delegate_factory,
            file_forms_loader=file_forms_loader,
            export_forms_loader=export_forms_loader,
        )

    @property
    def ui_thread_id(self) -> int:
        return self._ui_thread_id

    @property
    def closed(self) -> bool:
        return self._file_runtime.closed

    @property
    def import_running(self) -> bool:
        return self._file_runtime.import_running

    @property
    def import_mailbox(self) -> Version2ImportUiEventMailbox:
        return self._file_runtime.import_mailbox

    @property
    def file_runtime(self) -> Version2WindowsFileWorkflowRuntime:
        return self._file_runtime

    @property
    def library_export_dialogs(self) -> object:
        return self._library_dialogs

    def __call__(self, action_id: str, payload: Mapping[str, object]) -> Any:
        return self._file_runtime(action_id, payload)

    def wait_for_import(self, timeout: float | None = None) -> bool:
        return self._file_runtime.wait_for_import(timeout)

    def request_pending_import_wakeup(self) -> bool:
        return self._file_runtime.request_pending_import_wakeup()

    def shutdown(self, timeout: float | None = None) -> bool:
        return self._file_runtime.shutdown(timeout)


__all__ = ["Version2WindowsSaveExportRuntime"]
