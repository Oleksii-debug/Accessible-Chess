"""Accessible Library/Search WebView projection over the existing DEV1 presenter.

This module owns presentation only. Search semantics, paging cursors and database
identity remain in ``GameSearchService`` / ``LibraryPresenter``. Browser actions
never receive raw SQL, SQLite rows, FEN, local filesystem paths or backend return
payloads.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata
from typing import Any

from .full_product_presenters import LibraryPresenter, LibraryRowView, LibraryView, SurfaceStatus
from .full_product_ui_shell import UILanguage, concise_user_error
from .search_service import GameSearchQuery

CommandDispatch = Callable[[str, Mapping[str, object]], Any]
_SQLITE_INTEGER_MAX = (1 << 63) - 1
_MAX_TERM = 256
_WINDOWS_PATH = re.compile(r"(?i)(?<![\w])([a-z]:[\\/][^\r\n\t]*)")
_POSIX_PATH = re.compile(r"(?i)(?<![\w])(/(?:home|users|tmp|mnt|var/tmp|private/tmp)/[^\r\n\t ]*)")
_RESULTS = ("", "1-0", "0-1", "1/2-1/2", "*")

_LABELS = {
    UILanguage.UA: {
        "heading": "Бібліотека і пошук",
        "search": "Пошук",
        "player": "Гравець",
        "event": "Турнір або подія",
        "eco": "ECO",
        "opening": "Дебют",
        "result": "Результат",
        "source": "Джерело",
        "any_result": "Будь-який результат",
        "submit": "Знайти",
        "reset": "Скинути фільтри",
        "results": "Результати пошуку",
        "empty": "Партій не знайдено.",
        "previous": "Попередня сторінка",
        "next": "Наступна сторінка",
        "open": "Відкрити вибрану партію",
        "import": "Імпортувати",
        "export": "Експортувати",
        "cancel_import": "Скасувати імпорт",
        "action_failed": "Не вдалося виконати дію.",
        "hidden_path": "[локальний шлях приховано]",
    },
    UILanguage.EN: {
        "heading": "Library and search",
        "search": "Search",
        "player": "Player",
        "event": "Event",
        "eco": "ECO",
        "opening": "Opening",
        "result": "Result",
        "source": "Source",
        "any_result": "Any result",
        "submit": "Search",
        "reset": "Reset filters",
        "results": "Search results",
        "empty": "No games found.",
        "previous": "Previous page",
        "next": "Next page",
        "open": "Open selected game",
        "import": "Import",
        "export": "Export",
        "cancel_import": "Cancel import",
        "action_failed": "The action could not be completed.",
        "hidden_path": "[local path hidden]",
    },
}


def _scrub_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("library presentation text must be text")
    text = value.replace("\x00", "").strip()
    replacement = _LABELS[language]["hidden_path"]
    text = _WINDOWS_PATH.sub(replacement, text)
    text = _POSIX_PATH.sub(replacement, text)
    return text[:limit]


def _term(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if len(normalized) > _MAX_TERM:
        raise ValueError(f"{name} exceeds {_MAX_TERM} characters")
    return normalized


def _dom_id(game_id: int) -> str:
    token = sha256(f"library-game:{game_id}".encode("ascii")).hexdigest()[:20]
    return "library-game-" + token


@dataclass(frozen=True, slots=True)
class LibraryWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class LibraryWebViewProjection:
    """JSON-ready Library/Search surface backed by ``LibraryPresenter`` only."""

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
        self._presenter.set_language(language)
        self._filters = {
            "player": "",
            "event": "",
            "eco": "",
            "opening": "",
            "result": "",
            "source_name": "",
        }

    @property
    def language(self) -> UILanguage:
        return self._language

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
        return LibraryWebViewEvent("render", {"snapshot": self.snapshot(), "focus_target": ""})

    def _row(self, row: LibraryRowView) -> dict[str, object]:
        if type(row.game_id) is not int or not 1 <= row.game_id <= _SQLITE_INTEGER_MAX:
            raise ValueError("library row has invalid game id")
        return {
            "dom_id": _dom_id(row.game_id),
            "game_id": row.game_id,
            "label": _scrub_text(row.label, language=self._language, limit=360),
            "source": _scrub_text(row.source_label, language=self._language, limit=160),
            "result": _scrub_text(row.result, language=self._language, limit=32),
            "selected": bool(row.selected),
        }

    def _snapshot_from_view(self, view: LibraryView) -> dict[str, object]:
        if not isinstance(view, LibraryView):
            raise TypeError("library presenter must return LibraryView")
        labels = _LABELS[self._language]
        rows = tuple(self._row(row) for row in view.rows)
        selected_rows = tuple(row for row in rows if row["selected"])
        if view.selected_game_id is None:
            if selected_rows:
                raise ValueError("library view has selected row without selected id")
        else:
            if type(view.selected_game_id) is not int or not 1 <= view.selected_game_id <= _SQLITE_INTEGER_MAX:
                raise ValueError("library view has invalid selected id")
            if len(selected_rows) != 1 or selected_rows[0]["game_id"] != view.selected_game_id:
                raise ValueError("library view selection is inconsistent")
        if not rows and view.selected_game_id is not None:
            raise ValueError("empty library view cannot keep selection")
        status = view.status.value if isinstance(view.status, SurfaceStatus) else "error"
        if status not in {"ready", "loading", "empty", "error"}:
            raise ValueError("library view has invalid status")
        focus_target = str(selected_rows[0]["dom_id"]) if selected_rows else ""
        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            "heading": labels["heading"],
            "search_heading": labels["search"],
            "results_heading": labels["results"],
            "status": status,
            "message": _scrub_text(view.message, language=self._language, limit=720),
            "empty_message": labels["empty"],
            "filters": {
                "player": {"label": labels["player"], "value": self._filters["player"]},
                "event": {"label": labels["event"], "value": self._filters["event"]},
                "eco": {"label": labels["eco"], "value": self._filters["eco"]},
                "opening": {"label": labels["opening"], "value": self._filters["opening"]},
                "result": {
                    "label": labels["result"],
                    "value": self._filters["result"],
                    "options": (
                        {"value": "", "label": labels["any_result"]},
                        {"value": "1-0", "label": "1-0"},
                        {"value": "0-1", "label": "0-1"},
                        {"value": "1/2-1/2", "label": "1/2-1/2"},
                        {"value": "*", "label": "*"},
                    ),
                },
                "source_name": {"label": labels["source"], "value": self._filters["source_name"]},
                "submit_label": labels["submit"],
                "reset_label": labels["reset"],
            },
            "rows": rows,
            "selected_game_id": view.selected_game_id,
            "focus_target": focus_target,
            "paging": {
                "previous_label": labels["previous"],
                "next_label": labels["next"],
                "has_previous": bool(view.has_previous_page),
                "has_next": bool(view.has_next_page),
            },
            "actions": (
                {"command": "library.open", "label": labels["open"], "enabled": view.selected_game_id is not None},
                {"command": "library.import", "label": labels["import"], "enabled": True},
                {"command": "library.export", "label": labels["export"], "enabled": view.selected_game_id is not None},
            ),
            "action_failed": labels["action_failed"],
        }

    def snapshot(self) -> dict[str, object]:
        return self._snapshot_from_view(self._presenter.view())

    def _event(self, view: LibraryView, *, focus: str = "selected", announce: str = "") -> LibraryWebViewEvent:
        snapshot = self._snapshot_from_view(view)
        focus_target = ""
        if focus == "selected":
            focus_target = str(snapshot["focus_target"])
        elif focus == "search":
            focus_target = "library-search-player"
        return LibraryWebViewEvent(
            "render",
            {"snapshot": snapshot, "focus_target": focus_target, "announcement": announce},
        )

    def search(self, values: Mapping[str, object]) -> LibraryWebViewEvent:
        if not isinstance(values, Mapping):
            raise TypeError("library search values must be a mapping")
        expected = {"player", "event", "eco", "opening", "result", "source_name"}
        if set(values) != expected:
            raise ValueError("library search fields are invalid")
        normalized = {
            "player": _term(values["player"], name="player"),
            "event": _term(values["event"], name="event"),
            "eco": _term(values["eco"], name="eco"),
            "opening": _term(values["opening"], name="opening"),
            "result": _term(values["result"], name="result"),
            "source_name": _term(values["source_name"], name="source_name"),
        }
        if normalized["result"] not in _RESULTS:
            raise ValueError("unsupported library result filter")
        self._filters = normalized
        query = GameSearchQuery(
            player=normalized["player"] or None,
            event=normalized["event"] or None,
            eco=normalized["eco"] or None,
            opening=normalized["opening"] or None,
            result=normalized["result"] or None,
            source_name=normalized["source_name"] or None,
            limit=50,
        )
        view = self._presenter.search(query)
        announcement = view.message
        if not view.rows and not announcement:
            announcement = _LABELS[self._language]["empty"]
        return self._event(view, focus="selected" if view.rows else "search", announce=announcement)

    def reset(self) -> LibraryWebViewEvent:
        self._filters = {key: "" for key in self._filters}
        view = self._presenter.search(GameSearchQuery(limit=50))
        return self._event(view, focus="search", announce=view.message)

    def select(self, game_id: int) -> LibraryWebViewEvent:
        if type(game_id) is not int or not 1 <= game_id <= _SQLITE_INTEGER_MAX:
            raise ValueError("invalid library game id")
        return self._event(self._presenter.select(game_id), focus="selected")

    def move_selection(self, delta: int) -> LibraryWebViewEvent:
        if type(delta) is not int or delta not in {-1, 1}:
            raise ValueError("library selection delta must be -1 or 1")
        view = self._presenter.view()
        if not view.rows or view.selected_game_id is None:
            raise LookupError("library has no selected result")
        ids = [row.game_id for row in view.rows]
        try:
            index = ids.index(view.selected_game_id)
        except ValueError as exc:
            raise ValueError("library view selection is inconsistent") from exc
        target = index + delta
        if not 0 <= target < len(ids):
            raise LookupError("library selection boundary")
        return self._event(self._presenter.select(ids[target]), focus="selected")

    def previous_page(self) -> LibraryWebViewEvent:
        return self._event(self._presenter.previous_page(), focus="selected")

    def next_page(self) -> LibraryWebViewEvent:
        return self._event(self._presenter.next_page(), focus="selected")

    def open_selected(self) -> LibraryWebViewEvent:
        self._presenter.open_selected(self._dispatch)
        return LibraryWebViewEvent("delegated", {"action": "library.open_game"})

    def external_action(self, action_id: str) -> LibraryWebViewEvent:
        if action_id not in {"library.import", "library.export", "library.cancel_import"}:
            raise ValueError("unsupported library external action")
        self._dispatch(action_id, {})
        return LibraryWebViewEvent("delegated", {"action": action_id})

    def generic_error(self) -> LibraryWebViewEvent:
        return LibraryWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._language)},
        )
