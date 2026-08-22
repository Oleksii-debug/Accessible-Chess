"""Accessible Book Reader WebView projection over the canonical BookReaderPresenter.

DEV1 owns presentation only. Semantic book structure, durable reader state, chess
positions, imported content, and GameTree semantics remain canonical service/domain
responsibilities. The browser receives bounded text and neutral command intents.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any

from .full_product_presenters import BookBlockView, BookReaderPresenter
from .full_product_ui_shell import UILanguage, concise_user_error

CommandDispatch = Callable[[str, Mapping[str, object]], Any]
BlockCountProvider = Callable[[], int]

_WINDOWS_LOCAL_PATH = re.compile(r"(?i)(?<![\w])([a-z]:[\\/][^\r\n\t]*)")
_POSIX_LOCAL_PATH = re.compile(
    r"(?i)(?<![\w])(/(?:home|users|tmp|mnt|var/tmp|private/tmp)/[^\r\n\t ]*)"
)

_LABELS = {
    UILanguage.UA: {
        "heading": "Читач шахової книги",
        "description": "Структуроване читання книги з переходами до позицій і поверненням у те саме місце.",
        "empty": "У книзі немає доступних блоків.",
        "previous": "Попередній блок",
        "next": "Наступний блок",
        "previous_heading": "Попередній заголовок",
        "next_heading": "Наступний заголовок",
        "next_position": "Наступна позиція",
        "next_game": "Наступна партія",
        "bookmark": "Зберегти закладку",
        "restore": "Відновити закладку",
        "bookmark_name": "Назва закладки",
        "open_position": "Відкрити позицію на шахівниці",
        "return_from_board": "Повернутися до книги",
        "source": "Джерело",
        "section_path": "Розділ",
        "position": "Позиція для шахівниці",
        "block": "Блок",
        "of": "з",
        "transport_error": "Не вдалося виконати дію книги.",
        "local_path": "[локальний шлях приховано]",
    },
    UILanguage.EN: {
        "heading": "Chess book reader",
        "description": "Structured book reading with position hand-off and exact return to reading context.",
        "empty": "The book has no readable blocks.",
        "previous": "Previous block",
        "next": "Next block",
        "previous_heading": "Previous heading",
        "next_heading": "Next heading",
        "next_position": "Next position",
        "next_game": "Next game",
        "bookmark": "Save bookmark",
        "restore": "Restore bookmark",
        "bookmark_name": "Bookmark name",
        "open_position": "Open position on board",
        "return_from_board": "Return to book",
        "source": "Source",
        "section_path": "Section",
        "position": "Board position",
        "block": "Block",
        "of": "of",
        "transport_error": "The book action could not be completed.",
        "local_path": "[local path hidden]",
    },
}


def _safe_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("book presentation text must be text")
    text = value.replace("\x00", "").strip()
    replacement = _LABELS[language]["local_path"]
    text = _WINDOWS_LOCAL_PATH.sub(replacement, text)
    text = _POSIX_LOCAL_PATH.sub(replacement, text)
    return text[:limit]


def _dom_token(index: int, kind: str) -> str:
    return "book-block-" + sha256(f"{index}:{kind}".encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class BookWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class BookWebViewProjection:
    """JSON-ready semantic reader surface with explicit focus restoration."""

    def __init__(
        self,
        presenter: BookReaderPresenter,
        dispatch: CommandDispatch,
        block_count: BlockCountProvider,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(presenter, BookReaderPresenter):
            raise TypeError("presenter must be BookReaderPresenter")
        if not callable(dispatch):
            raise TypeError("book dispatcher must be callable")
        if not callable(block_count):
            raise TypeError("book block_count provider must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._presenter = presenter
        self._dispatch = dispatch
        self._block_count = block_count
        self._language = language
        self._presenter.set_language(language)

    @property
    def language(self) -> UILanguage:
        return self._language

    def _count(self) -> int:
        value = self._block_count()
        if type(value) is not int or not 0 <= value <= 10_000_000:
            raise ValueError("book block count is invalid")
        return value

    def _block(self, block: BookBlockView, count: int) -> dict[str, object]:
        if type(block.index) is not int or not 0 <= block.index < count:
            raise ValueError("book presenter index disagrees with document size")
        if not isinstance(block.kind, str) or not block.kind or len(block.kind) > 80:
            raise ValueError("book presenter kind is invalid")
        if block.heading_level is not None and (
            type(block.heading_level) is not int or not 1 <= block.heading_level <= 6
        ):
            raise ValueError("book heading level is invalid")
        heading_path = tuple(
            _safe_text(item, language=self._language, limit=240)
            for item in block.heading_path
        )
        source_anchor = _safe_text(block.source_anchor, language=self._language, limit=160)
        title = _safe_text(block.title, language=self._language, limit=320)
        text = _safe_text(block.text, language=self._language, limit=12_000)
        warning = _safe_text(block.warning, language=self._language, limit=720)
        fen = block.position_fen
        if fen is not None:
            if not isinstance(fen, str) or "\x00" in fen or len(fen) > 512:
                raise ValueError("book board position is invalid")
            fen = fen.strip()
            if not fen:
                raise ValueError("book board position is empty")
        return {
            "dom_id": _dom_token(block.index, block.kind),
            "index": block.index,
            "kind": block.kind,
            "role": block.role,
            "title": title,
            "text": text,
            "heading_level": block.heading_level,
            "heading_path": heading_path,
            "source_anchor": source_anchor,
            "warning": warning,
            # FEN is canonical book position state passed through for the shared
            # sighted/NVDA board surface. DEV1 does not parse or mutate it.
            "board_position_fen": fen,
        }

    def _snapshot_from_block(self, block: BookBlockView, count: int) -> dict[str, object]:
        labels = _LABELS[self._language]
        projected = self._block(block, count)
        can_open_position = projected["board_position_fen"] is not None
        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            "status": "ready",
            "heading": labels["heading"],
            "description": labels["description"],
            "empty_message": "",
            "position_label": f"{labels['block']} {block.index + 1} {labels['of']} {count}",
            "section_path_label": labels["section_path"],
            "source_label": labels["source"],
            "board_label": labels["position"],
            "bookmark_name_label": labels["bookmark_name"],
            "transport_error_message": labels["transport_error"],
            "current": projected,
            "focus_target": projected["dom_id"],
            "actions": (
                {"action": "book.previous_block", "label": labels["previous"], "enabled": block.index > 0},
                {"action": "book.next_block", "label": labels["next"], "enabled": block.index + 1 < count},
                {"action": "book.previous_heading", "label": labels["previous_heading"], "enabled": block.index > 0},
                {"action": "book.next_heading", "label": labels["next_heading"], "enabled": block.index + 1 < count},
                {"action": "book.next_position", "label": labels["next_position"], "enabled": block.index + 1 < count},
                {"action": "book.next_game", "label": labels["next_game"], "enabled": block.index + 1 < count},
                {"action": "book.bookmark", "label": labels["bookmark"], "enabled": True},
                {"action": "book.restore_bookmark", "label": labels["restore"], "enabled": True},
                {"action": "book.open_position", "label": labels["open_position"], "enabled": can_open_position},
                {"action": "book.return_from_board", "label": labels["return_from_board"], "enabled": True},
            ),
        }

    def snapshot(self) -> dict[str, object]:
        count = self._count()
        if count == 0:
            labels = _LABELS[self._language]
            return {
                "document": {"lang": self._language.value, "landmark": "main"},
                "status": "empty",
                "heading": labels["heading"],
                "description": labels["description"],
                "empty_message": labels["empty"],
                "position_label": "",
                "section_path_label": labels["section_path"],
                "source_label": labels["source"],
                "board_label": labels["position"],
                "bookmark_name_label": labels["bookmark_name"],
                "transport_error_message": labels["transport_error"],
                "current": {},
                "focus_target": "book-reader-root",
                "actions": (),
            }
        # Exactly one immutable BookBlockView drives the full active render.
        return self._snapshot_from_block(self._presenter.current(), count)

    def _render(self, block: BookBlockView, *, announce: bool = False) -> BookWebViewEvent:
        snapshot = self._snapshot_from_block(block, self._count())
        current = snapshot["current"]
        announcement = ""
        if announce:
            announcement = str(current.get("title") or current.get("text") or snapshot["position_label"])
        return BookWebViewEvent(
            "render",
            {
                "snapshot": snapshot,
                "focus_target": snapshot["focus_target"],
                "announcement": announcement,
            },
        )

    def previous_block(self) -> BookWebViewEvent:
        return self._render(self._presenter.previous_block())

    def next_block(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_block())

    def previous_heading(self) -> BookWebViewEvent:
        return self._render(self._presenter.previous_heading(), announce=True)

    def next_heading(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_heading(), announce=True)

    def next_position(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_position(), announce=True)

    def next_game(self) -> BookWebViewEvent:
        return self._render(self._presenter.next_game(), announce=True)

    def bookmark(self, name: str) -> BookWebViewEvent:
        return self._render(self._presenter.bookmark(name), announce=False)

    def restore_bookmark(self, name: str) -> BookWebViewEvent:
        return self._render(self._presenter.restore_bookmark(name), announce=True)

    def open_current_position(self) -> BookWebViewEvent:
        self._presenter.open_current_position(self._dispatch)
        return BookWebViewEvent("delegated", {"action": "book.open_position"})

    def return_from_board(self) -> BookWebViewEvent:
        return self._render(self._presenter.return_from_board(), announce=True)

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
        return BookWebViewEvent("render", {"snapshot": self.snapshot(), "focus_target": "", "announcement": ""})

    def safe_call(self, method: Callable[[], BookWebViewEvent]) -> BookWebViewEvent:
        try:
            return method()
        except Exception as exc:
            return BookWebViewEvent(
                "error",
                {"message": concise_user_error(exc, language=self._language)},
            )
