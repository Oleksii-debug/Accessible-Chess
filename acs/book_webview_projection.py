"""Accessible BookReader WebView projection over the canonical BookReaderPresenter.

DEV1 owns presentation only. The browser never receives raw FEN/PGN or source
filesystem paths. Opening a chess position delegates inside Python through the
existing BookReaderPresenter so the canonical board/application layer remains the
only owner of chess state.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from typing import Any

from .full_product_presenters import BookBlockView, BookReaderPresenter
from .full_product_ui_shell import UILanguage, concise_user_error

CommandDispatch = Callable[[str, Mapping[str, object]], Any]
_MAX_BOOKMARK_NAME = 80
_WINDOWS_PATH = re.compile(r"(?i)(?<![\w])([a-z]:[\\/][^\r\n\t]*)")
_POSIX_PATH = re.compile(r"(?i)(?<![\w])(/(?:home|users|tmp|mnt|var/tmp|private/tmp)/[^\r\n\t ]*)")

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
        "next_position": "Наступна позиція",
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
        "next_position": "Next position",
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
    replacement = _LABELS[language]["hidden_path"]
    text = _WINDOWS_PATH.sub(replacement, text)
    text = _POSIX_PATH.sub(replacement, text)
    return text[:limit]


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

    def set_language(self, language: UILanguage | str) -> BookWebViewEvent:
        if isinstance(language, str):
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language
        self._presenter.set_language(language)
        return BookWebViewEvent("render", {"snapshot": self.snapshot(), "focus_target": ""})

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
        if role not in {"heading", "paragraph", "img", "group", "tree", "note"}:
            raise ValueError("book block role is invalid")
        labels = _LABELS[self._language]
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
                "text": _safe_text(block.text, language=self._language, limit=8000),
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
                {"command": "book.previous", "label": labels["previous"], "enabled": block.index > 0},
                {"command": "book.next", "label": labels["next"], "enabled": True},
                {"command": "book.previous_heading", "label": labels["previous_heading"], "enabled": block.index > 0},
                {"command": "book.next_heading", "label": labels["next_heading"], "enabled": True},
                {"command": "book.next_position", "label": labels["next_position"], "enabled": True},
                {"command": "book.next_game", "label": labels["next_game"], "enabled": True},
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

    def next_game(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_game())

    def save_bookmark(self, name: object) -> BookWebViewEvent:
        token = _bookmark_name(name)
        block = self._presenter.bookmark(token)
        self._last_bookmark = token
        return self._render(block, announcement=_LABELS[self._language]["saved"])

    def restore_bookmark(self, name: object) -> BookWebViewEvent:
        token = _bookmark_name(name)
        block = self._presenter.restore_bookmark(token)
        self._last_bookmark = token
        return self._render(block, announcement=_LABELS[self._language]["restored"])

    def open_position(self) -> BookWebViewEvent:
        # Presenter supplies FEN directly to the canonical dispatcher. Discard the
        # backend return value and expose no FEN/path/provider payload to WebView.
        self._presenter.open_current_position(self._dispatch)
        return BookWebViewEvent(
            "delegated",
            {"action": "book.open_position", "announcement": _LABELS[self._language]["opened"]},
        )

    def return_from_board(self) -> BookWebViewEvent:
        block = self._presenter.return_from_board()
        return self._render(block, announcement=_LABELS[self._language]["returned"])

    def generic_error(self) -> BookWebViewEvent:
        return BookWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._language)},
        )
