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
# Accepted TXT/HTML ingress bounds visible content at 12 MiB. Preserve the
# complete current semantic block up to that release budget instead of silently
# truncating reader-visible/copyable content to a small UI preview.
_MAX_BOOK_BLOCK_VISIBLE_CHARS = 12 * 1024 * 1024
_MAX_BOOK_LIST_ITEMS = 65536
_MAX_BOOK_HEADING_PATH_PARTS = 6
_MAX_BOOK_POSITION_TOKEN_CHARS = 4096
_MAX_JS_SAFE_INTEGER = (1 << 53) - 1
_BOOK_ROLE_BY_KIND = {
    "Heading": "heading",
    "Paragraph": "paragraph",
    "List": "list",
    "Position": "group",
    "Diagram": "img",
    "Game": "group",
    # VariationTree is currently a read-only semantic text block. Do not expose
    # an ARIA tree until the structured GameTree projection is present in this
    # lineage; a one-item tree would imply keyboard/tree semantics that do not exist.
    "VariationTree": "group",
    "Exercise": "group",
    "Note": "note",
}
_POSITION_KINDS = {"Position", "Diagram", "Exercise", "VariationTree"}
_NAVIGATION_KEYS = {
    "previous",
    "next",
    "previous_heading",
    "next_heading",
    "previous_position",
    "next_position",
    "previous_game",
    "next_game",
}

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
        "open_game": "Відкрити партію на дошці",
        "return_from_board": "Повернутися до книги",
        "saved": "Закладку збережено.",
        "restored": "Закладку відновлено.",
        "returned": "Повернуто до місця читання.",
        "opened": "Позицію відкрито на дошці.",
        "game_opened": "Партію відкрито на дошці.",
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
        "open_game": "Open game on board",
        "return_from_board": "Return to book",
        "saved": "Bookmark saved.",
        "restored": "Bookmark restored.",
        "returned": "Returned to the reading location.",
        "opened": "Position opened on the board.",
        "game_opened": "Game opened on the board.",
        "hidden_path": "[local path hidden]",
    },
}


def _utf16_units(value: str) -> int:
    """Return the exact JavaScript String.length for one Python string."""

    return sum(2 if ord(character) > 0xFFFF else 1 for character in value)


def _truncate_utf16(value: str, limit: int) -> str:
    """Bound text by WebView UTF-16 units without splitting a Unicode scalar."""

    if type(limit) is not int or limit < 0:
        raise ValueError("book presentation text limit is invalid")
    used = 0
    end = 0
    for end, character in enumerate(value, start=1):
        width = 2 if ord(character) > 0xFFFF else 1
        if used + width > limit:
            return value[: end - 1]
        used += width
    return value


def _safe_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    # Exact built-in strings only: presentation ingress must never execute
    # overridden replace/strip/iteration hooks from a hostile str subclass.
    if type(value) is not str:
        raise TypeError("book presentation text must be text")
    # Keep every sanitizer scan behind the canonical imported-content ceiling.
    # Small WebView fields may still be deterministically truncated to their
    # field-specific limit, but malformed trusted-side state cannot make that
    # sanitizer traverse an unbounded scalar first.
    if len(value) > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
        raise ValueError("book presentation text exceeds the raw text budget")
    text = value.replace("\x00", "").strip()
    text = redact_local_paths(text, _LABELS[language]["hidden_path"])
    return _truncate_utf16(text, limit)


def _safe_visible_block_text(value: object, *, language: UILanguage) -> str:
    # Imported Book content is already bounded by the same 12 MiB release
    # envelope. Reject wrong scalar types before even asking them for length,
    # then reject oversized text from O(1) Python length metadata before NUL
    # stripping/path redaction scan it.
    if type(value) is not str:
        raise TypeError("book presentation text must be text")
    if len(value) > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
        raise ValueError("book presentation block exceeds the visible-text budget")
    # Two UTF-16 units are enough to retain one complete non-BMP scalar beyond
    # the canonical WebView budget, making oversize detection exact without
    # slicing through a surrogate pair on the browser side.
    text = _safe_text(
        value,
        language=language,
        limit=_MAX_BOOK_BLOCK_VISIBLE_CHARS + 2,
    )
    if _utf16_units(text) > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
        raise ValueError("book presentation block exceeds the visible-text budget")
    return text


def _safe_visible_list_items(
    values: tuple[str, ...],
    *,
    language: UILanguage,
) -> tuple[str, ...]:
    if len(values) > _MAX_BOOK_LIST_ITEMS:
        raise ValueError("book presentation list exceeds the item-count budget")
    rendered: list[str] = []
    total = 0
    for value in values:
        item = _safe_visible_block_text(value, language=language)
        if not item:
            raise ValueError("book presentation list contains an empty visible item")
        total += _utf16_units(item)
        if total > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
            raise ValueError("book presentation list exceeds the visible-text budget")
        rendered.append(item)
    return tuple(rendered)


def _bookmark_name(value: object) -> str:
    if type(value) is not str:
        raise TypeError("bookmark name must be text")
    # Browser maxLength already constrains this field to 80 UTF-16 units. Apply
    # the raw Python-character bound before split/join so direct host ingress
    # cannot make bookmark normalization scan an arbitrarily large value.
    if len(value) > _MAX_BOOKMARK_NAME:
        raise ValueError("bookmark name is invalid")
    if "\x00" in value:
        raise ValueError("bookmark name contains NUL")
    token = " ".join(value.split())
    if not token or _utf16_units(token) > _MAX_BOOKMARK_NAME:
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
        # The projection owns the browser/NVDA publication boundary. Accept only
        # the canonical presenter so provider-defined subclasses cannot override
        # current(), navigation, language, or board-handoff behavior.
        if type(presenter) is not BookReaderPresenter:
            raise TypeError("presenter must be BookReaderPresenter")
        if not callable(dispatch):
            raise TypeError("book dispatcher must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._presenter = presenter
        self._dispatch = dispatch
        self._language = language
        BookReaderPresenter.set_language(self._presenter, language)
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
        if key not in {"saved", "restored", "opened", "game_opened", "returned"}:
            raise ValueError("unsupported book result announcement")
        return _LABELS[self._language][key]

    def restore_bookmark_name(self, name: object) -> None:
        """Restore previously validated transient bookmark input state."""
        self._last_bookmark = _bookmark_name(name)

    def set_language(self, language: UILanguage | str) -> BookWebViewEvent:
        if type(language) is str:
            if len(language) > 8:
                raise ValueError("unsupported UI language")
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        previous_language = self._language
        try:
            self._language = language
            BookReaderPresenter.set_language(self._presenter, language)
            snapshot = self.snapshot()
        except BaseException:
            # Language is presentation state, but a failed render must not publish
            # a half-applied locale. Restore both projection and presenter so the
            # bridge's generic error and the next successful render remain coherent.
            self._language = previous_language
            BookReaderPresenter.set_language(self._presenter, previous_language)
            raise
        return BookWebViewEvent("render", {"snapshot": snapshot, "focus_target": ""})

    def _snapshot_from_block(self, block: BookBlockView) -> dict[str, object]:
        if type(block) is not BookBlockView:
            raise TypeError("BookReaderPresenter must return exact BookBlockView")
        if (
            type(block.index) is not int
            or block.index < 0
            or block.index > _MAX_JS_SAFE_INTEGER
        ):
            raise ValueError("book block index is invalid")
        if block.heading_level is not None and (
            type(block.heading_level) is not int or not 1 <= block.heading_level <= 6
        ):
            raise ValueError("book heading level is invalid")
        if type(block.kind) is not str or block.kind not in _BOOK_ROLE_BY_KIND:
            raise ValueError("book block kind is invalid")
        if type(block.role) is not str:
            raise TypeError("book block role must be text")
        role = block.role
        if role != _BOOK_ROLE_BY_KIND[block.kind]:
            raise ValueError("book block kind/role is inconsistent")
        for field_name, field_value in (
            ("title", block.title),
            ("text", block.text),
            ("source anchor", block.source_anchor),
            ("warning", block.warning),
        ):
            if type(field_value) is not str:
                raise TypeError(f"book block {field_name} must be text")
            # The visible body already owns the 12 MiB release envelope. Reuse
            # that envelope as the absolute trusted-side scalar ceiling for
            # presentation metadata too, so malformed presenter state cannot
            # force replace/strip/path-redaction to scan an unbounded string
            # before the smaller WebView-specific truncation is applied.
            if len(field_value) > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise ValueError(f"book block {field_name} exceeds the raw text budget")
        if block.position_fen is not None:
            # Raw FEN never crosses the WebView boundary, but it still reaches
            # this presentation preflight. Bound it before strip/dispatch so a
            # malformed trusted-side DTO cannot trigger an unbounded scan.
            if type(block.position_fen) is not str:
                raise TypeError("book block position must be text")
            if (
                len(block.position_fen) > _MAX_BOOK_POSITION_TOKEN_CHARS
                or "\x00" in block.position_fen
            ):
                raise ValueError("book board-position token is invalid")
            if not block.position_fen.strip():
                raise ValueError("book block position must not be empty")
        if type(block.heading_path) is not tuple or len(block.heading_path) > _MAX_BOOK_HEADING_PATH_PARTS:
            raise ValueError("book heading path is invalid")
        for part in block.heading_path:
            if type(part) is not str:
                raise ValueError("book heading path is invalid")
            if len(part) > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise ValueError("book heading path exceeds the raw text budget")
            if not part.strip():
                raise ValueError("book heading path is invalid")
        if block.kind == "Heading":
            if block.heading_level is None:
                raise ValueError("book heading block requires a heading level")
        elif block.heading_level is not None:
            raise ValueError("non-heading book block contains a heading level")
        if (block.position_fen is not None) != (block.kind in _POSITION_KINDS):
            raise ValueError("book block position presence disagrees with semantic kind")
        if type(block.list_items) is not tuple:
            raise ValueError("book list items are invalid")
        if len(block.list_items) > _MAX_BOOK_LIST_ITEMS:
            raise ValueError("book presentation list exceeds the item-count budget")
        for item in block.list_items:
            if type(item) is not str or not item:
                raise ValueError("book list items are invalid")
            # Reject one malformed scalar from O(1) length metadata before
            # NUL stripping, whitespace normalization, path redaction or
            # UTF-16 accounting can scan attacker-controlled presentation text.
            if len(item) > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise ValueError("book list item exceeds the raw text budget")
        if type(block.list_ordered) is not bool:
            raise ValueError("book list ordered flag is invalid")
        if block.list_start is not None and (
            type(block.list_start) is not int
            or block.list_start < 1
            or block.list_start > _MAX_JS_SAFE_INTEGER
        ):
            raise ValueError("book list start is invalid")
        if block.list_start is not None and not block.list_ordered:
            raise ValueError("book list start requires an ordered list")
        if role == "list":
            if not block.list_items:
                raise ValueError("book list must contain items")
        elif block.list_items or block.list_ordered or block.list_start is not None:
            raise ValueError("non-list book block contains list metadata")
        safe_heading_path = tuple(
            _safe_text(part, language=self._language, limit=360)
            for part in block.heading_path
        )
        if any(not part for part in safe_heading_path):
            raise ValueError("book heading path contains an empty visible part")
        labels = _LABELS[self._language]
        navigation = BookReaderPresenter.navigation_availability(self._presenter)
        # Presenter navigation is a trust boundary just like BookBlockView.
        # Require the canonical built-in container before iteration, hashing,
        # equality or lookup can invoke provider-defined hooks.
        if type(navigation) is not dict or len(navigation) != len(_NAVIGATION_KEYS):
            raise ValueError("book navigation availability schema is invalid")
        for key, value in navigation.items():
            if type(key) is not str or key not in _NAVIGATION_KEYS:
                raise ValueError("book navigation availability schema is invalid")
            if type(value) is not bool:
                raise ValueError("book navigation availability flags are invalid")
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
                "heading_path": safe_heading_path,
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
                {"command": "book.open_game", "label": labels["open_game"], "enabled": block.kind == "Game"},
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
        return self._snapshot_from_block(BookReaderPresenter.current(self._presenter))

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

    def _navigate(
        self,
        operation: Callable[[BookReaderPresenter], BookBlockView],
        *,
        announcement: str = "",
    ) -> BookWebViewEvent:
        before_index = self._presenter.cursor_index
        try:
            return self._render(operation(self._presenter), announcement=announcement)
        except BaseException:
            if self._presenter.cursor_index != before_index:
                BookReaderPresenter.restore_cursor(self._presenter, before_index)
            raise

    def previous(self) -> BookWebViewEvent:
        return self._navigate(BookReaderPresenter.previous_block)

    def next(self) -> BookWebViewEvent:
        return self._navigate(BookReaderPresenter.next_block)

    def previous_heading(self) -> BookWebViewEvent:
        return self._navigate(BookReaderPresenter.previous_heading)

    def next_heading(self) -> BookWebViewEvent:
        return self._navigate(BookReaderPresenter.next_heading)

    def next_position(self) -> BookWebViewEvent:
        return self._navigate(BookReaderPresenter.next_position)

    def previous_position(self) -> BookWebViewEvent:
        return self._navigate(BookReaderPresenter.previous_position)

    def next_game(self) -> BookWebViewEvent:
        return self._navigate(BookReaderPresenter.next_game)

    def previous_game(self) -> BookWebViewEvent:
        return self._navigate(BookReaderPresenter.previous_game)

    def save_bookmark(self, name: object) -> BookWebViewEvent:
        token = _bookmark_name(name)
        previous_name = self._last_bookmark
        announcement = self._result_announcement("saved")
        # Saving a bookmark does not move the canonical cursor. Validate the
        # exact post-save WebView snapshot first so a presentation failure can
        # never leave behind a bookmark that the browser did not accept.
        self._last_bookmark = token
        try:
            event = self._render(
                BookReaderPresenter.current(self._presenter),
                announcement=announcement,
            )
            BookReaderPresenter.bookmark(self._presenter, token)
        except BaseException:
            self._last_bookmark = previous_name
            raise
        return event

    def restore_bookmark(self, name: object) -> BookWebViewEvent:
        token = _bookmark_name(name)
        previous_name = self._last_bookmark
        self._last_bookmark = token
        try:
            return self._navigate(
                lambda presenter: BookReaderPresenter.restore_bookmark(presenter, token),
                announcement=self._result_announcement("restored"),
            )
        except BaseException:
            self._last_bookmark = previous_name
            raise

    def open_position(self) -> BookWebViewEvent:
        # Complete the exact WebView presentation contract before the irreversible
        # board handoff. A local semantic/schema failure must never activate Book
        # Board while the browser remains on a reading surface it could not render.
        announcement = self._result_announcement("opened")
        self.snapshot()
        # Presenter supplies FEN directly to the canonical dispatcher. Discard the
        # backend return value and expose no FEN/path/provider payload to WebView.
        BookReaderPresenter.open_current_position(self._presenter, self._dispatch)
        return BookWebViewEvent(
            "delegated",
            {"action": "book.open_position", "announcement": announcement},
        )

    def open_game(self) -> BookWebViewEvent:
        announcement = self._result_announcement("game_opened")
        self.snapshot()
        BookReaderPresenter.open_current_game(self._presenter, self._dispatch)
        return BookWebViewEvent(
            "delegated",
            {"action": "book.open_game", "announcement": announcement},
        )

    def return_from_board(self) -> BookWebViewEvent:
        return self._navigate(
            BookReaderPresenter.return_from_board,
            announcement=self._result_announcement("returned"),
        )

    def generic_error(self) -> BookWebViewEvent:
        return BookWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._language)},
        )
