from __future__ import annotations

"""Trusted Windows destination workflow for PGN selection export.

The canonical PGN/GameTree owner decides what a selected game/variation means and
provides the exact export implementation through an injected callable.  This
module owns only the Windows host boundary: it receives the already-enriched
trusted target produced by ``PgnWorkspaceWebViewProjection``, opens a native
Save dialog, and supplies that host-selected destination to the canonical
exporter.  Browser content can never submit a filesystem path here.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path
from typing import Any

from .version2_windows_file_workflows import Version2WindowsFileDialogs


_LOG = logging.getLogger(__name__)
_EXPORT_ACTION = "pgn.export_selection"
_REQUIRED_TARGET_KEYS = frozenset(
    {
        "game_index",
        "line_path",
        "move_index",
        "expected_record_digest",
        "content_revision",
    }
)


class PgnSelectionExportEventKind(str, Enum):
    EXPORTED = "exported"
    DIALOG_CANCELLED = "dialog_cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PgnSelectionExportRequest:
    """Validated canonical selection identity; never contains a local path."""

    game_index: int
    line_path: tuple[tuple[int, int], ...]
    move_index: int | None
    expected_record_digest: str
    content_revision: int

    def __post_init__(self) -> None:
        if type(self.game_index) is not int or self.game_index < 0:
            raise ValueError("PGN export game index is invalid")
        if type(self.content_revision) is not int or self.content_revision < 0:
            raise ValueError("PGN export content revision is invalid")
        if self.move_index is not None and (
            type(self.move_index) is not int or self.move_index < 0
        ):
            raise ValueError("PGN export move index is invalid")
        if type(self.line_path) is not tuple:
            raise TypeError("PGN export line path must be a tuple")
        for step in self.line_path:
            if (
                type(step) is not tuple
                or len(step) != 2
                or type(step[0]) is not int
                or type(step[1]) is not int
                or step[0] < 0
                or step[1] < 0
            ):
                raise ValueError("PGN export line path is invalid")
        if self.move_index is None and not self.line_path:
            raise ValueError("PGN export requires a selected game-tree item")
        digest = self.expected_record_digest
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("PGN export record digest is invalid")

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "PgnSelectionExportRequest":
        if not isinstance(payload, Mapping):
            raise TypeError("PGN export payload must be a mapping")
        keys = frozenset(payload)
        if keys != _REQUIRED_TARGET_KEYS:
            raise ValueError("PGN export payload contains missing or untrusted fields")
        line_path = payload["line_path"]
        if type(line_path) is not tuple:
            raise TypeError("PGN export line path must be a tuple")
        return cls(
            game_index=payload["game_index"],  # type: ignore[arg-type]
            line_path=line_path,  # type: ignore[arg-type]
            move_index=payload["move_index"],  # type: ignore[arg-type]
            expected_record_digest=payload["expected_record_digest"],  # type: ignore[arg-type]
            content_revision=payload["content_revision"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class PgnSelectionExportEvent:
    """Path-free event for an accessible UI/status projection."""

    kind: PgnSelectionExportEventKind
    action_id: str = _EXPORT_ACTION
    focus_target: str = ""
    error_code: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PgnSelectionExportEventKind):
            raise TypeError("PGN export event kind is invalid")
        if self.action_id != _EXPORT_ACTION:
            raise ValueError("PGN export event action is invalid")
        for name in ("focus_target", "error_code"):
            if type(getattr(self, name)) is not str:
                raise TypeError(f"{name} must be text")


class Version2WindowsPgnExportDialogs(Version2WindowsFileDialogs):
    """Native Save dialog with an export-specific accessible title."""

    def export_selection(self, suggested_filename: str = "selection.pgn") -> Path | None:
        if type(suggested_filename) is not str:
            raise TypeError("suggested export filename must be text")
        safe_name = Path(suggested_filename).name or "selection.pgn"
        DialogResult, _, SaveFileDialog = self._load_forms()
        dialog = SaveFileDialog()
        try:
            dialog.Title = "Export PGN selection"
            dialog.Filter = "PGN files (*.pgn)|*.pgn|All files (*.*)|*.*"
            dialog.DefaultExt = "pgn"
            dialog.AddExtension = True
            dialog.OverwritePrompt = True
            dialog.CheckPathExists = True
            dialog.FileName = safe_name
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()


class Version2WindowsPgnExportDelegate:
    """Chainable trusted-host port for ``pgn.export_selection`` only."""

    OWNED_ACTIONS = frozenset({_EXPORT_ACTION})

    def __init__(
        self,
        *,
        dialogs: object,
        export_selected: Callable[[PgnSelectionExportRequest, Path], Any],
        event_sink: Callable[[PgnSelectionExportEvent], Any],
        next_delegate: Callable[[str, Mapping[str, object]], Any],
        current_focus_provider: Callable[[], str] | None = None,
    ) -> None:
        if not callable(getattr(dialogs, "export_selection", None)):
            raise TypeError("Windows PGN export dialogs must expose export_selection")
        for name, callback in (
            ("export_selected", export_selected),
            ("event_sink", event_sink),
            ("next_delegate", next_delegate),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("current_focus_provider must be callable")
        self._dialogs = dialogs
        self._export_selected = export_selected
        self._event_sink = event_sink
        self._next_delegate = next_delegate
        self._focus_provider = current_focus_provider or (lambda: "")

    def _focus(self) -> str:
        try:
            value = self._focus_provider()
        except Exception:
            return ""
        return value if type(value) is str else ""

    def _emit(self, event: PgnSelectionExportEvent) -> PgnSelectionExportEvent:
        try:
            self._event_sink(event)
        except Exception:
            _LOG.warning("Version 2 PGN export event sink failed", exc_info=True)
        return event

    def _failed(self, error_code: str, focus_target: str) -> PgnSelectionExportEvent:
        return self._emit(
            PgnSelectionExportEvent(
                PgnSelectionExportEventKind.FAILED,
                focus_target=focus_target,
                error_code=error_code,
            )
        )

    def __call__(self, action_id: str, payload: Mapping[str, object]) -> Any:
        if action_id != _EXPORT_ACTION:
            return self._next_delegate(action_id, payload)

        previous_focus = self._focus()
        try:
            request = PgnSelectionExportRequest.from_payload(payload)
        except Exception:
            return self._failed("invalid_export_target", previous_focus)

        try:
            destination = self._dialogs.export_selection("selection.pgn")
        except Exception:
            return self._failed("file_dialog_failed", previous_focus)
        if destination is None:
            return self._emit(
                PgnSelectionExportEvent(
                    PgnSelectionExportEventKind.DIALOG_CANCELLED,
                    focus_target=previous_focus,
                )
            )
        if not isinstance(destination, Path):
            return self._failed("file_dialog_failed", previous_focus)

        try:
            # The injected canonical owner validates the request against current
            # GameTree state and owns exactly what bytes constitute this selection.
            # Its return value may contain internal details and is never projected.
            self._export_selected(request, destination)
        except Exception:
            return self._failed("pgn_export_failed", previous_focus)

        return self._emit(
            PgnSelectionExportEvent(
                PgnSelectionExportEventKind.EXPORTED,
                focus_target=previous_focus,
            )
        )
