"""V2 application composition. All format and chess semantics stay in their owners.

Create and use this object on the native UI thread. Only the observer callbacks
accept worker-thread calls; their exact D07 DTOs never enter a browser payload.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict
from pathlib import Path
import threading

from .acsdb import AcsDatabase
from .book_board_workflow import BookBoardWorkflow
from .book_html_import import import_html_book, MAX_HTML_SOURCE_BYTES
from .book_text_import import import_text_book, BookTextFormat, MAX_TEXT_SOURCE_BYTES
from .book_library_game_lookup import AcsdbBookGameLookup
from .book_progress_store import BookProgressStore
from .bookreader import BookReader
from .engine_assisted_workflows import EngineAssistedWorkflowService
from .full_product_ui_shell import UILanguage, concise_user_error
from .library_export_service import LibraryExportService
from .library_export_workspace import build_library_export_webview
from .library_import_service import LibraryImportProgress, LibraryImportResult, LibraryImportService
from .library_webview_projection import LibraryImportPhase
from .pgn_document import PgnDocumentSession
from .pgn_workspace import PgnWorkspace
from .pgn_webview_bridge import PgnWebViewBridge
from .pgn_workspace_webview_adapter import PgnWorkspaceWebViewProjection
from .report_paths import report_safe_name
from .search_service import GameSearchQuery
from .version2_book_workspace import build_version2_book_webview
from .version2_pgn_commands import Version2PgnCommands
from .version2_profile import build_version2_shell, build_version2_router, build_version2_webview_adapter
from .version2_training_workspace import Version2BookTrainingWorkspace
from .version2_windows_book_board_adapter import Version2WindowsBookBoardActionDelegate, BookBoardUiEventKind
from .version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind, Version2ImportWorkerServices
from .version2_windows_library_import_observer import Version2ObservedImportServicesFactory


class Version2Application:
    # Some canonical shutdown/recovery tests deliberately construct a minimal
    # application via __new__ instead of __init__. Keep optional Training state
    # absent-safe on those valid pre-Training construction paths.
    training_workspace = None
    training = None

    _BOOK_PROGRESS_COMMANDS = frozenset(
        {
            "book.previous",
            "book.next",
            "book.previous_heading",
            "book.next_heading",
            "book.next_position",
            "book.next_game",
            "book.bookmark.save",
            "book.bookmark.restore",
        }
    )
    _BOOK_BOARD_OPEN_COMMANDS = frozenset({"book.open_position", "book.open_game"})

    def __init__(self, database: AcsDatabase, *, progress_store: BookProgressStore,
                 engine_assistance: EngineAssistedWorkflowService, board_dispatch,
                 board_position_projector=None, copy_text=lambda _: None,
                 language=UILanguage.UA):
        self._thread = threading.get_ident()
        self.database = database
        self.progress_store = progress_store
        self.training_progress_root = progress_store.path.parent / "training-progress"
        self.engine_assistance = engine_assistance
        self._board_dispatch = board_dispatch
        if board_position_projector is not None and not callable(board_position_projector):
            raise TypeError("board_position_projector must be callable or None")
        self._board_position_projector = board_position_projector
        self._events = deque(maxlen=64)
        self._observation_lock = threading.Lock()
        self._progress = self._result = None
        self._files = None
        self._focus = ""
        self.session = None
        self.pgn_board_active = False
        self.pgn = None
        self.reader = self.book_key = self.book_workflow = self.book_delegate = self.books = None
        self.training_workspace = self.training = None
        self.shell = build_version2_shell(language=language)
        self.router = build_version2_router(self.shell, self._delegate)
        self.adapter = build_version2_webview_adapter(self.shell, self.router)
        self.pgn_commands = Version2PgnCommands(lambda: self.session, copy_text=copy_text)
        self.library_export = LibraryExportService(database)
        self.library = build_library_export_webview(database, self.router.dispatch, language=language)
        self.library.projection.search(GameSearchQuery())
        self.confirm_document_replace = lambda: not (self.session and self.session.dirty)
        self.open_book_dialog = lambda: None

    def _assert_thread(self):
        if threading.get_ident() != self._thread:
            raise RuntimeError("V2 application requires the native UI thread")

    def bind_files(self, runtime):
        self._assert_thread()
        self._files = runtime

    def observe_progress(self, value: LibraryImportProgress):
        if not isinstance(value, LibraryImportProgress): raise TypeError("invalid import progress")
        with self._observation_lock: self._progress = value

    def observe_result(self, value: LibraryImportResult):
        if not isinstance(value, LibraryImportResult): raise TypeError("invalid import result")
        with self._observation_lock: self._result = value

    def worker_factory(self, database_path, *, chessbase_factory=None):
        def create():
            database = AcsDatabase(database_path)
            try:
                chessbase = chessbase_factory(database) if chessbase_factory else None
                return Version2ImportWorkerServices(LibraryImportService(database), chessbase, database.close)
            except Exception:
                database.close()
                raise
        return Version2ObservedImportServicesFactory(create, progress_sink=self.observe_progress, result_sink=self.observe_result)

    def set_document(self, session):
        self._assert_thread()
        if not isinstance(session, PgnDocumentSession): raise TypeError("invalid PGN document")
        if self.book_workflow is not None and self.book_workflow.active:
            raise ValueError("return to the book before replacing the PGN document")
        if self.session is not None and self.session.dirty and not self.confirm_document_replace():
            raise ValueError("PGN replacement cancelled")
        projection = PgnWorkspaceWebViewProjection(session.workspace, self.router, language=self.shell.language)
        self.session, self.pgn = session, PgnWebViewBridge(projection)
        self.pgn_board_active = False
        self.shell.open_route("pgn")

    def open_book(self, source: Path):
        self._assert_thread()
        if self.book_workflow is not None and self.book_workflow.active:
            raise ValueError("return to the book before opening another source")
        suffix = source.suffix.casefold()
        if suffix not in {".html", ".htm", ".xhtml", ".txt", ".md", ".markdown"}:
            raise ValueError("unsupported book source")
        limit = MAX_HTML_SOURCE_BYTES if suffix in {".html", ".htm", ".xhtml"} else MAX_TEXT_SOURCE_BYTES
        with source.open("rb") as handle: raw = handle.read(limit + 1)
        if len(raw) > limit: raise ValueError("book source exceeds the supported limit")
        if suffix in {".html", ".htm", ".xhtml"}:
            imported = import_html_book(raw, source_name=report_safe_name(source), available_assets=())
        else:
            kind = BookTextFormat.TXT if suffix == ".txt" else BookTextFormat.MARKDOWN
            imported = import_text_book(raw, source_name=report_safe_name(source), source_format=kind)
        # Persist the old durable state before staging a replacement.
        self.save_training_progress()
        self.save_book_progress()
        reader = self.progress_store.restore(imported.book_key, imported.document) if self.progress_store.has(imported.book_key) else BookReader(imported.document)
        workflow = BookBoardWorkflow(reader, self.engine_assistance, game_lookup=AcsdbBookGameLookup(self.database))
        delegate = Version2WindowsBookBoardActionDelegate(workflow, event_sink=self._book_event, next_delegate=self._board_dispatch)
        bridge = build_version2_book_webview(reader, workflow, self.router.dispatch, language=self.shell.language)
        # Do not publish the staged reader/workflow/route until its initial
        # progress state is durably accepted by the canonical progress store.
        self.progress_store.save(imported.book_key, reader)
        self.reader, self.book_key, self.book_workflow, self.book_delegate, self.books = reader, imported.book_key, workflow, delegate, bridge
        self.training_workspace = self.training = None
        self.shell.open_route("books")
        return len(imported.warnings)

    def save_book_progress(self):
        self._assert_thread()
        if self.reader is not None: self.progress_store.save(self.book_key, self.reader)

    def save_training_progress(self):
        self._assert_thread()
        if self.training_workspace is not None and self.training is not None:
            self.training_workspace.save()

    def _restore_book_progress(self, snapshot, *, language, bookmark_name):
        """Restore a failed Book progress transaction without partial UI state."""
        training_was_active = self.training_workspace is not None or self.training is not None
        restored_reader = BookReader.restore_snapshot(self.reader.document, snapshot)
        restored_workflow = BookBoardWorkflow(
            restored_reader,
            self.engine_assistance,
            game_lookup=AcsdbBookGameLookup(self.database),
        )
        restored_delegate = Version2WindowsBookBoardActionDelegate(
            restored_workflow,
            event_sink=self._book_event,
            next_delegate=self._board_dispatch,
        )
        restored_books = build_version2_book_webview(
            restored_reader,
            restored_workflow,
            self.router.dispatch,
            language=language,
        )
        restored_books.projection.restore_bookmark_name(bookmark_name)
        self.reader = restored_reader
        self.book_workflow = restored_workflow
        self.book_delegate = restored_delegate
        self.books = restored_books
        # Training is transient UI over a specific reader object. Once rollback
        # replaces that reader, discard any bridge that would otherwise reference
        # the rejected post-mutation state.
        self.training_workspace = self.training = None
        # If that invalidated Training model was the active shell surface, do not
        # leave a dead Training route published. Recover through the canonical
        # Books route/focus contract; unrelated active routes remain untouched.
        if training_was_active and self.shell.current_route.route_id == "training":
            self._focus = self.shell.open_route("books")
            # The packaged WebView consumes the application event queue on its
            # polling seam. A route event requests one authoritative snapshot
            # refresh; omit focus_target so the host chooses the real current
            # Book block DOM id instead of the shell-only ``book-reader`` token.
            self._events.append({"kind": "route", "payload": {"route_id": "books"}})

    def _start_training_from_current_book(self):
        self._assert_thread()
        if self.reader is None or self.reader.location().kind != "Exercise":
            return False
        workspace = self.training_workspace
        if workspace is None or workspace.reader is not self.reader:
            workspace = Version2BookTrainingWorkspace(
                self.reader,
                progress_root=self.training_progress_root,
                language=self.shell.language,
            )
        bridge = workspace.start_current()
        self.training_workspace, self.training = workspace, bridge
        return True

    def _dispatch_book_surface_command(self, command, payload=None):
        """Publish mutating Book commands only after durable progress succeeds."""
        if self.books is None or self.reader is None:
            raise ValueError("no book is open")
        if command == "book.language":
            # Language is presentation state, not durable reader progress.
            return self.books.dispatch(command, payload)
        if command in self._BOOK_BOARD_OPEN_COMMANDS:
            # The canonical BookBoard delegate owns board-opening publication.
            return self.books.dispatch(command, payload)
        if command in self._BOOK_PROGRESS_COMMANDS:
            before = self.reader.snapshot()
            language = self.books.projection.language
            bookmark_name = self.books.projection.bookmark_name
            result = self.books.dispatch(command, payload)
            if result.kind == "error":
                return result
            try:
                self.save_book_progress()
            except Exception:
                self._restore_book_progress(
                    before,
                    language=language,
                    bookmark_name=bookmark_name,
                )
                return self.books.projection.generic_error()
            return result
        result = self.books.dispatch(command, payload)
        if result.kind != "error":
            self.save_book_progress()
        return result

    def _book_event(self, event):
        # Board-open/update success becomes authoritative only after the application
        # has projected the canonical BookBoard FEN into the real release board.
        if event.kind is BookBoardUiEventKind.RETURNED_TO_BOOK:
            self.shell.open_route("books")
            self.save_book_progress()
        elif event.kind is BookBoardUiEventKind.FAILED:
            self._events.append(self._error())

    def _error(self):
        return {"kind": "error", "payload": {"message": concise_user_error("", language=self.shell.language)}}

    def _project_board_position(self, position):
        projector = self._board_position_projector
        if projector is None:
            raise RuntimeError("release board position projector is unavailable")
        if not isinstance(position, str) or not position.strip():
            raise RuntimeError("canonical board position is unavailable")
        result = projector(position)
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise RuntimeError("release board rejected canonical position")
        return position

    def _project_pgn_position(self, fen=None):
        position = self.pgn_commands.current_fen() if fen is None else fen
        return self._project_board_position(position)

    def _recover_book_projection_failure(self, before_view):
        # Navigation has already committed inside the canonical BookBoardWorkflow.
        # Roll it back through that owner's immutable cursor API; if the release
        # board cannot even restore the previous position, leave Board review
        # entirely through the canonical exact-return path instead of diverging.
        if before_view is not None and before_view.cursor is not None:
            try:
                self.book_workflow.go_to_cursor(before_view.cursor)
                self._project_board_position(before_view.current_fen)
                return
            except Exception:
                pass
        if self.book_workflow is not None and self.book_workflow.active:
            try:
                self.book_workflow.return_to_book()
            except Exception:
                return
            self.shell.open_route("books")
            self.save_book_progress()

    def _delegate(self, action, payload):
        # Native menus enter the same projection commands as keyboard buttons.
        if action == "pgn.open_on_board":
            if payload: raise ValueError("PGN board accepts no payload")
            self._project_pgn_position()
            self.pgn_board_active = True
            self.shell.open_route("board")
            return None
        if action == "pgn.return":
            if payload: raise ValueError("PGN return accepts no payload")
            self.pgn_board_active = False
            self.shell.open_route("pgn")
            return None
        if action in {"pgn.board_next_move", "pgn.board_previous_move", "pgn.board_enter_variation", "pgn.board_leave_variation"}:
            if payload or not self.pgn_board_active: raise ValueError("no PGN board review")
            workspace = self.session.workspace
            before = workspace.cursor
            before_fen = self.pgn_commands.current_fen()
            try:
                method = {"pgn.board_next_move": workspace.next_move, "pgn.board_previous_move": workspace.previous_move,
                          "pgn.board_enter_variation": workspace.enter_variation, "pgn.board_leave_variation": workspace.leave_variation}[action]
                method()
                self._project_pgn_position()
            except Exception:
                workspace.set_cursor(before)
                try:
                    self._project_pgn_position(before_fen)
                except Exception:
                    pass
                raise
            return None
        if action.startswith("pgn.") and action not in {"pgn.open", "pgn.save", "pgn.save_as", "pgn.export_selection"}:
            if not payload and self.pgn is not None and action == "pgn.copy_selection":
                return self.pgn.dispatch(action)
            return self.pgn_commands(action, payload)
        if action == "pgn.export_selection" and not payload and self.pgn is not None:
            return self.pgn.dispatch(action)
        if action == "library.open_game":
            if not payload: return self.library.projection.open_selected()
            if set(payload) != {"game_id", "source_id", "source_index"}: raise ValueError("invalid Library game request")
            row = self.database.get_game(payload["game_id"])
            if row is None or (row["source_id"], row["source_index"]) != (payload["source_id"], payload["source_index"]):
                raise ValueError("Library selection is stale")
            game = AcsdbBookGameLookup(self.database).load_book_game(payload["game_id"])
            # Opening a detached Library record must not renumber/write its source.
            game.source_index = 0
            self.set_document(PgnDocumentSession(PgnWorkspace((game,))))
            return None
        if action in {"library.search", "library.reset_filters"}:
            self.shell.open_route("library")
            return self.library.projection.search(self.library.projection.query) if action.endswith("search") else self.library.projection.reset_filters()
        if action == "library.next_page": return self.library.projection.next_page()
        if action == "library.previous_page": return self.library.projection.previous_page()
        if action == "library.export" and not payload:
            return self.library.projection.request_export_selected()
        if action == "book.open":
            if payload: raise ValueError("book file selection belongs to the host")
            source = self.open_book_dialog()
            return None if source is None else self.open_book(source)
        if action.startswith("book."):
            if self.book_delegate is None: raise ValueError("no book is open")
            if action in self.book_delegate.OWNED_ACTIONS:
                before_view = self.book_delegate.view() if self.book_workflow.active else None
                opening_board = action in self._BOOK_BOARD_OPEN_COMMANDS
                before_reader = self.reader.snapshot() if opening_board else None
                before_language = self.books.projection.language if opening_board else None
                before_bookmark = self.books.projection.bookmark_name if opening_board else None
                result = self.book_delegate(action, payload)
                if result.kind in {BookBoardUiEventKind.BOARD_OPENED, BookBoardUiEventKind.BOARD_UPDATED}:
                    if result.kind is BookBoardUiEventKind.BOARD_OPENED and opening_board:
                        try:
                            self.save_book_progress()
                        except Exception:
                            self._restore_book_progress(
                                before_reader,
                                language=before_language,
                                bookmark_name=before_bookmark,
                            )
                            raise
                    try:
                        self._project_board_position(self.book_delegate.view().current_fen)
                    except Exception:
                        self._recover_book_projection_failure(before_view)
                        raise
                    self.pgn_board_active = False
                    self.shell.open_route("board")
                    if result.kind is BookBoardUiEventKind.BOARD_OPENED:
                        self._events.append({"kind": "book-board", "payload": {"focus_target": "board-launcher"}})
                return result
            command = {"book.previous_block": "book.previous", "book.next_block": "book.next", "book.bookmark": "book.bookmark.save"}.get(action, action)
            result = self._dispatch_book_surface_command(
                command,
                {"name": "default"} if action == "book.bookmark" else payload,
            )
            if result.kind == "error": raise ValueError("book command failed")
            return result
        if action.startswith("training."):
            if self.training_workspace is None or self.training is None:
                raise ValueError("no Training exercise is active")
            if action == "training.reset":
                raise ValueError("Training reset requires explicit WebView confirmation")
            command = "training.reveal" if action == "training.reveal_solution" else action
            result = self.training_workspace.dispatch(command, payload)
            if result.kind == "error": raise ValueError("Training command failed")
            if command == "training.continue": self.save_book_progress()
            self.training = self.training_workspace.bridge
            return result
        if self._files is not None and action in {"pgn.open", "pgn.save", "pgn.save_as", "pgn.export_selection", "library.import", "library.cancel_import", "library.export"}:
            result = self._files(action, payload)
            if isinstance(result, FileWorkflowEvent):
                ui = self.library.projection.import_projection
                if result.kind is FileWorkflowEventKind.IMPORT_STARTED:
                    self._events.append(asdict(ui.prepare()))
                elif result.kind is FileWorkflowEventKind.IMPORT_CANCELLING:
                    self._events.append(asdict(ui.host_cancelling()))
                else:
                    self._file_event(result)
            return result
        return self._board_dispatch(action, payload)

    def browser_command(self, area, command, payload=None):
        self._assert_thread()
        try:
            if area == "review":
                allowed = {"pgn.open_on_board", "pgn.return", "pgn.board_next_move", "pgn.board_previous_move", "pgn.board_enter_variation", "pgn.board_leave_variation",
                           "book.board_next_move", "book.board_previous_move", "book.board_enter_variation", "book.board_leave_variation", "book.return"}
                if command not in allowed or payload: raise ValueError("invalid review command")
                result = self.router.dispatch(command).value
                if getattr(result, "kind", None) is BookBoardUiEventKind.FAILED: return self._error()
                return {"kind": "review", "payload": {}}
            if area == "shell":
                if payload: raise ValueError("shell accepts no authority payload")
                if type(command) is not str or not (command.startswith("screen.") or command in {"pgn.open", "pgn.save", "pgn.save_as", "book.open"}):
                    raise ValueError("unsupported shell command")
                if command == "screen.training":
                    self._start_training_from_current_book()
                value = self.adapter.activate_action(command, current_focus_id=self._focus)
                return asdict(value)
            if area == "training":
                if self.training_workspace is None or self.training is None:
                    raise ValueError("Training exercise is unavailable")
                value = self.training_workspace.dispatch(command, payload)
                self.training = self.training_workspace.bridge
                if command == "training.continue" and value.kind != "error": self.save_book_progress()
                return asdict(value)
            if area == "books":
                value = self._dispatch_book_surface_command(command, payload)
                return asdict(value)
            bridge = {"pgn": self.pgn, "library": self.library}.get(area)
            if bridge is None: raise ValueError("surface is unavailable")
            value = bridge.dispatch(command, payload)
            return asdict(value)
        except Exception:
            return self._error()

    def snapshot(self):
        self._assert_thread()
        return {
            **self.adapter.snapshot(),
            "pgn": None if self.pgn is None else self.pgn.projection.snapshot(),
            "library": self.library.projection.snapshot(),
            "books": None if self.books is None else self.books.projection.snapshot(),
            "training": None if self.training_workspace is None else self.training_workspace.snapshot(),
            "book_board_active": self.book_workflow is not None and self.book_workflow.active,
            "pgn_board_active": self.pgn_board_active,
            "document_dirty": bool(self.session and self.session.dirty),
        }

    def drain_events(self):
        self._assert_thread()
        events = tuple(self._events)
        self._events.clear()
        return events

    def native_command(self, value):
        self._assert_thread()
        if getattr(value, "action_id", None) == "screen.training":
            try:
                self._start_training_from_current_book()
            except Exception:
                self._events.append(self._error())
        self._events.append(asdict(value))

    def record_focus(self, token):
        self._assert_thread()
        if type(token) is str and len(token) <= 160 and all(c.isalnum() or c in "-_" for c in token):
            self._focus = token
            self.shell.record_focus(token)

    def import_ui_ready(self, mailbox):
        self._assert_thread()
        ui = self.library.projection.import_projection
        active = {LibraryImportPhase.RUNNING, LibraryImportPhase.CANCELLING}
        events = mailbox.drain()
        with self._observation_lock:
            progress, result = self._progress, self._result
            self._progress = self._result = None
        for event in events:
            if event.action_id not in {"library.import", "library.cancel_import"}:
                self._file_event(event)
                continue
            rendered = None
            if event.kind is FileWorkflowEventKind.IMPORT_STARTED:
                if ui.phase not in active: rendered = ui.prepare()
                if event.total_games and ui.snapshot()["total_games"] == 0: ui.begin(event.total_games)
            elif event.kind is FileWorkflowEventKind.IMPORT_CANCELLING and ui.phase in active:
                rendered = ui.host_cancelling()
            elif event.kind is FileWorkflowEventKind.IMPORT_EMPTY:
                rendered = ui.empty()
            elif event.kind is FileWorkflowEventKind.IMPORT_CANCELLED and ui.phase in active:
                rendered = ui.cancelled()
            elif event.kind is FileWorkflowEventKind.FAILED:
                if ui.phase not in active: ui.prepare()
                rendered = ui.fail("")
            if rendered: self._events.append(asdict(rendered))
        if progress is not None and ui.phase in active:
            if ui.snapshot()["total_games"] == 0: ui.begin(progress.total_games)
            self._events.append(asdict(ui.progress(progress)))
        if result is not None and ui.phase in active:
            if ui.snapshot()["total_games"] == 0: ui.begin(result.game_count)
            self._events.append(asdict(ui.complete(result)))
            # Update rows without moving focus from another surface.
            self.library.projection.search(self.library.projection.query)

    def _file_event(self, event):
        failed = getattr(event.kind, "value", "") == "failed"
        if failed:
            self._events.append(self._error())
            return
        kind = getattr(event.kind, "value", "")
        messages = {
            "pgn_opened": ("PGN відкрито.", "PGN opened."),
            "pgn_saved": ("PGN збережено.", "PGN saved."),
            "pgn_saved_as": ("PGN збережено.", "PGN saved."),
            "exported": ("Експорт завершено.", "Export completed."),
            "dialog_cancelled": ("Скасовано.", "Cancelled."),
        }
        message = messages.get(kind)
        if message: self._events.append({"kind": "status", "payload": {"announcement": message[self.shell.language is UILanguage.EN]}})

    def shutdown(self, timeout: float | None = None):
        """Cancel and join native import work before closing shared application state.

        ``None`` deliberately waits for the canonical import worker to honour its
        cancellation contract.  The worker is non-daemon because abandoning an
        in-flight SQLite/import transaction on process exit is not an acceptable
        release behaviour.  Tests and recovery callers may supply a bounded
        timeout and retry without closing the database when the worker is still
        alive. Once worker shutdown succeeds, ACSDB cleanup is attempted even if
        durable Book progress publication fails, without letting a later close
        failure replace that first progress failure.
        """
        self._assert_thread()
        if self._files is not None and not self._files.shutdown(timeout=timeout):
            return False
        self.save_training_progress()
        try:
            self.save_book_progress()
        except BaseException as progress_error:
            progress_traceback = progress_error.__traceback__
            try:
                self.database.close()
            except BaseException:
                pass
            raise progress_error.with_traceback(progress_traceback)
        self.database.close()
        return True
