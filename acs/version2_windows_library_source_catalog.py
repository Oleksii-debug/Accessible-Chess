from __future__ import annotations

"""Windows/NVDA-safe presentation controller for the canonical Library source catalog.

The D07 ``LibrarySourceCatalogService`` remains the only source/provenance truth
and ``GameSearchService`` remains the only game-search truth.  This layer owns
only Windows presentation concerns: worker-thread execution, bounded semantic
rows, presentation-only paging/selection identity, deterministic focus tokens,
and path/private-identifier suppression.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import logging
import threading
from typing import Any

from .library_source_service import (
    LibrarySourceCatalogService,
    SourceCatalogCancelledError,
    SourceCatalogControlError,
    SourceCatalogItem,
    SourceCatalogPage,
    SourceCatalogQuery,
)
from .search_service import GameSearchPage


_LOG = logging.getLogger(__name__)
_MAX_PRESENTATION_TEXT = 256
_MAX_STATUS_TEXT = 64


class SourceCatalogUiEventKind(str, Enum):
    LOADING = "loading"
    PAGE = "page"
    SELECTION = "selection"
    DETAIL = "detail"
    GAMES_READY = "games_ready"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SourceCatalogUiAction(str, Enum):
    LOAD = "load"
    REFRESH = "refresh"
    NEXT_PAGE = "next_page"
    PREVIOUS_PAGE = "previous_page"
    SELECT = "select"
    DETAIL = "detail"
    OPEN_GAMES = "open_games"


@dataclass(frozen=True, slots=True)
class AccessibleSourceRow:
    """Browser/NVDA-safe projection of one canonical source aggregate.

    Canonical source ids, SHA-256 values, import-attempt ids and game ids are
    intentionally absent.  ``row_index`` is presentation identity scoped to one
    ``generation`` only.
    """

    row_index: int
    source_name: str
    source_format: str
    imported_at: str
    game_count: int
    full_game_count: int
    warning_game_count: int
    partial_game_count: int
    damaged_game_count: int
    attempt_count: int
    latest_attempt_status: str | None


@dataclass(frozen=True, slots=True)
class AccessibleSourcePage:
    generation: int
    rows: tuple[AccessibleSourceRow, ...]
    has_next: bool
    has_previous: bool
    selected_index: int | None
    focus_target: str


@dataclass(frozen=True, slots=True)
class SourceCatalogUiEvent:
    kind: SourceCatalogUiEventKind
    action: SourceCatalogUiAction
    focus_target: str
    page: AccessibleSourcePage | None = None
    detail: AccessibleSourceRow | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SourceCatalogUiEventKind):
            raise TypeError("kind must be SourceCatalogUiEventKind")
        if not isinstance(self.action, SourceCatalogUiAction):
            raise TypeError("action must be SourceCatalogUiAction")
        if not isinstance(self.focus_target, str) or not self.focus_target:
            raise ValueError("focus_target must be non-empty text")
        if self.page is not None and not isinstance(self.page, AccessibleSourcePage):
            raise TypeError("page must be AccessibleSourcePage or None")
        if self.detail is not None and not isinstance(self.detail, AccessibleSourceRow):
            raise TypeError("detail must be AccessibleSourceRow or None")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or not self.error_code
        ):
            raise ValueError("error_code must be non-empty text or None")


SourceCatalogServiceLease = (
    LibrarySourceCatalogService
    | tuple[LibrarySourceCatalogService, Callable[[], Any]]
)
SourceCatalogServiceFactory = Callable[[], SourceCatalogServiceLease]
SourceCatalogUiSink = Callable[[SourceCatalogUiEvent], Any]
TrustedGamesSink = Callable[[GameSearchPage], Any]
UiPoster = Callable[[Callable[[], None]], Any]


def _exact_nonnegative_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _bounded_text(value: object, *, limit: int, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    clean = "".join(" " if ord(char) < 32 else char for char in value).strip()
    if not clean:
        return fallback
    if len(clean) <= limit:
        return clean
    return clean[: max(1, limit - 1)] + "…"


def _source_leaf(value: object) -> str:
    """Return a bounded leaf label without exposing a local directory path."""

    text = _bounded_text(value, limit=4096, fallback="source")
    normalized = text.replace("\\", "/").rstrip("/")
    leaf = normalized.rsplit("/", 1)[-1] if normalized else "source"
    return _bounded_text(leaf, limit=_MAX_PRESENTATION_TEXT, fallback="source")


def _status_text(value: object) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, limit=_MAX_STATUS_TEXT, fallback="unknown")


def _row(index: int, item: SourceCatalogItem) -> AccessibleSourceRow:
    if not isinstance(item, SourceCatalogItem):
        raise TypeError("canonical source item is invalid")
    return AccessibleSourceRow(
        row_index=index,
        source_name=_source_leaf(item.source_name),
        source_format=_bounded_text(
            item.source_format,
            limit=_MAX_STATUS_TEXT,
            fallback="unknown",
        ),
        imported_at=_bounded_text(
            item.imported_at,
            limit=_MAX_PRESENTATION_TEXT,
            fallback="unknown",
        ),
        game_count=item.game_count,
        full_game_count=item.full_game_count,
        warning_game_count=item.warning_game_count,
        partial_game_count=item.partial_game_count,
        damaged_game_count=item.damaged_game_count,
        attempt_count=item.attempt_count,
        latest_attempt_status=_status_text(item.latest_attempt_status),
    )


class Version2WindowsLibrarySourceCatalogController:
    """Asynchronous presentation adapter over ``LibrarySourceCatalogService``.

    Every database-backed operation obtains its service from ``service_factory``
    inside the worker thread.  This preserves SQLite thread affinity and avoids
    moving an ``AcsDatabase`` connection from the UI thread.  If the factory
    returns ``(service, cleanup)``, cleanup executes in the same worker after the
    operation.

    The controller never exposes canonical source ids to presentation.  A
    browser selects ``(generation, row_index)``; the private row->source-id map is
    checked under the controller lock.  ``trusted_games_sink`` is an application
    seam, not a browser event: it receives the exact canonical ``GameSearchPage``
    returned by D07 rather than a second game projection.
    """

    def __init__(
        self,
        service_factory: SourceCatalogServiceFactory,
        *,
        event_sink: SourceCatalogUiSink,
        trusted_games_sink: TrustedGamesSink,
        post_to_ui: UiPoster,
        page_size: int = 50,
    ) -> None:
        if not callable(service_factory):
            raise TypeError("service_factory must be callable")
        if not callable(event_sink):
            raise TypeError("event_sink must be callable")
        if not callable(trusted_games_sink):
            raise TypeError("trusted_games_sink must be callable")
        if not callable(post_to_ui):
            raise TypeError("post_to_ui must be callable")
        # Reuse the canonical query validator rather than inventing page bounds.
        normalized = SourceCatalogQuery(limit=page_size).normalized()
        self._page_size = normalized.limit
        self._service_factory = service_factory
        self._event_sink = event_sink
        self._trusted_games_sink = trusted_games_sink
        self._post_to_ui = post_to_ui
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._done = threading.Event()
        self._cancel = threading.Event()
        self._generation = 0
        self._source_format: str | None = None
        self._history: list[int | None] = [None]
        self._current_source_ids: tuple[int, ...] = ()
        self._next_cursor: int | None = None
        self._has_next = False
        self._selected_index: int | None = None
        self._page: AccessibleSourcePage | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            worker = self._worker
            return worker is not None and worker.is_alive()

    @property
    def page(self) -> AccessibleSourcePage | None:
        with self._lock:
            return self._page

    def _deliver(self, event: SourceCatalogUiEvent) -> None:
        def invoke() -> None:
            try:
                self._event_sink(event)
            except Exception:
                _LOG.warning("Library source catalog UI observer failed")

        try:
            self._post_to_ui(invoke)
        except Exception:
            # Never invoke UI directly as a worker-thread fallback.
            _LOG.warning("Library source catalog UI posting failed")

    def _deliver_games(self, page: GameSearchPage) -> None:
        def invoke() -> None:
            try:
                self._trusted_games_sink(page)
            except Exception:
                _LOG.warning("Library source catalog trusted game handoff failed")

        try:
            self._post_to_ui(invoke)
        except Exception:
            _LOG.warning("Library source catalog game handoff posting failed")

    def _lease(self) -> tuple[LibrarySourceCatalogService, Callable[[], Any] | None]:
        raw = self._service_factory()
        if isinstance(raw, LibrarySourceCatalogService):
            return raw, None
        if (
            isinstance(raw, tuple)
            and len(raw) == 2
            and isinstance(raw[0], LibrarySourceCatalogService)
            and callable(raw[1])
        ):
            return raw[0], raw[1]
        raise TypeError("service_factory returned an invalid source catalog lease")

    def _start(
        self,
        action: SourceCatalogUiAction,
        operation: Callable[[LibrarySourceCatalogService, Callable[[], bool]], None],
    ) -> bool:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return False
            self._cancel = threading.Event()
            self._done.clear()
            worker = threading.Thread(
                target=self._run_operation,
                args=(action, operation, self._cancel),
                name=f"AccessibleChess-V2-SourceCatalog-{action.value}",
                daemon=False,
            )
            self._worker = worker
        self._deliver(
            SourceCatalogUiEvent(
                SourceCatalogUiEventKind.LOADING,
                action,
                focus_target="library-source-list",
            )
        )
        worker.start()
        return True

    def _run_operation(
        self,
        action: SourceCatalogUiAction,
        operation: Callable[[LibrarySourceCatalogService, Callable[[], bool]], None],
        cancel_event: threading.Event,
    ) -> None:
        cleanup: Callable[[], Any] | None = None
        try:
            service, cleanup = self._lease()
            operation(service, cancel_event.is_set)
        except SourceCatalogCancelledError:
            self._deliver(
                SourceCatalogUiEvent(
                    SourceCatalogUiEventKind.CANCELLED,
                    action,
                    focus_target="library-source-list",
                )
            )
        except (TypeError, ValueError):
            self._deliver(
                SourceCatalogUiEvent(
                    SourceCatalogUiEventKind.FAILED,
                    action,
                    focus_target="library-source-list",
                    error_code="SOURCE_CATALOG_INVALID_REQUEST",
                )
            )
        except SourceCatalogControlError:
            self._deliver(
                SourceCatalogUiEvent(
                    SourceCatalogUiEventKind.FAILED,
                    action,
                    focus_target="library-source-list",
                    error_code="SOURCE_CATALOG_CONTROL_FAILED",
                )
            )
        except Exception:
            self._deliver(
                SourceCatalogUiEvent(
                    SourceCatalogUiEventKind.FAILED,
                    action,
                    focus_target="library-source-list",
                    error_code="SOURCE_CATALOG_UNAVAILABLE",
                )
            )
        finally:
            if cleanup is not None:
                try:
                    cleanup()
                except Exception:
                    _LOG.warning("Library source catalog worker cleanup failed")
            with self._lock:
                if self._worker is threading.current_thread():
                    self._worker = None
            self._done.set()

    def _publish_page(
        self,
        canonical: SourceCatalogPage,
        *,
        history: list[int | None],
        source_format: str | None,
        preferred_index: int | None = None,
    ) -> None:
        if not isinstance(canonical, SourceCatalogPage):
            raise TypeError("canonical source page is invalid")
        rows = tuple(_row(index, item) for index, item in enumerate(canonical.items))
        source_ids = tuple(item.source_id for item in canonical.items)
        with self._lock:
            self._generation += 1
            generation = self._generation
            if rows:
                selected = 0 if preferred_index is None else min(preferred_index, len(rows) - 1)
                focus = f"library-source-{selected}"
            else:
                selected = None
                focus = "library-source-list"
            page = AccessibleSourcePage(
                generation=generation,
                rows=rows,
                has_next=canonical.has_more,
                has_previous=len(history) > 1,
                selected_index=selected,
                focus_target=focus,
            )
            self._source_format = source_format
            self._history = list(history)
            self._current_source_ids = source_ids
            self._next_cursor = canonical.next_after_source_id
            self._has_next = canonical.has_more
            self._selected_index = selected
            self._page = page
        self._deliver(
            SourceCatalogUiEvent(
                SourceCatalogUiEventKind.PAGE,
                SourceCatalogUiAction.LOAD if len(history) == 1 else SourceCatalogUiAction.REFRESH,
                focus_target=page.focus_target,
                page=page,
            )
        )

    def load(self, *, source_format: str | None = None) -> bool:
        # Canonical normalization runs before worker creation so obviously invalid
        # browser scalars cannot allocate a worker.  No SQL/domain rule is copied.
        query = SourceCatalogQuery(
            source_format=source_format,
            limit=self._page_size,
        ).normalized()
        normalized_format = query.source_format

        def operation(service: LibrarySourceCatalogService, cancel_check: Callable[[], bool]) -> None:
            page = service.list_sources(query, cancel_check=cancel_check)
            self._publish_page(
                page,
                history=[None],
                source_format=normalized_format,
            )

        return self._start(SourceCatalogUiAction.LOAD, operation)

    def refresh(self) -> bool:
        with self._lock:
            history = list(self._history)
            source_format = self._source_format
            preferred = self._selected_index
            cursor = history[-1]
        query = SourceCatalogQuery(
            source_format=source_format,
            after_source_id=cursor,
            limit=self._page_size,
        )

        def operation(service: LibrarySourceCatalogService, cancel_check: Callable[[], bool]) -> None:
            page = service.list_sources(query, cancel_check=cancel_check)
            self._publish_page(
                page,
                history=history,
                source_format=source_format,
                preferred_index=preferred,
            )

        return self._start(SourceCatalogUiAction.REFRESH, operation)

    def next_page(self) -> bool:
        with self._lock:
            if not self._has_next or self._next_cursor is None:
                return False
            cursor = self._next_cursor
            history = [*self._history, cursor]
            source_format = self._source_format
        query = SourceCatalogQuery(
            source_format=source_format,
            after_source_id=cursor,
            limit=self._page_size,
        )

        def operation(service: LibrarySourceCatalogService, cancel_check: Callable[[], bool]) -> None:
            page = service.list_sources(query, cancel_check=cancel_check)
            self._publish_page(page, history=history, source_format=source_format)

        return self._start(SourceCatalogUiAction.NEXT_PAGE, operation)

    def previous_page(self) -> bool:
        with self._lock:
            if len(self._history) <= 1:
                return False
            history = self._history[:-1]
            cursor = history[-1]
            source_format = self._source_format
        query = SourceCatalogQuery(
            source_format=source_format,
            after_source_id=cursor,
            limit=self._page_size,
        )

        def operation(service: LibrarySourceCatalogService, cancel_check: Callable[[], bool]) -> None:
            page = service.list_sources(query, cancel_check=cancel_check)
            self._publish_page(page, history=history, source_format=source_format)

        return self._start(SourceCatalogUiAction.PREVIOUS_PAGE, operation)

    def select(self, row_index: int, *, generation: int) -> bool:
        row_index = _exact_nonnegative_int(row_index, name="row_index")
        generation = _exact_nonnegative_int(generation, name="generation")
        with self._lock:
            page = self._page
            if page is None or generation != page.generation or row_index >= len(page.rows):
                return False
            self._selected_index = row_index
            updated = AccessibleSourcePage(
                generation=page.generation,
                rows=page.rows,
                has_next=page.has_next,
                has_previous=page.has_previous,
                selected_index=row_index,
                focus_target=f"library-source-{row_index}",
            )
            self._page = updated
            detail = updated.rows[row_index]
        self._deliver(
            SourceCatalogUiEvent(
                SourceCatalogUiEventKind.SELECTION,
                SourceCatalogUiAction.SELECT,
                focus_target=updated.focus_target,
                page=updated,
                detail=detail,
            )
        )
        return True

    def _selected_source_id(self) -> tuple[int, int, AccessibleSourceRow] | None:
        with self._lock:
            page = self._page
            index = self._selected_index
            if (
                page is None
                or index is None
                or index < 0
                or index >= len(self._current_source_ids)
                or index >= len(page.rows)
            ):
                return None
            return self._current_source_ids[index], page.generation, page.rows[index]

    def selected_detail(self) -> bool:
        selected = self._selected_source_id()
        if selected is None:
            return False
        source_id, expected_generation, _ = selected

        def operation(service: LibrarySourceCatalogService, cancel_check: Callable[[], bool]) -> None:
            item = service.get_source(source_id, cancel_check=cancel_check)
            if item is None:
                raise LookupError("selected source is no longer available")
            with self._lock:
                page = self._page
                index = self._selected_index
                if page is None or page.generation != expected_generation or index is None:
                    return
            detail = _row(index, item)
            self._deliver(
                SourceCatalogUiEvent(
                    SourceCatalogUiEventKind.DETAIL,
                    SourceCatalogUiAction.DETAIL,
                    focus_target=f"library-source-{index}",
                    detail=detail,
                )
            )

        return self._start(SourceCatalogUiAction.DETAIL, operation)

    def open_selected_games(self, *, limit: int = 50) -> bool:
        selected = self._selected_source_id()
        if selected is None:
            return False
        source_id, expected_generation, _ = selected

        def operation(service: LibrarySourceCatalogService, cancel_check: Callable[[], bool]) -> None:
            games = service.source_games(
                source_id,
                limit=limit,
                cancel_check=cancel_check,
            )
            if not isinstance(games, GameSearchPage):
                raise TypeError("canonical source-games result is invalid")
            with self._lock:
                page = self._page
                index = self._selected_index
                if page is None or page.generation != expected_generation or index is None:
                    return
            self._deliver_games(games)
            self._deliver(
                SourceCatalogUiEvent(
                    SourceCatalogUiEventKind.GAMES_READY,
                    SourceCatalogUiAction.OPEN_GAMES,
                    focus_target="library-game-list",
                )
            )

        return self._start(SourceCatalogUiAction.OPEN_GAMES, operation)

    def cancel(self) -> bool:
        with self._lock:
            worker = self._worker
            if worker is None or not worker.is_alive():
                return False
            self._cancel.set()
            return True

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def join(self, timeout: float | None = None) -> bool:
        with self._lock:
            worker = self._worker
        if worker is None:
            return True
        worker.join(timeout)
        return not worker.is_alive()


__all__ = [
    "AccessibleSourcePage",
    "AccessibleSourceRow",
    "SourceCatalogUiAction",
    "SourceCatalogUiEvent",
    "SourceCatalogUiEventKind",
    "Version2WindowsLibrarySourceCatalogController",
]
