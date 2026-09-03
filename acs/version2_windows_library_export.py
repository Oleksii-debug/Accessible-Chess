from __future__ import annotations

"""Trusted Windows host seam for canonical D07 Library PGN export.

The browser supplies only a selection/filter identity. This module validates that
identity before opening a native Save dialog, then gives the host-selected path
to :class:`LibraryExportService`. It deliberately reuses #300's owner-bound PGN
Save-dialog implementation and D06's writer through the D07 service.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path
from typing import Any

from .library_export_service import (
    LibraryExportRequest,
    LibraryExportResult,
    LibraryExportService,
)
from .version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime
from .version2_windows_native_dialog_ownership import Version2OwnedWindowsPgnExportDialogs


_LOG = logging.getLogger(__name__)
_LIBRARY_EXPORT_ACTION = "library.export"


class LibraryExportHostEventKind(str, Enum):
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
        if not isinstance(self.kind, LibraryExportHostEventKind):
            raise TypeError("Library export event kind is invalid")
        if self.action_id != _LIBRARY_EXPORT_ACTION:
            raise ValueError("Library export event action is invalid")
        if type(self.focus_target) is not str or type(self.error_code) is not str:
            raise TypeError("Library export event text fields must be text")
        if type(self.game_count) is not int or self.game_count < 0:
            raise ValueError("Library export event game count is invalid")
        if self.kind is LibraryExportHostEventKind.EXPORTED and self.game_count < 1:
            raise ValueError("successful Library export requires a positive game count")
        if self.kind is not LibraryExportHostEventKind.EXPORTED and self.game_count != 0:
            raise ValueError("failed/cancelled Library export cannot claim games")


class Version2WindowsLibraryExportDelegate:
    """Chainable trusted-host delegate owning only ``library.export``."""

    OWNED_ACTIONS = frozenset({_LIBRARY_EXPORT_ACTION})

    def __init__(
        self,
        *,
        dialogs: object,
        service: LibraryExportService,
        event_sink: Callable[[LibraryExportHostEvent], Any],
        next_delegate: Callable[[str, Mapping[str, object]], Any],
        current_focus_provider: Callable[[], str] | None = None,
    ) -> None:
        if not callable(getattr(dialogs, "export_selection", None)):
            raise TypeError("Windows Library export dialogs must expose export_selection")
        if not isinstance(service, LibraryExportService):
            raise TypeError("service must be LibraryExportService")
        for name, callback in (("event_sink", event_sink), ("next_delegate", next_delegate)):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("current_focus_provider must be callable")
        self._dialogs = dialogs
        self._service = service
        self._event_sink = event_sink
        self._next_delegate = next_delegate
        self._focus_provider = current_focus_provider or (lambda: "")

    def _focus(self) -> str:
        try:
            value = self._focus_provider()
        except Exception:
            return ""
        return value if type(value) is str else ""

    def _emit(self, event: LibraryExportHostEvent) -> LibraryExportHostEvent:
        try:
            self._event_sink(event)
        except Exception:
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
        if action_id != _LIBRARY_EXPORT_ACTION:
            return self._next_delegate(action_id, payload)

        previous_focus = self._focus()
        try:
            request = LibraryExportRequest.from_payload(payload)
        except Exception:
            # Path/destination authority supplied by WebView fails before any dialog.
            return self._failed("invalid_export_request", previous_focus)

        try:
            destination = self._dialogs.export_selection("library-export.pgn")
        except Exception:
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

        try:
            result = self._service.export_to(destination, request)
        except Exception:
            # Never surface destination/backend/local-path text through this event.
            return self._failed("library_export_failed", previous_focus)
        if not isinstance(result, LibraryExportResult):
            return self._failed("library_export_failed", previous_focus)

        return self._emit(
            LibraryExportHostEvent(
                LibraryExportHostEventKind.EXPORTED,
                focus_target=previous_focus,
                game_count=result.game_count,
            )
        )


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
    mailbox_max_events: int = 64,
    ui_delegate_factory: Callable[[Callable[[], None]], object] | None = None,
    file_forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]] | None = None,
    export_forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]] | None = None,
) -> Version2WindowsFileWorkflowRuntime:
    """Stack Library export behind the unchanged #300 file/PGN host runtime."""

    if not isinstance(library_service, LibraryExportService):
        raise TypeError("library_service must be LibraryExportService")
    library_dialogs = Version2OwnedWindowsPgnExportDialogs(
        lambda: owner_control,
        forms_loader=export_forms_loader,
    )
    library_delegate = Version2WindowsLibraryExportDelegate(
        dialogs=library_dialogs,
        service=library_service,
        event_sink=library_export_event_sink,
        next_delegate=next_delegate,
        current_focus_provider=current_focus_provider,
    )
    # Existing #300 runtime owns pgn.*, library.import/cancel and dialog/UI-thread
    # mechanics. Its terminal next_delegate is the export-specific D07 seam above.
    return Version2WindowsFileWorkflowRuntime(
        owner_control=owner_control,
        get_pgn_session=get_pgn_session,  # type: ignore[arg-type]
        set_pgn_session=set_pgn_session,  # type: ignore[arg-type]
        import_services_factory=import_services_factory,  # type: ignore[arg-type]
        export_selected=export_selected,
        import_ui_ready=import_ui_ready,  # type: ignore[arg-type]
        pgn_export_event_sink=pgn_export_event_sink,
        next_delegate=library_delegate,
        current_focus_provider=current_focus_provider,
        mailbox_max_events=mailbox_max_events,
        ui_delegate_factory=ui_delegate_factory,
        file_forms_loader=file_forms_loader,
        export_forms_loader=export_forms_loader,
    )


__all__ = [
    "LibraryExportHostEvent",
    "LibraryExportHostEventKind",
    "Version2WindowsLibraryExportDelegate",
    "build_version2_windows_library_file_runtime",
]
