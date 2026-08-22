"""Accessible Library/Search WebView projection over the canonical DEV3 search service.

DEV1 owns only presentation, keyboard/focus state, and browser command projection
here. Database queries, Unicode matching, keyset cursor semantics, provenance,
imports, and persistence remain owned by the canonical ACSDB/search layer.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any

from .full_product_presenters import LibraryPresenter, LibraryView, SurfaceStatus
from .full_product_ui_shell import UILanguage, concise_user_error
from .search_service import GameSearchQuery

CommandDispatch = Callable[[str, Mapping[str, object]], Any]

_WINDOWS_LOCAL_PATH = re.compile(r"(?i)(?<![\w])([a-z]:[\\/][^\r\n\t]*)")
_POSIX_LOCAL_PATH = re.compile(
    r"(?i)(?<![\w])(/(?:home|users|tmp|mnt|var/tmp|private/tmp)/[^\r\n\t ]*)"
)

_LABELS = {
    UILanguage.UA: {
        "heading": "Бібліотека партій",
        "description": "Пошук і відкриття партій із шахової бібліотеки.",
        "filters": "Фільтри пошуку",
        "results": "Результати пошуку",
        "player": "Гравець",
        "event": "Турнір або подія",
        "eco": "ECO",
        "opening": "Дебют",
        "result": "Результат",
        "source_id": "Ідентифікатор джерела",
        "source_name": "Назва джерела",
        "limit": "Партій на сторінці",
        "any": "Будь-який",
        "search": "Шукати",
        "reset": "Скинути фільтри",
        "previous": "Попередня сторінка",
        "next": "Наступна сторінка",
        "open": "Відкрити вибрану партію",
        "empty": "За цими фільтрами партій не знайдено.",
        "shown_one": "Показано 1 партію.",
        "shown_many": "Показано партій: {count}.",
        "source": "Джерело",
        "local_path": "[локальний шлях приховано]",
        "transport_error": "Не вдалося виконати дію.",
    },
    UILanguage.EN: {
        "heading": "Game library",
        "description": "Search and open games from the chess library.",
        "filters": "Search filters",
        "results": "Search results",
        "player": "Player",
        "event": "Event",
        "eco": "ECO",
        "opening": "Opening",
        "result": "Result",
        "source_id": "Source identifier",
        "source_name": "Source name",
        "limit": "Games per page",
        "any": "Any",
        "search": "Search",
        "reset": "Reset filters",
        "previous": "Previous page",
        "next": "Next page",
        "open": "Open selected game",
        "empty": "No games match these filters.",
        "shown_one": "1 game shown.",
        "shown_many": "{count} games shown.",
        "source": "Source",
        "local_path": "[local path hidden]",
        "transport_error": "The action could not be completed.",
    },
}


def _scrub_visible_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("library presentation text must be text")
    text = value.replace("\x00", "").strip()
    replacement = _LABELS[language]["local_path"]
    text = _WINDOWS_LOCAL_PATH.sub(replacement, text)
    text = _POSIX_LOCAL_PATH.sub(replacement, text)
    return text[:limit]


def _dom_token(game_id: int) -> str:
    return "library-game-" + sha256(f"game:{game_id}".encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class LibraryWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class LibraryWebViewProjection:
    """JSON-ready, keyboard-first Library/Search surface.

    Each browser render is derived from one immutable ``LibraryView`` returned by
    ``LibraryPresenter``. The browser never receives database rows, SQL, keyset
    cursors, local source paths, or arbitrary backend return values.
    """

    def __init__(
        self,
        presenter: LibraryPresenter,
        dispatch: CommandDispatch,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(presenter, LibraryPresenter):
            raise TypeError("presenter must be LibraryPresenter")
        if not callable(dispatch):
            raise TypeError("library dispatcher must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._presenter = presenter
        self._dispatch = dispatch
        self._language = language
        self._query = GameSearchQuery().normalized()
        self._presenter.set_language(language)

    @property
    def language(self) -> UILanguage:
        return self._language

    @property
    def query(self) -> GameSearchQuery:
        return self._query

    def _filters(self) -> tuple[dict[str, object], ...]:
        labels = _LABELS[self._language]
        q = self._query
        return (
            {"id": "player", "kind": "text", "label": labels["player"], "value": q.player or ""},
            {"id": "event", "kind": "text", "label": labels["event"], "value": q.event or ""},
            {"id": "eco", "kind": "text", "label": labels["eco"], "value": q.eco or ""},
            {"id": "opening", "kind": "text", "label": labels["opening"], "value": q.opening or ""},
            {
                "id": "result",
                "kind": "select",
                "label": labels["result"],
                "value": q.result or "",
                "options": (
                    {"value": "", "label": labels["any"]},
                    {"value": "1-0", "label": "1-0"},
                    {"value": "0-1", "label": "0-1"},
                    {"value": "1/2-1/2", "label": "1/2-1/2"},
                    {"value": "*", "label": "*"},
                ),
            },
            {
                "id": "source_id",
                "kind": "number",
                "label": labels["source_id"],
                "value": "" if q.source_id is None else str(q.source_id),
                "minimum": 1,
            },
            {"id": "source_name", "kind": "text", "label": labels["source_name"], "value": q.source_name or ""},
            {
                "id": "limit",
                "kind": "select",
                "label": labels["limit"],
                "value": str(q.limit),
                "options": tuple(
                    {"value": str(value), "label": str(value)}
                    for value in (25, 50, 100, 200)
                ),
            },
        )

    def _row(self, row: object, *, position: int) -> dict[str, object]:
        game_id = getattr(row, "game_id", None)
        if type(game_id) is not int or game_id <= 0:
            raise ValueError("library row has invalid game identity")
        selected = getattr(row, "selected", None)
        if type(selected) is not bool:
            raise ValueError("library row has invalid selection state")
        label = _scrub_visible_text(
            getattr(row, "label", ""), language=self._language, limit=520
        )
        source = _scrub_visible_text(
            getattr(row, "source_label", ""), language=self._language, limit=160
        )
        result = _scrub_visible_text(
            getattr(row, "result", ""), language=self._language, limit=32
        )
        return {
            "dom_id": _dom_token(game_id),
            "game_id": game_id,
            "position": position,
            "selected": selected,
            "label": label,
            "source_label": source,
            "result": result,
        }

    def _summary(self, view: LibraryView) -> str:
        labels = _LABELS[self._language]
        if view.status is SurfaceStatus.ERROR:
            return _scrub_visible_text(view.message, language=self._language, limit=500)
        if not view.rows:
            return labels["empty"]
        if len(view.rows) == 1:
            return labels["shown_one"]
        return labels["shown_many"].format(count=len(view.rows))

    def _snapshot_from_view(self, view: LibraryView) -> dict[str, object]:
        if not isinstance(view, LibraryView):
            raise TypeError("library presenter returned invalid view")
        labels = _LABELS[self._language]
        rows = tuple(self._row(row, position=index + 1) for index, row in enumerate(view.rows))
        selected = tuple(row for row in rows if row["selected"])
        if len(selected) > 1:
            raise ValueError("library view exposes multiple selected games")
        selected_game_id = view.selected_game_id
        if selected_game_id is None:
            if selected:
                raise ValueError("library view selection identity is inconsistent")
            focus_target = "library-search-player"
        else:
            if type(selected_game_id) is not int or selected_game_id <= 0:
                raise ValueError("library selected game identity is invalid")
            if len(selected) != 1 or selected[0]["game_id"] != selected_game_id:
                raise ValueError("library selected game is not present in rendered rows")
            focus_target = str(selected[0]["dom_id"])

        message = _scrub_visible_text(view.message, language=self._language, limit=500)
        status = view.status.value
        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            "status": status,
            "heading": labels["heading"],
            "description": labels["description"],
            "filters_heading": labels["filters"],
            "results_heading": labels["results"],
            "search_label": labels["search"],
            "transport_error_message": labels["transport_error"],
            "filters": self._filters(),
            "rows": rows,
            "selected_game_id": selected_game_id,
            "focus_target": focus_target,
            "message": message,
            "summary": self._summary(view),
            "actions": (
                {
                    "action": "library.previous_page",
                    "label": labels["previous"],
                    "enabled": view.has_previous_page,
                },
                {
                    "action": "library.next_page",
                    "label": labels["next"],
                    "enabled": view.has_next_page,
                },
                {
                    "action": "library.open_game",
                    "label": labels["open"],
                    "enabled": selected_game_id is not None,
                },
                {
                    "action": "library.reset_filters",
                    "label": labels["reset"],
                    "enabled": self._query != GameSearchQuery().normalized(),
                },
            ),
        }

    def snapshot(self) -> dict[str, object]:
        # One immutable LibraryView is the complete source of a browser render.
        return self._snapshot_from_view(self._presenter.view())

    def _render_event(self, view: LibraryView, *, announce: bool) -> LibraryWebViewEvent:
        snapshot = self._snapshot_from_view(view)
        return LibraryWebViewEvent(
            "render",
            {
                "snapshot": snapshot,
                "focus_target": snapshot["focus_target"],
                "announcement": snapshot["summary"] if announce else "",
            },
        )

    def search(self, query: GameSearchQuery) -> LibraryWebViewEvent:
        if not isinstance(query, GameSearchQuery):
            raise TypeError("query must be GameSearchQuery")
        normalized = query.normalized()
        if normalized.after_game_id is not None:
            raise ValueError("browser search cannot supply a keyset cursor")
        self._query = normalized
        view = self._presenter.search(normalized)
        return self._render_event(view, announce=True)

    def reset_filters(self) -> LibraryWebViewEvent:
        return self.search(GameSearchQuery())

    def select(self, game_id: int) -> LibraryWebViewEvent:
        if type(game_id) is not int or game_id <= 0:
            raise ValueError("game_id must be a positive integer")
        view = self._presenter.select(game_id)
        return self._render_event(view, announce=False)

    def move_selection(self, delta: int) -> LibraryWebViewEvent:
        if type(delta) is not int or delta not in {-1, 1}:
            raise ValueError("library selection delta must be -1 or 1")
        current = self._presenter.view()
        if not current.rows or current.selected_game_id is None:
            raise LookupError("library has no selected game")
        ids = [row.game_id for row in current.rows]
        try:
            index = ids.index(current.selected_game_id)
        except ValueError:
            raise ValueError("library selection is inconsistent") from None
        target = index + delta
        if not 0 <= target < len(ids):
            raise LookupError("library selection boundary")
        view = self._presenter.select(ids[target])
        return self._render_event(view, announce=False)

    def next_page(self) -> LibraryWebViewEvent:
        return self._render_event(self._presenter.next_page(), announce=True)

    def previous_page(self) -> LibraryWebViewEvent:
        return self._render_event(self._presenter.previous_page(), announce=True)

    def open_selected(self) -> LibraryWebViewEvent:
        self._presenter.open_selected(self._dispatch)
        # Never return backend/DB/application values to the browser as authority.
        return LibraryWebViewEvent("delegated", {"action": "library.open_game"})

    def set_language(self, language: UILanguage | str) -> LibraryWebViewEvent:
        if isinstance(language, str):
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language
        self._presenter.set_language(language)
        return self._render_event(self._presenter.view(), announce=False)

    def safe_call(self, method: Callable[[], LibraryWebViewEvent]) -> LibraryWebViewEvent:
        try:
            return method()
        except Exception as exc:
            return LibraryWebViewEvent(
                "error",
                {"message": concise_user_error(exc, language=self._language)},
            )
