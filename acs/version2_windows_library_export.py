from __future__ import annotations

"""Trusted Windows host boundary for ``library.export``.

The browser never supplies a filesystem path and does not define the Library
subset. A trusted application selection provider supplies stable Library game
IDs; the Windows host owns the native Save dialog; the canonical Library PGN
export service owns database lookup, strict PGN validation and atomic publish.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path
from typing import Any

from .version2_windows_file_workflows import Version2WindowsFileDialogs
from .version2_windows_native_dialog_ownership import _OwnedDialogMixin


_LOG = logging.getLogger(__name__)
_ACTION = "library.export"


class LibraryPgnExportEventKind(str, Enum):
    EXPORTED = "exported"
    DIALOG_CANCELLED = "dialog_cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LibraryPgnExportEvent:
    kind: LibraryPgnExportEventKind
    action_id: str = _ACTION
    focus_target: str = ""
    error_code: str = ""
    game_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LibraryPgnExportEventKind):
            raise TypeError("library export event kind is invalid")
        if self.action_id != _ACTION:
            raise ValueError("library export event action is invalid")
        if type(self.focus_target) is not str or type(self.error_code) is not str:
            raise TypeError("library export event text fields are invalid")
        if type(self.game_count) is not int or self.game_count < 0:
            raise ValueError("library export event game count is invalid")


class Version2WindowsLibraryExportDialogs(Version2WindowsFileDialogs):
    """Native Save dialog owned by the trusted Windows host."""

    def export_library(self, suggested_filename: str = "library-selection.pgn") -> Path | None:
        if type(suggested_filename) is not str:
            raise TypeError("suggested export filename must be text")
        safe_name = Path(suggested_filename).name or "library-selection.pgn"
        DialogResult, _, SaveFileDialog = self._load_forms()
        dialog = SaveFileDialog()
        try:
            dialog.Title = "Export Library games to PGN"
            dialog.Filter = "PGN files (*.pgn)|*.pgn|All files (*.*)|*.*"
            dialog.DefaultExt = "pgn"
            dialog.AddExtension = True
            dialog.OverwritePrompt = True
            dialog.CheckPathExists = True
            dialog.FileName = safe_name
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()


class Version2OwnedWindowsLibraryExportDialogs(
    _OwnedDialogMixin,
    Version2WindowsLibraryExportDialogs,
):
    """Owner-bound Library export dialog reusing the #300 modality primitive."""

    def __init__(
        self,
        owner_provider: Callable[[], object],
        *,
        forms_loader: Callable[
            [], tuple[object, Callable[[], object], Callable[[], object]]
        ]
        | None = None,
    ) -> None:
        self._configure_owned_dialogs(
            owner_provider,
            forms_loader or Version2WindowsLibraryExportDialogs._load_forms,
        )


class Version2WindowsLibraryExportDelegate:
    """Chainable trusted-host port for the already-registered Library action."""

    OWNED_ACTIONS = frozenset({_ACTION})

    def __init__(
        self,
        *,
        dialogs: object,
        selection_provider: Callable[[], tuple[int, ...]],
        export_subset: Callable[[tuple[int, ...], Path], Any],
        event_sink: Callable[[LibraryPgnExportEvent], Any],
        next_delegate: Callable[[str, Mapping[str, object]], Any],
        current_focus_provider: Callable[[], str] | None = None,
    ) -> None:
        if not callable(getattr(dialogs, "export_library", None)):
            raise TypeError("Windows Library export dialogs must expose export_library")
        for name, callback in (
            ("selection_provider", selection_provider),
            ("export_subset", export_subset),
            ("event_sink", event_sink),
            ("next_delegate", next_delegate),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("current_focus_provider must be callable")
        self._dialogs = dialogs
        self._selection_provider = selection_provider
        self._export_subset = export_subset
        self._event_sink = event_sink
        self._next_delegate = next_delegate
        self._focus_provider = current_focus_provider or (lambda: "")

    def _focus(self) -> str:
        try:
            value = self._focus_provider()
        except Exception:
            return ""
        return value if type(value) is str else ""

    def _emit(self, event: LibraryPgnExportEvent) -> LibraryPgnExportEvent:
        try:
            self._event_sink(event)
        except Exception:
            _LOG.warning("Version 2 Library export event sink failed", exc_info=True)
        return event

    def _failed(self, code: str, focus: str) -> LibraryPgnExportEvent:
        return self._emit(
            LibraryPgnExportEvent(
                LibraryPgnExportEventKind.FAILED,
                focus_target=focus,
                error_code=code,
            )
        )

    @staticmethod
    def _selection(value: object) -> tuple[int, ...]:
        if type(value) is not tuple or not value:
            raise ValueError("trusted Library export selection is empty or invalid")
        if any(type(game_id) is not int or game_id <= 0 for game_id in value):
            raise ValueError("trusted Library export selection contains an invalid game")
        if len(set(value)) != len(value):
            raise ValueError("trusted Library export selection contains duplicates")
        return value

    def __call__(self, action_id: str, payload: Mapping[str, object]) -> Any:
        if action_id != _ACTION:
            return self._next_delegate(action_id, payload)

        previous_focus = self._focus()
        if not isinstance(payload, Mapping) or payload:
            # No browser authority is accepted: not even a destination or game ID.
            return self._failed("invalid_export_request", previous_focus)

        try:
            selected = self._selection(self._selection_provider())
        except Exception:
            return self._failed("invalid_export_selection", previous_focus)

        try:
            destination = self._dialogs.export_library("library-selection.pgn")
        except Exception:
            return self._failed("file_dialog_failed", previous_focus)
        if destination is None:
            return self._emit(
                LibraryPgnExportEvent(
                    LibraryPgnExportEventKind.DIALOG_CANCELLED,
                    focus_target=previous_focus,
                )
            )
        if not isinstance(destination, Path):
            return self._failed("file_dialog_failed", previous_focus)

        try:
            self._export_subset(selected, destination)
        except Exception:
            return self._failed("library_export_failed", previous_focus)

        return self._emit(
            LibraryPgnExportEvent(
                LibraryPgnExportEventKind.EXPORTED,
                focus_target=previous_focus,
                game_count=len(selected),
            )
        )


__all__ = [
    "LibraryPgnExportEvent",
    "LibraryPgnExportEventKind",
    "Version2OwnedWindowsLibraryExportDialogs",
    "Version2WindowsLibraryExportDelegate",
    "Version2WindowsLibraryExportDialogs",
]
