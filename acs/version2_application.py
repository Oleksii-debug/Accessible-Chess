"""V2 application composition. All format and chess semantics stay in their owners.

Create and use this object on the native UI thread. Only the observer callbacks
accept worker-thread calls; their exact D07 DTOs never enter a browser payload.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
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
    _book_key as _validate_book_progress_key,
)
from .bookdocument import BookDocument, MAX_BOOK_DOCUMENT_WARNINGS
from .bookreader import BookReader
from .engine_assisted_workflows import EngineAssistedWorkflowService
from .full_product_ui_shell import UILanguage, concise_user_error
from .input_limits import MAX_FEN_CHARS
from .import_contract import SourceReadCancelledError, read_source_snapshot
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
from .version2_windows_book_open_worker import (
    BookOpenWorkerEvent,
    BookOpenWorkerEventKind,
    Version2BookOpenWorker,
)
from .version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind, Version2ImportWorkerServices
from .version2_windows_library_import_observer import Version2ObservedImportServicesFactory


class _BookBrowserLeaseRejected(ValueError):
    """Rendered Books presentation no longer owns canonical Book intent."""


class BookOpenCancelled(RuntimeError):
    """Trusted Book Open preparation was cancelled before UI publication."""


@dataclass(frozen=True, slots=True)
class PreparedBookOpen:
    """Immutable semantic result prepared without touching application UI state."""

    book_key: str
    document: BookDocument
    warnings: tuple[str, ...]


class Version2Application:
    # Some canonical shutdown/recovery paths deliberately construct a minimal
    # application via __new__ instead of __init__. Keep optional native owners and
    # Training state absent-safe on those valid pre-composition construction paths.
    training_workspace = None
    training = None
    _files = None
    _book_open_worker = None
    _pending_shell_publication = None
    _pgn_browser_lease_required = False
    _book_browser_lease_required = False
    _book_browser_dispatch_token = None

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
    _BOOK_BOARD_RETURN_COMMANDS = frozenset({"book.return", "book.return_from_board"})
    _BOOK_BOARD_RETURN_ROUTES = frozenset({"board", "books", "library"})
    _BOOK_BOARD_ACTIVE_COMMANDS = frozenset(
        {
            "book.board_next_move",
            "book.board_previous_move",
            "book.board_enter_variation",
            "book.board_leave_variation",
            "book.board_analyze",
        }
    )
    _PGN_BOARD_RETURN_ROUTES = frozenset({"board", "pgn"})
    _PGN_BOARD_ACTIVE_COMMANDS = frozenset(
        {
            "pgn.board_next_move",
            "pgn.board_previous_move",
            "pgn.board_enter_variation",
            "pgn.board_leave_variation",
        }
    )
    _BOOK_PROGRESS_RELOAD_CODES = frozenset(
        {
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
            BookProgressStoreErrorCode.STALE_WRITE,
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
        self._book_open_worker: Version2BookOpenWorker | None = None
        self._focus = ""
        self._shell_publication_sequence = 0
        self._pending_shell_publication = None
        self._last_shell_publication_resolution = None
        self.session = None
        self.pgn_board_active = False
        self.pgn = None
        self._pgn_browser_lease_required = False
        self._book_browser_lease_required = False
        self._book_browser_dispatch_token = None
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

    @staticmethod
    def _shell_publication_token(payload):
        """Validate one browser presentation acknowledgement token."""
        if type(payload) is not dict or len(payload) != 1:
            raise ValueError("invalid shell publication acknowledgement")
        key = next(iter(payload))
        if type(key) is not str or key != "token":
            raise ValueError("invalid shell publication acknowledgement")
        token = payload[key]
        if type(token) is not int or token <= 0 or token > 9007199254740991:
            raise ValueError("invalid shell publication acknowledgement")
        return token

    @staticmethod
    def _passive_browser_payload_keys(payload):
        """Return exact text keys without executing caller-controlled key hooks."""
        if type(payload) is not dict:
            return None
        keys = tuple(payload)
        if any(type(key) is not str for key in keys):
            raise ValueError("browser payload keys must be exact text")
        return keys

    def _finish_shell_publication(self, token: int, *, commit: bool):
        """Commit or roll back one browser route only after DOM publication."""
        pending = self._pending_shell_publication
        if pending is None:
            last = self._last_shell_publication_resolution
            if (
                last is not None
                and last[0] == token
                and last[1] is commit
            ):
                if commit:
                    return {
                        "kind": "presentation-commit",
                        "payload": {"token": token},
                    }
                return {
                    "kind": "presentation-rollback",
                    "payload": {
                        "token": token,
                        "route_id": last[2],
                        "focus_target": last[3],
                    },
                }
            raise ValueError("stale shell publication acknowledgement")
        if pending[0] != token:
            raise ValueError("stale shell publication acknowledgement")
        if commit:
            # Retain the pending token until the shell has actually released its
            # publication hold. If that boundary aborts, the exact same
            # acknowledgement remains retryable instead of leaving a stuck hold
            # with no recovery token.
            self.shell._end_publication_hold()
            self._pending_shell_publication = None
            self._last_shell_publication_resolution = (token, True, "", "")
            return {
                "kind": "presentation-commit",
                "payload": {"token": token},
            }

        (
            _token,
            _route_command,
            _request_id,
            _projected_route,
            shell_state,
            prior_focus,
            prior_training_workspace,
            prior_training,
        ) = pending
        # Rollback is a transaction too: do not consume its authority until the
        # exact shell/application checkpoint and publication hold are restored.
        self.shell._restore_presentation_state(shell_state)
        self._focus = prior_focus
        self.training_workspace = prior_training_workspace
        self.training = prior_training
        self.shell._end_publication_hold()
        self._pending_shell_publication = None
        rollback_route = self.shell.current_route.route_id
        rollback_focus = self._focus
        self._last_shell_publication_resolution = (
            token,
            False,
            rollback_route,
            rollback_focus,
        )
        return {
            "kind": "presentation-rollback",
            "payload": {
                "token": token,
                "route_id": rollback_route,
                "focus_target": rollback_focus,
            },
        }

    @staticmethod
    def _valid_book_browser_token(value):
        if type(value) is not str or len(value) != 64:
            return False
        return all(character in "0123456789abcdef" for character in value)

    def _book_presentation_token(self):
        """Bind browser intent to one exact Book owner and presentation state."""

        if self.reader is None or self.books is None:
            raise ValueError("no Book presentation is available")
        if (
            type(self.book_key) is not str
            or not self.book_key
            or len(self.book_key) > 4096
            or "\x00" in self.book_key
        ):
            raise ValueError("Book presentation identity is invalid")
        language = self.books.projection.language
        bookmark_name = self.books.projection.bookmark_name
        if not isinstance(language, UILanguage) or type(bookmark_name) is not str:
            raise ValueError("Book presentation state is invalid")
        material = {
            "schema": 1,
            "book_key": self.book_key,
            # Object identities make same-key owner replacement stale while the
            # digest keeps raw process addresses outside the browser contract.
            "reader_owner": id(self.reader),
            "bridge_owner": id(self.books),
            "language": language.value,
            "bookmark_name": bookmark_name,
            "reader": self.reader.snapshot(),
        }
        encoded = json.dumps(
            material,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _lease_book_snapshot(self, snapshot):
        if type(snapshot) is not dict:
            raise TypeError("Book browser snapshot must be a built-in mapping")
        leased = dict(snapshot)
        leased["presentation_token"] = self._book_presentation_token()
        # Merely producing a host snapshot does not prove that the current JS
        # surface rendered it. Lease enforcement becomes sticky after the browser
        # actually echoes one token back; current web assets always do so.
        return leased

    def _lease_book_result(self, result):
        if type(result) is not dict:
            raise TypeError("Book browser result must be a built-in mapping")
        if result.get("kind") != "render":
            return result
        payload = result.get("payload")
        if type(payload) is not dict:
            raise TypeError("Book browser render payload must be a built-in mapping")
        snapshot = payload.get("snapshot")
        if type(snapshot) is not dict:
            raise TypeError("Book browser render snapshot must be a built-in mapping")
        projected_payload = dict(payload)
        projected_payload["snapshot"] = self._lease_book_snapshot(snapshot)
        projected = dict(result)
        projected["payload"] = projected_payload
        return projected

    def _authorize_book_browser_payload(self, payload):
        payload_keys = self._passive_browser_payload_keys(payload)
        token_present = (
            payload_keys is not None and "presentation_token" in payload_keys
        )
        if payload_keys is not None:
            forwarded = dict(payload)
            token = forwarded.pop("presentation_token", None)
        else:
            forwarded = payload
            token = None

        if self._book_browser_lease_required or token_present:
            if not token_present or not self._valid_book_browser_token(token):
                raise _BookBrowserLeaseRejected("Book presentation lease is missing")
            try:
                current = self._book_presentation_token()
            except Exception as exc:
                raise _BookBrowserLeaseRejected(
                    "Book presentation lease cannot be verified"
                ) from exc
            if not hmac.compare_digest(token, current):
                raise _BookBrowserLeaseRejected("Book presentation lease is stale")
            self._book_browser_lease_required = True
            return forwarded, token

        # Preserve the pre-render compatibility boundary: native/bootstrap tests
        # may issue the first Book command before any browser snapshot exists.
        return forwarded, None

    def _book_browser_recovery_result(self):
        if self.books is None or self.reader is None:
            return self._error()
        try:
            snapshot = self._lease_book_snapshot(self.books.projection.snapshot())
            block = snapshot["block"]
            if type(block) is not dict or type(block.get("dom_id")) is not str:
                raise ValueError("Book recovery focus is unavailable")
            return {
                "kind": "render",
                "payload": {
                    "snapshot": snapshot,
                    "focus_target": block["dom_id"],
                    "announcement": "",
                },
            }
        except Exception:
            return self._error()

    def _require_book_browser_dispatch_authority(self, expected_token):
        if expected_token is None:
            return
        if not self._valid_book_browser_token(expected_token):
            raise _BookBrowserLeaseRejected("Book presentation lease is invalid")
        try:
            current = self._book_presentation_token()
        except Exception as exc:
            raise _BookBrowserLeaseRejected(
                "Book presentation owner changed before dispatch"
            ) from exc
        if not hmac.compare_digest(expected_token, current):
            raise _BookBrowserLeaseRejected(
                "Book presentation owner changed before dispatch"
            )

    def bind_files(self, runtime):
        self._assert_thread()
        self._files = runtime

    def bind_book_open_worker(self, worker: Version2BookOpenWorker) -> None:
        self._assert_thread()
        if not isinstance(worker, Version2BookOpenWorker):
            raise TypeError("Book Open worker must be Version2BookOpenWorker")
        if self._book_open_worker is not None:
            raise RuntimeError("Book Open worker is already bound")
        self._book_open_worker = worker

    def unbind_book_open_worker(self, worker: Version2BookOpenWorker) -> bool:
        """Release only the exact unpublished Book worker owned by startup."""
        self._assert_thread()
        if not isinstance(worker, Version2BookOpenWorker):
            raise TypeError("Book Open worker must be Version2BookOpenWorker")
        if self._book_open_worker is not worker:
            return False
        self._book_open_worker = None
        return True

    def _book_open_event(self, event: BookOpenWorkerEvent) -> BookOpenWorkerEvent:
        self._assert_thread()
        if type(event) is not BookOpenWorkerEvent:
            raise TypeError("invalid Book Open worker event")
        english = self.shell.language is UILanguage.EN
        messages = {
            BookOpenWorkerEventKind.STARTED: (
                "Відкриття книги розпочато. Операцію можна скасувати.",
                "Book opening started. You can cancel the operation.",
            ),
            BookOpenWorkerEventKind.CANCELLING: (
                "Скасовуємо відкриття книги.",
                "Cancelling Book open.",
            ),
            BookOpenWorkerEventKind.CANCELLED: (
                "Відкриття книги скасовано. Поточний стан не змінено.",
                "Book open cancelled. Current state was not changed.",
            ),
            BookOpenWorkerEventKind.COMPLETED: (
                "Книгу відкрито.",
                "Book opened.",
            ),
            BookOpenWorkerEventKind.FAILED: (
                "Не вдалося відкрити книгу. Поточний стан не змінено.",
                "The book could not be opened. Current state was not changed.",
            ),
        }
        self._events.append(
            {
                "kind": "status" if event.kind is not BookOpenWorkerEventKind.FAILED else "error",
                "payload": {
                    "announcement": messages[event.kind][english],
                    "focus_target": event.focus_target,
                    "book_open_busy": event.kind
                    in {BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.CANCELLING},
                },
            }
        )
        return event

    def observe_progress(self, value: LibraryImportProgress):
        if type(value) is not LibraryImportProgress:
            raise TypeError("invalid import progress")
        canonical = LibraryImportProgress(
            value.attempt_id,
            value.processed_games,
            value.total_games,
        )
        with self._observation_lock:
            self._progress = canonical

    def observe_result(self, value: LibraryImportResult):
        if type(value) is not LibraryImportResult:
            raise TypeError("invalid import result")
        canonical = LibraryImportResult(
            value.attempt_id,
            value.source_id,
            value.game_count,
            value.warning_count,
            value.first_game_id,
            value.last_game_id,
            value.reused,
        )
        with self._observation_lock:
            self._result = canonical

    def worker_factory(self, database_path, *, chessbase_factory=None):
        def create():
            database = AcsDatabase(database_path)
            try:
                chessbase = chessbase_factory(database) if chessbase_factory else None
                return Version2ImportWorkerServices(LibraryImportService(database), chessbase, database.close)
            except BaseException:
                # A provider/factory abort must not leak the per-worker DB handle,
                # and a secondary close failure must not replace the original
                # factory failure that the host will classify path-free.
                try:
                    database.close()
                except BaseException:
                    pass
                raise
        return Version2ObservedImportServicesFactory(create, progress_sink=self.observe_progress, result_sink=self.observe_result)

    def set_document(self, session):
        self._assert_thread()
        if type(session) is not PgnDocumentSession: raise TypeError("invalid PGN document")
        # Library/native domain actions can reach this seam without a shell route
        # action. Reject before publishing a new PGN session while modal focus is
        # owned elsewhere, matching AccessibleShellState.open_route().
        if self.shell.active_dialog_id is not None:
            raise ValueError("close the active dialog before replacing the PGN document")
        if self.book_workflow is not None and self.book_workflow.active:
            raise ValueError("return to the book before replacing the PGN document")
        if self.session is not None and self.session.dirty and not self.confirm_document_replace():
            raise ValueError("PGN replacement cancelled")
        document_view = session.view()
        projection = PgnWorkspaceWebViewProjection(
            session.workspace,
            self.router,
            language=self.shell.language,
            document_warnings=document_view.global_warnings,
        )
        bridge = PgnWebViewBridge(projection)
        # Route acquisition is part of accepting a replacement owner. Do not
        # publish the staged session or relinquish an existing PGN Board owner
        # until the shell has accepted the PGN route. open_route() can partially
        # write its route before a focus-restore tail fails, so recover from the
        # actual shell state.
        shell_checkpoint = self.shell._capture_presentation_state()
        focus_checkpoint = self._focus
        try:
            route_focus = self.shell.open_route("pgn")
        except BaseException:
            # Restore both presentation authorities exactly. Rollback is
            # best-effort so a secondary rollback abort cannot replace the
            # primary route/publication failure.
            self._focus = focus_checkpoint
            try:
                self.shell._restore_presentation_state(shell_checkpoint)
            except BaseException:
                pass
            raise
        self.session, self.pgn = session, bridge
        self.pgn_board_active = False
        self._focus = route_focus

    @staticmethod
    def prepare_book_open(
        source: Path,
        *,
        cancel_check=None,
    ) -> PreparedBookOpen:
        """Read and semantically import one Book without touching live UI state.

        This phase is safe to run outside the application UI thread. It uses the
        canonical stable-source reader and each format owner\'s existing control
        checkpoint seam so cancellation is observed during source read/import.
        """

        if not isinstance(source, Path):
            raise TypeError("Book source must be a Path")
        if cancel_check is not None and not callable(cancel_check):
            raise TypeError("Book Open cancel_check must be callable")

        def checkpoint() -> None:
            if cancel_check is None:
                return
            cancelled = cancel_check()
            if type(cancelled) is not bool:
                raise TypeError("Book Open cancel_check must return bool")
            if cancelled:
                raise BookOpenCancelled("Book Open preparation cancelled")

        checkpoint()
        suffix = source.suffix.casefold()
        if suffix not in {".epub", ".html", ".htm", ".xhtml", ".txt", ".md", ".markdown"}:
            raise ValueError("unsupported book source")
        if suffix == ".epub":
            limit = MAX_EPUB_SOURCE_BYTES
        elif suffix in {".html", ".htm", ".xhtml"}:
            limit = MAX_HTML_SOURCE_BYTES
        else:
            limit = MAX_TEXT_SOURCE_BYTES

        try:
            _, raw = read_source_snapshot(
                source,
                max_bytes=limit,
                cancel_check=(None if cancel_check is None else cancel_check),
            )
        except SourceReadCancelledError:
            raise BookOpenCancelled("Book Open preparation cancelled") from None
        checkpoint()
        safe_name = report_safe_name(source)
        if suffix == ".epub":
            imported = import_epub_book(
                raw,
                source_name=safe_name,
                control_checkpoint=checkpoint,
            )
        elif suffix in {".html", ".htm", ".xhtml"}:
            imported = import_html_book(
                raw,
                source_name=safe_name,
                available_assets=(),
                control_checkpoint=checkpoint,
            )
        else:
            kind = BookTextFormat.TXT if suffix == ".txt" else BookTextFormat.MARKDOWN
            imported = import_text_book(
                raw,
                source_name=safe_name,
                source_format=kind,
                control_checkpoint=checkpoint,
            )
        checkpoint()
        return PreparedBookOpen(
            book_key=imported.book_key,
            document=imported.document,
            warnings=tuple(imported.warnings),
        )

    def _assert_book_open_allowed(self) -> None:
        """Reject Book owner replacement before source I/O or UI publication."""

        self._assert_thread()
        if self.shell.active_dialog_id is not None:
            raise ValueError("close the active dialog before opening a book")
        if self.book_workflow is not None and self.book_workflow.active:
            raise ValueError("return to the book before opening another source")

    def commit_prepared_book_open(self, prepared: PreparedBookOpen) -> int:
        """Transactionally publish one already-prepared Book on the UI thread."""

        self._assert_book_open_allowed()
        if type(prepared) is not PreparedBookOpen:
            raise TypeError("prepared Book Open result is invalid")
        # PreparedBookOpen crosses a worker/UI ownership boundary. Its frozen
        # dataclass shell does not make referenced values canonical: callers can
        # construct it directly, and object.__setattr__ can mutate frozen fields.
        # Snapshot and validate warnings before any persistence/route publication
        # so an active container or element cannot run a hook after the Book has
        # already become visible and turn a successful open into FAILED.
        book_key = prepared.book_key
        document = prepared.document
        warnings = prepared.warnings
        if type(book_key) is not str:
            raise TypeError("prepared Book Open book key is invalid")
        if type(document) is not BookDocument:
            raise TypeError("prepared Book Open document is invalid")
        book_key = _validate_book_progress_key(book_key)
        if (
            type(warnings) is not tuple
            or len(warnings) > MAX_BOOK_DOCUMENT_WARNINGS
            or any(type(warning) is not str for warning in warnings)
        ):
            raise TypeError("prepared Book Open warnings are invalid")
        # Validate and detach the mutable BookDocument before saving any current
        # owner state. BookReader.document_snapshot() rechecks the live revision
        # before and after cloning; bind the candidate reader to that detached
        # canonical snapshot so later authoring mutation cannot change this Open.
        validating_reader = BookReader(document)
        document = validating_reader.document_snapshot()
        fresh_reader = BookReader(document)
        canonical_warnings = fresh_reader.document_warnings_snapshot()
        if warnings != canonical_warnings:
            raise TypeError("prepared Book Open warnings do not match the document")
        warning_count = len(canonical_warnings)

        self.save_training_progress()
        self.save_book_progress()
        reader = (
            self.progress_store.restore(book_key, document)
            if self.progress_store.has(book_key)
            else fresh_reader
        )
        workflow = BookBoardWorkflow(
            reader,
            self.engine_assistance,
            game_lookup=AcsdbBookGameLookup(self.database),
        )
        delegate = Version2WindowsBookBoardActionDelegate(
            workflow,
            event_sink=self._book_event,
            next_delegate=self._board_dispatch,
        )
        bridge = build_version2_book_webview(
            reader,
            workflow,
            self.router.dispatch,
            language=self.shell.language,
        )
        bridge.projection.snapshot()

        origin_route = self.shell.current_route.route_id
        shell_checkpoint = self.shell._capture_presentation_state()
        focus_checkpoint = self._focus
        try:
            route_focus = self.shell.open_route("books")
            # Focus derived from the Book route is part of candidate publication,
            # not a post-commit observer. Accept only passive exact text before
            # inspecting or persisting it: an active str subclass or non-text
            # host result must not become application/NVDA focus authority.
            if type(route_focus) is not str:
                raise TypeError("Book route focus is invalid")
            # Resolve reader-container/stale-block focus while the candidate owners
            # are still staged so a host/focus failure rolls the route back and
            # cannot produce a FAILED terminal after the Book already opened.
            if (
                route_focus == "book-reader"
                or route_focus.startswith("book-block-")
            ):
                canonical_focus = f"book-block-{reader.index}"
                if route_focus != canonical_focus:
                    self.shell.record_focus(canonical_focus)
                    route_focus = canonical_focus
            try:
                self._persist_book_progress(book_key, reader)
            except BookProgressStoreError as error:
                if error.code != BookProgressStoreErrorCode.DURABILITY_UNKNOWN:
                    raise
                try:
                    canonical = self.progress_store.restore_primary(
                        book_key,
                        document,
                    )
                    canonical_matches = canonical.snapshot() == reader.snapshot()
                except Exception:
                    canonical_matches = False
                if not canonical_matches:
                    raise error
        except BaseException:
            # Candidate Book owners are still staged here. Restore the exact
            # shell/focus presentation rather than routing back through a second
            # command that could replace the primary persistence/publication
            # failure. If exact restoration itself aborts, one best-effort route
            # recovery may repair the visible shell but never becomes authority.
            self._focus = focus_checkpoint
            try:
                self.shell._restore_presentation_state(shell_checkpoint)
            except BaseException:
                try:
                    self.shell.open_route(origin_route)
                except BaseException:
                    pass
                self._focus = focus_checkpoint
            raise

        self.reader, self.book_key, self.book_workflow, self.book_delegate, self.books = (
            reader,
            book_key,
            workflow,
            delegate,
            bridge,
        )
        self.training_workspace = self.training = None
        self._focus = route_focus
        if warning_count:
            announcement = (
                f"Книгу відкрито з попередженнями імпорту: {warning_count}."
                if self.shell.language is UILanguage.UA
                else f"Book opened with import warnings: {warning_count}."
            )
            self._events.append(
                {"kind": "status", "payload": {"announcement": announcement}}
            )
        return warning_count

    def open_book(self, source: Path):
        """Compatibility wrapper preserving current synchronous Book Open."""

        # Preserve the historical fail-before-read authority fence for direct
        # callers. The commit repeats it because a future background preparation
        # can race with a modal or Book-Board owner becoming active.
        self._assert_book_open_allowed()
        prepared = self.prepare_book_open(source)
        return self.commit_prepared_book_open(prepared)

    def _persist_book_progress(self, book_key, reader):
        """Publish Book progress, offering only explicit bounded backup rollback."""

        try:
            return self.progress_store.save(book_key, reader)
        except BookProgressStoreError as error:
            if error.code != BookProgressStoreErrorCode.CORRUPT_STORE:
                raise
            # Validate the exact primary/backup recovery pair. Confirmation
            # intentionally releases the storage lock, so the later commit must
            # be bound both to the semantically valid backup and to the exact
            # corrupt/missing primary state the user agreed may be discarded.
            try:
                (
                    primary_revision,
                    backup_revision,
                ) = self.progress_store.validated_recovery_revisions(
                    book_key,
                    reader.document,
                )
            except BookProgressStoreError as recovery_error:
                if recovery_error.code == BookProgressStoreErrorCode.STALE_WRITE:
                    raise
                raise error
            except (LookupError, TypeError, ValueError):
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
                expected_primary_revision=primary_revision,
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
                if error.code in self._BOOK_PROGRESS_RELOAD_CODES:
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
        """Rebind Books/Training after ambiguous durability or a stale write.

        Both conditions mean local speculative reader state is no longer the
        storage authority: DURABILITY_UNKNOWN may have published it, while
        STALE_WRITE proves a different canonical generation won. In either case
        only the current primary is safe to project back into Books/Training.
        """

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
        # Recovery/reload is a staged owner replacement just like initial Book
        # install/import. Prove the replacement bridge can render its exact
        # semantic WebView contract before publishing any canonical owner.
        restored_books.projection.snapshot()
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
        previous_workspace = self.training_workspace
        training_language = (
            previous_workspace.language
            if (
                previous_workspace is not None
                and previous_workspace.reader is self.reader
            )
            else self.shell.language
        )
        # Re-entry is a staged owner replacement, not an in-place mutation of a
        # retained Training workspace. start_current() publishes material,
        # session, bridge and durable revision into its workspace. Building that
        # state on a fresh owner keeps the currently published Training model
        # untouched until the caller's shell-route transaction succeeds.
        workspace = Version2BookTrainingWorkspace(
            self.reader,
            progress_root=self.training_progress_root,
            language=training_language,
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
                if error.code not in self._BOOK_PROGRESS_RELOAD_CODES:
                    self._restore_book_progress(
                        before_reader,
                        language=language,
                        bookmark_name=bookmark_name,
                        restore_training=True,
                        training_language=training_language,
                        training_message=training_message,
                        training_message_key=training_message_key,
                    )
                # Storage-authority conflicts already rebound to the canonical
                # primary (or failed Books/Training closed). Never overwrite
                # that authority with the pre-Continue snapshot.
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

    def _dispatch_book_surface_command(
        self,
        command,
        payload=None,
        *,
        expected_browser_token=None,
    ):
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
        books_owner = self.books
        reader_owner = self.reader

        def dispatch_owned(command_value, payload_value):
            previous_token = self._book_browser_dispatch_token
            self._book_browser_dispatch_token = expected_browser_token
            try:
                result = books_owner.dispatch(command_value, payload_value)
            finally:
                self._book_browser_dispatch_token = previous_token
            if expected_browser_token is not None and (
                self.books is not books_owner or self.reader is not reader_owner
            ):
                raise _BookBrowserLeaseRejected(
                    "Book owner changed while browser command was in flight"
                )
            return result

        if is_language:
            # Language is presentation-only, but the Book-local WebView must still
            # own the visible route/focus before it may mutate projection state.
            if (
                self.shell.current_route.route_id != "books"
                or self.shell.active_dialog_id is not None
            ):
                return self.books.projection.generic_error()
            return dispatch_owned(command_id, payload)
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
            if self.pgn_board_active:
                # The release Board has one owner. An active PGN review must be
                # returned explicitly before Books may acquire that surface.
                return self.books.projection.generic_error()
            # The router delegate below is the one durability owner for
            # browser, native-menu and NVDA ingress. Do not pre-save here: the
            # Book WebView dispatches its open through that same delegate, and a
            # second write would advance BookProgress twice for one transition.
            return dispatch_owned(command_id, payload)
        if is_return_from_board:
            # Return belongs to the active Book Board transaction. It is
            # reachable from the visible Board and from the visible Books reader
            # (whose projection intentionally exposes Return while Board review
            # remains active), but never from Library/PGN/Settings or another
            # hidden route.
            if self.shell.current_route.route_id not in self._BOOK_BOARD_RETURN_ROUTES:
                return self.books.projection.generic_error()
            if self.shell.active_dialog_id is not None:
                return self.books.projection.generic_error()
            if self.book_workflow is None or not self.book_workflow.active:
                return self.books.projection.generic_error()
            # The canonical workflow unwinds through the shared router delegate,
            # which re-publishes the exact Book origin once after safe Return.
            # Keeping persistence in that one owner also makes browser/native
            # failure behavior identical.
            return dispatch_owned(command_id, payload)
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
            result = dispatch_owned(command_id, payload)
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
                if error.code not in self._BOOK_PROGRESS_RELOAD_CODES:
                    self._restore_book_progress(
                        before,
                        language=language,
                        bookmark_name=bookmark_name,
                    )
                # On durability/stale-generation conflicts the save path already
                # rebound to the visible canonical primary. Do not restore
                # speculative history over the generation that actually won.
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
        result = dispatch_owned(command_id, payload)
        if result.kind != "error":
            self.save_book_progress()
        return result

    def _book_event(self, event):
        # Board-open/update success becomes authoritative only after the application
        # has projected the canonical BookBoard FEN into the real release board.
        if event.kind is BookBoardUiEventKind.RETURNED_TO_BOOK:
            # Route ownership for explicit Return is a transaction participant,
            # not an observer side effect. The shared delegate precommits Books
            # before asking the workflow to discard its Board session, then emits
            # the one route refresh only after exact Return succeeds. Keeping this
            # sink passive matters because the UI adapter deliberately contains
            # observer failures instead of propagating them to domain state.
            return
        elif event.kind is BookBoardUiEventKind.FAILED:
            self._events.append(self._error())

    def _error(self):
        return {"kind": "error", "payload": {"message": concise_user_error("", language=self.shell.language)}}

    def announce_shutdown_failure(self) -> None:
        """Explain a refused native close without exposing internal failure detail."""

        self._assert_thread()
        message = (
            "Не вдалося безпечно завершити роботу. Вікно залишено відкритим; "
            "спробуйте вийти ще раз."
            if self.shell.language is UILanguage.UA
            else
            "Accessible Chess could not close safely. The window remains open; "
            "try exiting again."
        )
        self._events.append({"kind": "error", "payload": {"message": message}})

    def _project_board_position(self, position):
        projector = self._board_position_projector
        if projector is None:
            raise RuntimeError("release board position projector is unavailable")
        # The board projector is a release-boundary sink. Fail closed before
        # invoking subclass hooks or scanning an unbounded malformed token.
        if type(position) is not str:
            raise RuntimeError("canonical board position is unavailable")
        if (
            len(position) > MAX_FEN_CHARS
            or "\x00" in position
            or not position.strip()
        ):
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
            # The external Board is now untrustworthy, but the canonical workflow
            # still owns its exact Book origin. Acquire a non-Board shell owner
            # before discarding that workflow session; otherwise a rejected Books
            # route would strand the visible Board with no canonical owner.
            origin_route = self.shell.current_route.route_id
            try:
                route_focus = self.shell.open_route("books")
            except Exception:
                if self.shell.current_route.route_id != origin_route:
                    try:
                        self._focus = self.shell.open_route(origin_route)
                    except Exception:
                        pass
                return
            try:
                self.book_workflow.return_to_book()
            except Exception:
                if self.shell.current_route.route_id != origin_route:
                    try:
                        self._focus = self.shell.open_route(origin_route)
                    except Exception:
                        pass
                return
            self._focus = route_focus
            self._repair_book_block_focus_after_rebind()
            self._events.append(
                {"kind": "route", "payload": {"route_id": "books"}}
            )

    def _delegate(self, action, payload):
        # Route-changing delegated PGN actions must respect modal focus before
        # they mutate Board projection or ownership flags. Otherwise open_route()
        # can reject the transition after domain state has already moved.
        if (
            (
                action in {"pgn.open_on_board", "pgn.return"}
                or action in self._PGN_BOARD_ACTIVE_COMMANDS
            )
            and self.shell.active_dialog_id is not None
        ):
            raise ValueError("close the active dialog before changing PGN Board state")
        # Native menus enter the same projection commands as keyboard buttons.
        if action == "pgn.open_on_board":
            if payload:
                raise ValueError("PGN board accepts no payload")
            if self.shell.current_route.route_id != "pgn":
                raise ValueError("PGN board open requires the visible PGN workspace")
            if self.pgn_board_active:
                raise ValueError("PGN board review is already active")
            if self.book_workflow is not None and self.book_workflow.active:
                raise ValueError("return from Book Board before opening PGN review")
            # Shell ownership is fallible and must commit before the external
            # release-board projector accepts a PGN FEN. If either shell commit
            # or projection fails, restore PGN and leave the ownership flag false.
            try:
                route_focus = self.shell.open_route("board")
            except Exception:
                if self.shell.current_route.route_id == "board":
                    self._focus = self.shell.open_route("pgn")
                raise
            self._focus = route_focus
            try:
                self._project_pgn_position()
            except Exception:
                # No PGN Board owner is published until the release projector
                # accepts the canonical FEN. A rejected projection therefore
                # must not leave the shell visibly stranded on ownerless Board.
                # Prefer the PGN workspace; if that route rejects before commit,
                # fall back to Library, which has no transient Board authority.
                try:
                    self._focus = self.shell.open_route("pgn")
                except Exception:
                    if self.shell.current_route.route_id == "pgn":
                        # open_route() may have committed the safe non-Board route
                        # before a focus-restore tail failed.
                        self._focus = self.shell.restore_focus_target()
                    else:
                        try:
                            self._focus = self.shell.open_route("library")
                        except Exception:
                            if self.shell.current_route.route_id == "library":
                                self._focus = self.shell.restore_focus_target()
                raise
            self.pgn_board_active = True
            return None
        if action == "pgn.return":
            if payload:
                raise ValueError("PGN return accepts no payload")
            if not self.pgn_board_active:
                raise ValueError("no PGN board review")
            origin_route = self.shell.current_route.route_id
            if origin_route not in self._PGN_BOARD_RETURN_ROUTES:
                raise ValueError("PGN return requires Board or PGN ownership")
            if self.book_workflow is not None and self.book_workflow.active:
                raise ValueError("Book Board owns the release Board")
            try:
                self._focus = self.shell.open_route("pgn")
            except Exception:
                if self.shell.current_route.route_id != origin_route:
                    self._focus = self.shell.open_route(origin_route)
                raise
            self.pgn_board_active = False
            return None
        if action in self._PGN_BOARD_ACTIVE_COMMANDS:
            if payload or not self.pgn_board_active:
                raise ValueError("no PGN board review")
            if self.shell.current_route.route_id != "board":
                raise ValueError("PGN board command requires the visible Board")
            if self.book_workflow is not None and self.book_workflow.active:
                raise ValueError("Book Board owns the release Board")
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
                    # The canonical cursor is restored, but the release Board no
                    # longer has a trustworthy projection. Acquire the PGN shell
                    # route before relinquishing Board ownership so a rejected or
                    # partial route transition cannot leave a visible ownerless
                    # Board. If route acquisition fails, restore Board when
                    # possible and keep the PGN review owner active for explicit
                    # Return/recovery.
                    origin_route = self.shell.current_route.route_id
                    try:
                        route_focus = self.shell.open_route("pgn")
                    except Exception:
                        if self.shell.current_route.route_id != origin_route:
                            try:
                                self._focus = self.shell.open_route(origin_route)
                            except Exception:
                                pass
                        raise
                    self._focus = route_focus
                    self.pgn_board_active = False
                raise
            return None
        if action.startswith("pgn.") and action not in {"pgn.open", "pgn.cancel_open", "pgn.save", "pgn.save_as", "pgn.cancel_save", "pgn.export_selection"}:
            # All Board-owned PGN actions returned above. The remaining PGN
            # document/navigation commands belong to the visible PGN workspace;
            # central native/menu dispatch must not bypass the same route/modal
            # authority fence enforced for the WebView.
            if (
                self.shell.current_route.route_id != "pgn"
                or self.shell.active_dialog_id is not None
            ):
                raise ValueError("PGN command requires the visible PGN workspace")
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
        if action == "book.cancel_open":
            if payload:
                raise ValueError("Book Open cancellation takes no payload")
            if self._book_open_worker is None:
                raise ValueError("Book Open worker is unavailable")
            if not self._book_open_worker.cancel(focus_target=str(self._focus)):
                raise ValueError("no Book Open is running")
            return None
        if action == "book.open":
            if payload:
                raise ValueError("book file selection belongs to the host")
            self._assert_book_open_allowed()
            if self._book_open_worker is not None and self._book_open_worker.active:
                raise ValueError("Book Open is already running")
            source = self.open_book_dialog()
            if source is None:
                return None
            if self._book_open_worker is not None:
                self._book_open_worker.start(source, focus_target=str(self._focus))
                return None
            return self.open_book(source)
        if action.startswith("book."):
            if self.book_delegate is None: raise ValueError("no book is open")
            if action in self.book_delegate.OWNED_ACTIONS:
                # Browser Book commands carry an opaque presentation lease. Recheck
                # it at the final shared delegate boundary so a re-entrant owner
                # replacement cannot reinterpret stale DOM intent against a newer
                # reader between outer authorization and canonical Board mutation.
                if self._book_browser_dispatch_token is not None:
                    self._require_book_browser_dispatch_authority(
                        self._book_browser_dispatch_token
                    )
                # Modal focus owns the application while open. Reject every Book
                # Board transition before workflow dispatch so open/navigation/
                # analysis/return cannot partially mutate state behind the dialog.
                if self.shell.active_dialog_id is not None:
                    raise ValueError("close the active dialog before changing Book Board state")
                opening_board = action in self._BOOK_BOARD_OPEN_COMMANDS
                returning_to_book = action in self._BOOK_BOARD_RETURN_COMMANDS
                if returning_to_book:
                    # Return is valid from the visible Board and the visible Books
                    # reader, but not from unrelated shell routes. The review
                    # WebView has its own stricter Board-only ingress fence below.
                    if self.shell.current_route.route_id not in self._BOOK_BOARD_RETURN_ROUTES:
                        raise ValueError("book return requires Board or Books ownership")
                    if self.book_workflow is None or not self.book_workflow.active:
                        raise ValueError("no Book Board review is active")
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
                    if self.pgn_board_active:
                        raise ValueError("return from PGN Board before opening Book review")
                # Native menu/NVDA activation reaches this delegate directly,
                # bypassing _dispatch_book_surface_command(). Apply the same
                # durability boundary as the Book WebView: the exact reading
                # origin must be accepted by BookProgress before Board ownership
                # can become active.
                if opening_board:
                    self.save_book_progress()
                before_view = self.book_delegate.view() if self.book_workflow.active else None
                return_route_precommitted = False
                return_origin_route = None
                if returning_to_book:
                    return_origin_route = self.shell.current_route.route_id
                    # Acquire Books route ownership before the canonical workflow
                    # discards its exact-return Board session. The adapter treats
                    # event_sink as a non-authoritative observer and intentionally
                    # contains observer exceptions, so route mutation cannot live
                    # in _book_event() without risking inactive-workflow/Board-route
                    # divergence. Focus repair is part of the same precommit.
                    #
                    # open_route() writes the route before restoring focus, so an
                    # exception does not itself prove that ownership stayed on
                    # Board. Roll back from the actual shell state, not from a
                    # local "call returned" flag.
                    try:
                        self._focus = self.shell.open_route("books")
                        self._repair_book_block_focus_after_rebind()
                        return_route_precommitted = True
                    except Exception:
                        if (
                            return_origin_route is not None
                            and self.shell.current_route.route_id != return_origin_route
                        ):
                            self._focus = self.shell.open_route(return_origin_route)
                        raise
                result = self.book_delegate(action, payload)
                if result.kind is BookBoardUiEventKind.FAILED:
                    if return_route_precommitted:
                        # BookBoardWorkflow keeps the session alive when exact
                        # Return fails. Restore the exact route from which the
                        # user attempted Return (Board or visible Books) before
                        # surfacing the sanitized failure.
                        self._focus = self.shell.open_route(return_origin_route)
                    raise ValueError(
                        concise_user_error("", language=self.shell.language)
                    )
                if result.kind in {BookBoardUiEventKind.BOARD_OPENED, BookBoardUiEventKind.BOARD_UPDATED}:
                    # Commit every fallible shell ownership operation before
                    # calling the release Board projector. The projector is an
                    # external host seam; once it accepts a FEN, a later route or
                    # focus failure must not turn that accepted state into an
                    # application error with divergent ownership.
                    try:
                        route_focus = self.shell.open_route("board")
                        if result.kind is BookBoardUiEventKind.BOARD_OPENED:
                            # Bind the canonical launch focus before publication
                            # as part of the same shell precommit.
                            self.shell.record_focus("board-launcher")
                            route_focus = "board-launcher"
                    except Exception:
                        if before_view is not None and before_view.cursor is not None:
                            self.book_workflow.go_to_cursor(before_view.cursor)
                        elif self.book_workflow is not None and self.book_workflow.active:
                            self.book_workflow.return_to_book()
                        # Version2ShellState.open_route() writes _route_id before
                        # restore_focus_target(). If that tail raises, the shell
                        # may already own Board even though open_route() did not
                        # return. A just-opened Book session must restore Books.
                        if (
                            result.kind is BookBoardUiEventKind.BOARD_OPENED
                            and self.shell.current_route.route_id == "board"
                        ):
                            self._focus = self.shell.open_route("books")
                            self._repair_book_block_focus_after_rebind()
                        raise
                    self._focus = route_focus
                    try:
                        self._project_board_position(self.book_delegate.view().current_fen)
                    except Exception:
                        self._recover_book_projection_failure(before_view)
                        raise
                    self.pgn_board_active = False
                    if result.kind is BookBoardUiEventKind.BOARD_OPENED:
                        self._events.append({"kind": "book-board", "payload": {"focus_target": "board-launcher"}})
                if result.kind is BookBoardUiEventKind.RETURNED_TO_BOOK:
                    if not return_route_precommitted:
                        raise RuntimeError("Book return route ownership was not precommitted")
                    # Exact Return and Books route ownership are now both accepted.
                    # Publish one refresh event before durability acknowledgement
                    # so browser/native NVDA surfaces cannot remain visually on
                    # the obsolete Board if the subsequent progress save reports
                    # an ambiguity or ordinary persistence failure.
                    self._events.append(
                        {"kind": "route", "payload": {"route_id": "books"}}
                    )
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
        if self._files is not None and action in {"pgn.open", "pgn.cancel_open", "pgn.save", "pgn.save_as", "pgn.cancel_save", "pgn.export_selection", "library.import", "library.cancel_import", "library.export"}:
            ui = self.library.projection.import_projection
            if (
                action == "library.import"
                and ui.phase
                in {LibraryImportPhase.RUNNING, LibraryImportPhase.CANCELLING}
            ):
                # The canonical worker may already have committed and exited
                # while its terminal batch is still leased/pending for native
                # presentation. Starting a second attempt here could overwrite
                # the one-slot D07 observer state before that first terminal is
                # projected. Presentation ownership therefore remains exclusive
                # until the prior terminal has been delivered successfully.
                result = FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.import",
                    focus_target="library-import-file",
                    error_code="import_already_running",
                )
                self._file_event(result)
                return result

            result = self._files(action, payload)
            if isinstance(result, FileWorkflowEvent):
                if result.kind is FileWorkflowEventKind.IMPORT_STARTED:
                    self._events.append(asdict(ui.prepare()))
                elif result.kind is FileWorkflowEventKind.IMPORT_CANCELLING:
                    # A result observer may already have advanced the canonical
                    # import projection to a terminal phase before the host's
                    # late cancelling event reaches this direct/native path.
                    # Terminal projection state wins; never regress it or raise
                    # from host_cancelling() after completion.
                    if ui.phase in {LibraryImportPhase.RUNNING, LibraryImportPhase.CANCELLING}:
                        self._events.append(asdict(ui.host_cancelling()))
                else:
                    self._file_event(result)
            return result
        return self._board_dispatch(action, payload)

    def browser_command(self, area, command, payload=None):
        self._assert_thread()
        try:
            # Browser surface names and shell/review envelopes are authority
            # inputs. Validate exact bounded JSON-shaped values before equality,
            # hashing, prefix scans or payload truthiness can run subclass hooks.
            if type(area) is not str or len(area) > 16:
                raise ValueError("invalid browser surface")
            area_id = area
            payload_keys = self._passive_browser_payload_keys(payload)
            empty_authority_payload = payload is None or (
                payload_keys is not None and len(payload_keys) == 0
            )
            if (
                self._pending_shell_publication is not None
                and area_id != "shell"
            ):
                # Until the browser commits or rolls back its route snapshot,
                # the old DOM may still be interactive while Python already
                # holds the candidate route. Never reinterpret those stale
                # surface commands against the unpublished owner.
                raise ValueError("shell presentation publication is pending")
            if area_id == "review":
                allowed = {"pgn.open_on_board", "pgn.return", "pgn.board_next_move", "pgn.board_previous_move", "pgn.board_enter_variation", "pgn.board_leave_variation",
                           "book.board_next_move", "book.board_previous_move", "book.board_enter_variation", "book.board_leave_variation", "book.return"}
                if (
                    type(command) is not str
                    or len(command) > 64
                    or command not in allowed
                    or not empty_authority_payload
                ):
                    raise ValueError("invalid review command")
                if (
                    command.startswith("book.")
                    and self.shell.current_route.route_id != "board"
                ):
                    # The review WebView is a Board-owned surface. Its retained
                    # DOM must never unwind or navigate Book Board state after a
                    # shell route change, even when Books itself is visible.
                    raise ValueError("Book review command requires the visible Board")
                result = self.router.dispatch(command).value
                if getattr(result, "kind", None) is BookBoardUiEventKind.FAILED: return self._error()
                return {"kind": "review", "payload": {}}
            if area_id == "shell":
                is_publication_control = (
                    type(command) is str
                    and command in {
                        "shell.presentation_commit",
                        "shell.presentation_rollback",
                    }
                )
                if is_publication_control:
                    token = self._shell_publication_token(payload)
                    return self._finish_shell_publication(
                        token,
                        commit=command == "shell.presentation_commit",
                    )

                publication_protocol = False
                publication_request_id = None
                if (
                    payload_keys is not None
                    and "publication_protocol" in payload_keys
                ):
                    if (
                        len(payload_keys) != 2
                        or "request_id" not in payload_keys
                    ):
                        raise ValueError("invalid shell publication request")
                    value = payload["publication_protocol"]
                    if type(value) is not str or value != "ack-v1":
                        raise ValueError("unsupported shell publication protocol")
                    publication_request_id = payload["request_id"]
                    if (
                        type(publication_request_id) is not int
                        or publication_request_id <= 0
                        or publication_request_id > 9007199254740991
                    ):
                        raise ValueError("invalid shell publication request")
                    publication_protocol = True

                if not empty_authority_payload and not publication_protocol:
                    raise ValueError("shell accepts no authority payload")
                if (
                    type(command) is not str
                    or len(command) > 64
                    or not (
                        command.startswith("screen.")
                        or command in {"pgn.open", "pgn.save", "pgn.save_as", "book.open"}
                    )
                ):
                    raise ValueError("unsupported shell command")
                if publication_protocol and not command.startswith("screen."):
                    raise ValueError("shell publication protocol requires a route command")
                if publication_protocol and self._pending_shell_publication is not None:
                    pending = self._pending_shell_publication
                    if (
                        pending[1] == command
                        and pending[2] == publication_request_id
                    ):
                        return pending[3]
                    raise ValueError("shell publication acknowledgement is pending")
                if (
                    publication_protocol
                    and self._shell_publication_sequence >= 9007199254740990
                ):
                    raise RuntimeError("shell publication sequence exhausted")

                publication_before = None
                if publication_protocol:
                    publication_before = (
                        self.shell._capture_presentation_state(),
                        self._focus,
                        self.training_workspace,
                        self.training,
                    )

                training_transition = None
                if command == "screen.training":
                    # Route changes are modal-blocked by the shell. Apply the same
                    # fence before Training preflight can move or wrap the reader.
                    if self.shell.active_dialog_id is not None:
                        raise ValueError("close the active dialog before opening Training")
                    training_transition = (
                        self.training_workspace,
                        self.training,
                        self.shell.current_route.route_id,
                    )
                    if not self._start_training_from_current_book():
                        raise ValueError("Training exercise is unavailable")
                try:
                    value = self.adapter.activate_action(
                        command,
                        current_focus_id=self._focus,
                    )
                except Exception:
                    if training_transition is not None:
                        previous_workspace, previous_training, origin_route = training_transition
                        self.training_workspace = previous_workspace
                        self.training = previous_training
                        if self.shell.current_route.route_id != origin_route:
                            self._focus = self.shell.open_route(origin_route)
                            self._repair_book_block_focus_after_rebind()
                    raise
                if training_transition is not None and value.kind != "route":
                    # FullProductWebViewAdapter sanitizes shell failures into an
                    # error command. Treat that as a rejected transaction: a
                    # staged Training owner must not survive on the old route,
                    # and a partial open_route() commit must be restored.
                    previous_workspace, previous_training, origin_route = training_transition
                    self.training_workspace = previous_workspace
                    self.training = previous_training
                    if self.shell.current_route.route_id != origin_route:
                        self._focus = self.shell.open_route(origin_route)
                        self._repair_book_block_focus_after_rebind()
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
                        if publication_protocol:
                            self._shell_publication_sequence += 1
                            token = self._shell_publication_sequence
                            (
                                prior_shell,
                                prior_focus,
                                prior_training_workspace,
                                prior_training,
                            ) = publication_before
                            self.shell._begin_publication_hold()
                            projected_payload["publication_token"] = token
                            self._pending_shell_publication = (
                                token,
                                command,
                                publication_request_id,
                                projected,
                                prior_shell,
                                prior_focus,
                                prior_training_workspace,
                                prior_training,
                            )
                return projected
            if area_id == "training":
                try:
                    return asdict(self._dispatch_training_surface_command(command, payload))
                except Exception:
                    return {
                        "kind": "error",
                        "payload": {"message": self._training_error_message()},
                    }
            if area_id == "books":
                try:
                    forwarded_payload, expected_token = (
                        self._authorize_book_browser_payload(payload)
                    )
                    value = self._dispatch_book_surface_command(
                        command,
                        forwarded_payload,
                        expected_browser_token=expected_token,
                    )
                    return self._lease_book_result(asdict(value))
                except _BookBrowserLeaseRejected:
                    # Stale browser intent is a presentation-recovery request only.
                    # Never reinterpret it against the current Book owner.
                    return self._book_browser_recovery_result()
            bridge = {"pgn": self.pgn, "library": self.library}.get(area_id)
            if bridge is None: raise ValueError("surface is unavailable")
            pgn_refresh = (
                area_id == "pgn"
                and type(command) is str
                and command == "pgn.refresh"
            )
            if (
                area_id == "pgn"
                and not pgn_refresh
                and (
                    self.shell.current_route.route_id != "pgn"
                    or self.shell.active_dialog_id is not None
                )
            ):
                # The retained PGN WebView is not an authority surface once the
                # shell leaves PGN or a modal owns focus. Reject before lease
                # comparison or bridge dispatch so stale DOM cannot select,
                # navigate or edit the canonical PGN behind another screen.
                raise ValueError("PGN command requires the visible PGN workspace")
            if (
                area_id == "pgn"
                and type(command) is str
                and not pgn_refresh
                and self._pgn_browser_lease_required
                and (
                    payload_keys is None
                    or "presentation_token" not in payload_keys
                )
            ):
                # A rendered PGN surface has an opaque lease. Missing it is
                # stale/unbound browser intent: recover presentation only and
                # never reinterpret the command against newer canonical state.
                return asdict(bridge.dispatch("pgn.refresh"))
            value = bridge.dispatch(command, payload)
            if area_id == "pgn" and (
                pgn_refresh
                or (
                    payload_keys is not None
                    and "presentation_token" in payload_keys
                )
            ):
                self._pgn_browser_lease_required = True
            return asdict(value)
        except Exception:
            return self._error()

    def snapshot(self):
        self._assert_thread()
        pgn_snapshot = None if self.pgn is None else self.pgn.projection.snapshot()
        if pgn_snapshot is not None:
            # Host-side snapshots can advance the projection without proving
            # that the browser/NVDA DOM rendered that newer presentation.
            self._pgn_browser_lease_required = True
        book_snapshot = None if self.books is None else self.books.projection.snapshot()
        if book_snapshot is not None:
            book_snapshot = self._lease_book_snapshot(book_snapshot)
        pending_shell_publication_token = (
            self._pending_shell_publication[0]
            if self._pending_shell_publication is not None
            else 0
        )
        return {
            **self.adapter.snapshot(),
            "shell_publication_token": pending_shell_publication_token,
            "pgn": pgn_snapshot,
            "library": self.library.projection.snapshot(),
            "books": book_snapshot,
            "training": None if self.training_workspace is None else self.training_workspace.snapshot(),
            "book_board_active": self.book_workflow is not None and self.book_workflow.active,
            "pgn_board_active": self.pgn_board_active,
            "document_dirty": bool(self.session and self.session.dirty),
        }

    def drain_events(self):
        self._assert_thread()
        # Book Open completion posting can fail transiently after background
        # preparation finishes. Recover its retained terminal only here, on the
        # canonical owner/UI thread, so NVDA/browser state cannot remain stuck at
        # STARTED and no worker thread ever calls presentation code directly.
        if self._book_open_worker is not None:
            self._book_open_worker.flush_pending_terminal()
        if self._pending_shell_publication is not None:
            # The browser is rendering a candidate route. Preserve every prior
            # native/domain presentation event in order until that route is
            # either committed or rolled back; applying an event to the
            # unpublished DOM would create a second presentation authority.
            return ()
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
                    "book.open_game": "game_opened",
                    "book.return": "returned",
                }.get(action_id)
                if action_id == "book.open_position" and self.reader is not None:
                    # Legacy native/keymap ingress keeps book.open_position as
                    # OPEN_CURRENT compatibility even on a Game. The visible
                    # browser has a separate Game action, so make NVDA/native
                    # feedback describe the semantic item that actually opened.
                    try:
                        if self.reader.location().kind == "Game":
                            announcement_key = "game_opened"
                    except Exception:
                        # Delegation already succeeded. If the read-only semantic
                        # probe is unavailable, preserve the established generic
                        # position announcement instead of breaking event delivery.
                        announcement_key = "opened"
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
        self.shell.record_observed_focus(token)
        self._focus = token

    def import_ui_ready(self, mailbox):
        self._assert_thread()
        delivery_batch = getattr(mailbox, "delivery_batch", None)
        if not callable(delivery_batch):
            raise TypeError("Windows import UI mailbox must support transactional delivery")

        ui = self.library.projection.import_projection
        active = {LibraryImportPhase.RUNNING, LibraryImportPhase.CANCELLING}
        ui_checkpoint = ui._capture_presentation_state()
        application_events_checkpoint = tuple(self._events)

        with delivery_batch() as events:
            with self._observation_lock:
                progress, result = self._progress, self._result

            # Observer DTOs are published immediately before their corresponding
            # worker callback/terminal. A worker can therefore update the
            # observer slot and then block on the mailbox lease. Consume a DTO
            # only when this exact leased batch already contains the matching
            # path-free event; otherwise leave the newer observation pending.
            progress_ready = (
                progress is not None
                and any(
                    event.action_id == "library.import"
                    and event.kind is FileWorkflowEventKind.IMPORT_PROGRESS
                    and not event.source_parsing
                    and event.processed_games == progress.processed_games
                    and event.total_games == progress.total_games
                    for event in events
                )
            )
            result_ready = (
                result is not None
                and any(
                    event.action_id == "library.import"
                    and event.kind is FileWorkflowEventKind.IMPORT_COMPLETED
                    and event.game_count == result.game_count
                    and event.warning_count == result.warning_count
                    for event in events
                )
            )
            retire_observers = any(
                event.action_id in {"library.import", "library.cancel_import"}
                and event.kind
                in {
                    FileWorkflowEventKind.IMPORT_EMPTY,
                    FileWorkflowEventKind.IMPORT_CANCELLED,
                    FileWorkflowEventKind.FAILED,
                }
                for event in events
            )

            try:
                for event in events:
                    if event.action_id not in {"library.import", "library.cancel_import"}:
                        # Deferred PGN Open completion already committed the canonical
                        # document and shell route on the owner thread. Publish one
                        # route refresh so a retained WebView/NVDA presentation cannot
                        # remain on the document that was visible before the worker.
                        if event.kind is FileWorkflowEventKind.PGN_OPENED:
                            self._events.append(
                                {
                                    "kind": "route",
                                    "payload": {
                                        "route_id": "pgn",
                                        "focus_target": event.focus_target,
                                    },
                                }
                            )
                        self._file_event(event)
                        continue
                    rendered = None
                    if (
                        event.kind
                        in {
                            FileWorkflowEventKind.IMPORT_COMPLETED,
                            FileWorkflowEventKind.IMPORT_EMPTY,
                        }
                        and event.source_format
                        and ui.phase in active
                    ):
                        ui.book_source_report(
                            event.source_format,
                            event.retained_book_blocks,
                        )
                    if event.kind is FileWorkflowEventKind.IMPORT_STARTED:
                        if ui.phase not in active:
                            rendered = ui.prepare()
                        if (
                            event.total_games
                            and ui.snapshot()["total_games"] == 0
                        ):
                            ui.begin(event.total_games)
                        if event.source_format:
                            ui.book_source_report(
                                event.source_format,
                                event.retained_book_blocks,
                            )
                    elif (
                        event.kind is FileWorkflowEventKind.IMPORT_CANCELLING
                        and ui.phase in active
                    ):
                        rendered = ui.host_cancelling()
                    elif (
                        event.kind is FileWorkflowEventKind.IMPORT_PROGRESS
                        and event.source_parsing
                        and ui.phase is LibraryImportPhase.RUNNING
                        and ui.snapshot()["total_games"] == 0
                    ):
                        rendered = ui.source_reading(
                            event.source_bytes_read,
                            event.source_total_bytes,
                            event.processed_games,
                        )
                    elif event.kind is FileWorkflowEventKind.IMPORT_EMPTY:
                        rendered = ui.empty(warning_count=event.warning_count)
                    elif (
                        event.kind is FileWorkflowEventKind.IMPORT_CANCELLED
                        and ui.phase in active
                    ):
                        rendered = ui.cancelled()
                    elif event.kind is FileWorkflowEventKind.FAILED:
                        if ui.phase not in active:
                            ui.prepare()
                        rendered = ui.fail(
                            self._native_file_error_message(event)
                        )
                    if rendered:
                        self._events.append(asdict(rendered))

                if progress_ready and progress is not None and ui.phase in active:
                    if ui.snapshot()["total_games"] == 0:
                        ui.begin(progress.total_games)
                    self._events.append(asdict(ui.progress(progress)))

                if result_ready and result is not None and ui.phase in active:
                    if ui.snapshot()["total_games"] == 0:
                        ui.begin(result.game_count)
                    self._events.append(asdict(ui.complete(result)))
                    # Update rows without moving focus from another surface.
                    self.library.projection.search(self.library.projection.query)
            except BaseException:
                ui._restore_presentation_state(ui_checkpoint)
                self._events.clear()
                self._events.extend(application_events_checkpoint)
                raise
            else:
                # A newer worker observation may have arrived while this owner
                # batch was rendering. Clear only the exact DTOs actually
                # consumed by this successful transaction.
                with self._observation_lock:
                    if (
                        (progress_ready or retire_observers)
                        and self._progress is progress
                    ):
                        self._progress = None
                    if (
                        (result_ready or retire_observers)
                        and self._result is result
                    ):
                        self._result = None

    def _native_file_error_message(self, event):
        if type(event) is not FileWorkflowEvent:
            return concise_user_error("", language=self.shell.language)
        language = self.library.projection.language if event.action_id in {"library.import", "library.cancel_import"} else self.shell.language
        messages = {
            "unsupported_import_source": (
                "Імпорт підтримує PGN, EPUB, HTML, Markdown та CBH/CBV з підтримуваним декодером. Інші формати не можна імпортувати.",
                "Import supports PGN, EPUB, HTML, Markdown and CBH/CBV with a supported decoder. Other formats cannot be imported.",
            ),
            "chessbase_backend_unavailable": (
                "Для імпорту CBH/CBV потрібен налаштований підтримуваний декодер. Можна імпортувати PGN.",
                "CBH/CBV import requires a configured supported decoder. You can import PGN instead.",
            ),
            "chessbase_import_failed": (
                "Не вдалося імпортувати ChessBase. Перевірте повноту сімейства файлів і налаштування декодера.",
                "ChessBase import failed. Check the complete file family and the decoder configuration.",
            ),
            "pgn_import_failed": (
                "Не вдалося імпортувати PGN. Перевірте формат і коректність партій.",
                "PGN import failed. Check the format and game validity.",
            ),
            "book_source_read_failed": (
                "Не вдалося безпечно прочитати джерело книги. Перевірте файл і повторіть імпорт.",
                "The book source could not be read safely. Check the file and retry the import.",
            ),
            "import_already_running": (
                "Попередній імпорт ще завершується. Повторіть дію після завершення.",
                "The previous import is still finishing. Retry after it completes.",
            ),
            "import_worker_unavailable": (
                "Не вдалося запустити фоновий імпорт. Бібліотеку не змінено. Повторіть імпорт.",
                "Background import could not be started. The Library was not changed. Retry the import.",
            ),
            "no_import_running": (
                "Імпорт уже завершився або не був розпочатий.",
                "The import has finished or has not started.",
            ),
            "file_worker_busy": (
                "Інша файлова операція ще виконується. Завершіть або скасуйте її та повторіть дію.",
                "Another file operation is still running. Finish or cancel it, then retry.",
            ),
            "ui_event_queue_overflow": (
                "Черга повідомлень файлової операції переповнилася. Остаточний результат міг бути виконаний, але не відображений. Не повторюйте дію навмання: оновіть відповідний екран і перевірте документ або бібліотеку.",
                "The file-operation message queue overflowed. The final result may have completed without being shown. Do not retry blindly: refresh the relevant screen and verify the document or Library.",
            ),
            "file_dialog_failed": (
                "Не вдалося відкрити системне вікно вибору файла. Файлова операція не розпочалася. Повторіть дію.",
                "The system file picker could not be opened. The file operation was not started. Retry the action.",
            ),
            "file_workflow_closed": (
                "Файлові операції вже завершуються.",
                "File operations are already shutting down.",
            ),
            "pgn_session_invalid": (
                "Поточний PGN-документ має некоректний внутрішній стан. Файлову операцію зупинено без зміни документа або файла. Перезапустіть програму, відкрийте PGN заново та повторіть дію.",
                "The current PGN document has an invalid internal state. The file operation was stopped without changing the document or file. Restart the application, reopen the PGN, and retry.",
            ),
            "pgn_session_unavailable": (
                "Не вдалося безпечно отримати поточний PGN. Файлову операцію зупинено без зміни документа або файла. Перезапустіть програму та повторіть дію.",
                "The current PGN could not be accessed safely. The file operation was stopped without changing the document or file. Restart the application and retry.",
            ),
            "no_pgn_document": (
                "Немає відкритого PGN для збереження. Відкрийте або створіть PGN і повторіть дію.",
                "There is no open PGN to save. Open or create a PGN and retry.",
            ),
            "no_pgn_open_running": (
                "Фонове відкриття PGN уже завершилося або не було розпочате.",
                "Background PGN opening has finished or has not started.",
            ),
            "pgn_open_stale": (
                "PGN не замінено, бо поточний документ змінився під час відкриття. Повторіть дію за потреби.",
                "The PGN was not replaced because the current document changed while opening. Retry if needed.",
            ),
            "pgn_open_failed": (
                "Не вдалося відкрити вибраний PGN. Поточний документ не змінено. Перевірте файл і повторіть дію.",
                "The selected PGN could not be opened. The current document was not changed. Check the file and retry.",
            ),
            "unsaved_confirmation_unavailable": (
                "Не вдалося показати підтвердження для незбережених змін. Інший PGN не відкрито, поточний документ не змінено. Збережіть його та повторіть відкриття.",
                "The unsaved-changes confirmation could not be shown. No other PGN was opened and the current document was not changed. Save it, then retry opening.",
            ),
            "unsaved_confirmation_failed": (
                "Не вдалося завершити підтвердження для незбережених змін. Інший PGN не відкрито, поточний документ не змінено. Збережіть його та повторіть відкриття.",
                "The unsaved-changes confirmation could not be completed. No other PGN was opened and the current document was not changed. Save it, then retry opening.",
            ),
            "pgn_open_worker_unavailable": (
                "Не вдалося запустити фонове відкриття PGN.",
                "Background PGN opening could not be started.",
            ),
            "pgn_open_publish_failed": (
                "PGN підготовлено, але безпечно показати його не вдалося. Поточний документ не змінено.",
                "The PGN was prepared but could not be published safely. The current document was not changed.",
            ),
            "pgn_open_ui_post_failed": (
                "PGN підготовлено, але передати результат у вікно програми не вдалося. Поточний документ не змінено.",
                "The PGN was prepared but its result could not be delivered to the application window. The current document was not changed.",
            ),
            "no_pgn_save_running": (
                "Фонове збереження PGN уже завершилося або не було розпочате.",
                "Background PGN saving has finished or has not started.",
            ),
            "pgn_save_preflight_stale": (
                "Збереження не розпочато, бо документ змінився, поки було відкрито вікно вибору файла.",
                "Saving was not started because the document changed while the file dialog was open.",
            ),
            "pgn_save_stale": (
                "Файл уже записано, але його не прив’язано до поточного документа, бо активний документ змінився під час збереження.",
                "The file was written, but it was not committed to the current document because the active document changed while saving.",
            ),
            "pgn_save_worker_unavailable": (
                "Не вдалося запустити фонове збереження PGN.",
                "Background PGN saving could not be started.",
            ),
            "pgn_save_commit_failed": (
                "Файл уже записано, але стан документа не вдалося безпечно оновити. Не повторюйте збереження навмання. Якщо після початку збереження ви вносили нові зміни, не закривайте і не перевідкривайте документ, доки не зафіксуєте ці зміни окремо, наприклад копіюванням або експортом вибраного PGN. Після цього перевідкрийте записаний PGN і перевірте його перед наступним збереженням.",
                "The file was written, but document state could not be updated safely. Do not retry saving blindly. If you made newer edits after the save started, do not close or reopen the document until you preserve those edits separately, for example by copying or exporting the selected PGN. Then reopen the written PGN and verify it before saving again.",
            ),
            "pgn_save_publication_unverified": (
                "Збереження PGN уже перейшло межу публікації, але остаточно перевірити опублікований файл не вдалося. Не повторюйте збереження навмання: перевідкрийте вибраний PGN і перевірте його вміст перед наступним збереженням.",
                "The PGN save crossed the publication boundary, but the published file could not be verified safely. Do not retry blindly: reopen the selected PGN and verify its contents before saving again.",
            ),
            "pgn_save_conflict": (
                "PGN змінився на диску під час збереження. Файл не перезаписано; перевірте актуальну версію та повторіть дію.",
                "The PGN changed on disk while saving. The file was not overwritten; review the current version and retry.",
            ),
            "pgn_save_failed": (
                "Не вдалося зберегти PGN. Поточні незбережені зміни залишилися в документі.",
                "PGN could not be saved. The current unsaved edits remain in the document.",
            ),
            "pgn_save_as_preserve_original": (
                "Цей PGN відкрито з відновленням. У «Зберегти як» виберіть інше ім’я або папку, щоб не перезаписати оригінальний файл.",
                "This PGN was opened with recovery. In Save As, choose a different filename or folder so the original file is not overwritten.",
            ),
            "pgn_save_as_failed": (
                "Не вдалося зберегти PGN у вибраний файл. Поточні незбережені зміни залишилися в документі.",
                "PGN could not be saved to the selected file. The current unsaved edits remain in the document.",
            ),
            "pgn_save_ui_post_failed": (
                "Не вдалося передати результат фонового збереження у вікно програми.",
                "The background save result could not be delivered to the application window.",
            ),
        }
        code = event.error_code
        if type(code) is str and len(code) <= 64:
            message = messages.get(code)
            if message is not None:
                return message[language is UILanguage.EN]
        return concise_user_error("", language=language)

    def _file_event(self, event):
        if type(event) is not FileWorkflowEvent:
            self._events.append(
                {
                    "kind": "error",
                    "payload": {
                        "message": concise_user_error(
                            "", language=self.shell.language
                        )
                    },
                }
            )
            return
        failed = getattr(event.kind, "value", "") == "failed"
        if failed:
            self._events.append({"kind": "error", "payload": {"message": self._native_file_error_message(event)}})
            return
        kind = getattr(event.kind, "value", "")
        if kind == "pgn_opened" and type(event.warning_count) is int and event.warning_count > 0:
            warning_count = event.warning_count
            announcement = (
                f"PGN відкрито з попередженнями відновлення: {warning_count}. "
                "Оригінальний файл захищено від звичайного перезапису; "
                "для збереження виправленої версії використовуйте «Зберегти як»."
                if self.shell.language is UILanguage.UA
                else
                f"PGN opened with recovery warnings: {warning_count}. "
                "The original file is protected from normal overwrite; "
                "use Save As to save the recovered version."
            )
            self._events.append(
                {"kind": "status", "payload": {"announcement": announcement}}
            )
            return
        messages = {
            "pgn_open_started": (
                "PGN відкривається у фоновому режимі. За потреби скористайтеся командою скасування відкриття PGN.",
                "PGN is opening in the background. Use Cancel PGN Open if needed.",
            ),
            "pgn_open_cancelling": (
                "Скасовую відкриття PGN.",
                "Cancelling PGN open.",
            ),
            "pgn_open_cancelled": (
                "Відкриття PGN скасовано. Поточний документ не змінено.",
                "PGN open cancelled. The current document was not changed.",
            ),
            "pgn_opened": ("PGN відкрито.", "PGN opened."),
            "pgn_save_started": (
                "PGN зберігається у фоновому режимі. За потреби скористайтеся командою скасування збереження PGN.",
                "PGN is saving in the background. Use Cancel PGN Save if needed.",
            ),
            "pgn_save_cancelling": (
                "Запит на скасування збереження PGN надіслано. Якщо файл ще не опубліковано, збереження буде зупинено.",
                "PGN save cancellation requested. If the file has not been published yet, saving will stop.",
            ),
            "pgn_save_cancelled": (
                "Збереження PGN скасовано до публікації файла.",
                "PGN save cancelled before file publication.",
            ),
            "pgn_saved": ("PGN збережено.", "PGN saved."),
            "pgn_saved_as": ("PGN збережено.", "PGN saved."),
            "exported": ("Експорт завершено.", "Export completed."),
            "dialog_cancelled": ("Скасовано.", "Cancelled."),
        }
        message = messages.get(kind)
        if message: self._events.append({"kind": "status", "payload": {"announcement": message[self.shell.language is UILanguage.EN]}})

    def _resume_native_workers_after_refused_shutdown(self) -> None:
        """Restore retired native workers atomically or leave all of them fenced."""
        recovery_error: BaseException | None = None
        attempted: list[object] = []
        for owner in (self._book_open_worker, self._files):
            if owner is None:
                continue
            # Every bound native owner participated in retirement, so every one
            # must also have an explicit recovery contract before a refused close
            # can be called recovered. Treating a missing resume method as
            # success can leave the visible application pointing at a silently
            # retired owner.
            attempted.append(owner)
            resume = getattr(type(owner), "resume_after_refused_shutdown", None)
            if not callable(resume):
                if recovery_error is None:
                    recovery_error = RuntimeError(
                        "native worker has no refused-shutdown recovery contract"
                    )
                continue
            try:
                restored = resume(owner)
            except BaseException as error:
                if recovery_error is None:
                    recovery_error = error
            else:
                if restored is not True and recovery_error is None:
                    recovery_error = RuntimeError(
                        "native worker could not recover after refused shutdown"
                    )

        if recovery_error is None:
            # A later successful recovery supersedes any diagnostic left by an
            # earlier refused close.
            self._native_shutdown_recovery_error = None
            return

        # Reopening is one recovery transaction. If any owner cannot resume,
        # best-effort re-retire every owner we attempted so the visible
        # application never advertises a mixed live/closed native boundary.
        for owner in reversed(attempted):
            shutdown = getattr(type(owner), "shutdown", None)
            if not callable(shutdown):
                continue
            try:
                shutdown(owner, timeout=0.0)
            except BaseException:
                pass
        self._native_shutdown_recovery_error = recovery_error

    def shutdown(self, timeout: float | None = None):
        """Cancel and join native import work before closing shared application state.

        ``None`` deliberately waits for the canonical import worker to honour its
        cancellation contract.  The worker is non-daemon because abandoning an
        in-flight SQLite/import transaction on process exit is not an acceptable
        release behaviour.  Tests and recovery callers may supply a bounded
        timeout and retry without closing the database when the worker is still
        alive. Every independent native worker retirement is attempted before a
        refused/failed close is reported; shared progress and ACSDB remain untouched
        unless all workers confirm retirement. Once worker shutdown succeeds, both
        durable progress owners are attempted. Any progress failure keeps ACSDB open
        so native FormClosing can refuse the close and a later attempt can retry the
        exact owner state; only successful progress publication permits ACSDB close.
        """
        self._assert_thread()
        retirement_complete = True
        retirement_error: BaseException | None = None
        retirement_traceback = None
        for owner in (self._book_open_worker, self._files):
            if owner is None:
                continue
            try:
                retired = owner.shutdown(timeout=timeout)
            except BaseException as error:
                retirement_complete = False
                if retirement_error is None:
                    retirement_error = error
                    retirement_traceback = error.__traceback__
            else:
                if retired is not True:
                    retirement_complete = False
        if retirement_error is not None:
            self._resume_native_workers_after_refused_shutdown()
            raise retirement_error.with_traceback(retirement_traceback)
        if not retirement_complete:
            self._resume_native_workers_after_refused_shutdown()
            return False
        if self._pending_shell_publication is not None:
            # Native close/Alt+F4 can race a browser route render. An
            # unacknowledged candidate route is not user-visible authority and
            # must never become durable merely because shutdown began. Retire
            # workers first so a refused close can keep the pending browser
            # transaction alive; once shutdown may proceed, roll it back before
            # any Training or Book progress publication. A failed rollback keeps
            # its exact token retryable and must also keep shared persistence
            # open because the native close is refused.
            token = self._pending_shell_publication[0]
            try:
                self._finish_shell_publication(token, commit=False)
            except BaseException:
                self._resume_native_workers_after_refused_shutdown()
                raise
        progress_error: BaseException | None = None
        progress_traceback = None
        for save_progress in (self.save_training_progress, self.save_book_progress):
            try:
                save_progress()
            except BaseException as error:
                if progress_error is None:
                    progress_error = error
                    progress_traceback = error.__traceback__
        if progress_error is not None:
            # Native FormClosing refuses the close when durable progress cannot
            # be published. Keep ACSDB open and restore only workers that already
            # proved complete retirement, so the still-visible application does
            # not become a half-shut-down shell. Recovery errors are diagnostic
            # and never replace the primary durability failure.
            self._resume_native_workers_after_refused_shutdown()
            raise progress_error.with_traceback(progress_traceback)
        try:
            self.database.close()
        except BaseException:
            # A failed ACSDB close leaves native FormClosing in its refused-close
            # path just like a worker/progress failure. Restore only fully retired
            # native owners before propagating so a transient database-close error
            # cannot strand the still-visible application in a half-closed state.
            self._resume_native_workers_after_refused_shutdown()
            raise
        return True
