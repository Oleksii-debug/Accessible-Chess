from __future__ import annotations

"""Trusted Windows host workflows for Version 2 file actions.

This module is composition only. It never parses PGN itself, decodes ChessBase,
implements Library storage, or owns chess state. Native Windows dialogs choose
filesystem paths on the trusted host. PGN operations delegate to
``PgnDocumentSession``; PGN Library import delegates to ``open_pgn`` plus the
canonical ``LibraryImportService``; CBH/CBV delegates to
``ChessBaseLibraryImportService``. EPUB/HTML book game collections delegate to
the existing Book import/resolution path and that same LibraryImportService;
narrative and diagrams remain in the original book with an explicit report.

Long imports and production PGN Open preparation run on one shared non-daemon
worker slot so WinForms keyboard/NVDA processing remains operable. PGN Open
publication is marshalled back through an injected owner-thread poster before
the active document can change. Only bounded, path-free events leave this host
boundary.
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
    LibraryImportResult,
)
from .book_library_import import (
    BOOK_LIBRARY_SUFFIXES,
    BookLibrarySourceReadError,
    open_book_library_source,
)
from .import_contract import SourceFingerprint, SourceReadCancelledError
from .pgn_document import (
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
    PgnDocumentView,
)
from .pgn_save_snapshot import (
    PgnSaveCancelledError,
    PgnSaveMode,
    PgnSavePublication,
    PgnSaveSnapshot,
    capture_pgn_save_snapshot,
    commit_pgn_save_publication,
    expected_pgn_destination_sha256,
    publish_pgn_save_snapshot,
)
from .pgn_service import (
    PgnConcurrentWriteError,
    PgnFileError,
    PgnPublicationUnverifiedError,
    open_pgn,
)
from .report_paths import report_safe_name


_LOG = logging.getLogger(__name__)


class FileWorkflowEventKind(str, Enum):
    PGN_OPEN_STARTED = "pgn_open_started"
    PGN_OPEN_CANCELLING = "pgn_open_cancelling"
    PGN_OPEN_CANCELLED = "pgn_open_cancelled"
    PGN_OPENED = "pgn_opened"
    PGN_SAVE_STARTED = "pgn_save_started"
    PGN_SAVE_CANCELLING = "pgn_save_cancelling"
    PGN_SAVE_CANCELLED = "pgn_save_cancelled"
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
    source_bytes_read: int = 0
    source_total_bytes: int = 0
    source_parsing: bool = False
    source_format: str = ""
    retained_book_blocks: int = 0

    def __post_init__(self) -> None:
        if type(self) is not FileWorkflowEvent:
            raise TypeError("file workflow event must be an exact passive DTO")
        if type(self.kind) is not FileWorkflowEventKind:
            raise TypeError("file workflow event kind is invalid")
        for name in ("action_id", "focus_target", "error_code", "source_format"):
            if type(getattr(self, name)) is not str:
                raise TypeError(f"{name} must be text")
        if not self.action_id:
            raise ValueError("file workflow action id must not be empty")
        if self.source_format not in {
            "",
            "epub",
            "html",
            "htm",
            "xhtml",
            "md",
            "markdown",
        }:
            raise ValueError("source format is invalid")
        if type(self.source_parsing) is not bool:
            raise TypeError("source_parsing must be a boolean")
        for name in (
            "processed_games",
            "total_games",
            "game_count",
            "warning_count",
            "source_bytes_read",
            "source_total_bytes",
            "retained_book_blocks",
        ):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.total_games and self.processed_games > self.total_games:
            raise ValueError("processed_games must not exceed total_games")
        if self.source_bytes_read > self.source_total_bytes:
            raise ValueError("source_bytes_read must not exceed source_total_bytes")


@dataclass(frozen=True, slots=True)
class Version2ImportWorkerServices:
    """Per-worker canonical import services and their connection cleanup."""

    library: object
    chessbase: object | None
    close: Callable[[], Any]

    def __post_init__(self) -> None:
        if type(self) is not Version2ImportWorkerServices:
            raise TypeError("worker service bundle must be an exact passive DTO")
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

    def confirm_discard_unsaved_pgn(self) -> bool:
        DialogResult, _, _ = self._load_forms()
        from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon  # type: ignore

        result = MessageBox.Show(
            "The current PGN has unsaved changes. Discard those changes and open another PGN?",
            "Unsaved PGN changes",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
        )
        return result == DialogResult.Yes

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
            dialog.Title = "Import games into Library (book text remains in its source file)"
            dialog.Filter = (
                "Supported chess sources and book games|*.pgn;*.cbh;*.cbv;*.epub;*.html;*.htm;*.xhtml;*.md;*.markdown|"
                "PGN files (*.pgn)|*.pgn|ChessBase files (*.cbh;*.cbv)|*.cbh;*.cbv|"
                "Book game collections (*.epub;*.html;*.htm;*.xhtml;*.md;*.markdown)|*.epub;*.html;*.htm;*.xhtml;*.md;*.markdown"
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
            "pgn.cancel_open",
            "pgn.save",
            "pgn.cancel_save",
            "pgn.save_as",
            "library.import",
            "library.cancel_import",
        }
    )
    _IMPORT_SUFFIXES = frozenset({".pgn", ".cbh", ".cbv"}) | BOOK_LIBRARY_SUFFIXES
    _IMPORT_TERMINAL_KINDS = frozenset(
        {
            FileWorkflowEventKind.IMPORT_COMPLETED,
            FileWorkflowEventKind.IMPORT_CANCELLED,
            FileWorkflowEventKind.IMPORT_EMPTY,
            FileWorkflowEventKind.FAILED,
        }
    )

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
        post_to_ui: Callable[[Callable[[], None]], Any] | None = None,
        owner_async_event_sink: Callable[[FileWorkflowEvent], Any] | None = None,
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
        if post_to_ui is not None and not callable(post_to_ui):
            raise TypeError("post_to_ui must be callable")
        if owner_async_event_sink is not None and not callable(owner_async_event_sink):
            raise TypeError("owner_async_event_sink must be callable")
        self._dialogs = dialogs
        self._get_pgn_session = get_pgn_session
        self._set_pgn_session = set_pgn_session
        self._import_services_factory = import_services_factory
        self._event_sink = event_sink
        self._next_delegate = next_delegate
        self._focus_provider = current_focus_provider or (lambda: "")
        self._post_to_ui = post_to_ui
        self._owner_async_event_sink = owner_async_event_sink or event_sink
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._worker_started = False
        self._worker_kind = ""
        self._cancel_event: threading.Event | None = None
        self._terminal_pending: tuple[int, FileWorkflowEvent] | None = None
        self._pending_save_result: tuple[object, ...] | None = None
        self._generation = 0
        self._shutdown_requested = False

    @property
    def import_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker_kind == "import"

    @property
    def pgn_open_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker_kind == "pgn_open"

    @property
    def pgn_save_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker_kind == "pgn_save"

    @staticmethod
    def _worker_focus_target(worker_kind: str) -> str:
        if worker_kind == "import":
            return "library-import-cancel"
        if worker_kind == "pgn_open":
            return "pgn-open-cancel"
        if worker_kind == "pgn_save":
            return "pgn-save-cancel"
        return ""

    def _focus(self) -> str:
        try:
            value = self._focus_provider()
        except BaseException:
            return ""
        return value if type(value) is str else ""

    def _emit(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        try:
            self._event_sink(event)
        except BaseException:
            _LOG.warning("Version 2 file workflow event sink failed", exc_info=True)
        return event

    def _emit_owner_async(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        """Publish one async terminal already executing on the owner UI thread."""

        try:
            self._owner_async_event_sink(event)
        except BaseException:
            _LOG.warning(
                "Version 2 owner asynchronous file event sink failed",
                exc_info=True,
            )
        return event

    @staticmethod
    def _empty_payload(payload: Mapping[str, object]) -> None:
        if type(payload) is not dict:
            raise TypeError("file action payload must be an exact object")
        if payload:
            raise ValueError("file actions accept no browser path payload")

    def __call__(self, action_id: str, payload: Mapping[str, object]) -> Any:
        if type(action_id) is not str:
            raise TypeError("file action id must be exact text")
        if action_id not in self.OWNED_ACTIONS:
            return self._next_delegate(action_id, payload)
        self._empty_payload(payload)
        if action_id == "pgn.open":
            return self._open_pgn()
        if action_id == "pgn.cancel_open":
            return self._cancel_pgn_open()
        if action_id == "pgn.save":
            return self._save_pgn()
        if action_id == "pgn.cancel_save":
            return self._cancel_pgn_save()
        if action_id == "pgn.save_as":
            return self._save_pgn_as()
        if action_id == "library.import":
            return self._start_import()
        return self._cancel_import()

    def _failed(
        self,
        action_id: str,
        error_code: str,
        *,
        focus_target: str = "",
    ) -> FileWorkflowEvent:
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

    def _prepare_open_path(
        self,
    ) -> tuple[
        Path | None,
        FileWorkflowEvent | None,
        str,
        PgnDocumentSession | None,
        int | None,
    ]:
        previous_focus = self._focus()
        try:
            current = self._get_pgn_session()
        except BaseException:
            return None, self._failed(
                "pgn.open", "pgn_session_unavailable", focus_target=previous_focus
            ), previous_focus, None, None
        if current is not None and type(current) is not PgnDocumentSession:
            return None, self._failed(
                "pgn.open", "pgn_session_invalid", focus_target=previous_focus
            ), previous_focus, None, None
        try:
            current_revision = None if current is None else current.document_revision
            current_dirty = False if current is None else current.dirty
        except BaseException:
            return None, self._failed(
                "pgn.open", "pgn_session_invalid", focus_target=previous_focus
            ), previous_focus, None, None
        if current is not None:
            if current_dirty:
                confirmation = getattr(self._dialogs, "confirm_discard_unsaved_pgn", None)
                if not callable(confirmation):
                    return None, self._failed(
                        "pgn.open",
                        "unsaved_confirmation_unavailable",
                        focus_target=previous_focus,
                    ), previous_focus, current, current_revision
                try:
                    discard = confirmation()
                except BaseException:
                    return None, self._failed(
                        "pgn.open",
                        "unsaved_confirmation_failed",
                        focus_target=previous_focus,
                    ), previous_focus, current, current_revision
                if not discard:
                    return None, self._dialog_cancelled(
                        "pgn.open", previous_focus
                    ), previous_focus, current, current_revision
        try:
            path = self._dialogs.open_pgn()
            if path is not None:
                path = Path(path)
        except BaseException:
            return None, self._failed(
                "pgn.open", "file_dialog_failed", focus_target=previous_focus
            ), previous_focus, current, current_revision
        if path is None:
            return None, self._dialog_cancelled(
                "pgn.open", previous_focus
            ), previous_focus, current, current_revision
        return path, None, previous_focus, current, current_revision

    def _open_pgn(self) -> FileWorkflowEvent:
        # Fail before any dirty-confirmation or file-picker I/O when the shared
        # worker is already owned. Native WinForms dialogs pump messages, so the
        # existing post-dialog ownership recheck below remains authoritative for
        # races that begin while the picker is open.
        previous_focus = self._focus()
        with self._lock:
            shutdown_requested = self._shutdown_requested
            worker_kind = self._worker_kind if self._worker is not None else ""
        if shutdown_requested:
            return self._failed(
                "pgn.open", "file_workflow_closed", focus_target=previous_focus
            )
        if worker_kind:
            focus_target = self._worker_focus_target(worker_kind)
            return self._failed(
                "pgn.open", "file_worker_busy", focus_target=focus_target
            )

        (
            source_path,
            early,
            previous_focus,
            expected_session,
            expected_revision,
        ) = self._prepare_open_path()
        if early is not None:
            return early
        assert source_path is not None

        # Native file dialogs are modal but still pump Windows messages. A
        # re-entrant host callback can therefore replace/edit the document while
        # the dialog is open. Never apply the earlier discard decision to a
        # different or newer document generation.
        try:
            live_session = self._get_pgn_session()
        except BaseException:
            return self._failed(
                "pgn.open", "pgn_session_unavailable", focus_target=previous_focus
            )
        if (
            live_session is not expected_session
            or (
                expected_session is not None
                and expected_revision is not None
                and expected_session.document_revision != expected_revision
            )
        ):
            return self._failed(
                "pgn.open", "pgn_open_stale", focus_target=previous_focus
            )

        # The modal picker may have pumped a re-entrant file action or shutdown.
        # Revalidate shared-worker ownership before *any* PGN parsing path,
        # including the legacy synchronous embedding seam below.
        with self._lock:
            shutdown_requested = self._shutdown_requested
            worker_kind = self._worker_kind if self._worker is not None else ""
        if shutdown_requested:
            return self._failed(
                "pgn.open", "file_workflow_closed", focus_target=previous_focus
            )
        if worker_kind:
            focus_target = self._worker_focus_target(worker_kind)
            return self._failed(
                "pgn.open", "file_worker_busy", focus_target=focus_target
            )

        # Legacy direct-controller tests and non-Windows embeddings do not own a
        # UI poster. Keep their historical synchronous seam while the real
        # Version2 Windows composition always injects the WinForms poster below.
        if self._post_to_ui is None:
            try:
                session = PgnDocumentSession.open(source_path)
                view = session.view()
                self._set_pgn_session(session)
            except BaseException:
                return self._failed(
                    "pgn.open", "pgn_open_failed", focus_target=previous_focus
                )
            return self._emit(
                FileWorkflowEvent(
                    FileWorkflowEventKind.PGN_OPENED,
                    "pgn.open",
                    focus_target="pgn-game-list",
                    game_count=view.game_count,
                    warning_count=len(view.global_warnings),
                )
            )

        with self._lock:
            if self._shutdown_requested:
                return self._failed(
                    "pgn.open", "file_workflow_closed", focus_target=previous_focus
                )
            if self._worker is not None:
                focus_target = self._worker_focus_target(self._worker_kind)
                return self._failed(
                    "pgn.open", "file_worker_busy", focus_target=focus_target
                )
            self._generation += 1
            generation = self._generation
            cancel_event = threading.Event()
            worker = threading.Thread(
                target=self._run_pgn_open,
                args=(
                    generation,
                    source_path,
                    previous_focus,
                    cancel_event,
                    expected_session,
                    expected_revision,
                ),
                name=f"AccessibleChess-V2-PgnOpen-{generation}",
                daemon=False,
            )
            self._worker = worker
            self._worker_started = False
            self._worker_kind = "pgn_open"
            self._cancel_event = cancel_event
            self._terminal_pending = None

        started = self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.PGN_OPEN_STARTED,
                "pgn.open",
                focus_target="pgn-open-cancel",
            )
        )
        shutdown_before_start = False
        try:
            with self._lock:
                if generation != self._generation or self._worker is not worker:
                    raise RuntimeError("PGN Open worker ownership changed before start")
                if self._shutdown_requested:
                    self._clear_worker_locked()
                    shutdown_before_start = True
                else:
                    worker.start()
                    if self._worker is worker:
                        self._worker_started = True
        except BaseException:
            with self._lock:
                if generation == self._generation and self._worker is worker:
                    self._clear_worker_locked()
            return self._failed(
                "pgn.open", "pgn_open_worker_unavailable", focus_target=previous_focus
            )
        if shutdown_before_start:
            return self._failed(
                "pgn.open", "file_workflow_closed", focus_target=previous_focus
            )
        return started

    def _run_pgn_open(
        self,
        generation: int,
        source_path: Path,
        previous_focus: str,
        cancel_event: threading.Event,
        expected_session: PgnDocumentSession | None,
        expected_revision: int | None,
    ) -> None:
        session: PgnDocumentSession | None = None
        view = None
        error_code = ""
        try:
            if cancel_event.is_set():
                error_code = "pgn_open_cancelled"
            else:
                session = PgnDocumentSession.open(source_path)
                if cancel_event.is_set():
                    error_code = "pgn_open_cancelled"
                else:
                    # Canonical initial presentation materialization can also be
                    # substantial and therefore remains on the same worker.
                    view = session.view()
                    if cancel_event.is_set():
                        error_code = "pgn_open_cancelled"
        except BaseException:
            _LOG.warning("Version 2 PGN Open preparation failed", exc_info=True)
            error_code = "pgn_open_failed"

        def finish_on_owner() -> None:
            self._finish_pgn_open_on_owner(
                generation,
                session,
                view,
                error_code,
                previous_focus,
                cancel_event,
                expected_session,
                expected_revision,
            )

        try:
            assert self._post_to_ui is not None
            self._post_to_ui(finish_on_owner)
        except BaseException:
            _LOG.warning("Version 2 PGN Open UI publication post failed", exc_info=True)
            with self._lock:
                current = (
                    generation == self._generation
                    and self._worker_kind == "pgn_open"
                    and not self._shutdown_requested
                )
                if current:
                    self._clear_worker_locked()
            if current:
                self._emit(
                    FileWorkflowEvent(
                        FileWorkflowEventKind.FAILED,
                        "pgn.open",
                        focus_target=previous_focus,
                        error_code="pgn_open_ui_post_failed",
                    )
                )

    def _finish_pgn_open_on_owner(
        self,
        generation: int,
        session: PgnDocumentSession | None,
        view: object | None,
        error_code: str,
        previous_focus: str,
        cancel_event: threading.Event,
        expected_session: PgnDocumentSession | None,
        expected_revision: int | None,
    ) -> None:
        with self._lock:
            current = (
                generation == self._generation
                and self._worker is not None
                and self._worker_kind == "pgn_open"
                and not self._shutdown_requested
            )
            cancelled = cancel_event.is_set()
            if not current:
                return

        if cancelled or error_code == "pgn_open_cancelled":
            terminal = FileWorkflowEvent(
                FileWorkflowEventKind.PGN_OPEN_CANCELLED,
                "pgn.open",
                focus_target=previous_focus,
            )
        elif error_code or session is None or view is None:
            terminal = FileWorkflowEvent(
                FileWorkflowEventKind.FAILED,
                "pgn.open",
                focus_target=previous_focus,
                error_code=error_code or "pgn_open_failed",
            )
        else:
            # The worker result crosses back into the owner/UI thread. Treat it
            # as a passive DTO boundary before publishing the prepared session:
            # no __int__, __len__, property, subclass or warning-item hook may
            # execute after the active document has already been replaced.
            try:
                if type(session) is not PgnDocumentSession:
                    raise TypeError("prepared PGN session is not canonical")
                if type(view) is not PgnDocumentView:
                    raise TypeError("prepared PGN view is not canonical")
                game_count = view.game_count
                global_warnings = view.global_warnings
                if type(game_count) is not int or game_count < 0:
                    raise TypeError("prepared PGN game count is invalid")
                if type(global_warnings) is not tuple or any(
                    type(item) is not str for item in global_warnings
                ):
                    raise TypeError("prepared PGN warnings are invalid")
                warning_count = len(global_warnings)
            except BaseException:
                _LOG.warning(
                    "Version 2 PGN Open prepared result rejected",
                    exc_info=True,
                )
                terminal = FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "pgn.open",
                    focus_target=previous_focus,
                    error_code="pgn_open_failed",
                )
            else:
                try:
                    live_session = self._get_pgn_session()
                except BaseException:
                    terminal = FileWorkflowEvent(
                        FileWorkflowEventKind.FAILED,
                        "pgn.open",
                        focus_target=previous_focus,
                        error_code="pgn_session_unavailable",
                    )
                else:
                    try:
                        stale = live_session is not expected_session
                        if not stale and expected_session is not None:
                            if (
                                type(expected_revision) is not int
                                or expected_revision < 0
                            ):
                                raise TypeError(
                                    "PGN Open expected revision is invalid"
                                )
                            live_revision = expected_session.document_revision
                            stale = live_revision != expected_revision
                        elif not stale and expected_revision is not None:
                            raise TypeError(
                                "PGN Open unexpected revision without session"
                            )
                    except BaseException:
                        _LOG.warning(
                            "Version 2 PGN Open stale-generation check failed",
                            exc_info=True,
                        )
                        stale = True
                    if stale:
                        # The user changed, replaced, or invalidated the document
                        # while bounded parsing/materialization was in flight.
                        # Preserve that newer/uncertain authority and discard the
                        # prepared replacement.
                        terminal = FileWorkflowEvent(
                            FileWorkflowEventKind.FAILED,
                            "pgn.open",
                            focus_target=previous_focus,
                            error_code="pgn_open_stale",
                        )
                    else:
                        try:
                            # This is the only publication point and it executes through the
                            # owner-thread poster supplied by the production Windows runtime.
                            self._set_pgn_session(session)
                        except BaseException:
                            _LOG.warning(
                                "Version 2 PGN Open session publication failed",
                                exc_info=True,
                            )
                            terminal = FileWorkflowEvent(
                                FileWorkflowEventKind.FAILED,
                                "pgn.open",
                                focus_target=previous_focus,
                                error_code="pgn_open_publish_failed",
                            )
                        else:
                            terminal = FileWorkflowEvent(
                                FileWorkflowEventKind.PGN_OPENED,
                                "pgn.open",
                                focus_target="pgn-game-list",
                                game_count=game_count,
                                warning_count=warning_count,
                            )

        with self._lock:
            if (
                generation != self._generation
                or self._worker_kind != "pgn_open"
                or self._shutdown_requested
            ):
                return
            self._clear_worker_locked()
        self._emit_owner_async(terminal)

    def _cancel_pgn_open(self) -> FileWorkflowEvent:
        with self._lock:
            worker = self._worker
            cancel_event = self._cancel_event
            running = (
                worker is not None
                and self._worker_kind == "pgn_open"
                and cancel_event is not None
            )
            if running:
                cancel_event.set()
        if not running:
            return self._failed(
                "pgn.cancel_open",
                "no_pgn_open_running",
                focus_target="pgn-game-list",
            )
        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.PGN_OPEN_CANCELLING,
                "pgn.cancel_open",
                focus_target="pgn-open-cancel",
            )
        )

    def _clear_worker_locked(self) -> None:
        self._worker = None
        self._worker_started = False
        self._worker_kind = ""
        self._cancel_event = None
        self._terminal_pending = None
        self._pending_save_result = None

    def _session_or_failure(
        self, action_id: str
    ) -> PgnDocumentSession | FileWorkflowEvent:
        try:
            session = self._get_pgn_session()
        except BaseException:
            return self._failed(
                action_id, "pgn_session_unavailable", focus_target=self._focus()
            )
        if session is None:
            return self._failed(
                action_id, "no_pgn_document", focus_target=self._focus()
            )
        if not isinstance(session, PgnDocumentSession):
            return self._failed(
                action_id, "pgn_session_invalid", focus_target=self._focus()
            )
        return session

    def _save_pgn(self) -> FileWorkflowEvent:
        previous_focus = self._focus()
        with self._lock:
            active_kind = self._worker_kind if self._worker is not None else ""
            shutdown_requested = self._shutdown_requested
        if shutdown_requested:
            return self._failed(
                "pgn.save", "file_workflow_closed", focus_target=previous_focus
            )
        if active_kind:
            return self._failed(
                "pgn.save",
                "file_worker_busy",
                focus_target=self._worker_focus_target(active_kind),
            )

        current = self._session_or_failure("pgn.save")
        if isinstance(current, FileWorkflowEvent):
            return current

        # Preserve the historical synchronous seam for non-Windows/direct
        # embeddings that do not supply an owner-thread poster.
        if self._post_to_ui is None:
            try:
                game_count = current.view().game_count
                current.save()
            except PgnPublicationUnverifiedError:
                return self._failed(
                    "pgn.save",
                    "pgn_save_publication_unverified",
                    focus_target=previous_focus,
                )
            except PgnDocumentError as exc:
                if exc.code in {
                    PgnDocumentErrorCode.NO_SOURCE,
                    PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
                }:
                    return self._save_pgn_as(
                        session=current, prior_focus=previous_focus
                    )
                error_code = (
                    "pgn_save_commit_failed"
                    if exc.code is PgnDocumentErrorCode.SAVE_COMMIT_FAILED
                    else "pgn_save_failed"
                )
                return self._failed(
                    "pgn.save", error_code, focus_target=previous_focus
                )
            except BaseException:
                return self._failed(
                    "pgn.save", "pgn_save_failed", focus_target=previous_focus
                )
            return self._emit(
                FileWorkflowEvent(
                    FileWorkflowEventKind.PGN_SAVED,
                    "pgn.save",
                    focus_target=previous_focus,
                    game_count=game_count,
                )
            )

        if type(current) is not PgnDocumentSession:
            return self._failed(
                "pgn.save", "pgn_session_invalid", focus_target=previous_focus
            )
        try:
            snapshot = capture_pgn_save_snapshot(current, mode=PgnSaveMode.SAVE)
        except PgnDocumentError as exc:
            if exc.code in {
                PgnDocumentErrorCode.NO_SOURCE,
                PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            }:
                return self._save_pgn_as(
                    session=current, prior_focus=previous_focus
                )
            return self._failed(
                "pgn.save", "pgn_save_failed", focus_target=previous_focus
            )
        except BaseException:
            return self._failed(
                "pgn.save", "pgn_save_failed", focus_target=previous_focus
            )
        return self._start_pgn_save_worker(
            action_id="pgn.save",
            session=current,
            snapshot=snapshot,
            destination=None,
            previous_focus=previous_focus,
        )

    def _save_pgn_as(
        self,
        *,
        session: PgnDocumentSession | None = None,
        prior_focus: str | None = None,
    ) -> FileWorkflowEvent:
        previous_focus = self._focus() if prior_focus is None else prior_focus
        with self._lock:
            active_kind = self._worker_kind if self._worker is not None else ""
            shutdown_requested = self._shutdown_requested
        if shutdown_requested:
            return self._failed(
                "pgn.save_as", "file_workflow_closed", focus_target=previous_focus
            )
        if active_kind:
            return self._failed(
                "pgn.save_as",
                "file_worker_busy",
                focus_target=self._worker_focus_target(active_kind),
            )

        current: PgnDocumentSession | FileWorkflowEvent
        current = (
            session
            if session is not None
            else self._session_or_failure("pgn.save_as")
        )
        if isinstance(current, FileWorkflowEvent):
            return current
        if not isinstance(current, PgnDocumentSession):
            return self._failed(
                "pgn.save_as", "pgn_session_invalid", focus_target=previous_focus
            )
        if self._post_to_ui is not None and type(current) is not PgnDocumentSession:
            return self._failed(
                "pgn.save_as", "pgn_session_invalid", focus_target=previous_focus
            )

        suggested = "game.pgn"
        if self._post_to_ui is None:
            # Preserve the historical direct-embedding seam, including its
            # presentation-derived game count and suggested source filename.
            try:
                view = current.view()
                expected_revision = current.document_revision
            except BaseException:
                return self._failed(
                    "pgn.save_as",
                    "pgn_save_as_failed",
                    focus_target=previous_focus,
                )
            game_count = view.game_count
            if view.source_path:
                suggested = Path(view.source_path).name or suggested
        else:
            # Production Windows Save As must not materialize the complete PGN
            # presentation before opening the native picker. The exact detached
            # save snapshot is captured after the dialog returns; here we need
            # only a passive source filename and the pre-dialog revision fence.
            expected_revision = current.document_revision
            source = current.source
            if type(source) is SourceFingerprint and type(source.path) is str:
                suggested = Path(source.path).name or suggested
        try:
            destination = self._dialogs.save_pgn_as(suggested)
            if destination is not None:
                destination = Path(destination)
        except BaseException:
            return self._failed(
                "pgn.save_as", "file_dialog_failed", focus_target=previous_focus
            )
        if destination is None:
            return self._dialog_cancelled("pgn.save_as", previous_focus)

        # Native dialogs pump messages. Do not publish a detached snapshot for a
        # document that was replaced or edited while the picker was open.
        try:
            live_session = self._get_pgn_session()
        except BaseException:
            return self._failed(
                "pgn.save_as", "pgn_session_unavailable", focus_target=previous_focus
            )
        if (
            live_session is not current
            or current.document_revision != expected_revision
        ):
            return self._failed(
                "pgn.save_as", "pgn_save_preflight_stale", focus_target=previous_focus
            )

        # The modal picker can pump a re-entrant file action or shutdown just as
        # PGN Open can. Revalidate the shared worker before detached snapshot
        # capture so a losing Save As does not spend owner-thread time freezing
        # a document that it is no longer allowed to publish.
        with self._lock:
            shutdown_requested = self._shutdown_requested
            active_kind = self._worker_kind if self._worker is not None else ""
        if shutdown_requested:
            return self._failed(
                "pgn.save_as", "file_workflow_closed", focus_target=previous_focus
            )
        if active_kind:
            return self._failed(
                "pgn.save_as",
                "file_worker_busy",
                focus_target=self._worker_focus_target(active_kind),
            )

        if self._post_to_ui is None:
            try:
                expected = current.expected_destination_sha256(destination)
                current.save_as(
                    destination,
                    overwrite=expected is not None,
                    expected_sha256=expected,
                )
            except PgnPublicationUnverifiedError:
                return self._failed(
                    "pgn.save_as",
                    "pgn_save_publication_unverified",
                    focus_target=previous_focus,
                )
            except PgnDocumentError as exc:
                if (
                    exc.code
                    is PgnDocumentErrorCode.RECOVERY_SOURCE_REQUIRES_DIFFERENT_DESTINATION
                ):
                    error_code = "pgn_save_as_preserve_original"
                elif exc.code is PgnDocumentErrorCode.SAVE_COMMIT_FAILED:
                    error_code = "pgn_save_commit_failed"
                else:
                    error_code = "pgn_save_as_failed"
                return self._failed(
                    "pgn.save_as",
                    error_code,
                    focus_target=previous_focus,
                )
            except BaseException:
                return self._failed(
                    "pgn.save_as",
                    "pgn_save_as_failed",
                    focus_target=previous_focus,
                )
            return self._emit(
                FileWorkflowEvent(
                    FileWorkflowEventKind.PGN_SAVED_AS,
                    "pgn.save_as",
                    focus_target=previous_focus,
                    game_count=game_count,
                )
            )

        if type(current) is not PgnDocumentSession:
            return self._failed(
                "pgn.save_as", "pgn_session_invalid", focus_target=previous_focus
            )
        try:
            snapshot = capture_pgn_save_snapshot(
                current,
                mode=PgnSaveMode.SAVE_AS,
            )
        except BaseException:
            return self._failed(
                "pgn.save_as",
                "pgn_save_as_failed",
                focus_target=previous_focus,
            )

        return self._start_pgn_save_worker(
            action_id="pgn.save_as",
            session=current,
            snapshot=snapshot,
            destination=destination,
            previous_focus=previous_focus,
        )

    def _start_pgn_save_worker(
        self,
        *,
        action_id: str,
        session: PgnDocumentSession,
        snapshot: PgnSaveSnapshot,
        destination: Path | None,
        previous_focus: str,
    ) -> FileWorkflowEvent:
        if action_id not in {"pgn.save", "pgn.save_as"}:
            raise ValueError("invalid PGN save action")
        if type(session) is not PgnDocumentSession:
            raise TypeError("PGN save worker requires an exact document session")
        if type(snapshot) is not PgnSaveSnapshot:
            raise TypeError("PGN save worker requires an exact detached snapshot")
        if action_id == "pgn.save" and destination is not None:
            raise ValueError("Save may not carry a Save As destination")
        if action_id == "pgn.save_as" and destination is None:
            raise ValueError("Save As requires a destination")

        with self._lock:
            if self._shutdown_requested:
                return self._failed(
                    action_id, "file_workflow_closed", focus_target=previous_focus
                )
            if self._worker is not None:
                return self._failed(
                    action_id,
                    "file_worker_busy",
                    focus_target=self._worker_focus_target(self._worker_kind),
                )
            self._generation += 1
            generation = self._generation
            cancel_event = threading.Event()
            worker = threading.Thread(
                target=self._run_pgn_save,
                args=(
                    generation,
                    action_id,
                    session,
                    snapshot,
                    destination,
                    previous_focus,
                    cancel_event,
                ),
                name=f"AccessibleChess-V2-PgnSave-{generation}",
                daemon=False,
            )
            self._worker = worker
            self._worker_started = False
            self._worker_kind = "pgn_save"
            self._cancel_event = cancel_event
            self._terminal_pending = None
            self._pending_save_result = None

        started = self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.PGN_SAVE_STARTED,
                action_id,
                focus_target="pgn-save-cancel",
                game_count=len(snapshot.games),
            )
        )
        shutdown_before_start = False
        try:
            with self._lock:
                if generation != self._generation or self._worker is not worker:
                    raise RuntimeError("PGN save worker ownership changed before start")
                if self._shutdown_requested:
                    self._clear_worker_locked()
                    shutdown_before_start = True
                else:
                    worker.start()
                    if self._worker is worker:
                        self._worker_started = True
        except BaseException:
            with self._lock:
                if generation == self._generation and self._worker is worker:
                    self._clear_worker_locked()
            return self._failed(
                action_id,
                "pgn_save_worker_unavailable",
                focus_target=previous_focus,
            )
        if shutdown_before_start:
            return self._failed(
                action_id, "file_workflow_closed", focus_target=previous_focus
            )
        return started

    def _run_pgn_save(
        self,
        generation: int,
        action_id: str,
        session: PgnDocumentSession,
        snapshot: PgnSaveSnapshot,
        destination: Path | None,
        previous_focus: str,
        cancel_event: threading.Event,
    ) -> None:
        publication: PgnSavePublication | None = None
        error_code = ""
        ordinary_failure_code = (
            "pgn_save_as_failed" if action_id == "pgn.save_as" else "pgn_save_failed"
        )
        try:
            if action_id == "pgn.save":
                publication = publish_pgn_save_snapshot(
                    snapshot,
                    cancel_check=cancel_event.is_set,
                )
            else:
                assert destination is not None
                expected = expected_pgn_destination_sha256(
                    destination,
                    cancel_check=cancel_event.is_set,
                )
                publication = publish_pgn_save_snapshot(
                    snapshot,
                    path=destination,
                    overwrite=expected is not None,
                    expected_sha256=expected,
                    cancel_check=cancel_event.is_set,
                )
        except PgnSaveCancelledError:
            error_code = "pgn_save_cancelled"
        except PgnConcurrentWriteError:
            error_code = "pgn_save_conflict"
        except PgnPublicationUnverifiedError:
            # The atomic writer already crossed its publication boundary but
            # could not bind final provenance safely. This must not be reported
            # as an ordinary save failure: a blind retry could overwrite the
            # generation that may already be on disk.
            error_code = "pgn_save_publication_unverified"
        except PgnDocumentError as exc:
            if (
                exc.code
                is PgnDocumentErrorCode.RECOVERY_SOURCE_REQUIRES_DIFFERENT_DESTINATION
            ):
                error_code = "pgn_save_as_preserve_original"
            else:
                _LOG.warning("Version 2 PGN save publication failed", exc_info=True)
                error_code = ordinary_failure_code
        except BaseException:
            _LOG.warning("Version 2 PGN save publication failed", exc_info=True)
            error_code = ordinary_failure_code

        pending = (
            generation,
            action_id,
            session,
            publication,
            error_code,
            previous_focus,
            cancel_event,
            len(snapshot.games),
        )
        with self._lock:
            if generation == self._generation and self._worker_kind == "pgn_save":
                self._pending_save_result = pending

        def finish_on_owner() -> None:
            self._finish_pgn_save_on_owner(*pending)

        try:
            assert self._post_to_ui is not None
            self._post_to_ui(finish_on_owner)
        except BaseException:
            _LOG.warning("Version 2 PGN save UI publication post failed", exc_info=True)
            # Keep the result recoverable. A durable publication must be
            # committed on the owner thread during shutdown or the next posted
            # owner callback; do not clear its worker authority here.
            if publication is None:
                with self._lock:
                    current = (
                        generation == self._generation
                        and self._worker_kind == "pgn_save"
                        and not self._shutdown_requested
                    )
                    if current:
                        self._clear_worker_locked()
                if current:
                    self._emit(
                        FileWorkflowEvent(
                            FileWorkflowEventKind.FAILED,
                            action_id,
                            focus_target=previous_focus,
                            error_code="pgn_save_ui_post_failed",
                        )
                    )

    def _finish_pgn_save_on_owner(
        self,
        generation: int,
        action_id: str,
        session: PgnDocumentSession,
        publication: PgnSavePublication | None,
        error_code: str,
        previous_focus: str,
        cancel_event: threading.Event,
        game_count: int,
        *,
        allow_shutdown_commit: bool = False,
    ) -> FileWorkflowEvent | None:
        with self._lock:
            current = (
                generation == self._generation
                and self._worker is not None
                and self._worker_kind == "pgn_save"
                and (allow_shutdown_commit or not self._shutdown_requested)
            )
            if not current:
                return None

        # Terminal truth is fixed by the worker result. A Cancel click that
        # arrives after publication success or a completed worker failure must
        # not rewrite that result into a contradictory cancellation terminal.
        if publication is None and error_code == "pgn_save_cancelled":
            terminal = FileWorkflowEvent(
                FileWorkflowEventKind.PGN_SAVE_CANCELLED,
                action_id,
                focus_target=previous_focus,
            )
        elif error_code or publication is None:
            terminal = FileWorkflowEvent(
                FileWorkflowEventKind.FAILED,
                action_id,
                focus_target=previous_focus,
                error_code=error_code or "pgn_save_failed",
            )
        else:
            try:
                live_session = self._get_pgn_session()
            except BaseException:
                terminal = FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    action_id,
                    focus_target=previous_focus,
                    # Durable publication has already succeeded. Reuse the
                    # post-publication commit failure classification so the
                    # accessible status truthfully says the file was written
                    # even though document provenance could not be finalized.
                    error_code="pgn_save_commit_failed",
                )
            else:
                if live_session is not session:
                    terminal = FileWorkflowEvent(
                        FileWorkflowEventKind.FAILED,
                        action_id,
                        focus_target=previous_focus,
                        error_code="pgn_save_stale",
                    )
                else:
                    try:
                        commit_pgn_save_publication(session, publication)
                    except BaseException:
                        _LOG.warning(
                            "Version 2 PGN save owner commit failed",
                            exc_info=True,
                        )
                        terminal = FileWorkflowEvent(
                            FileWorkflowEventKind.FAILED,
                            action_id,
                            focus_target=previous_focus,
                            error_code="pgn_save_commit_failed",
                        )
                    else:
                        terminal = FileWorkflowEvent(
                            (
                                FileWorkflowEventKind.PGN_SAVED
                                if action_id == "pgn.save"
                                else FileWorkflowEventKind.PGN_SAVED_AS
                            ),
                            action_id,
                            focus_target=previous_focus,
                            game_count=game_count,
                        )

        with self._lock:
            if (
                generation != self._generation
                or self._worker_kind != "pgn_save"
                or (
                    self._shutdown_requested
                    and not allow_shutdown_commit
                )
            ):
                return None
            self._clear_worker_locked()
        return self._emit_owner_async(terminal)

    def _cancel_pgn_save(self) -> FileWorkflowEvent:
        pending: tuple[object, ...] | None = None
        with self._lock:
            worker = self._worker
            cancel_event = self._cancel_event
            running = (
                worker is not None
                and self._worker_kind == "pgn_save"
                and cancel_event is not None
            )
            if running:
                candidate = self._pending_save_result
                if candidate is not None and candidate[0] == self._generation:
                    # A pending result exists only after the worker has finished
                    # publication/classification. At that point cancellation can
                    # no longer change disk truth, whether the fixed result is a
                    # durable success, cancellation, conflict, or other failure.
                    # Resolve that exact terminal now instead of announcing a
                    # contradictory new cancellation request.
                    pending = candidate
                else:
                    cancel_event.set()
        if pending is not None:
            terminal = self._finish_pgn_save_on_owner(*pending)
            if terminal is not None:
                return terminal
        if not running:
            return self._failed(
                "pgn.cancel_save",
                "no_pgn_save_running",
                focus_target="pgn-game-list",
            )
        return self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.PGN_SAVE_CANCELLING,
                "pgn.cancel_save",
                focus_target="pgn-save-cancel",
            )
        )

    def _start_import(self) -> FileWorkflowEvent:
        previous_focus = self._focus()
        with self._lock:
            active_kind = self._worker_kind if self._worker is not None else ""
            shutdown_requested = self._shutdown_requested
        if shutdown_requested:
            return self._failed(
                "library.import", "file_workflow_closed", focus_target=previous_focus
            )
        if active_kind:
            return self._failed(
                "library.import",
                (
                    "import_already_running"
                    if active_kind == "import"
                    else "file_worker_busy"
                ),
                focus_target=self._worker_focus_target(active_kind),
            )
        try:
            source_path = self._dialogs.select_library_import()
            if source_path is not None:
                source_path = Path(source_path)
        except BaseException:
            return self._failed(
                "library.import", "file_dialog_failed", focus_target=previous_focus
            )
        if source_path is None:
            return self._dialog_cancelled("library.import", previous_focus)
        suffix = source_path.suffix.lower()
        if suffix not in self._IMPORT_SUFFIXES:
            return self._failed(
                "library.import",
                "unsupported_import_source",
                focus_target="library-import-file",
            )

        with self._lock:
            shutdown_requested = self._shutdown_requested
            conflict_kind = self._worker_kind if self._worker is not None else ""
            if not shutdown_requested and not conflict_kind:
                self._generation += 1
                generation = self._generation
                cancel_event = threading.Event()
                self._cancel_event = cancel_event
                self._terminal_pending = None
                worker = threading.Thread(
                    target=self._run_import,
                    args=(generation, Path(source_path), suffix, cancel_event),
                    name=f"AccessibleChess-V2-Import-{generation}",
                    daemon=False,
                )
                self._worker = worker
                self._worker_started = False
                self._worker_kind = "import"

        if shutdown_requested:
            return self._failed(
                "library.import", "file_workflow_closed", focus_target=previous_focus
            )
        if conflict_kind:
            return self._failed(
                "library.import",
                "file_worker_busy",
                focus_target=self._worker_focus_target(conflict_kind),
            )

        started = self._emit(
            FileWorkflowEvent(
                FileWorkflowEventKind.IMPORT_STARTED,
                "library.import",
                focus_target="library-import-cancel",
            )
        )
        shutdown_before_start = False
        try:
            with self._lock:
                if generation != self._generation or self._worker is not worker:
                    raise RuntimeError("import worker ownership changed before start")
                if self._shutdown_requested:
                    self._clear_worker_locked()
                    shutdown_before_start = True
                else:
                    worker.start()
                    if self._worker is worker:
                        self._worker_started = True
        except BaseException:
            with self._lock:
                if generation == self._generation and self._worker is worker:
                    self._clear_worker_locked()
            return self._failed(
                "library.import",
                "import_worker_unavailable",
                focus_target=previous_focus,
            )
        if shutdown_before_start:
            return self._failed(
                "library.import", "file_workflow_closed", focus_target=previous_focus
            )
        return started

    def _cancel_import(self) -> FileWorkflowEvent:
        with self._lock:
            if self._worker_kind != "import":
                no_import_running = True
                pending = None
                cancel_event = None
            else:
                pending = self._terminal_pending
                if pending is not None and pending[0] == self._generation:
                    return pending[1]
                cancel_event = self._cancel_event
                no_import_running = self._worker is None or cancel_event is None
                if not no_import_running:
                    cancel_event.set()
        if no_import_running:
            return self._failed(
                "library.cancel_import",
                "no_import_running",
                focus_target="library-import-file",
            )
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
        book_source_format = ""
        retained_book_blocks = 0

        def cancelled() -> bool:
            return cancel_event.is_set()

        def progress(progress_value: LibraryImportProgress) -> None:
            nonlocal progress_started
            if type(progress_value) is not LibraryImportProgress:
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
                        source_format=book_source_format,
                        retained_book_blocks=retained_book_blocks,
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
            candidate_services = self._import_services_factory()
            if type(candidate_services) is not Version2ImportWorkerServices:
                raise TypeError(
                    "import_services_factory returned an invalid service bundle"
                )
            services = candidate_services
            if cancelled():
                raise LibraryImportCancelledError("Library import cancelled")

            if suffix == ".pgn" or suffix in BOOK_LIBRARY_SUFFIXES:
                opened = (
                    open_pgn(source_path)
                    if suffix == ".pgn"
                    else open_book_library_source(
                        source_path, cancel_check=cancelled
                    )
                )
                if cancelled():
                    raise LibraryImportCancelledError("Library import cancelled")
                if suffix in BOOK_LIBRARY_SUFFIXES:
                    book_source_format = suffix.lstrip(".")
                    retained_book_blocks = opened.retained_book_blocks
                if not opened.games:
                    self._emit_if_current(
                        generation,
                        FileWorkflowEvent(
                            FileWorkflowEventKind.IMPORT_EMPTY,
                            "library.import",
                            focus_target="library-import-file",
                            warning_count=(
                                0 if suffix == ".pgn" else len(opened.warnings)
                            ),
                            source_format=book_source_format,
                            retained_book_blocks=retained_book_blocks,
                        ),
                    )
                    return
                imported = services.library.import_games(
                    opened.games,
                    source_name=report_safe_name(opened.source.path),
                    source_format=(
                        "pgn" if suffix == ".pgn" else suffix.lstrip(".")
                    ),
                    source_sha256=opened.source.sha256,
                    source_warning_count=(
                        len(opened.global_warnings)
                        if suffix == ".pgn"
                        else len(opened.warnings)
                    ),
                    cancel_check=cancelled,
                    progress_callback=progress,
                )
                if type(imported) is not LibraryImportResult:
                    raise TypeError("canonical Library import result is invalid")
                game_count = imported.game_count
                warning_count = imported.warning_count
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
                            warning_count=int(
                                getattr(report, "warning_count", 0)
                            ),
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
                    source_format=book_source_format,
                    retained_book_blocks=retained_book_blocks,
                    warning_count=warning_count,
                ),
            )
        except (LibraryImportCancelledError, SourceReadCancelledError):
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_CANCELLED,
                    "library.import",
                    focus_target="library-import-file",
                ),
            )
        except BookLibrarySourceReadError:
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.import",
                    focus_target="library-import-file",
                    error_code="book_source_read_failed",
                ),
            )
        except PgnFileError:
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.import",
                    focus_target="library-import-file",
                    error_code=(
                        "pgn_import_failed"
                        if suffix == ".pgn"
                        else "book_source_read_failed"
                        if suffix in BOOK_LIBRARY_SUFFIXES
                        else "chessbase_import_failed"
                    ),
                ),
            )
        except BaseException:
            _LOG.warning("Version 2 Library import failed", exc_info=True)
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.import",
                    focus_target="library-import-file",
                    error_code=(
                        "chessbase_import_failed"
                        if suffix in {".cbh", ".cbv"}
                        else "library_import_failed"
                    ),
                ),
            )
        finally:
            if services is not None:
                try:
                    services.close()
                except BaseException:
                    # Cleanup is secondary to the already selected terminal and
                    # must never strand shared file-worker ownership.
                    _LOG.warning(
                        "Version 2 import worker cleanup failed", exc_info=True
                    )
            with self._lock:
                if (
                    generation == self._generation
                    and self._worker_kind == "import"
                ):
                    self._clear_worker_locked()

    def _emit_if_current(self, generation: int, event: FileWorkflowEvent) -> None:
        with self._lock:
            current = (
                generation == self._generation
                and self._worker_kind == "import"
                and not self._shutdown_requested
            )
            terminal = current and event.kind in self._IMPORT_TERMINAL_KINDS
            if terminal:
                self._terminal_pending = (generation, event)
                self._cancel_event = None
        if not current:
            return
        try:
            self._emit(event)
        finally:
            if terminal:
                with self._lock:
                    pending = self._terminal_pending
                    if (
                        pending is not None
                        and pending[0] == generation
                        and pending[1] is event
                    ):
                        self._terminal_pending = None

    def wait_for_import(self, timeout: float | None = None) -> bool:
        """Wait for the current import worker; useful for orderly shutdown/tests."""

        with self._lock:
            worker = self._worker if self._worker_kind == "import" else None
            worker_started = self._worker_started
        if worker is None:
            return True
        if not worker_started:
            return False
        worker.join(timeout)
        return not worker.is_alive()

    def wait_for_pgn_open(self, timeout: float | None = None) -> bool:
        """Wait only for PGN Open preparation; owner publication may still be queued."""

        with self._lock:
            worker = self._worker if self._worker_kind == "pgn_open" else None
            worker_started = self._worker_started
        if worker is None:
            return True
        if not worker_started:
            return False
        worker.join(timeout)
        return not worker.is_alive()

    def wait_for_pgn_save(self, timeout: float | None = None) -> bool:
        """Wait for background PGN save publication; owner commit may still be queued."""

        with self._lock:
            worker = self._worker if self._worker_kind == "pgn_save" else None
            worker_started = self._worker_started
        if worker is None:
            return True
        if not worker_started:
            return False
        worker.join(timeout)
        return not worker.is_alive()

    def shutdown(self, timeout: float | None = None) -> bool:
        """Cancel/join worker and make any queued PGN Open publication stale."""

        with self._lock:
            self._shutdown_requested = True
            worker = self._worker
            worker_started = self._worker_started
            worker_kind = self._worker_kind
            cancel_event = self._cancel_event
            if cancel_event is not None:
                cancel_event.set()
        if worker is None:
            return True
        if not worker_started:
            return False
        worker.join(timeout)
        stopped = not worker.is_alive()
        if stopped and worker_kind == "pgn_open":
            # The worker may already have queued an owner callback. Removing its
            # ownership here makes that callback terminally stale before the
            # runtime closes its UI pump.
            with self._lock:
                if self._worker is worker and self._worker_kind == "pgn_open":
                    self._clear_worker_locked()
        elif stopped and worker_kind == "pgn_save":
            # Publication may already be durable while its owner-thread commit
            # is still queued. Complete that exact pending transaction before
            # application state is torn down; the queued callback becomes stale.
            with self._lock:
                pending = self._pending_save_result
            if pending is not None:
                self._finish_pgn_save_on_owner(
                    *pending,
                    allow_shutdown_commit=True,
                )
            else:
                with self._lock:
                    if self._worker is worker and self._worker_kind == "pgn_save":
                        self._clear_worker_locked()
        return stopped


__all__ = [
    "FileWorkflowEvent",
    "FileWorkflowEventKind",
    "Version2ImportWorkerServices",
    "Version2WindowsFileActionDelegate",
    "Version2WindowsFileDialogs",
]
