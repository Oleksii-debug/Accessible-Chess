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

from .bookdocument import Diagram, Exercise, Game, Heading, Note, Paragraph, Position, VariationTree
from .bookreader import BookReader, ReadingLocation
from .full_product_ui_shell import UILanguage, concise_user_error
from .gametree import PgnGame, VariationLine
from .search_service import GameSearchItem, GameSearchPage, GameSearchQuery, GameSearchService
from .training import ExerciseResult, ExerciseSession, ExerciseStatus, HintResult

CommandDispatch = Callable[[str, Mapping[str, object]], Any]


class SurfaceStatus(str, Enum):
    READY = "ready"
    LOADING = "loading"
    EMPTY = "empty"
    ERROR = "error"


def _safe_source_label(value: object) -> str:
    """Keep useful source identity without projecting local directory paths."""
    text = str(value or "").strip()
    if not text:
        return ""
    if "/" in text or "\\" in text:
        text = text.replace("\\", "/").rsplit("/", 1)[-1]
    return text[:120]


def _localized(language: UILanguage, uk: str, en: str) -> str:
    return uk if language is UILanguage.UA else en


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


@dataclass(frozen=True, slots=True)
class PgnGameView:
    game_index: int
    title: str
    result: str
    tags: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...]
    items: tuple[PgnTreeItem, ...]
    selected_node_id: str | None


class PgnTreePresenter:
    """Read-only recursive projection plus canonical edit-command dispatch.

    The presenter never edits :class:`PgnGame` or :class:`VariationLine`
    directly. Edit/delete/promote/export operations are emitted as stable
    application command intents for the canonical GameTree command layer.
    """

    _EDIT_ACTIONS = frozenset(
        {
            "pgn.comment_edit",
            "pgn.comment_delete",
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
        self._games = tuple(games)
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

    def set_language(self, language: UILanguage) -> None:
        self._language = language
        self._rebuild()

    def select_game(self, index: int) -> PgnGameView:
        if not 0 <= index < len(self._games):
            raise IndexError("PGN game index is outside the collection")
        self._game_index = index
        self._selected_node_id = None
        self._rebuild()
        return self.view()

    def next_game(self) -> PgnGameView:
        return self.select_game(self._game_index + 1)

    def previous_game(self) -> PgnGameView:
        return self.select_game(self._game_index - 1)

    def _rebuild(self) -> None:
        if self._game_index < 0:
            self._items = ()
            self._selected_node_id = None
            return
        items: list[PgnTreeItem] = []
        self._append_line(
            self._games[self._game_index].line,
            items,
            line_id=f"g{self._game_index}:main",
            parent_id=None,
            depth=0,
            variation_label=None,
        )
        self._items = tuple(items)
        ids = {item.node_id for item in self._items}
        if self._selected_node_id not in ids:
            self._selected_node_id = self._items[0].node_id if self._items else None

    def _append_line(
        self,
        line: VariationLine,
        out: list[PgnTreeItem],
        *,
        line_id: str,
        parent_id: str | None,
        depth: int,
        variation_label: str | None,
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
                )
            )
            parent_id = line_id
            depth += 1
        for move_index, move in enumerate(line.moves):
            node_id = f"{line_id}/m{move_index}"
            number = f"{move.move_number} " if move.move_number else ""
            comments = tuple(
                comment.text
                for comment in (*move.comments_before, *move.comments_after)
                if comment.text.strip()
            )
            annotation = " ".join(move.nags)
            label = f"{number}{move.san}"
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
                        self._language,
                        f"Варіант {variation_index + 1}",
                        f"Variation {variation_index + 1}",
                    ),
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
    """Exact in-memory Library state for one presentation transaction."""

    pages: tuple[tuple[GameSearchQuery, GameSearchPage], ...]
    page_index: int
    selected_game_id: int | None
    selected_by_page: tuple[tuple[int, int | None], ...]
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
        self._selected_by_page: dict[int, int | None] = {}
        self._status = SurfaceStatus.EMPTY
        self._message = ""

    @property
    def selected_game_id(self) -> int | None:
        return self._selected_game_id

    def set_language(self, language: UILanguage) -> None:
        self._language = language

    def _capture_state(self) -> _LibraryPresenterState:
        """Capture state so a failed projection can roll back atomically."""
        return _LibraryPresenterState(
            pages=tuple(self._pages),
            page_index=self._page_index,
            selected_game_id=self._selected_game_id,
            selected_by_page=tuple(sorted(self._selected_by_page.items())),
            status=self._status,
            message=self._message,
        )

    def _restore_state(self, state: _LibraryPresenterState) -> None:
        if not isinstance(state, _LibraryPresenterState):
            raise TypeError("invalid Library presenter state")
        self._pages = list(state.pages)
        self._page_index = state.page_index
        self._selected_game_id = state.selected_game_id
        self._selected_by_page = dict(state.selected_by_page)
        self._status = state.status
        self._message = state.message

    @staticmethod
    def _validate_page(
        page: GameSearchPage,
        *,
        query: GameSearchQuery,
    ) -> GameSearchPage:
        """Validate one backend page before publishing it into presenter state."""
        if not isinstance(page, GameSearchPage):
            raise TypeError("library search returned an invalid page")
        if not isinstance(query, GameSearchQuery):
            raise TypeError("library page query is invalid")
        if not isinstance(page.items, tuple):
            raise TypeError("library page items must be an immutable tuple")
        if len(page.items) > query.limit:
            raise ValueError("library page exceeds the requested limit")
        if type(page.has_more) is not bool:
            raise ValueError("library page has invalid continuation state")

        ids: list[int] = []
        previous_id = query.after_game_id or 0
        optional_text = (
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
        for item in page.items:
            if not isinstance(item, GameSearchItem):
                raise TypeError("library page contains an invalid game")
            if type(item.game_id) is not int or item.game_id <= 0:
                raise ValueError("library page contains an invalid game identity")
            if item.game_id <= previous_id:
                raise ValueError("library page violates keyset game ordering")
            if type(item.source_id) is not int or item.source_id <= 0:
                raise ValueError("library page contains an invalid source identity")
            if type(item.source_index) is not int or item.source_index < 0:
                raise ValueError("library page contains an invalid source index")
            for field_name in ("source_name", "source_format", "import_status"):
                if type(getattr(item, field_name)) is not str:
                    raise TypeError("library page contains invalid source metadata")
            for field_name in optional_text:
                value = getattr(item, field_name)
                if value is not None and type(value) is not str:
                    raise TypeError("library page contains invalid game metadata")
            ids.append(item.game_id)
            previous_id = item.game_id

        cursor = page.next_after_game_id
        if page.has_more:
            if (
                not ids
                or type(cursor) is not int
                or cursor <= 0
                or cursor != ids[-1]
            ):
                raise ValueError("library page has an invalid keyset cursor")
        elif cursor is not None:
            raise ValueError("terminal library page must not expose a keyset cursor")
        return page

    def search(self, query: GameSearchQuery | None = None) -> LibraryView:
        q = (query or GameSearchQuery()).normalized()
        try:
            page = self._validate_page(self._service.search(q), query=q)
        except Exception as exc:
            # Treat a failed replacement search as a rejected transaction.
            # Preserve the last committed page, selection, status and cache so
            # native/global callers cannot silently destroy hidden Library state.
            # Return a transient error view for the attempted operation instead.
            current = self.view()
            return replace(
                current,
                status=SurfaceStatus.ERROR,
                message=concise_user_error(exc, language=self._language),
            )
        self._pages = [(q, page)]
        self._page_index = 0
        self._selected_by_page = {}
        self._status = SurfaceStatus.READY if page.items else SurfaceStatus.EMPTY
        self._message = ""
        self._stabilize_selection(page)
        return self.view()

    def _stabilize_selection(self, page: GameSearchPage) -> None:
        ids = {item.game_id for item in page.items}
        saved = self._selected_by_page.get(self._page_index)
        if saved in ids:
            self._selected_game_id = saved
        elif self._selected_game_id not in ids:
            self._selected_game_id = page.items[0].game_id if page.items else None
        self._selected_by_page[self._page_index] = self._selected_game_id

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
            self._status = SurfaceStatus.READY if cached.items else SurfaceStatus.EMPTY
            self._message = ""
            self._stabilize_selection(cached)
            return self.view()
        query = replace(
            self._pages[self._page_index][0],
            after_game_id=current.next_after_game_id,
        )
        try:
            page = self._validate_page(self._service.search(query), query=query)
        except Exception as exc:
            # A failed page fetch is only an error for this attempted action.
            # Keep the last committed page/selection/status available for retry,
            # matching replacement-search transaction semantics.
            current_view = self.view()
            return replace(
                current_view,
                status=SurfaceStatus.ERROR,
                message=concise_user_error(exc, language=self._language),
            )
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
        page = self.current_page()
        if page is None:
            raise RuntimeError("library page cache is inconsistent")
        self._status = SurfaceStatus.READY if page.items else SurfaceStatus.EMPTY
        self._message = ""
        self._stabilize_selection(page)
        return self.view()

    def select(self, game_id: int) -> LibraryView:
        page = self.current_page()
        if page is None or game_id not in {item.game_id for item in page.items}:
            raise LookupError("Game is not present on the current library page")
        self._selected_game_id = game_id
        self._selected_by_page[self._page_index] = game_id
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


class BookReaderPresenter:
    """Semantic book projection over the canonical :class:`BookReader` cursor."""

    _BOARD_RETURN_POINT = "__full_product_board_return__"

    def __init__(
        self,
        reader: BookReader,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        self._reader = reader
        self._language = language

    def set_language(self, language: UILanguage) -> None:
        self._language = language

    def _block_view(self, location: ReadingLocation) -> BookBlockView:
        block = self._reader.document.blocks[location.index]
        role = "group"
        title = ""
        text = ""
        heading_level: int | None = None
        warning = ""
        if isinstance(block, Heading):
            role = "heading"
            title = block.text
            text = block.text
            heading_level = block.level
        elif isinstance(block, Paragraph):
            role = "paragraph"
            text = block.text
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
            role = "tree"
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
        )

    def current(self) -> BookBlockView:
        return self._block_view(self._reader.location())

    def next_block(self) -> BookBlockView:
        return self._block_view(self._reader.next_block())

    def previous_block(self) -> BookBlockView:
        return self._block_view(self._reader.previous_block())

    def next_heading(self) -> BookBlockView:
        return self._block_view(self._reader.next_heading())

    def previous_heading(self) -> BookBlockView:
        return self._block_view(self._reader.previous_heading())

    def next_position(self) -> BookBlockView:
        return self._block_view(self._reader.next_position())

    def next_game(self) -> BookBlockView:
        return self._block_view(self._reader.next_game())

    def bookmark(self, name: str = "default") -> BookBlockView:
        return self._block_view(self._reader.save_return_point(name))

    def restore_bookmark(self, name: str = "default") -> BookBlockView:
        return self._block_view(self._reader.restore_return_point(name))

    def open_current_position(self, dispatch: CommandDispatch) -> Any:
        current = self.current()
        if current.position_fen is None:
            raise LookupError("Current book block has no board position")
        self._reader.save_return_point(self._BOARD_RETURN_POINT)
        return dispatch(
            "book.open_position",
            {
                "fen": current.position_fen,
                "book_index": current.index,
            },
        )

    def return_from_board(self) -> BookBlockView:
        return self.restore_bookmark(self._BOARD_RETURN_POINT)


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

    def __init__(
        self,
        session: ExerciseSession,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        self._session = session
        self._language = language
        self._message = ""

    @property
    def session(self) -> ExerciseSession:
        return self._session

    def set_language(self, language: UILanguage) -> None:
        self._language = language

    def view(self) -> TrainingView:
        total = len(self._session.definition.steps)
        visible_step = min(self._session.step_index + 1, total)
        return TrainingView(
            status=self._session.status,
            title=self._session.definition.title,
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
            self._message = _localized(
                self._language,
                "Вправу завершено.",
                "Exercise completed.",
            )
        elif result.accepted:
            self._message = result.explanation or _localized(
                self._language,
                "Правильно. Наступний крок.",
                "Correct. Next step.",
            )
        else:
            self._message = _localized(
                self._language,
                "Спробуйте ще раз.",
                "Try again.",
            )
        return result, self.view()

    def request_hint(self) -> tuple[HintResult, TrainingView]:
        hint = self._session.request_hint()
        if hint.available:
            self._message = hint.hint or ""
        else:
            self._message = _localized(
                self._language,
                "Підказки для цього кроку немає.",
                "No hint is available for this step.",
            )
        return hint, self.view()

    def reveal_solution(self) -> tuple[str, ...]:
        step = self._session.current_step()
        if step is None:
            return ()
        self._message = _localized(
            self._language,
            "Розв’язок показано.",
            "Solution revealed.",
        )
        return tuple(sorted(step.accepted_moves))

    def retry(self) -> TrainingView:
        """Clear transient UI feedback without changing canonical progress."""
        self._message = ""
        return self.view()

    def reset(self) -> TrainingView:
        self._session.reset()
        self._message = ""
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
    ) -> "TrainingPresenter":
        return cls(ExerciseSession.restore(definition, snapshot), language=language)
