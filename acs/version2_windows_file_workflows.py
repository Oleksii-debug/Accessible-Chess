from __future__ import annotations

"""Trusted Windows host workflows for Version 2 file actions.

This module is composition only.  It never parses PGN itself, decodes ChessBase,
implements Library storage, or owns chess state.  Native Windows dialogs choose
filesystem paths on the trusted host.  PGN operations delegate to
``PgnDocumentSession``; PGN Library import delegates to ``open_pgn`` plus the
canonical ``LibraryImportService``; CBH/CBV delegates to
``ChessBaseLibraryImportService``.

Long imports run on a dedicated worker so the Windows UI remains operable and a
Cancel command can be delivered.  The worker-service factory is deliberately
invoked *inside* that worker: SQLite connections are thread-affine by default,
so a UI-thread ``AcsDatabase`` must never be smuggled into the background task.
Only bounded, path-free events leave this host boundary.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import logging
import os
from pathlib import Path
import threading
from typing import Any

from .library_import_service import (
    LibraryImportCancelledError,
    LibraryImportProgress,
)
from .pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession
from .pgn_service import PgnFileError, open_pgn
from .report_paths import report_safe_name


_LOG = logging.getLogger(__name__)


class FileWorkflowEventKind(str, Enum):
    PGN_OPENED = "pgn_opened"
    PGN_SAVED = "pgn_saved"
    PGN_SAVED_AS = "pgn_saved_as"
    DIALOG_CANCELLED = "dialog_cancelled"
    IMPORT_STARTED = "import_started"
    IMPORT_PROGRESS = "import_progress"
    IMPORT_CANCELLING = "import_cancelling"
    IMPORT_COMPLETED = "import_completed"
    IMPORT_CANCELLED = "import_cancelled"
    IMPORT_EMPTY = "import_empty"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FileWorkflowEvent:
    """Path-free host event for a WebView/native accessibility projection."""

    kind: FileWorkflowEventKind
    action_id: str
    focus_target: str = ""
    processed_games: int = 0
    total_games: int = 0
    game_count: int = 0
    warning_count: int = 0
    error_code: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FileWorkflowEventKind):
            raise TypeError("file workflow event kind is invalid")
        for name in ("action_id", "focus_target", "error_code"):
            if type(getattr(self, name)) is not str:
                raise TypeError(f"{name} must be text")
        if not self.action_id:
            raise ValueError("file workflow action id must not be empty")
        for name in ("processed_games", "total_games", "game_count", "warning_count"):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.total_games and self.processed_games > self.total_games:
            raise ValueError("processed_games must not exceed total_games")


@dataclass(frozen=True, slots=True)
class Version2ImportWorkerServices:
    """Per-worker canonical import services and their connection cleanup."""

    library: object
    chessbase: object | None
    close: Callable[[], Any]

    def __post_init__(self) -> None:
        if not callable(getattr(self.library, "import_games", None)):
            raise TypeError("worker library service must expose import_games")
        if self.chessbase is not None and not callable(
            getattr(self.chessbase, "import_database", None)
        ):
            raise TypeError("worker ChessBase service must expose import_database")
        if not callable(self.close):
            raise TypeError("worker service cleanup must be callable")


class Version2WindowsFileDialogs:
    """Real WinForms Open/Save dialogs used only by the trusted Windows host."""

    @staticmethod
    def _load_forms():
        if os.name != "nt":
            raise RuntimeError("Version 2 native file dialogs require Windows")
        import clr  # type: ignore

        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import DialogResult, OpenFileDialog, SaveFileDialog  # type: ignore

        return DialogResult, OpenFileDialog, SaveFileDialog

    @staticmethod
    def _selected(dialog: object, dialog_result: object, ok_value: object) -> Path | None:
        if dialog_result != ok_value:
            return None
        value = getattr(dialog, "FileName", "")
        if type(value) is not str or not value:
            return None
        return Path(value)

    def open_pgn(self) -> Path | None:
        DialogResult, OpenFileDialog, _ = self._load_forms()
        dialog = OpenFileDialog()
        try:
            dialog.Title = "Open PGN"
            dialog.Filter = "PGN files (*.pgn)|*.pgn|All files (*.*)|*.*"
            dialog.CheckFileExists = True
            dialog.CheckPathExists = True
            dialog.Multiselect = False
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()

    def save_pgn_as(self, suggested_filename: str = "game.pgn") -> Path | None:
        if type(suggested_filename) is not str:
            raise TypeError("suggested PGN filename must be text")
        safe_name = Path(suggested_filename).name or "game.pgn"
        DialogResult, _, SaveFileDialog = self._load_forms()
        dialog = SaveFileDialog()
        try:
            dialog.Title = "Save PGN As"
            dialog.Filter = "PGN files (*.pgn)|*.pgn|All files (*.*)|*.*"
            dialog.DefaultExt = "pgn"
            dialog.AddExtension = True
            dialog.OverwritePrompt = True
            dialog.CheckPathExists = True
            dialog.FileName = safe_name
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()

    def select_library_import(self) -> Path | None:
        DialogResult, OpenFileDialog, _ = self._load_forms()
        dialog = OpenFileDialog()
        try:
            dialog.Title = "Import into Library"
            dialog.Filter = (
                "Supported chess sources (*.pgn;*.cbh;*.cbv)|*.pgn;*.cbh;*.cbv|"
                "PGN files (*.pgn)|*.pgn|ChessBase files (*.cbh;*.cbv)|*.cbh;*.cbv"
            )
            dialog.CheckFileExists = True
            dialog.CheckPathExists = True
            dialog.Multiselect = False
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()


class Version2WindowsFileActionDelegate:
    """Chainable host delegate for PGN Open/Save and Library import actions."""

    OWNED_ACTIONS = frozenset(
        {
            "pgn.open",
            "pgn.save",
            "pgn.save_as",
            "library.import",
            "library.cancel_import",
        }
    )
    _IMPORT_SUFFIXES = frozenset({".pgn", ".cbh", ".cbv"})

    def __init__(
        self,
        *,
        dialogs: object,
        get_pgn_session: Callable[[], PgnDocumentSession | None],
        set_pgn_session: Callable[[PgnDocumentSession], Any],
        import_services_factory: Callable[[], Version2ImportWorkerServices],
        event_sink: Callable[[FileWorkflowEvent], Any],
        next_delegate: Callable[[str, Mapping[str, object]], Any],
        current_focus_provider: Callable[[], str] | None = None,
    ) -> None:
        for method in ("open_pgn", "save_pgn_as", "select_library_import"):
            if not callable(getattr(dialogs, method, None)):
                raise TypeError(f"Windows file dialogs must expose {method}")
        for name, callback in (
            ("get_pgn_session", get_pgn_session),
            ("set_pgn_session", set_pgn_session),
            ("import_services_factory", import_services_factory),
            ("event_sink", event_sink),
            ("next_delegate", next_delegate),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("current_focus_provider must be callable")
        self._dialogs = dialogs
        self._get_pgn_session = get_pgn_session
        self._set_pgn_session = set_pgn_session
        self._import_services_factory = import_services_factory
        self._event_sink = event_sink
        self._next_delegate = next_delegate
        self._focus_provider = current_focus_provider or (lambda: "")
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._generation = 0

    @property
    def import_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def _focus(self) -> str:
        try:
            value = self._focus_provider()
        except Exception:
            return ""
        return value if type(value) is str else ""

    def _emit(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        try:
            self._event_sink(event)
        except Exception:
            # Event delivery is an observer boundary.  A WebView failure must not
            # roll back a successful canonical PGN save or corrupt an ACSDB import.
            _LOG.warning("Version 2 file workflow event sink failed", exc_info=True)
        return event

    @staticmethod
    def _empty_payload(payload: Mapping[str, object]) -> None:
        if not isinstance(payload, Mapping):
            raise TypeError("file action payload must be a mapping")
        if payload:
            raise ValueError("file actions accept no browser path payload")

    def __call__(self, action_id: str, payload: Mapping[str, object]) -> Any:
        if action_id not in self.OWNED_ACTIONS:
            return self._next_delegate(action_id, payload)
        self._empty_payload(payload)
        if action_id == "pgn.open":
            return self._open_pgn()
        if action_id == "pgn.save":
            return self._save_pgn()
        if action_id == "pgn.save_as":
            return self._save_pgn_as()
        if action_id == "library.import":
            return self._start_import()
        return self._cancel_import()

    def _failed(self, action_id: str, error_code: str, *, focus_target: str = "") -> FileWorkflowEvent:
        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.FAILED,
                action_id,
                focus_target=focus_target,
                error_code=error_code,
            )
        )

    def _dialog_cancelled(self, action_id: str, focus_target: str) -> FileWorkflowEvent:
        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.DIALOG_CANCELLED,
                action_id,
                focus_target=focus_target,
            )
        )

    def _open_pgn(self) -> FileWorkflowEvent:
        previous_focus = self._focus()
        try:
            path = self._dialogs.open_pgn()
        except Exception:
            return self._failed("pgn.open", "file_dialog_failed", focus_target=previous_focus)
        if path is None:
            return self._dialog_cancelled("pgn.open", previous_focus)
        try:
            session = PgnDocumentSession.open(path)
            self._set_pgn_session(session)
            view = session.view()
        except Exception:
            return self._failed("pgn.open", "pgn_open_failed", focus_target=previous_focus)
        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.PGN_OPENED,
                "pgn.open",
                focus_target="pgn-game-list",
                game_count=view.game_count,
                warning_count=len(view.global_warnings),
            )
        )

    def _session_or_failure(self, action_id: str) -> PgnDocumentSession | FileWorkflowEvent:
        try:
            session = self._get_pgn_session()
        except Exception:
            return self._failed(action_id, "pgn_session_unavailable", focus_target=self._focus())
        if session is None:
            return self._failed(action_id, "no_pgn_document", focus_target=self._focus())
        if not isinstance(session, PgnDocumentSession):
            return self._failed(action_id, "pgn_session_invalid", focus_target=self._focus())
        return session

    def _save_pgn(self) -> FileWorkflowEvent:
        current = self._session_or_failure("pgn.save")
        if isinstance(current, FileWorkflowEvent):
            return current
        previous_focus = self._focus()
        try:
            current.save()
        except PgnDocumentError as exc:
            if exc.code in {
                PgnDocumentErrorCode.NO_SOURCE,
                PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            }:
                return self._save_pgn_as(session=current, prior_focus=previous_focus)
            return self._failed("pgn.save", "pgn_save_failed", focus_target=previous_focus)
        except Exception:
            return self._failed("pgn.save", "pgn_save_failed", focus_target=previous_focus)
        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.PGN_SAVED,
                "pgn.save",
                focus_target=previous_focus,
                game_count=current.view().game_count,
            )
        )

    def _save_pgn_as(
        self,
        *,
        session: PgnDocumentSession | None = None,
        prior_focus: str | None = None,
    ) -> FileWorkflowEvent:
        current: PgnDocumentSession | FileWorkflowEvent
        current = session if session is not None else self._session_or_failure("pgn.save_as")
        if isinstance(current, FileWorkflowEvent):
            return current
        previous_focus = self._focus() if prior_focus is None else prior_focus
        view = current.view()
        suggested = "game.pgn"
        if view.source_path:
            suggested = Path(view.source_path).name or suggested
        try:
            destination = self._dialogs.save_pgn_as(suggested)
        except Exception:
            return self._failed("pgn.save_as", "file_dialog_failed", focus_target=previous_focus)
        if destination is None:
            return self._dialog_cancelled("pgn.save_as", previous_focus)
        try:
            expected = current.expected_destination_sha256(destination)
            current.save_as(
                destination,
                overwrite=expected is not None,
                expected_sha256=expected,
            )
        except Exception:
            return self._failed("pgn.save_as", "pgn_save_as_failed", focus_target=previous_focus)
        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.PGN_SAVED_AS,
                "pgn.save_as",
                focus_target=previous_focus,
                game_count=current.view().game_count,
            )
        )

    def _start_import(self) -> FileWorkflowEvent:
        previous_focus = self._focus()
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return self._failed(
                    "library.import",
                    "import_already_running",
                    focus_target="library-import-cancel",
                )
        try:
            source_path = self._dialogs.select_library_import()
        except Exception:
            return self._failed("library.import", "file_dialog_failed", focus_target=previous_focus)
        if source_path is None:
            return self._dialog_cancelled("library.import", previous_focus)
        suffix = Path(source_path).suffix.lower()
        if suffix not in self._IMPORT_SUFFIXES:
            return self._failed(
                "library.import",
                "unsupported_import_source",
                focus_target="library-import-file",
            )

        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return self._failed(
                    "library.import",
                    "import_already_running",
                    focus_target="library-import-cancel",
                )
            self._generation += 1
            generation = self._generation
            cancel_event = threading.Event()
            self._cancel_event = cancel_event
            worker = threading.Thread(
                target=self._run_import,
                args=(generation, Path(source_path), suffix, cancel_event),
                name=f"AccessibleChess-V2-Import-{generation}",
                daemon=False,
            )
            self._worker = worker
            worker.start()

        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.IMPORT_STARTED,
                "library.import",
                focus_target="library-import-cancel",
            )
        )

    def _cancel_import(self) -> FileWorkflowEvent:
        with self._lock:
            worker = self._worker
            cancel_event = self._cancel_event
            if worker is None or cancel_event is None or not worker.is_alive():
                return self._failed(
                    "library.cancel_import",
                    "no_import_running",
                    focus_target="library-import-file",
                )
            cancel_event.set()
        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.IMPORT_CANCELLING,
                "library.cancel_import",
                focus_target="library-import-cancel",
            )
        )

    def _run_import(
        self,
        generation: int,
        source_path: Path,
        suffix: str,
        cancel_event: threading.Event,
    ) -> None:
        services: Version2ImportWorkerServices | None = None
        progress_started = False

        def cancelled() -> bool:
            return cancel_event.is_set()

        def progress(progress_value: LibraryImportProgress) -> None:
            nonlocal progress_started
            if not isinstance(progress_value, LibraryImportProgress):
                raise TypeError("canonical import progress object is invalid")
            if not progress_started:
                progress_started = True
                self._emit_if_current(
                    generation,
                    FileWorkflowEvent(
                        FileWorkflowEventKind.IMPORT_STARTED,
                        "library.import",
                        focus_target="library-import-cancel",
                        total_games=progress_value.total_games,
                    ),
                )
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_PROGRESS,
                    "library.import",
                    processed_games=progress_value.processed_games,
                    total_games=progress_value.total_games,
                ),
            )

        try:
            services = self._import_services_factory()
            if not isinstance(services, Version2ImportWorkerServices):
                raise TypeError("import_services_factory returned an invalid service bundle")
            if cancelled():
                raise LibraryImportCancelledError("Library import cancelled")

            if suffix == ".pgn":
                opened = open_pgn(source_path)
                if cancelled():
                    raise LibraryImportCancelledError("Library import cancelled")
                if not opened.games:
                    self._emit_if_current(
                        generation,
                        FileWorkflowEvent(
                            FileWorkflowEventKind.IMPORT_EMPTY,
                            "library.import",
                            focus_target="library-import-file",
                        ),
                    )
                    return
                imported = services.library.import_games(
                    opened.games,
                    source_name=report_safe_name(opened.source.path),
                    source_format="pgn",
                    source_sha256=opened.source.sha256,
                    source_warning_count=len(opened.global_warnings),
                    cancel_check=cancelled,
                    progress_callback=progress,
                )
                game_count = int(imported.game_count)
                warning_count = int(imported.warning_count)
            else:
                if services.chessbase is None:
                    self._emit_if_current(
                        generation,
                        FileWorkflowEvent(
                            FileWorkflowEventKind.FAILED,
                            "library.import",
                            focus_target="library-import-file",
                            error_code="chessbase_backend_unavailable",
                        ),
                    )
                    return
                report = services.chessbase.import_database(
                    source_path,
                    cancel_check=cancelled,
                    progress_callback=progress,
                )
                library_result = getattr(report, "library_result", None)
                if library_result is None:
                    self._emit_if_current(
                        generation,
                        FileWorkflowEvent(
                            FileWorkflowEventKind.IMPORT_EMPTY,
                            "library.import",
                            focus_target="library-import-file",
                            warning_count=int(getattr(report, "warning_count", 0)),
                        ),
                    )
                    return
                game_count = int(library_result.game_count)
                warning_count = int(library_result.warning_count)

            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_COMPLETED,
                    "library.import",
                    focus_target="library-import-file",
                    processed_games=game_count,
                    total_games=game_count,
                    game_count=game_count,
                    warning_count=warning_count,
                ),
            )
        except LibraryImportCancelledError:
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_CANCELLED,
                    "library.import",
                    focus_target="library-import-file",
                ),
            )
        except PgnFileError:
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.import",
                    focus_target="library-import-file",
                    error_code="pgn_import_failed",
                ),
            )
        except Exception:
            # Backend exception text may contain paths, SQLite details, decoder
            # names, or provider internals.  It remains machine-log evidence only.
            _LOG.warning("Version 2 Library import failed", exc_info=True)
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.import",
                    focus_target="library-import-file",
                    error_code=(
                        "chessbase_import_failed" if suffix in {".cbh", ".cbv"}
                        else "library_import_failed"
                    ),
                ),
            )
        finally:
            if services is not None:
                try:
                    services.close()
                except Exception:
                    _LOG.warning("Version 2 import worker cleanup failed", exc_info=True)
            with self._lock:
                if generation == self._generation:
                    self._worker = None
                    self._cancel_event = None

    def _emit_if_current(self, generation: int, event: FileWorkflowEvent) -> None:
        with self._lock:
            current = generation == self._generation
        if current:
            self._emit(event)

    def wait_for_import(self, timeout: float | None = None) -> bool:
        """Wait for the current import worker; useful for orderly host shutdown/tests."""

        with self._lock:
            worker = self._worker
        if worker is None:
            return True
        worker.join(timeout)
        return not worker.is_alive()

    def shutdown(self, timeout: float | None = None) -> bool:
        """Request cancellation and wait so the host does not orphan import work."""

        with self._lock:
            worker = self._worker
            cancel_event = self._cancel_event
            if cancel_event is not None:
                cancel_event.set()
        if worker is None:
            return True
        worker.join(timeout)
        return not worker.is_alive()


__all__ = [
    "FileWorkflowEvent",
    "FileWorkflowEventKind",
    "Version2ImportWorkerServices",
    "Version2WindowsFileActionDelegate",
    "Version2WindowsFileDialogs",
]
