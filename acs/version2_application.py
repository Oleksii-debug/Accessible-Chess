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
from .book_epub_import import import_epub_book, MAX_EPUB_SOURCE_BYTES
from .book_html_import import import_html_book, MAX_HTML_SOURCE_BYTES
from .book_text_import import import_text_book, BookTextFormat, MAX_TEXT_SOURCE_BYTES
from .book_library_game_lookup import AcsdbBookGameLookup
from .book_progress_store import (
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
)
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
            "book.previous_position",
            "book.next_position",
            "book.previous_game",
            "book.next_game",
            "book.bookmark.save",
            "book.bookmark.restore",
        }
    )
    _BOOK_BOARD_OPEN_COMMANDS = frozenset({"book.open_position", "book.open_game"})
    _BOOK_BOARD_ACTIVE_COMMANDS = frozenset(
        {
            "book.board_next_move",
            "book.board_previous_move",
            "book.board_enter_variation",
            "book.board_leave_variation",
            "book.board_analyze",
        }
    )

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
        # Backup rollback can discard the newest saved progress generation, so
        # production must bind an explicit owner-controlled confirmation. Tests
        # and non-Windows compositions fail closed by default.
        self.confirm_book_progress_recovery = lambda: False
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
        # Library/native domain actions can reach this seam without a shell route
        # action. Reject before publishing a new PGN session while modal focus is
        # owned elsewhere, matching AccessibleShellState.open_route().
        if self.shell.active_dialog_id is not None:
            raise ValueError("close the active dialog before replacing the PGN document")
        if self.book_workflow is not None and self.book_workflow.active:
            raise ValueError("return to the book before replacing the PGN document")
        if self.session is not None and self.session.dirty and not self.confirm_document_replace():
            raise ValueError("PGN replacement cancelled")
        projection = PgnWorkspaceWebViewProjection(session.workspace, self.router, language=self.shell.language)
        self.session, self.pgn = session, PgnWebViewBridge(projection)
        self.pgn_board_active = False
        self._focus = self.shell.open_route("pgn")

    def open_book(self, source: Path):
        self._assert_thread()
        # Domain/native Book Open can bypass shell route dispatch. Reject it
        # before any reader/progress mutation while a modal owns keyboard focus.
        if self.shell.active_dialog_id is not None:
            raise ValueError("close the active dialog before opening a book")
        if self.book_workflow is not None and self.book_workflow.active:
            raise ValueError("return to the book before opening another source")
        suffix = source.suffix.casefold()
        if suffix not in {".epub", ".html", ".htm", ".xhtml", ".txt", ".md", ".markdown"}:
            raise ValueError("unsupported book source")
        if suffix == ".epub":
            limit = MAX_EPUB_SOURCE_BYTES
        elif suffix in {".html", ".htm", ".xhtml"}:
            limit = MAX_HTML_SOURCE_BYTES
        else:
            limit = MAX_TEXT_SOURCE_BYTES
        with source.open("rb") as handle: raw = handle.read(limit + 1)
        if len(raw) > limit: raise ValueError("book source exceeds the supported limit")
        if suffix == ".epub":
            imported = import_epub_book(raw, source_name=report_safe_name(source))
        elif suffix in {".html", ".htm", ".xhtml"}:
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
        # Rendering is part of accepting an external Book source. Validate the
        # exact initial projection while every published application owner still
        # points at the previous Book. This matches bundled starter-content
        # staging and prevents a malformed/unrenderable import from creating new
        # durable progress for a Book the user never actually saw open.
        bridge.projection.snapshot()
        # Do not publish the staged reader/workflow/route until its initial
        # presentation and progress state are both accepted.
        self._persist_book_progress(imported.book_key, reader)
        self.reader, self.book_key, self.book_workflow, self.book_delegate, self.books = reader, imported.book_key, workflow, delegate, bridge
        self.training_workspace = self.training = None
        self._focus = self.shell.open_route("books")
        self._repair_book_block_focus_after_rebind()
        warning_count = len(imported.warnings)
        if warning_count:
            announcement = (
                f"Книгу відкрито з попередженнями імпорту: {warning_count}."
                if self.shell.language is UILanguage.UA
                else f"Book opened with import warnings: {warning_count}."
            )
            # Importer diagnostics remain trusted-host data. Publish only the
            # bounded count through the existing path-free status event.
            self._events.append(
                {"kind": "status", "payload": {"announcement": announcement}}
            )
        return warning_count

    def _persist_book_progress(self, book_key, reader):
        """Publish Book progress, offering only explicit bounded backup rollback."""

        try:
            return self.progress_store.save(book_key, reader)
        except BookProgressStoreError as error:
            if error.code != BookProgressStoreErrorCode.CORRUPT_STORE:
                raise
            # Validate the exact backup for this Book/document and retain its
            # byte revision. Confirmation may leave the store unlocked, but
            # recovery may publish only those same semantically validated bytes.
            try:
                backup_revision = self.progress_store.validated_backup_revision(
                    book_key,
                    reader.document,
                )
            except (BookProgressStoreError, LookupError, TypeError, ValueError):
                raise error
            # Recovery can lose the newest corrupt-primary generation, so user
            # consent remains mandatory even after the backup is proven usable.
            try:
                confirmed = self.confirm_book_progress_recovery()
            except Exception:
                confirmed = False
            if confirmed is not True:
                raise
            if not self.progress_store.recover_from_backup(
                expected_backup_revision=backup_revision,
            ):
                raise
            # Re-enter the canonical store write after recovery. This reloads
            # the recovered generation under normal interprocess/CAS locks.
            return self.progress_store.save(book_key, reader)

    def save_book_progress(self):
        self._assert_thread()
        if self.reader is not None:
            try:
                self._persist_book_progress(self.book_key, self.reader)
            except BookProgressStoreError as error:
                if error.code == BookProgressStoreErrorCode.DURABILITY_UNKNOWN:
                    self._reload_book_progress_after_durability_ambiguity()
                raise

    def _repair_book_block_focus_after_rebind(self):
        """Replace only a stale route-local Book block token after reader rebind.

        Stable controls such as the bookmark input keep their remembered focus.
        Block ids, however, encode the old reader index and can become invalid
        when canonical recovery accepts a different valid BookReader snapshot.
        """
        if self.reader is None or self.books is None:
            return
        if self.shell.current_route.route_id != "books":
            return
        remembered = self.shell.restore_focus_target()
        if type(remembered) is not str:
            return
        if remembered != "book-reader" and not remembered.startswith("book-block-"):
            return
        canonical = f"book-block-{self.reader.index}"
        if remembered == canonical:
            return
        self.shell.record_focus(canonical)
        self._focus = canonical

    def _reload_book_progress_after_durability_ambiguity(self):
        """Rebind Books/Training to the canonical primary after uncertain commit."""

        reader = self.reader
        books = self.books
        key = self.book_key
        workspace = self.training_workspace
        training_was_active = workspace is not None or self.training is not None
        training_language = None if workspace is None else workspace.language
        training_message = "" if workspace is None else workspace.presenter_message
        training_message_key = (
            None if workspace is None else workspace.presenter_message_key
        )
        book_board_was_active = (
            self.book_workflow is not None and self.book_workflow.active
        )
        if reader is not None and books is not None and key is not None:
            language = books.projection.language
            bookmark_name = books.projection.bookmark_name
            try:
                reloaded = self.progress_store.restore_primary(key, reader.document)
                self._restore_book_progress(
                    reloaded.snapshot(),
                    language=language,
                    bookmark_name=bookmark_name,
                    restore_training=training_was_active,
                    training_language=training_language,
                    training_message=training_message,
                    training_message_key=training_message_key,
                )
                # Book Board is transient state over the replaced reader/workflow
                # and is not represented by the durable BookReader snapshot.
                # Never leave keyboard/NVDA focus on a visible Board route whose
                # canonical owner was discarded by ambiguity recovery.
                if (
                    book_board_was_active
                    and self.shell.current_route.route_id == "board"
                ):
                    self._focus = self.shell.open_route("books")
                    self._events.append(
                        {"kind": "route", "payload": {"route_id": "books"}}
                    )
                # Canonical recovery may legitimately select a different Book
                # block than the one remembered by the previous reader. Repair
                # only index-bound block focus; persistent controls keep focus.
                self._repair_book_block_focus_after_rebind()
                return
            except Exception:
                pass

        # The primary publication cannot be re-read safely. Publishing either the
        # pre-write snapshot or the speculative in-memory state would split UI
        # authority from disk, so fail the Books/Training surfaces closed.
        self.reader = None
        self.book_key = None
        self.book_workflow = None
        self.book_delegate = None
        self.books = None
        self.training_workspace = None
        self.training = None
        current_route = self.shell.current_route.route_id
        if current_route in {"books", "training"} or (
            current_route == "board" and book_board_was_active
        ):
            self._focus = self.shell.open_route("library")
            self._events.append(
                {"kind": "route", "payload": {"route_id": "library"}}
            )

    def save_training_progress(self):
        self._assert_thread()
        if self.training_workspace is not None and self.training is not None:
            self.training_workspace.save()

    def _restore_book_progress(
        self,
        snapshot,
        *,
        language,
        bookmark_name,
        restore_training=False,
        training_language=None,
        training_message="",
        training_message_key=None,
    ):
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
        if restore_training and training_was_active:
            try:
                workspace = Version2BookTrainingWorkspace(
                    restored_reader,
                    progress_root=self.training_progress_root,
                    language=(
                        self.shell.language
                        if training_language is None
                        else training_language
                    ),
                )
                self.training = workspace.start_current(
                    message=training_message,
                    message_key=training_message_key,
                )
                self.training_workspace = workspace
            except Exception:
                # Secondary Training-state recovery failure must not mask the
                # primary transaction failure or leave a dead Training route.
                self.training_workspace = self.training = None
        # If that invalidated Training model cannot be restored, do not leave a
        # dead Training route published. Recover through canonical Books instead.
        if (
            training_was_active
            and self.shell.current_route.route_id == "training"
            and self.training_workspace is None
        ):
            self._focus = self.shell.open_route("books")
            self._repair_book_block_focus_after_rebind()
            # The packaged WebView consumes the application event queue on its
            # polling seam. A route event requests one authoritative snapshot
            # refresh; omit focus_target so the host chooses the real current
            # Book block DOM id instead of the shell-only ``book-reader`` token.
            self._events.append({"kind": "route", "payload": {"route_id": "books"}})

    def _start_training_from_current_book(self):
        self._assert_thread()
        # Book Board owns the exact reader origin until explicit Return.
        # Training must never retarget or wrap that reader behind the active Board.
        if self.book_workflow is not None and self.book_workflow.active:
            return False
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

    def _training_error_message(self) -> str:
        """Return one localized safe Training failure for browser/native ingress."""
        language = self.shell.language
        if (
            self.shell.current_route.route_id == "training"
            and self.training_workspace is not None
        ):
            language = self.training_workspace.language
        return concise_user_error("", language=language)

    def _dispatch_training_surface_command(self, command, payload=None):
        command_id = (
            command.strip()
            if type(command) is str and len(command) <= 64
            else command
        )
        classifiable_command = type(command_id) is str and len(command_id) <= 64
        is_continue = classifiable_command and command_id == "training.continue"
        if self.shell.current_route.route_id != "training":
            raise ValueError(self._training_error_message())
        if self.shell.active_dialog_id is not None:
            raise ValueError(self._training_error_message())
        if self.training_workspace is None or self.training is None:
            raise ValueError(self._training_error_message())
        before_reader = None
        language = bookmark_name = training_language = None
        training_message = ""
        training_message_key = None
        if is_continue:
            before_reader = self.reader.snapshot()
            language = self.books.projection.language
            bookmark_name = self.books.projection.bookmark_name
            training_language = self.training_workspace.language
            training_message = self.training_workspace.presenter_message
            training_message_key = self.training_workspace.presenter_message_key
        try:
            result = self.training_workspace.dispatch(command_id, payload)
        except Exception:
            if is_continue:
                # The strict Training bridge normally sanitizes callback/render
                # failures into an error event. If even that error projection
                # fails after continuation moved the canonical BookReader, keep
                # the transaction atomic before the outer application boundary
                # performs its own sanitization.
                rollback_required = True
                try:
                    rollback_required = self.reader.snapshot() != before_reader
                except Exception:
                    rollback_required = True
                if rollback_required:
                    self._restore_book_progress(
                        before_reader,
                        language=language,
                        bookmark_name=bookmark_name,
                        restore_training=True,
                        training_language=training_language,
                        training_message=training_message,
                        training_message_key=training_message_key,
                    )
            raise
        self.training = self.training_workspace.bridge
        if is_continue:
            if result.kind == "error":
                # The continuation callback can fail after moving the canonical
                # BookReader and swapping the Training model (for example while
                # rendering the next exercise). Keep the failed action atomic:
                # restore the completed origin only when reader mutation happened.
                rollback_required = True
                try:
                    rollback_required = self.reader.snapshot() != before_reader
                except Exception:
                    rollback_required = True
                if rollback_required:
                    self._restore_book_progress(
                        before_reader,
                        language=language,
                        bookmark_name=bookmark_name,
                        restore_training=True,
                        training_language=training_language,
                        training_message=training_message,
                        training_message_key=training_message_key,
                    )
                return result
            try:
                self.save_book_progress()
            except BookProgressStoreError as error:
                if error.code != BookProgressStoreErrorCode.DURABILITY_UNKNOWN:
                    self._restore_book_progress(
                        before_reader,
                        language=language,
                        bookmark_name=bookmark_name,
                        restore_training=True,
                        training_language=training_language,
                        training_message=training_message,
                        training_message_key=training_message_key,
                    )
                # DURABILITY_UNKNOWN already rebound to the canonical primary (or
                # failed Books/Training closed). Never overwrite that authority
                # with the pre-Continue snapshot.
                raise
            except Exception:
                self._restore_book_progress(
                    before_reader,
                    language=language,
                    bookmark_name=bookmark_name,
                    restore_training=True,
                    training_language=training_language,
                    training_message=training_message,
                    training_message_key=training_message_key,
                )
                raise
        return result

    def _dispatch_book_surface_command(self, command, payload=None):
        """Publish mutating Book commands only after durable progress succeeds."""
        command_id = (
            command.strip()
            if type(command) is str and len(command) <= 64
            else command
        )
        classifiable_command = type(command_id) is str and len(command_id) <= 64
        is_language = classifiable_command and command_id == "book.language"
        is_board_open = (
            classifiable_command and command_id in self._BOOK_BOARD_OPEN_COMMANDS
        )
        is_return_from_board = (
            classifiable_command and command_id == "book.return_from_board"
        )
        is_progress = (
            classifiable_command and command_id in self._BOOK_PROGRESS_COMMANDS
        )
        if self.books is None or self.reader is None:
            raise ValueError("no book is open")
        if is_language:
            # Language is presentation-only, but the Book-local WebView must still
            # own the visible route/focus before it may mutate projection state.
            if (
                self.shell.current_route.route_id != "books"
                or self.shell.active_dialog_id is not None
            ):
                return self.books.projection.generic_error()
            return self.books.dispatch(command_id, payload)
        if is_board_open:
            # Native menu actions are globally reachable even though Book Board
            # opening belongs to the visible Book Reader. Never open a hidden
            # Book position/game from Library, PGN, Settings, or another route.
            if self.shell.current_route.route_id != "books":
                return self.books.projection.generic_error()
            # A shell modal owns keyboard/focus authority over the Books route.
            # Do not publish progress or open Board underneath that modal.
            if self.shell.active_dialog_id is not None:
                return self.books.projection.generic_error()
            # Once Book Board owns an origin, only its explicit return path may
            # release that ownership; a second open must not replace it.
            if self.book_workflow is not None and self.book_workflow.active:
                return self.books.projection.generic_error()
            # The router delegate below is the one durability owner for
            # browser, native-menu and NVDA ingress. Do not pre-save here: the
            # Book WebView dispatches its open through that same delegate, and a
            # second write would advance BookProgress twice for one transition.
            return self.books.dispatch(command_id, payload)
        if is_return_from_board:
            # The canonical workflow unwinds through the shared router delegate,
            # which re-publishes the exact Book origin once after safe Return.
            # Keeping persistence in that one owner also makes browser/native
            # failure behavior identical.
            return self.books.dispatch(command_id, payload)
        if is_progress:
            # Native menu actions are globally reachable even though the keymap
            # correctly scopes these commands to BOOK_READER. Never mutate the
            # hidden reading cursor from Library/PGN/Settings or another route.
            if self.shell.current_route.route_id != "books":
                return self.books.projection.generic_error()
            # A shell modal owns keyboard/focus authority over the Books route.
            # Reject cursor/bookmark mutation before entering the Book surface.
            if self.shell.active_dialog_id is not None:
                return self.books.projection.generic_error()
            # Book Board owns the exact reading origin until its explicit return.
            # Ownership intentionally survives temporary route changes, so the
            # active workflow is a separate fence even when Books is visible.
            if self.book_workflow is not None and self.book_workflow.active:
                return self.books.projection.generic_error()
            before = self.reader.snapshot()
            language = self.books.projection.language
            bookmark_name = self.books.projection.bookmark_name
            result = self.books.dispatch(command_id, payload)
            if result.kind == "error":
                # Projection can fail after canonical reader/bookmark state moved.
                # Restore the exact pre-command state only when mutation occurred;
                # invalid payloads that failed before mutation keep reader identity.
                rollback_required = True
                try:
                    rollback_required = (
                        self.reader.snapshot() != before
                        or self.books.projection.language != language
                        or self.books.projection.bookmark_name != bookmark_name
                    )
                except Exception:
                    # Uninspectable post-error state is unsafe; fail closed through
                    # the existing exact snapshot restoration path.
                    rollback_required = True
                if rollback_required:
                    self._restore_book_progress(
                        before,
                        language=language,
                        bookmark_name=bookmark_name,
                    )
                return result
            try:
                self.save_book_progress()
            except BookProgressStoreError as error:
                if error.code != BookProgressStoreErrorCode.DURABILITY_UNKNOWN:
                    self._restore_book_progress(
                        before,
                        language=language,
                        bookmark_name=bookmark_name,
                    )
                # On ambiguous durability the save path already rebound to the
                # visible canonical primary. Do not restore speculative history.
                if self.books is None:
                    return self._error()
                return self.books.projection.generic_error()
            except Exception:
                self._restore_book_progress(
                    before,
                    language=language,
                    bookmark_name=bookmark_name,
                )
                return self.books.projection.generic_error()
            return result
        result = self.books.dispatch(command_id, payload)
        if result.kind != "error":
            self.save_book_progress()
        return result

    def _book_event(self, event):
        # Board-open/update success becomes authoritative only after the application
        # has projected the canonical BookBoard FEN into the real release board.
        if event.kind is BookBoardUiEventKind.RETURNED_TO_BOOK:
            # BookBoardWorkflow guarantees that read-only Board review and exact
            # Return preserve the BookReader snapshot. This observer owns only
            # route publication; the browser/native command boundary that caused
            # the explicit Return re-publishes the canonical origin durably after
            # the safe workflow unwind. Emergency projection-failure unwind stays
            # storage-independent in _recover_book_projection_failure().
            self._focus = self.shell.open_route("books")
            self._repair_book_block_focus_after_rebind()
            # Route ownership changed synchronously inside the domain workflow.
            # Publish one V2 refresh request even if the caller subsequently
            # reports a persistence error, so the visible/NVDA surface cannot
            # remain on a Board whose Book workflow has already unwound.
            self._events.append(
                {"kind": "route", "payload": {"route_id": "books"}}
            )
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
            self._focus = self.shell.open_route("books")
            self._repair_book_block_focus_after_rebind()
            self._events.append(
                {"kind": "route", "payload": {"route_id": "books"}}
            )

    def _delegate(self, action, payload):
        # Route-changing delegated PGN actions must respect modal focus before
        # they mutate Board projection or ownership flags. Otherwise open_route()
        # can reject the transition after domain state has already moved.
        if (
            action in {"pgn.open_on_board", "pgn.return"}
            and self.shell.active_dialog_id is not None
        ):
            raise ValueError("close the active dialog before changing PGN Board state")
        # Native menus enter the same projection commands as keyboard buttons.
        if action == "pgn.open_on_board":
            if payload: raise ValueError("PGN board accepts no payload")
            self._project_pgn_position()
            self.pgn_board_active = True
            self._focus = self.shell.open_route("board")
            return None
        if action == "pgn.return":
            if payload: raise ValueError("PGN return accepts no payload")
            self.pgn_board_active = False
            self._focus = self.shell.open_route("pgn")
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
            self._focus = self.shell.open_route("library")
            return self.library.projection.search(self.library.projection.query) if action.endswith("search") else self.library.projection.reset_filters()
        if action == "library.next_page": return self.library.projection.next_page()
        if action == "library.previous_page": return self.library.projection.previous_page()
        if action == "library.export" and not payload:
            return self.library.projection.request_export_selected()
        if action == "book.open":
            if payload:
                raise ValueError("book file selection belongs to the host")
            if self.shell.active_dialog_id is not None:
                raise ValueError("close the active dialog before opening a book")
            if self.book_workflow is not None and self.book_workflow.active:
                raise ValueError("return to the book before opening another source")
            source = self.open_book_dialog()
            return None if source is None else self.open_book(source)
        if action.startswith("book."):
            if self.book_delegate is None: raise ValueError("no book is open")
            if action in self.book_delegate.OWNED_ACTIONS:
                # Modal focus owns the application while open. Reject every Book
                # Board transition before workflow dispatch so open/navigation/
                # analysis/return cannot partially mutate state behind the dialog.
                if self.shell.active_dialog_id is not None:
                    raise ValueError("close the active dialog before changing Book Board state")
                opening_board = action in self._BOOK_BOARD_OPEN_COMMANDS
                if action in self._BOOK_BOARD_ACTIVE_COMMANDS:
                    # Book Board navigation/analysis is meaningful only while the
                    # canonical Board surface is visible. A workflow can remain
                    # active across temporary shell navigation; do not mutate
                    # that hidden Board from globally reachable native actions.
                    if self.shell.current_route.route_id != "board":
                        raise ValueError("book board command requires the visible Board")
                if opening_board:
                    # Native menus bypass the Book WebView bridge and enter this
                    # delegate directly. Apply the same visible-reader/ownership
                    # fences here before the canonical workflow can mutate.
                    if self.shell.current_route.route_id != "books":
                        raise ValueError("book board open requires the visible Book reader")
                    if self.book_workflow is not None and self.book_workflow.active:
                        raise ValueError("book board review is already active")
                # Native menu/NVDA activation reaches this delegate directly,
                # bypassing _dispatch_book_surface_command(). Apply the same
                # durability boundary as the Book WebView: the exact reading
                # origin must be accepted by BookProgress before Board ownership
                # can become active.
                if opening_board:
                    self.save_book_progress()
                before_view = self.book_delegate.view() if self.book_workflow.active else None
                result = self.book_delegate(action, payload)
                if result.kind is BookBoardUiEventKind.FAILED:
                    raise ValueError(
                        concise_user_error("", language=self.shell.language)
                    )
                if result.kind in {BookBoardUiEventKind.BOARD_OPENED, BookBoardUiEventKind.BOARD_UPDATED}:
                    try:
                        self._project_board_position(self.book_delegate.view().current_fen)
                    except Exception:
                        self._recover_book_projection_failure(before_view)
                        raise
                    self.pgn_board_active = False
                    self._focus = self.shell.open_route("board")
                    if result.kind is BookBoardUiEventKind.BOARD_OPENED:
                        # The repaint event and native application focus token
                        # must agree immediately. A second keyboard/menu action
                        # before WebView focusin must not write stale Book focus
                        # into the Board route's focus history.
                        self.shell.record_focus("board-launcher")
                        self._focus = "board-launcher"
                        self._events.append({"kind": "book-board", "payload": {"focus_target": "board-launcher"}})
                if result.kind is BookBoardUiEventKind.RETURNED_TO_BOOK:
                    # Returning already discarded only transient Board review and
                    # restored the exact BookReader origin. Re-publish that
                    # canonical origin through the same durability boundary as
                    # browser Return. If persistence fails, the safe return stays
                    # completed while the UI boundary projects only a sanitized
                    # error.
                    self.save_book_progress()
                return result
            command = {"book.previous_block": "book.previous", "book.next_block": "book.next", "book.bookmark": "book.bookmark.save"}.get(action, action)
            result = self._dispatch_book_surface_command(
                command,
                {"name": "default"} if action == "book.bookmark" else payload,
            )
            if result.kind == "error": raise ValueError("book command failed")
            return result
        if action.startswith("training."):
            if action == "training.reset":
                # Reset remains WebView-only because explicit confirmation belongs
                # to that dialog. Keep the native fail-closed response aligned with
                # the currently visible Training language instead of leaking a
                # hard-coded English implementation message to NVDA.
                raise ValueError(self._training_error_message()) from None
            command = "training.reveal" if action == "training.reveal_solution" else action
            result = self._dispatch_training_surface_command(command, payload)
            if result.kind == "error":
                # Preserve the already-sanitized Training-surface error. Replacing
                # it with a hard-coded English exception makes native/NVDA ingress
                # disagree with the visible Training language and browser ingress.
                message = result.payload.get("message")
                if not isinstance(message, str):
                    message = ""
                raise ValueError(message) from None
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
                    # Route changes are modal-blocked by the shell. Apply the same
                    # fence before Training preflight can move or wrap the reader.
                    if self.shell.active_dialog_id is not None:
                        raise ValueError("close the active dialog before opening Training")
                    if not self._start_training_from_current_book():
                        raise ValueError("Training exercise is unavailable")
                value = self.adapter.activate_action(command, current_focus_id=self._focus)
                if value.kind == "route":
                    # Router dispatch has already changed shell ownership.
                    # Synchronize before another keyboard/native action can
                    # reuse the previous route's focus token.
                    self._focus = self.shell.restore_focus_target()
                    self._repair_book_block_focus_after_rebind()
                projected = asdict(value)
                if value.kind == "route":
                    projected_payload = projected.get("payload")
                    if isinstance(projected_payload, dict):
                        projected_payload["focus_target"] = self._focus
                        projected_snapshot = projected_payload.get("snapshot")
                        if isinstance(projected_snapshot, dict):
                            projected_screen = projected_snapshot.get("screen")
                            if isinstance(projected_screen, dict):
                                projected_screen["focus_target"] = self._focus
                return projected
            if area == "training":
                try:
                    return asdict(self._dispatch_training_surface_command(command, payload))
                except Exception:
                    return {
                        "kind": "error",
                        "payload": {"message": self._training_error_message()},
                    }
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
        payload = getattr(value, "payload", {})
        training_route = (
            getattr(value, "kind", None) == "route"
            and hasattr(payload, "get")
            and payload.get("route_id") == "training"
        )
        if training_route:
            try:
                if not self._start_training_from_current_book():
                    raise ValueError("Training exercise is unavailable")
            except Exception:
                # Native-menu/keyboard routing has already changed the shell.
                # Recover to a coherent canonical owner instead of publishing a
                # dead Training surface. Active Book Board ownership wins.
                recovery_route = (
                    "board"
                    if self.book_workflow is not None and self.book_workflow.active
                    else "books"
                    if self.books is not None
                    else "board"
                )
                if self.shell.current_route.route_id == "training":
                    self._focus = self.shell.open_route(recovery_route)
                    if recovery_route == "books":
                        self._repair_book_block_focus_after_rebind()
                    self._events.append(
                        {"kind": "route", "payload": {"route_id": recovery_route}}
                    )
                self._events.append(self._error())
                return False
        if value.kind == "route":
            # Native menu/key routing changes the shell before the queued event
            # reaches this application boundary. Bind the application token to
            # the exact new route focus before another native action can arrive.
            self._focus = self.shell.restore_focus_target()
            self._repair_book_block_focus_after_rebind()
        event = asdict(value)
        if value.kind == "route":
            event_payload = event.get("payload")
            if isinstance(event_payload, dict):
                event_payload["focus_target"] = self._focus
                event_snapshot = event_payload.get("snapshot")
                if isinstance(event_snapshot, dict):
                    event_screen = event_snapshot.get("screen")
                    if isinstance(event_screen, dict):
                        event_screen["focus_target"] = self._focus
        if value.kind == "delegated" and self.books is not None:
            payload = event.get("payload")
            if isinstance(payload, dict):
                action_id = payload.get("action_id")
                announcement_key = {
                    "book.open_position": "opened",
                    "book.return": "returned",
                }.get(action_id)
                if announcement_key is not None:
                    # FullProductWebViewAdapter intentionally drops trusted domain
                    # DTOs at this browser boundary. Reattach only the bounded,
                    # already-localized Book transition result through the one
                    # existing V2 event queue after successful delegation.
                    payload["announcement"] = self.books.projection._result_announcement(
                        announcement_key
                    )
        self._events.append(event)
        return True

    def record_focus(self, token):
        self._assert_thread()
        if type(token) is not str:
            return
        if not token:
            return
        # AccessibleShellState owns the one canonical DOM focus-ID contract.
        # Validate there before publishing the token to native-menu ingress so
        # _focus can never diverge from the route-local shell memory.
        self.shell.record_focus(token)
        self._focus = token

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
