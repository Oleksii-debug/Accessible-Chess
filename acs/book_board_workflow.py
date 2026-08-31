from __future__ import annotations

"""Presentation-neutral Book -> Board/GameTree application workflow.

This coordinator intentionally owns no chess rules, PGN parsing, Library storage,
engine provider, Book navigation semantics, or Windows/WebView presentation.
It composes the existing canonical boundaries:

BookReader -> Book game-content resolver -> canonical GameTree navigation /
legality -> canonical Board -> existing EngineAssistedWorkflowService -> exact
BookReader return point.

D01 may map accessible action-registry commands onto :meth:`dispatch` without
creating a second Book/game/engine state path.  The workflow never writes a
referenced Library game and never exposes structural editing operations.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Mapping

from .book_game_content import (
    BookGameContentError,
    BookGameLookup,
    BookGameSource,
    resolve_book_game,
    resolve_book_variation,
)
from .bookdocument import Diagram, Exercise, Game, Position, VariationTree
from .bookreader import BookReader, ReadingLocation
from .chesscore import Board
from .engine_assisted_workflows import (
    AudienceAnalysisResult,
    EngineAssistedWorkflowService,
    EngineVisibility,
)
from .gametree import PgnGame
from .gametree_legality import (
    GameTreeLegalityReport,
    LegalMoveProjection,
    validate_game_legality,
)
from .gametree_navigation import (
    GameTreeCursor,
    GameTreeNavigationError,
    MoveAddress,
    advance,
    enter_variation,
    leave_variation,
    validate_cursor,
)


class BookBoardWorkflowCode(str, Enum):
    ACTIVE_SESSION = "active_session"
    NO_SESSION = "no_session"
    UNSUPPORTED_BLOCK = "unsupported_block"
    CONTENT_UNAVAILABLE = "content_unavailable"
    INVALID_POSITION = "invalid_position"
    INVALID_GAME = "invalid_game"
    NAVIGATION_UNAVAILABLE = "navigation_unavailable"
    RETURN_FAILED = "return_failed"
    INVALID_COMMAND = "invalid_command"


class BookBoardWorkflowError(ValueError):
    """Stable, provider-safe application error for the Book -> Board seam."""

    def __init__(self, message: str, *, code: BookBoardWorkflowCode) -> None:
        super().__init__(message)
        self.code = BookBoardWorkflowCode(code)


class BookBoardMode(str, Enum):
    POSITION = "position"
    GAME = "game"
    VARIATION = "variation"


class BookBoardCommand(str, Enum):
    """Application commands; D01 remains owner of user-facing action IDs."""

    OPEN_CURRENT = "book_board.open_current"
    NEXT_MOVE = "book_board.next_move"
    PREVIOUS_MOVE = "book_board.previous_move"
    ENTER_VARIATION = "book_board.enter_variation"
    LEAVE_VARIATION = "book_board.leave_variation"
    ANALYZE = "book_board.analyze"
    RETURN_TO_BOOK = "book_board.return"


@dataclass(frozen=True, slots=True)
class BookBoardView:
    mode: BookBoardMode
    origin: ReadingLocation
    current_fen: str
    cursor: GameTreeCursor | None
    source: BookGameSource | None
    game_id: int | None
    warnings: tuple[str, ...]
    revision: int


@dataclass(slots=True)
class _BookBoardSession:
    mode: BookBoardMode
    origin: ReadingLocation
    current_fen: str
    game: PgnGame | None
    cursor: GameTreeCursor | None
    legality: GameTreeLegalityReport | None
    source: BookGameSource | None
    game_id: int | None
    warnings: tuple[str, ...]


class BookBoardWorkflow:
    """One read-only Book Board session with exact semantic return.

    Game blocks and variation blocks are resolved to detached canonical
    ``PgnGame`` graphs. Navigation changes only this application session cursor;
    no GameTree edit API is exposed. Positions are materialized by canonical
    ``Board`` validation, and engine requests go exclusively through the existing
    ``EngineAssistedWorkflowService``.
    """

    _RETURN_POINT = "__book_board_workflow_origin__"

    def __init__(
        self,
        reader: BookReader,
        engine_assistance: EngineAssistedWorkflowService,
        *,
        game_lookup: BookGameLookup | None = None,
    ) -> None:
        if not isinstance(reader, BookReader):
            raise TypeError("reader must be BookReader")
        if not isinstance(engine_assistance, EngineAssistedWorkflowService):
            raise TypeError("engine_assistance must be EngineAssistedWorkflowService")
        self._reader = reader
        self._engine = engine_assistance
        self._game_lookup = game_lookup
        self._session: _BookBoardSession | None = None
        self._revision = 0
        self._lock = RLock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._session is not None

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @staticmethod
    def _error(message: str, code: BookBoardWorkflowCode) -> BookBoardWorkflowError:
        return BookBoardWorkflowError(message, code=code)

    @staticmethod
    def _canonical_fen(value: object) -> str:
        """Delegate the complete position policy to the one canonical Board."""

        # ``Board(None)`` means "start position" in the canonical constructor.
        # A Book payload is not allowed to use that convenience convention:
        # missing/corrupted semantic FEN must fail closed instead of silently
        # becoming a different chess position.
        if type(value) is not str or not value.strip():
            raise BookBoardWorkflow._error(
                "book position cannot be opened on the canonical board",
                BookBoardWorkflowCode.INVALID_POSITION,
            )
        try:
            return Board(value).fen()
        except Exception as exc:
            raise BookBoardWorkflow._error(
                "book position cannot be opened on the canonical board",
                BookBoardWorkflowCode.INVALID_POSITION,
            ) from exc

    @classmethod
    def _complete_legality(
        cls,
        game: PgnGame,
        *,
        explicit_root_fen: str | None = None,
    ) -> GameTreeLegalityReport:
        probe = game
        if explicit_root_fen is not None:
            # VariationTree keeps root FEN as semantic Book metadata.  Bind that
            # root only on a detached legality probe so the source GameTree is not
            # rewritten and the canonical legality walker remains the sole move
            # replay implementation.
            canonical_root = cls._canonical_fen(explicit_root_fen)
            probe = deepcopy(game)
            probe.tags = dict(probe.tags)
            probe.tags["SetUp"] = "1"
            probe.tags["FEN"] = canonical_root
        try:
            report = validate_game_legality(probe)
        except Exception as exc:
            raise cls._error(
                "book game cannot be opened as a canonical chess game",
                BookBoardWorkflowCode.INVALID_GAME,
            ) from exc
        if not report.complete or report.start_fen is None:
            raise cls._error(
                "book game cannot be opened as a canonical chess game",
                BookBoardWorkflowCode.INVALID_GAME,
            )
        return report

    @staticmethod
    def _projection_by_address(
        report: GameTreeLegalityReport,
    ) -> dict[MoveAddress, LegalMoveProjection]:
        return {item.address: item for item in report.moves}

    @classmethod
    def _fen_for_cursor(
        cls,
        game: PgnGame,
        report: GameTreeLegalityReport,
        cursor: GameTreeCursor,
    ) -> str:
        try:
            validate_cursor(game, cursor)
        except (TypeError, GameTreeNavigationError) as exc:
            raise cls._error(
                "book game cursor is not available",
                BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
            ) from exc
        projections = cls._projection_by_address(report)
        if cursor.next_move_index == 0:
            if not cursor.line_path:
                if report.start_fen is None:  # defensive after complete gate
                    raise cls._error(
                        "book game start position is unavailable",
                        BookBoardWorkflowCode.INVALID_GAME,
                    )
                return report.start_fen
            owner = cursor.line_path[-1]
            parent_address = MoveAddress(
                cursor.line_path[:-1], owner.parent_move_index
            )
            projection = projections.get(parent_address)
            if projection is None:
                raise cls._error(
                    "book variation start position is unavailable",
                    BookBoardWorkflowCode.INVALID_GAME,
                )
            return projection.fen_before

        previous_address = MoveAddress(
            cursor.line_path, cursor.next_move_index - 1
        )
        projection = projections.get(previous_address)
        if projection is None:
            raise cls._error(
                "book game position is unavailable at this cursor",
                BookBoardWorkflowCode.INVALID_GAME,
            )
        return projection.fen_after

    def _build_session(
        self,
        origin: ReadingLocation,
        *,
        game_source: BookGameSource | str,
    ) -> _BookBoardSession:
        block = self._reader.document.blocks[origin.index]
        if isinstance(block, Game):
            try:
                resolved = resolve_book_game(
                    block,
                    source=game_source,
                    lookup=self._game_lookup,
                )
            except BookGameContentError as exc:
                raise self._error(
                    "book game is unavailable",
                    BookBoardWorkflowCode.CONTENT_UNAVAILABLE,
                ) from exc
            report = self._complete_legality(resolved.game)
            cursor = GameTreeCursor()
            return _BookBoardSession(
                BookBoardMode.GAME,
                origin,
                self._fen_for_cursor(resolved.game, report, cursor),
                resolved.game,
                cursor,
                report,
                resolved.source,
                resolved.game_id,
                tuple(resolved.warnings),
            )

        if isinstance(block, VariationTree):
            try:
                resolved_variation = resolve_book_variation(block)
            except BookGameContentError as exc:
                raise self._error(
                    "book variation is unavailable",
                    BookBoardWorkflowCode.CONTENT_UNAVAILABLE,
                ) from exc
            report = self._complete_legality(
                resolved_variation.game,
                explicit_root_fen=resolved_variation.root_fen,
            )
            cursor = GameTreeCursor()
            return _BookBoardSession(
                BookBoardMode.VARIATION,
                origin,
                self._fen_for_cursor(resolved_variation.game, report, cursor),
                resolved_variation.game,
                cursor,
                report,
                BookGameSource.EMBEDDED,
                None,
                tuple(resolved_variation.warnings),
            )

        if isinstance(block, (Position, Diagram, Exercise)):
            fen = block.fen
            return _BookBoardSession(
                BookBoardMode.POSITION,
                origin,
                self._canonical_fen(fen),
                None,
                None,
                None,
                None,
                None,
                (),
            )

        raise self._error(
            "current book block has no board content",
            BookBoardWorkflowCode.UNSUPPORTED_BLOCK,
        )

    def _require_session(self) -> _BookBoardSession:
        if self._session is None:
            raise self._error(
                "no Book Board session is active",
                BookBoardWorkflowCode.NO_SESSION,
            )
        return self._session

    def _view_locked(self) -> BookBoardView:
        session = self._require_session()
        return BookBoardView(
            mode=session.mode,
            origin=session.origin,
            current_fen=session.current_fen,
            cursor=session.cursor,
            source=session.source,
            game_id=session.game_id,
            warnings=session.warnings,
            revision=self._revision,
        )

    def view(self) -> BookBoardView:
        with self._lock:
            return self._view_locked()

    def open_current(
        self,
        *,
        game_source: BookGameSource | str = BookGameSource.AUTO,
    ) -> BookBoardView:
        """Open the current semantic Book block without moving Book progress."""

        with self._lock:
            if self._session is not None:
                raise self._error(
                    "a Book Board session is already active",
                    BookBoardWorkflowCode.ACTIVE_SESSION,
                )
            origin = self._reader.location()
            candidate = self._build_session(origin, game_source=game_source)
            # The reader is externally owned.  Reject a concurrent cursor move
            # rather than returning to a different location later.
            if self._reader.location() != origin:
                raise self._error(
                    "book reading location changed while opening the board",
                    BookBoardWorkflowCode.RETURN_FAILED,
                )
            try:
                self._reader.save_return_point(self._RETURN_POINT)
            except Exception as exc:
                raise self._error(
                    "book return point could not be saved",
                    BookBoardWorkflowCode.RETURN_FAILED,
                ) from exc
            self._session = candidate
            self._revision += 1
            return self._view_locked()

    def board_snapshot(self) -> Board:
        """Return a detached canonical Board for Board Explorer/query consumers."""

        with self._lock:
            fen = self._require_session().current_fen
        return Board(fen)

    def game_snapshot(self) -> PgnGame:
        """Return a detached GameTree snapshot; structural editing is not exposed."""

        with self._lock:
            game = self._require_session().game
            if game is None:
                raise self._error(
                    "current Book Board session has no game tree",
                    BookBoardWorkflowCode.UNSUPPORTED_BLOCK,
                )
            return deepcopy(game)

    def _commit_cursor(self, cursor: GameTreeCursor) -> BookBoardView:
        session = self._require_session()
        if session.game is None or session.legality is None:
            raise self._error(
                "current Book Board session has no game navigation",
                BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
            )
        fen = self._fen_for_cursor(session.game, session.legality, cursor)
        session.cursor = cursor
        session.current_fen = fen
        self._revision += 1
        return self._view_locked()

    def next_move(self) -> BookBoardView:
        with self._lock:
            session = self._require_session()
            if session.game is None or session.cursor is None:
                raise self._error(
                    "current Book Board session has no game navigation",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                )
            try:
                cursor = advance(session.game, session.cursor)
            except GameTreeNavigationError as exc:
                raise self._error(
                    "already at the end of this book line",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                ) from exc
            return self._commit_cursor(cursor)

    def previous_move(self) -> BookBoardView:
        with self._lock:
            session = self._require_session()
            if session.game is None or session.cursor is None:
                raise self._error(
                    "current Book Board session has no game navigation",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                )
            try:
                validate_cursor(session.game, session.cursor)
            except GameTreeNavigationError as exc:
                raise self._error(
                    "book game cursor is not available",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                ) from exc
            if session.cursor.next_move_index == 0:
                raise self._error(
                    "already at the start of this book line",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                )
            cursor = GameTreeCursor(
                session.cursor.line_path,
                session.cursor.next_move_index - 1,
            )
            return self._commit_cursor(cursor)

    def enter_variation(self, variation_index: int = 0) -> BookBoardView:
        with self._lock:
            session = self._require_session()
            if session.game is None or session.cursor is None:
                raise self._error(
                    "current Book Board session has no variation navigation",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                )
            try:
                cursor = enter_variation(
                    session.game, session.cursor, variation_index
                )
            except (TypeError, ValueError, GameTreeNavigationError) as exc:
                raise self._error(
                    "requested book variation is unavailable",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                ) from exc
            return self._commit_cursor(cursor)

    def leave_variation(self) -> BookBoardView:
        with self._lock:
            session = self._require_session()
            if session.game is None or session.cursor is None:
                raise self._error(
                    "current Book Board session has no variation navigation",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                )
            try:
                cursor = leave_variation(session.game, session.cursor)
            except GameTreeNavigationError as exc:
                raise self._error(
                    "current book line has no parent variation",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                ) from exc
            return self._commit_cursor(cursor)

    def go_to_cursor(self, cursor: GameTreeCursor) -> BookBoardView:
        """Use the canonical immutable cursor for direct accessible navigation."""

        with self._lock:
            session = self._require_session()
            if session.game is None:
                raise self._error(
                    "current Book Board session has no game navigation",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                )
            try:
                canonical = validate_cursor(session.game, cursor)
            except (TypeError, GameTreeNavigationError) as exc:
                raise self._error(
                    "book game cursor is not available",
                    BookBoardWorkflowCode.NAVIGATION_UNAVAILABLE,
                ) from exc
            return self._commit_cursor(canonical)

    def _revision_provider(self) -> int:
        with self._lock:
            return self._revision

    def analyze(
        self,
        *,
        multipv: int = 5,
        depth: int = 16,
    ) -> AudienceAnalysisResult:
        """Analyze current Board FEN as application state, never as Book mutation."""

        with self._lock:
            session = self._require_session()
            fen = session.current_fen
            expected_revision = self._revision
        return self._engine.analyze_teacher(
            fen,
            visibility=EngineVisibility.VISIBLE_TO_TEACHER,
            context_revision=expected_revision,
            revision_provider=self._revision_provider,
            multipv=multipv,
            depth=depth,
        )

    def return_to_book(self) -> ReadingLocation:
        """Restore the exact durable BookReader origin and close the board session."""

        with self._lock:
            self._require_session()
            try:
                restored = self._reader.restore_return_point(self._RETURN_POINT)
            except Exception as exc:
                # Keep the session alive if its Book revision changed; silently
                # dropping it would destroy the user's only deterministic return.
                raise self._error(
                    "original book reading location is unavailable",
                    BookBoardWorkflowCode.RETURN_FAILED,
                ) from exc
            self._session = None
            self._revision += 1
        # Suppress any in-flight assisted result after the Board context closes.
        self._engine.invalidate()
        return restored

    @staticmethod
    def _command(value: BookBoardCommand | str) -> BookBoardCommand:
        if isinstance(value, BookBoardCommand):
            return value
        if type(value) is not str:
            raise BookBoardWorkflow._error(
                "Book Board command is invalid",
                BookBoardWorkflowCode.INVALID_COMMAND,
            )
        try:
            return BookBoardCommand(value)
        except ValueError as exc:
            raise BookBoardWorkflow._error(
                "Book Board command is unsupported",
                BookBoardWorkflowCode.INVALID_COMMAND,
            ) from exc

    @classmethod
    def _payload(
        cls,
        payload: Mapping[str, object] | None,
        *,
        allowed: frozenset[str],
    ) -> dict[str, object]:
        if payload is None:
            return {}
        if not isinstance(payload, Mapping):
            raise cls._error(
                "Book Board command payload must be a mapping",
                BookBoardWorkflowCode.INVALID_COMMAND,
            )
        data = dict(payload)
        if any(type(key) is not str for key in data):
            raise cls._error(
                "Book Board command payload keys must be text",
                BookBoardWorkflowCode.INVALID_COMMAND,
            )
        if set(data) - allowed:
            raise cls._error(
                "Book Board command payload contains unsupported fields",
                BookBoardWorkflowCode.INVALID_COMMAND,
            )
        return data

    def dispatch(
        self,
        command: BookBoardCommand | str,
        payload: Mapping[str, object] | None = None,
    ) -> BookBoardView | AudienceAnalysisResult | ReadingLocation:
        """Strict application router for a future D01 accessible action adapter."""

        selected = self._command(command)
        if selected is BookBoardCommand.OPEN_CURRENT:
            data = self._payload(payload, allowed=frozenset({"source"}))
            return self.open_current(
                game_source=data.get("source", BookGameSource.AUTO)  # type: ignore[arg-type]
            )
        if selected is BookBoardCommand.ENTER_VARIATION:
            data = self._payload(payload, allowed=frozenset({"variation_index"}))
            index = data.get("variation_index", 0)
            if type(index) is not int or index < 0:
                raise self._error(
                    "variation_index must be a non-negative exact integer",
                    BookBoardWorkflowCode.INVALID_COMMAND,
                )
            return self.enter_variation(index)
        if selected is BookBoardCommand.ANALYZE:
            data = self._payload(payload, allowed=frozenset({"multipv", "depth"}))
            multipv = data.get("multipv", 5)
            depth = data.get("depth", 16)
            if type(multipv) is not int or type(depth) is not int:
                raise self._error(
                    "analysis limits must be exact integers",
                    BookBoardWorkflowCode.INVALID_COMMAND,
                )
            return self.analyze(multipv=multipv, depth=depth)

        self._payload(payload, allowed=frozenset())
        if selected is BookBoardCommand.NEXT_MOVE:
            return self.next_move()
        if selected is BookBoardCommand.PREVIOUS_MOVE:
            return self.previous_move()
        if selected is BookBoardCommand.LEAVE_VARIATION:
            return self.leave_variation()
        if selected is BookBoardCommand.RETURN_TO_BOOK:
            return self.return_to_book()
        raise self._error(  # pragma: no cover - enum exhaustiveness
            "Book Board command is unsupported",
            BookBoardWorkflowCode.INVALID_COMMAND,
        )
