"""Accessible BookReader WebView projection over the canonical BookReaderPresenter.

DEV1 owns presentation only. The browser never receives raw FEN/PGN or source
filesystem paths. Opening a chess position delegates inside Python through the
existing BookReaderPresenter so the canonical board/application layer remains the
only owner of chess state.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .full_product_presenters import BookBlockView, BookReaderPresenter
from .full_product_ui_shell import UILanguage, concise_user_error
from .presentation_privacy import redact_local_paths

CommandDispatch = Callable[[str, Mapping[str, object]], Any]
_MAX_BOOKMARK_NAME = 80
_MAX_BOOK_LIST_ITEMS = 10_000
# Accepted TXT/HTML ingress bounds visible content at 12 MiB. Preserve the
# complete current semantic block up to that release budget instead of silently
# truncating reader-visible/copyable content to a small UI preview.
_MAX_BOOK_BLOCK_VISIBLE_CHARS = 12 * 1024 * 1024

_LABELS = {
    UILanguage.UA: {
        "heading": "Читач шахової книги",
        "location": "Місце в книзі",
        "heading_path": "Шлях заголовків",
        "source": "Джерело",
        "previous": "Попередній блок",
        "next": "Наступний блок",
        "previous_heading": "Попередній заголовок",
        "next_heading": "Наступний заголовок",
        "previous_position": "Попередня позиція",
        "next_position": "Наступна позиція",
        "previous_game": "Попередня партія",
        "next_game": "Наступна партія",
        "bookmark_name": "Назва закладки",
        "save_bookmark": "Зберегти закладку",
        "restore_bookmark": "Відновити закладку",
        "open_position": "Відкрити позицію на дошці",
        "return_from_board": "Повернутися до книги",
        "saved": "Закладку збережено.",
        "restored": "Закладку відновлено.",
        "returned": "Повернуто до місця читання.",
        "opened": "Позицію відкрито на дошці.",
        "hidden_path": "[локальний шлях приховано]",
    },
    UILanguage.EN: {
        "heading": "Chess book reader",
        "location": "Book location",
        "heading_path": "Heading path",
        "source": "Source",
        "previous": "Previous block",
        "next": "Next block",
        "previous_heading": "Previous heading",
        "next_heading": "Next heading",
        "previous_position": "Previous position",
        "next_position": "Next position",
        "previous_game": "Previous game",
        "next_game": "Next game",
        "bookmark_name": "Bookmark name",
        "save_bookmark": "Save bookmark",
        "restore_bookmark": "Restore bookmark",
        "open_position": "Open position on board",
        "return_from_board": "Return to book",
        "saved": "Bookmark saved.",
        "restored": "Bookmark restored.",
        "returned": "Returned to the reading location.",
        "opened": "Position opened on the board.",
        "hidden_path": "[local path hidden]",
    },
}


def _safe_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("book presentation text must be text")
    text = value.replace("\x00", "").strip()
    text = redact_local_paths(text, _LABELS[language]["hidden_path"])
    return text[:limit]


def _safe_visible_block_text(value: object, *, language: UILanguage) -> str:
    text = _safe_text(
        value,
        language=language,
        limit=_MAX_BOOK_BLOCK_VISIBLE_CHARS + 1,
    )
    if len(text) > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
        raise ValueError("book presentation block exceeds the visible-text budget")
    return text


def _safe_visible_list_items(
    values: tuple[str, ...],
    *,
    language: UILanguage,
) -> tuple[str, ...]:
    if len(values) > _MAX_BOOK_LIST_ITEMS:
        raise ValueError("book presentation list exceeds the item budget")
    rendered: list[str] = []
    total = 0
    for value in values:
        item = _safe_visible_block_text(value, language=language)
        total += len(item)
        if total > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
            raise ValueError("book presentation list exceeds the visible-text budget")
        rendered.append(item)
    return tuple(rendered)


def _bookmark_name(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("bookmark name must be text")
    if "\x00" in value:
        raise ValueError("bookmark name contains NUL")
    token = " ".join(value.split())
    if not token or len(token) > _MAX_BOOKMARK_NAME:
        raise ValueError("bookmark name is invalid")
    return token


@dataclass(frozen=True, slots=True)
class BookWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class BookWebViewProjection:
    def __init__(
        self,
        presenter: BookReaderPresenter,
        dispatch: CommandDispatch,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(presenter, BookReaderPresenter):
            raise TypeError("presenter must be BookReaderPresenter")
        if not callable(dispatch):
            raise TypeError("book dispatcher must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._presenter = presenter
        self._dispatch = dispatch
        self._language = language
        self._presenter.set_language(language)
        self._last_bookmark = "default"

    @property
    def language(self) -> UILanguage:
        return self._language

    @property
    def bookmark_name(self) -> str:
        """Return the transient bookmark input value for transaction rollback."""
        return self._last_bookmark

    def _result_announcement(self, key: str) -> str:
        """Return one localized deterministic success result for the Books surface."""
        if key not in {"saved", "restored", "opened", "returned"}:
            raise ValueError("unsupported book result announcement")
        return _LABELS[self._language][key]

    def restore_bookmark_name(self, name: object) -> None:
        """Restore previously validated transient bookmark input state."""
        self._last_bookmark = _bookmark_name(name)

    def set_language(self, language: UILanguage | str) -> BookWebViewEvent:
        if isinstance(language, str):
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        previous_language = self._language
        try:
            self._language = language
            self._presenter.set_language(language)
            snapshot = self.snapshot()
        except Exception:
            # Language is presentation state, but a failed render must not publish
            # a half-applied locale. Restore both projection and presenter so the
            # bridge's generic error and the next successful render remain coherent.
            self._language = previous_language
            self._presenter.set_language(previous_language)
            raise
        return BookWebViewEvent("render", {"snapshot": snapshot, "focus_target": ""})

    def _snapshot_from_block(self, block: BookBlockView) -> dict[str, object]:
        if not isinstance(block, BookBlockView):
            raise TypeError("BookReaderPresenter must return BookBlockView")
        if type(block.index) is not int or block.index < 0:
            raise ValueError("book block index is invalid")
        if block.heading_level is not None and (
            type(block.heading_level) is not int or not 1 <= block.heading_level <= 6
        ):
            raise ValueError("book heading level is invalid")
        role = str(block.role)
        if role not in {"heading", "paragraph", "img", "group", "tree", "note", "list"}:
            raise ValueError("book block role is invalid")
        if type(block.list_items) is not tuple or any(
            type(item) is not str or not item.strip() for item in block.list_items
        ):
            raise ValueError("book list items are invalid")
        if type(block.list_ordered) is not bool:
            raise ValueError("book list ordered flag is invalid")
        if block.list_start is not None and (
            type(block.list_start) is not int or block.list_start < 1
        ):
            raise ValueError("book list start is invalid")
        if block.list_start is not None and not block.list_ordered:
            raise ValueError("book list start requires an ordered list")
        if role == "list":
            if not block.list_items:
                raise ValueError("book list must contain items")
        elif block.list_items or block.list_ordered or block.list_start is not None:
            raise ValueError("non-list book block contains list metadata")
        labels = _LABELS[self._language]
        navigation = self._presenter.navigation_availability()
        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            "heading": labels["heading"],
            "location_label": labels["location"],
            "block": {
                "dom_id": f"book-block-{block.index}",
                "index": block.index,
                "kind": _safe_text(block.kind, language=self._language, limit=80),
                "role": role,
                "title": _safe_text(block.title, language=self._language, limit=360),
                "text": _safe_visible_block_text(
                    block.text,
                    language=self._language,
                ),
                "list": (
                    {
                        "items": _safe_visible_list_items(
                            block.list_items,
                            language=self._language,
                        ),
                        "ordered": block.list_ordered,
                        "start": block.list_start,
                    }
                    if role == "list"
                    else None
                ),
                "heading_level": block.heading_level,
                # Raw FEN stays in Python/presenter and is never serialized to browser.
                "has_position": block.position_fen is not None,
                "heading_path": tuple(
                    _safe_text(part, language=self._language, limit=360)
                    for part in block.heading_path
                ),
                "heading_path_label": labels["heading_path"],
                "source_anchor": _safe_text(block.source_anchor, language=self._language, limit=160),
                "source_label": labels["source"],
                "warning": _safe_text(block.warning, language=self._language, limit=1000),
            },
            "actions": (
                {"command": "book.previous", "label": labels["previous"], "enabled": navigation["previous"]},
                {"command": "book.next", "label": labels["next"], "enabled": navigation["next"]},
                {"command": "book.previous_heading", "label": labels["previous_heading"], "enabled": navigation["previous_heading"]},
                {"command": "book.next_heading", "label": labels["next_heading"], "enabled": navigation["next_heading"]},
                {"command": "book.previous_position", "label": labels["previous_position"], "enabled": navigation["previous_position"]},
                {"command": "book.next_position", "label": labels["next_position"], "enabled": navigation["next_position"]},
                {"command": "book.previous_game", "label": labels["previous_game"], "enabled": navigation["previous_game"]},
                {"command": "book.next_game", "label": labels["next_game"], "enabled": navigation["next_game"]},
                {"command": "book.open_position", "label": labels["open_position"], "enabled": block.position_fen is not None},
                {"command": "book.return_from_board", "label": labels["return_from_board"], "enabled": True},
            ),
            "bookmark": {
                "label": labels["bookmark_name"],
                "value": self._last_bookmark,
                "save_label": labels["save_bookmark"],
                "restore_label": labels["restore_bookmark"],
                "max_length": _MAX_BOOKMARK_NAME,
            },
        }

    def snapshot(self) -> dict[str, object]:
        # One immutable BookBlockView per browser render; no repeated mutable reads.
        return self._snapshot_from_block(self._presenter.current())

    def _render(self, block: BookBlockView, *, announcement: str = "") -> BookWebViewEvent:
        snapshot = self._snapshot_from_block(block)
        return BookWebViewEvent(
            "render",
            {
                "snapshot": snapshot,
                "focus_target": snapshot["block"]["dom_id"],
                "announcement": _safe_text(announcement, language=self._language, limit=1000),
            },
        )

    def previous(self) -> BookWebViewEvent:
        return self._render(self._presenter.previous_block())

    def next(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_block())

    def previous_heading(self) -> BookWebViewEvent:
        return self._render(self._presenter.previous_heading())

    def next_heading(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_heading())

    def next_position(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_position())

    def previous_position(self) -> BookWebViewEvent:
        return self._render(self._presenter.previous_position())

    def next_game(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_game())

    def previous_game(self) -> BookWebViewEvent:
        return self._render(self._presenter.previous_game())

    def save_bookmark(self, name: object) -> BookWebViewEvent:
        token = _bookmark_name(name)
        block = self._presenter.bookmark(token)
        self._last_bookmark = token
        return self._render(block, announcement=self._result_announcement("saved"))

    def restore_bookmark(self, name: object) -> BookWebViewEvent:
        token = _bookmark_name(name)
        block = self._presenter.restore_bookmark(token)
        self._last_bookmark = token
        return self._render(block, announcement=self._result_announcement("restored"))

    def open_position(self) -> BookWebViewEvent:
        # Presenter supplies FEN directly to the canonical dispatcher. Discard the
        # backend return value and expose no FEN/path/provider payload to WebView.
        self._presenter.open_current_position(self._dispatch)
        return BookWebViewEvent(
            "delegated",
            {"action": "book.open_position", "announcement": self._result_announcement("opened")},
        )

    def return_from_board(self) -> BookWebViewEvent:
        block = self._presenter.return_from_board()
        return self._render(block, announcement=self._result_announcement("returned"))

    def generic_error(self) -> BookWebViewEvent:
        return BookWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._language)},
        )
