"""Accessible full-product presenters over canonical application/domain services.

These adapters do not implement chess rules, GameTree mutation, database queries,
or training correctness. They project existing canonical state into concise
keyboard/NVDA-friendly view models and dispatch mutation intents through stable
application action IDs.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from .bookdocument import Diagram, Exercise, Game, Heading, ListBlock, Note, Paragraph, Position, VariationTree
from .bookreader import BookReader, ReadingLocation
from .full_product_ui_shell import UILanguage, concise_user_error
from .gametree import PgnGame, VariationLine
from .notation import NotationError, format_accessible_compact_san
from .pgn_presenter_graph_guard import (
    snapshot_pgn_presentation_games,
    validate_pgn_presentation_graph,
)
from .search_service import GameSearchItem, GameSearchPage, GameSearchQuery, GameSearchService
from .training import ExerciseResult, ExerciseSession, ExerciseStatus, HintResult

CommandDispatch = Callable[[str, Mapping[str, object]], Any]


class SurfaceStatus(str, Enum):
    READY = "ready"
    LOADING = "loading"
    EMPTY = "empty"
    ERROR = "error"


_MAX_LIBRARY_PROVIDER_TEXT = 65536
_MAX_LIBRARY_BROWSER_INTEGER = (1 << 53) - 1
_MAX_LIBRARY_STORAGE_INTEGER = (1 << 63) - 1


def _canonical_library_text(
    value: object,
    *,
    name: str,
    optional: bool,
) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        suffix = " or null" if optional else ""
        raise TypeError(f"library {name} must be text{suffix}")
    if len(value) > _MAX_LIBRARY_PROVIDER_TEXT:
        raise ValueError(f"library {name} exceeds the presentation text budget")
    return value


def _canonical_library_item(item: object) -> GameSearchItem:
    """Copy one provider-owned search DTO into passive presenter-owned data."""
    if type(item) is not GameSearchItem:
        raise TypeError("library search item must be GameSearchItem")

    for name, minimum, maximum in (
        ("game_id", 1, _MAX_LIBRARY_BROWSER_INTEGER),
        ("source_id", 1, _MAX_LIBRARY_STORAGE_INTEGER),
        ("source_index", 0, _MAX_LIBRARY_STORAGE_INTEGER),
    ):
        value = getattr(item, name)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"library {name} is invalid")

    required = {
        "source_name": _canonical_library_text(
            item.source_name, name="source_name", optional=False
        ),
        "source_format": _canonical_library_text(
            item.source_format, name="source_format", optional=False
        ),
        "import_status": _canonical_library_text(
            item.import_status, name="import_status", optional=False
        ),
    }
    optional = {
        name: _canonical_library_text(
            getattr(item, name),
            name=name,
            optional=True,
        )
        for name in (
            "white",
            "black",
            "event",
            "site",
            "game_date",
            "round",
            "result",
            "eco",
            "opening",
            "start_fen",
        )
    }
    return GameSearchItem(
        game_id=item.game_id,
        source_id=item.source_id,
        source_name=required["source_name"],
        source_format=required["source_format"],
        source_index=item.source_index,
        import_status=required["import_status"],
        white=optional["white"],
        black=optional["black"],
        event=optional["event"],
        site=optional["site"],
        game_date=optional["game_date"],
        round=optional["round"],
        result=optional["result"],
        eco=optional["eco"],
        opening=optional["opening"],
        start_fen=optional["start_fen"],
    )


def _canonical_library_page(
    page: object,
    *,
    query: GameSearchQuery,
) -> GameSearchPage:
    """Validate and detach one canonical keyset page before presenter commit."""
    if type(page) is not GameSearchPage:
        raise TypeError("library search provider must return GameSearchPage")
    if type(page.items) is not tuple:
        raise TypeError("library search page items must be a tuple")
    if len(page.items) > query.limit:
        raise ValueError("library search page exceeds the requested limit")
    if type(page.has_more) is not bool:
        raise TypeError("library search page has_more must be boolean")

    items = tuple(_canonical_library_item(item) for item in page.items)
    previous_id = 0
    for item in items:
        if item.game_id <= previous_id:
            raise ValueError("library search page game ids must be strictly increasing")
        previous_id = item.game_id

    cursor = page.next_after_game_id
    if page.has_more:
        if not items:
            raise ValueError("library search continuation requires a non-empty page")
        if type(cursor) is not int or cursor != items[-1].game_id:
            raise ValueError("library search continuation cursor is inconsistent")
    elif cursor is not None:
        raise ValueError("terminal library search page must not expose a cursor")

    return GameSearchPage(
        items=items,
        next_after_game_id=cursor,
        has_more=page.has_more,
    )


def _safe_source_label(value: object) -> str:
    """Keep useful source identity without projecting local directory paths."""
    if type(value) is not str:
        raise TypeError("library source label must be text")
    if len(value) > _MAX_LIBRARY_PROVIDER_TEXT:
        raise ValueError("library source label exceeds the presentation text budget")
    text = value.strip()
    if not text:
        return ""
    if "/" in text or "\\" in text:
        text = text.replace("\\", "/").rsplit("/", 1)[-1]
    return text[:120]


def _localized(language: UILanguage, uk: str, en: str) -> str:
    return uk if language is UILanguage.UA else en


def _pgn_accessible_move_label(san: str, language: UILanguage) -> str:
    """Project valid SAN through the shared NVDA formatter without losing recovery text."""
    try:
        return format_accessible_compact_san(
            san,
            "en" if language is UILanguage.EN else "uk",
        )
    except NotationError:
        prefix = _localized(
            language,
            "Необроблений запис ходу",
            "Unparsed move text",
        )
        return f"{prefix}: {san}"


@dataclass(frozen=True, slots=True)
class PgnTreeItem:
    node_id: str
    kind: str
    depth: int
    label: str
    parent_id: str | None
    san: str | None = None
    comments: tuple[str, ...] = ()
    nags: tuple[str, ...] = ()
    trailing_comments: tuple[str, ...] = ()
    comments_before: tuple[str, ...] = ()
    comments_after: tuple[str, ...] = ()
    result: str | None = None


@dataclass(frozen=True, slots=True)
class PgnGameView:
    game_index: int
    title: str
    result: str
    tags: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...]
    items: tuple[PgnTreeItem, ...]
    selected_node_id: str | None
    leading_comments: tuple[str, ...] = ()
    trailing_comments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PgnPresenterState:
    """Rollback-only state for one not-yet-published browser transition."""

    language: UILanguage
    game_index: int
    selected_node_id: str | None
    items: tuple[PgnTreeItem, ...]


class PgnTreePresenter:
    """Read-only recursive projection plus canonical edit-command dispatch.

    The presenter never edits :class:`PgnGame` or :class:`VariationLine`
    directly. Edit/delete/promote/export operations are emitted as stable
    application command intents for the canonical GameTree command layer.
    """

    _EDIT_ACTIONS = frozenset(
        {
            "pgn.search",
            "pgn.comment_edit",
            "pgn.comment_delete",
            "pgn.nag_edit",
            "pgn.variation_add",
            "pgn.variation_delete",
            "pgn.variation_promote",
            "pgn.copy_selection",
            "pgn.export_selection",
        }
    )

    def __init__(
        self,
        games: tuple[PgnGame, ...] | list[PgnGame],
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if type(language) is not UILanguage:
            raise TypeError("PGN presenter language must be UILanguage")
        self._games = snapshot_pgn_presentation_games(games)
        self._language = language
        self._game_index = 0 if self._games else -1
        self._selected_node_id: str | None = None
        self._items: tuple[PgnTreeItem, ...] = ()
        self._rebuild()

    @property
    def game_index(self) -> int:
        return self._game_index

    @property
    def selected_node_id(self) -> str | None:
        return self._selected_node_id

    @property
    def status(self) -> SurfaceStatus:
        return SurfaceStatus.READY if self._games else SurfaceStatus.EMPTY

    def _capture_presentation_state(self) -> _PgnPresenterState:
        """Capture transient PGN cursor/locale state for WebView publication rollback."""
        return _PgnPresenterState(
            language=self._language,
            game_index=self._game_index,
            selected_node_id=self._selected_node_id,
            items=self._items,
        )

    def _restore_presentation_state(self, state: _PgnPresenterState) -> None:
        if type(state) is not _PgnPresenterState:
            raise TypeError("PGN presentation rollback state is invalid")
        self._language = state.language
        self._game_index = state.game_index
        self._selected_node_id = state.selected_node_id
        self._items = state.items

    def set_language(self, language: UILanguage) -> None:
        """Rebuild localized labels transactionally before publishing the locale."""

        if type(language) is not UILanguage:
            raise TypeError("PGN presenter language must be UILanguage")
        items, selected = self._build_items(
            game_index=self._game_index,
            language=language,
            selected_node_id=self._selected_node_id,
        )
        self._items = items
        self._selected_node_id = selected
        self._language = language

    def select_game(self, index: int) -> PgnGameView:
        """Select one game without publishing a half-rebuilt presenter state."""

        if type(index) is not int:
            raise TypeError("PGN game index must be an exact integer")
        if not 0 <= index < len(self._games):
            raise IndexError("PGN game index is outside the collection")
        items, selected = self._build_items(
            game_index=index,
            language=self._language,
            selected_node_id=None,
        )
        self._game_index = index
        self._items = items
        self._selected_node_id = selected
        return self.view()

    def next_game(self) -> PgnGameView:
        return self.select_game(self._game_index + 1)

    def previous_game(self) -> PgnGameView:
        return self.select_game(self._game_index - 1)

    def _build_items(
        self,
        *,
        game_index: int,
        language: UILanguage,
        selected_node_id: str | None,
    ) -> tuple[tuple[PgnTreeItem, ...], str | None]:
        """Build one complete candidate tree without mutating live presentation state."""

        if game_index < 0:
            return (), None
        game = self._games[game_index]
        validate_pgn_presentation_graph(game)
        items: list[PgnTreeItem] = []
        self._append_line(
            game.line,
            items,
            line_id=f"g{game_index}:main",
            parent_id=None,
            depth=0,
            variation_label=None,
            language=language,
        )
        frozen = tuple(items)
        ids = {item.node_id for item in frozen}
        if selected_node_id not in ids:
            selected_node_id = frozen[0].node_id if frozen else None
        return frozen, selected_node_id

    def _rebuild(self) -> None:
        items, selected = self._build_items(
            game_index=self._game_index,
            language=self._language,
            selected_node_id=self._selected_node_id,
        )
        self._items = items
        self._selected_node_id = selected

    def _append_line(
        self,
        line: VariationLine,
        out: list[PgnTreeItem],
        *,
        line_id: str,
        parent_id: str | None,
        depth: int,
        variation_label: str | None,
        language: UILanguage,
    ) -> None:
        if variation_label is not None:
            out.append(
                PgnTreeItem(
                    node_id=line_id,
                    kind="variation",
                    depth=depth,
                    label=variation_label,
                    parent_id=parent_id,
                    comments=tuple(comment.text for comment in line.leading_comments),
                    trailing_comments=tuple(
                        comment.text for comment in line.trailing_comments
                    ),
                    result=line.result,
                )
            )
            parent_id = line_id
            depth += 1
        for move_index, move in enumerate(line.moves):
            node_id = f"{line_id}/m{move_index}"
            number = f"{move.move_number} " if move.move_number else ""
            comments_before = tuple(
                comment.text
                for comment in move.comments_before
                if comment.text.strip()
            )
            comments_after = tuple(
                comment.text
                for comment in move.comments_after
                if comment.text.strip()
            )
            # Preserve the historical aggregate for PGN editing callers while
            # exposing exact before/after slots to read-only semantic readers.
            comments = comments_before + comments_after
            annotation = " ".join(move.nags)
            accessible_move = _pgn_accessible_move_label(move.san, language)
            label = f"{number}{accessible_move}"
            if annotation:
                label += f" {annotation}"
            out.append(
                PgnTreeItem(
                    node_id=node_id,
                    kind="move",
                    depth=depth,
                    label=label,
                    parent_id=parent_id,
                    san=move.san,
                    comments=comments,
                    nags=tuple(move.nags),
                    comments_before=comments_before,
                    comments_after=comments_after,
                )
            )
            for variation_index, variation in enumerate(move.variations):
                self._append_line(
                    variation,
                    out,
                    line_id=f"{node_id}/v{variation_index}",
                    parent_id=node_id,
                    depth=depth + 1,
                    variation_label=_localized(
                        language,
                        f"Варіант {variation_index + 1}",
                        f"Variation {variation_index + 1}",
                    ),
                    language=language,
                )

    def items(self) -> tuple[PgnTreeItem, ...]:
        return self._items

    def select(self, node_id: str) -> PgnTreeItem:
        for item in self._items:
            if item.node_id == node_id:
                self._selected_node_id = node_id
                return item
        raise LookupError("Unknown GameTree presentation node")

    def selected(self) -> PgnTreeItem | None:
        if self._selected_node_id is None:
            return None
        return next(
            (item for item in self._items if item.node_id == self._selected_node_id),
            None,
        )

    def move_selection(self, delta: int) -> PgnTreeItem:
        if type(delta) is not int or delta not in {-1, 1}:
            raise ValueError("selection delta must be -1 or 1")
        if not self._items:
            raise LookupError("PGN has no selectable GameTree items")
        current = self.selected()
        index = self._items.index(current) if current is not None else 0
        target = index + delta
        if not 0 <= target < len(self._items):
            raise LookupError("GameTree selection boundary")
        return self.select(self._items[target].node_id)

    def select_parent(self) -> PgnTreeItem:
        current = self.selected()
        if current is None or current.parent_id is None:
            raise LookupError("Selected GameTree item has no parent")
        return self.select(current.parent_id)

    def view(self) -> PgnGameView:
        if self._game_index < 0:
            return PgnGameView(-1, "", "*", (), (), (), None)
        game = self._games[self._game_index]
        white = game.tags.get("White", "?")
        black = game.tags.get("Black", "?")
        title = f"{white} — {black}"
        return PgnGameView(
            game_index=self._game_index,
            title=title,
            result=game.result,
            tags=tuple(game.tags.items()),
            warnings=tuple(game.warnings),
            items=self._items,
            selected_node_id=self._selected_node_id,
            leading_comments=tuple(comment.text for comment in game.line.leading_comments),
            trailing_comments=tuple(comment.text for comment in game.line.trailing_comments),
        )

    def dispatch_edit(
        self,
        action_id: str,
        dispatch: CommandDispatch,
        *,
        extra: Mapping[str, object] | None = None,
    ) -> Any:
        if action_id not in self._EDIT_ACTIONS:
            raise ValueError("unsupported PGN presentation edit action")
        if not callable(dispatch):
            raise TypeError("PGN command dispatcher must be callable")
        payload: dict[str, object] = {
            "game_index": self._game_index,
            "node_id": self._selected_node_id or "",
        }
        payload.update(dict(extra or {}))
        return dispatch(action_id, payload)


@dataclass(frozen=True, slots=True)
class LibraryRowView:
    game_id: int
    label: str
    source_label: str
    result: str
    selected: bool


@dataclass(frozen=True, slots=True)
class LibraryView:
    status: SurfaceStatus
    rows: tuple[LibraryRowView, ...]
    selected_game_id: int | None
    has_previous_page: bool
    has_next_page: bool
    message: str = ""


@dataclass(frozen=True, slots=True)
class _LibraryPresenterState:
    """Rollback-only snapshot of presentation state, never domain/search state."""

    language: UILanguage
    pages: tuple[tuple[GameSearchQuery, GameSearchPage], ...]
    page_index: int
    selected_game_id: int | None
    status: SurfaceStatus
    message: str


class LibraryPresenter:
    """Keyboard-stable page/selection projection over :class:`GameSearchService`."""

    def __init__(
        self,
        service: GameSearchService,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        self._service = service
        self._language = language
        self._pages: list[tuple[GameSearchQuery, GameSearchPage]] = []
        self._page_index = -1
        self._selected_game_id: int | None = None
        self._status = SurfaceStatus.EMPTY
        self._message = ""

    @property
    def selected_game_id(self) -> int | None:
        return self._selected_game_id

    def _capture_presentation_state(self) -> _LibraryPresenterState:
        """Capture only browser-visible mutable state for failed-render rollback."""
        return _LibraryPresenterState(
            language=self._language,
            pages=tuple(self._pages),
            page_index=self._page_index,
            selected_game_id=self._selected_game_id,
            status=self._status,
            message=self._message,
        )

    def _restore_presentation_state(self, state: _LibraryPresenterState) -> None:
        if type(state) is not _LibraryPresenterState:
            raise TypeError("library presentation rollback state is invalid")
        self._language = state.language
        self._pages = list(state.pages)
        self._page_index = state.page_index
        self._selected_game_id = state.selected_game_id
        self._status = state.status
        self._message = state.message

    def set_language(self, language: UILanguage) -> None:
        if type(language) is not UILanguage:
            raise TypeError("library presenter language must be UILanguage")
        self._language = language

    def search(self, query: GameSearchQuery | None = None) -> LibraryView:
        if query is None:
            q = GameSearchQuery().normalized()
        elif type(query) is GameSearchQuery:
            q = query.normalized()
        else:
            raise TypeError("library search query must be GameSearchQuery")

        previous = self._capture_presentation_state()
        self._status = SurfaceStatus.LOADING
        self._message = ""
        try:
            raw_page = self._service.search(q)
        except Exception as exc:
            self._pages = []
            self._page_index = -1
            self._selected_game_id = None
            self._status = SurfaceStatus.ERROR
            self._message = concise_user_error(exc, language=self._language)
            return self.view()
        except BaseException:
            self._restore_presentation_state(previous)
            raise

        try:
            page = _canonical_library_page(raw_page, query=q)
        except BaseException:
            self._restore_presentation_state(previous)
            raise

        self._pages = [(q, page)]
        self._page_index = 0
        self._status = SurfaceStatus.READY if page.items else SurfaceStatus.EMPTY
        self._stabilize_selection(page)
        return self.view()

    def _stabilize_selection(self, page: GameSearchPage) -> None:
        ids = {item.game_id for item in page.items}
        if self._selected_game_id not in ids:
            self._selected_game_id = page.items[0].game_id if page.items else None

    def current_page(self) -> GameSearchPage | None:
        if self._page_index < 0:
            return None
        return self._pages[self._page_index][1]

    def next_page(self) -> LibraryView:
        current = self.current_page()
        if current is None or not current.has_more or current.next_after_game_id is None:
            raise LookupError("No next library page")
        if self._page_index + 1 < len(self._pages):
            self._page_index += 1
            cached = self.current_page()
            if cached is None:
                raise RuntimeError("library page cache is inconsistent")
            self._stabilize_selection(cached)
            return self.view()
        query = replace(
            self._pages[self._page_index][0],
            after_game_id=current.next_after_game_id,
        )
        previous = self._capture_presentation_state()
        self._status = SurfaceStatus.LOADING
        try:
            raw_page = self._service.search(query)
        except Exception as exc:
            self._status = SurfaceStatus.ERROR
            self._message = concise_user_error(exc, language=self._language)
            return self.view()
        except BaseException:
            self._restore_presentation_state(previous)
            raise

        try:
            page = _canonical_library_page(raw_page, query=query)
        except BaseException:
            self._restore_presentation_state(previous)
            raise

        self._pages.append((query, page))
        self._page_index += 1
        self._status = SurfaceStatus.READY if page.items else SurfaceStatus.EMPTY
        self._message = ""
        self._stabilize_selection(page)
        return self.view()

    def previous_page(self) -> LibraryView:
        if self._page_index <= 0:
            raise LookupError("No previous library page")
        self._page_index -= 1
        self._status = SurfaceStatus.READY
        self._message = ""
        page = self.current_page()
        if page is None:
            raise RuntimeError("library page cache is inconsistent")
        self._stabilize_selection(page)
        return self.view()

    def select(self, game_id: int) -> LibraryView:
        if (
            type(game_id) is not int
            or game_id <= 0
            or game_id > _MAX_LIBRARY_BROWSER_INTEGER
        ):
            raise ValueError("library game id must be a browser-safe positive integer")
        page = self.current_page()
        if page is None or game_id not in {item.game_id for item in page.items}:
            raise LookupError("Game is not present on the current library page")
        self._selected_game_id = game_id
        return self.view()

    def selected_item(self) -> GameSearchItem | None:
        page = self.current_page()
        if page is None or self._selected_game_id is None:
            return None
        return next(
            (item for item in page.items if item.game_id == self._selected_game_id),
            None,
        )

    def open_selected(self, dispatch: CommandDispatch) -> Any:
        item = self.selected_item()
        if item is None:
            raise LookupError("No library game is selected")
        return dispatch(
            "library.open_game",
            {
                "game_id": item.game_id,
                "source_id": item.source_id,
                "source_index": item.source_index,
            },
        )

    def _row(self, item: GameSearchItem) -> LibraryRowView:
        if type(item) is not GameSearchItem:
            raise TypeError("library cached search item is invalid")
        white = item.white or _localized(self._language, "невідомо", "unknown")
        black = item.black or _localized(self._language, "невідомо", "unknown")
        result = item.result or "*"
        event = f", {item.event}" if item.event else ""
        label = f"{white} — {black}, {result}{event}"
        return LibraryRowView(
            game_id=item.game_id,
            label=label,
            source_label=_safe_source_label(item.source_name),
            result=result,
            selected=item.game_id == self._selected_game_id,
        )

    def view(self) -> LibraryView:
        page = self.current_page()
        rows = tuple(self._row(item) for item in page.items) if page else ()
        return LibraryView(
            status=self._status,
            rows=rows,
            selected_game_id=self._selected_game_id,
            has_previous_page=self._page_index > 0,
            has_next_page=bool(page and page.has_more),
            message=self._message,
        )


@dataclass(frozen=True, slots=True)
class BookBlockView:
    index: int
    kind: str
    role: str
    title: str
    text: str
    heading_level: int | None
    position_fen: str | None
    heading_path: tuple[str, ...]
    source_anchor: str
    warning: str = ""
    list_items: tuple[str, ...] = ()
    list_ordered: bool = False
    list_start: int | None = None


class BookReaderPresenter:
    """Semantic book projection over the canonical :class:`BookReader` cursor."""

    _BOARD_RETURN_POINT = "__full_product_board_return__"
    _MAX_DOCUMENT_WARNING_ITEMS = 4
    _MAX_DOCUMENT_WARNING_ITEM_CHARS = 180

    def __init__(
        self,
        reader: BookReader,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        # BookReader is the canonical semantic cursor authority. Reject
        # subclasses before any overridable warning/navigation method can run.
        if type(reader) is not BookReader:
            raise TypeError("book presenter reader must be BookReader")
        self._reader = reader
        self._language = language
        self._document_warning_count = BookReader.document_warning_count(reader)
        warnings = BookReader.document_warnings_snapshot(
            reader,
            limit=self._MAX_DOCUMENT_WARNING_ITEMS,
        )
        if type(warnings) is not tuple or any(type(item) is not str for item in warnings):
            raise TypeError("BookDocument warnings must remain built-in text")
        # Bind presentation to BookReader's indexed document snapshot rather than
        # the mutable authoring document. Keep only the presentation-owned prefix
        # so rendering never copies or normalizes an unbounded warning collection.
        self._document_warnings = warnings

    def set_language(self, language: UILanguage) -> None:
        self._language = language

    @property
    def cursor_index(self) -> int:
        """Expose the transient canonical cursor for presentation transactions."""
        return self._reader.index

    def restore_cursor(self, index: int) -> None:
        """Restore a presentation transaction through BookReader's canonical API."""
        BookReader.go_to(self._reader, index)

    def _document_warning_summary(self) -> str:
        if not self._document_warnings:
            return ""
        shown: list[str] = []
        for raw in self._document_warnings[: self._MAX_DOCUMENT_WARNING_ITEMS]:
            # Check length before any normalization so one malformed but still
            # built-in string cannot make presentation scan unbounded content.
            was_truncated = len(raw) > self._MAX_DOCUMENT_WARNING_ITEM_CHARS
            if was_truncated:
                raw = raw[: self._MAX_DOCUMENT_WARNING_ITEM_CHARS]
            text = " ".join(raw.split())
            if text:
                shown.append(text)
            elif was_truncated:
                shown.append(
                    _localized(
                        self._language,
                        "текст попередження приховано після надмірних початкових пробілів",
                        "warning text omitted after excessive leading whitespace",
                    )
                )
        if not shown:
            return ""
        hidden = max(
            0,
            self._document_warning_count - len(self._document_warnings),
        )
        prefix = _localized(self._language, "Попередження імпорту", "Import warnings")
        summary = f"{prefix}: " + "; ".join(shown)
        if hidden:
            summary += _localized(
                self._language,
                f"; ще {hidden} попереджень",
                f"; {hidden} more warnings",
            )
        return summary

    def _block_view(self, location: ReadingLocation) -> BookBlockView:
        block = BookReader.block_snapshot(self._reader, location.index)
        role = "group"
        title = ""
        text = ""
        heading_level: int | None = None
        warning = ""
        list_items: tuple[str, ...] = ()
        list_ordered = False
        list_start: int | None = None
        if isinstance(block, Heading):
            role = "heading"
            title = block.text
            text = block.text
            heading_level = block.level
        elif isinstance(block, Paragraph):
            role = "paragraph"
            text = block.text
        elif isinstance(block, ListBlock):
            role = "list"
            list_items = tuple(block.items)
            list_ordered = block.ordered
            list_start = block.start
        elif isinstance(block, Diagram):
            role = "img"
            title = block.caption or _localized(self._language, "Діаграма", "Diagram")
            text = block.alt_text or title
            if not block.alt_text:
                warning = _localized(
                    self._language,
                    "Для діаграми немає окремого опису; позиція доступна на шахівниці.",
                    "No separate diagram description; the position is available on the board.",
                )
        elif isinstance(block, Position):
            role = "group"
            title = block.caption or _localized(self._language, "Позиція", "Position")
            text = block.side_to_move_note or title
        elif isinstance(block, Game):
            role = "group"
            title = block.title or _localized(self._language, "Партія", "Game")
            text = title
        elif isinstance(block, VariationTree):
            # Until the structured semantic GameTree projection is converged into
            # this lineage, expose the flat summary as a read-only group rather
            # than claiming an interactive ARIA tree contract.
            role = "group"
            title = block.title or _localized(self._language, "Дерево варіантів", "Variation tree")
            text = title
        elif isinstance(block, Exercise):
            role = "group"
            title = _localized(self._language, "Вправа", "Exercise")
            text = block.prompt
        elif isinstance(block, Note):
            role = "note"
            title = _localized(self._language, "Примітка", "Note")
            text = block.text
        document_warning = BookReaderPresenter._document_warning_summary(self)
        if document_warning:
            warning = f"{warning} {document_warning}".strip()
        return BookBlockView(
            index=location.index,
            kind=location.kind,
            role=role,
            title=title,
            text=text,
            heading_level=heading_level,
            position_fen=location.position_fen,
            heading_path=location.heading_path,
            source_anchor=_safe_source_label(location.source_anchor),
            warning=warning,
            list_items=list_items,
            list_ordered=list_ordered,
            list_start=list_start,
        )

    def current(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.location(self._reader))

    def next_block(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.next_block(self._reader))

    def previous_block(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.previous_block(self._reader))

    def next_heading(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.next_heading(self._reader))

    def previous_heading(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.previous_heading(self._reader))

    def next_position(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.next_position(self._reader))

    def previous_position(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.previous_position(self._reader))

    def next_game(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.next_game(self._reader))

    def previous_game(self) -> BookBlockView:
        return BookReaderPresenter._block_view(self, BookReader.previous_game(self._reader))

    def navigation_availability(self) -> dict[str, bool]:
        return BookReader.navigation_availability(self._reader)

    def bookmark(self, name: str = "default") -> BookBlockView:
        return BookReaderPresenter._block_view(
            self,
            BookReader.save_return_point(self._reader, name),
        )

    def restore_bookmark(self, name: str = "default") -> BookBlockView:
        return BookReaderPresenter._block_view(
            self,
            BookReader.restore_return_point(self._reader, name),
        )

    def open_current_position(self, dispatch: CommandDispatch) -> Any:
        current = BookReaderPresenter.current(self)
        if current.position_fen is None:
            raise LookupError("Current book block has no board position")
        with BookReader.provisional_return_point(self._reader, self._BOARD_RETURN_POINT):
            return dispatch(
                "book.open_position",
                {
                    "fen": current.position_fen,
                    "book_index": current.index,
                },
            )

    def open_current_game(self, dispatch: CommandDispatch) -> Any:
        current = BookReaderPresenter.current(self)
        if current.kind != "Game":
            raise LookupError("Current book block is not a game")
        with BookReader.provisional_return_point(self._reader, self._BOARD_RETURN_POINT):
            return dispatch("book.open_game", {})

    def return_from_board(self) -> BookBlockView:
        return BookReaderPresenter.restore_bookmark(self, self._BOARD_RETURN_POINT)


@dataclass(frozen=True, slots=True)
class TrainingView:
    status: ExerciseStatus
    title: str
    step_number: int
    total_steps: int
    attempts: int
    mistakes: int
    hints_used: int
    completed: bool
    message: str = ""


class TrainingPresenter:
    """Explicit-action feedback over the canonical :class:`ExerciseSession`."""

    _PRESENTATION_MESSAGES = {
        "completed": ("Вправу завершено.", "Exercise completed."),
        "accepted": ("Правильно. Наступний крок.", "Correct. Next step."),
        "retry": ("Спробуйте ще раз.", "Try again."),
        "no_hint": (
            "Підказки для цього кроку немає.",
            "No hint is available for this step.",
        ),
        "revealed": ("Розв’язок показано.", "Solution revealed."),
    }

    def __init__(
        self,
        session: ExerciseSession,
        *,
        language: UILanguage = UILanguage.UA,
        message: str = "",
        message_key: str | None = None,
    ) -> None:
        # ExerciseSession is the canonical mutable Training-state authority.
        # Reject subclasses before any overridable state/snapshot hook can run.
        if type(session) is not ExerciseSession:
            raise TypeError("training presenter session must be ExerciseSession")
        if not isinstance(language, UILanguage):
            raise TypeError("training presenter language must be UILanguage")
        self._validate_message(message)
        self._validate_message_key(message_key)
        self._session = session
        self._language = language
        self._message = ""
        self._message_key: str | None = None
        self._restore_message(message=message, message_key=message_key)

    @property
    def session(self) -> ExerciseSession:
        return self._session

    @property
    def message(self) -> str:
        return self._message

    @property
    def message_key(self) -> str | None:
        return self._message_key

    @staticmethod
    def _validate_message(message: object) -> None:
        if type(message) is not str:
            raise TypeError("training presenter message must be text")
        if len(message) > 4096:
            raise ValueError("training presenter message is too long")

    @classmethod
    def _validate_message_key(cls, message_key: object) -> None:
        if message_key is None:
            return
        if type(message_key) is not str:
            raise TypeError("training presenter message key must be text or None")
        if message_key not in cls._PRESENTATION_MESSAGES:
            raise ValueError("training presenter message key is invalid")

    def _set_presentation_message(self, key: str) -> None:
        self._validate_message_key(key)
        uk, en = self._PRESENTATION_MESSAGES[key]
        self._message_key = key
        self._message = _localized(self._language, uk, en)

    def _set_authored_message(self, message: str) -> None:
        self._validate_message(message)
        self._message_key = None
        self._message = message

    def _restore_message(self, *, message: str, message_key: str | None) -> None:
        self._validate_message(message)
        self._validate_message_key(message_key)
        if message_key is None:
            self._set_authored_message(message)
        else:
            self._set_presentation_message(message_key)

    def restore_state(
        self,
        snapshot: Mapping[str, object],
        *,
        message: str,
        message_key: str | None = None,
    ) -> None:
        self._validate_message(message)
        self._validate_message_key(message_key)
        self._session.restore_state(snapshot)
        self._restore_message(message=message, message_key=message_key)

    def set_language(self, language: UILanguage) -> None:
        if not isinstance(language, UILanguage):
            raise TypeError("training presenter language must be UILanguage")
        self._language = language
        if self._message_key is not None:
            self._set_presentation_message(self._message_key)

    def view(self) -> TrainingView:
        definition = self._session.canonical_definition
        total = len(definition.steps)
        visible_step = min(self._session.step_index + 1, total)
        return TrainingView(
            status=self._session.status,
            title=definition.title,
            step_number=visible_step,
            total_steps=total,
            attempts=self._session.attempts,
            mistakes=self._session.mistakes,
            hints_used=self._session.hints_used,
            completed=self._session.completed,
            message=self._message,
        )

    def submit(self, answer: str) -> tuple[ExerciseResult, TrainingView]:
        result = self._session.submit(answer)
        if result.completed:
            self._set_presentation_message("completed")
        elif result.accepted:
            if result.explanation:
                self._set_authored_message(result.explanation)
            else:
                self._set_presentation_message("accepted")
        else:
            self._set_presentation_message("retry")
        return result, self.view()

    def request_hint(self) -> tuple[HintResult, TrainingView]:
        hint = self._session.request_hint()
        if hint.available:
            self._set_authored_message(hint.hint or "")
        else:
            self._set_presentation_message("no_hint")
        return hint, self.view()

    def reveal_solution(self) -> tuple[str, ...]:
        step = self._session.current_step()
        if step is None:
            return ()
        self._set_presentation_message("revealed")
        return tuple(sorted(step.accepted_moves))

    def retry(self) -> TrainingView:
        """Clear transient UI feedback without changing canonical progress."""
        self._set_authored_message("")
        return self.view()

    def reset(self) -> TrainingView:
        self._session.reset()
        self._set_authored_message("")
        return self.view()

    def snapshot(self) -> dict[str, object]:
        return self._session.snapshot()

    @classmethod
    def restore(
        cls,
        definition,
        snapshot: Mapping[str, object],
        *,
        language: UILanguage = UILanguage.UA,
        message: str = "",
        message_key: str | None = None,
    ) -> "TrainingPresenter":
        return cls(
            ExerciseSession.restore(definition, snapshot),
            language=language,
            message=message,
            message_key=message_key,
        )
