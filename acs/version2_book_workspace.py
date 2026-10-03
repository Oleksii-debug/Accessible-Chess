"""Accessible Books composition over the accepted reader and Board workflow.

The V2 projection uses the workflow's return stack for both open and return.
It never creates the legacy presenter's independent Board return point.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .book_board_workflow import BookBoardWorkflow, BookBoardWorkflowError
from .book_webview_bridge import BookWebViewBridge
from .book_webview_projection import (
    BookWebViewEvent,
    BookWebViewProjection,
    _MAX_BOOK_BLOCK_VISIBLE_CHARS,
    _safe_text,
    _utf16_units,
)
from .bookdocument import Diagram, Exercise, Game, Position, VariationTree
from .bookreader import BookReader
from .full_product_presenters import BookReaderPresenter, PgnTreePresenter
from .full_product_ui_shell import UILanguage
from .version2_windows_book_board_adapter import BookBoardUiEvent, BookBoardUiEventKind


_MAX_BOOK_SEMANTIC_ITEMS = 10_000
_MAX_BOOK_SEMANTIC_DEPTH = 256
_MAX_BOOK_SEMANTIC_TEXT_ENTRIES = 50_000
_MAX_BOOK_SEMANTIC_SECTION_LABEL_UNITS = 360
_MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS = 120
_MAX_BOOK_SEMANTIC_PLAYERS_UNITS = 720
_MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS = 1_200
_MAX_BOOK_SEMANTIC_RESULT_UNITS = 16
_BOOK_SEMANTIC_RESULTS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})

_SEMANTIC_LABELS = {
    UILanguage.UA: {
        "moves": "Ходи та варіанти",
        "players": "Гравці",
        "result": "Результат",
        "unknown": "невідомо",
        "unavailable": "Ходи цієї партії неможливо безпечно показати; шахівниця залишається доступною.",
    },
    UILanguage.EN: {
        "moves": "Moves and variations",
        "players": "Players",
        "result": "Result",
        "unknown": "unknown",
        "unavailable": "This game's moves cannot be displayed safely; the board remains available.",
    },
}


class _BookSemanticProjectionError(ValueError):
    pass


class Version2BookReaderPresenter(BookReaderPresenter):
    """V2 presentation reuses the canonical BookReader semantic block projection."""


class Version2BookWebViewProjection(BookWebViewProjection):
    def __init__(
        self,
        reader: BookReader,
        workflow: BookBoardWorkflow,
        dispatch: Callable[[str, Mapping[str, object]], Any],
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(reader, BookReader) or not isinstance(workflow, BookBoardWorkflow):
            raise TypeError("V2 Books requires the canonical reader and workflow")
        self._reader = reader
        self._workflow = workflow
        super().__init__(Version2BookReaderPresenter(reader, language=language), dispatch, language=language)

    def _semantic_tree_snapshot(self, index: int) -> dict[str, object]:
        mode, game, _workflow_warnings = self._workflow.semantic_game_snapshot(index)
        stack: list[tuple[object, int]] = [(game.line, 0)]
        count = 0
        while stack:
            line, move_depth = stack.pop()
            moves = getattr(line, "moves", ())
            if moves and move_depth > _MAX_BOOK_SEMANTIC_DEPTH:
                raise _BookSemanticProjectionError("semantic GameTree depth limit exceeded")
            for move in moves:
                count += 1
                if count > _MAX_BOOK_SEMANTIC_ITEMS:
                    raise _BookSemanticProjectionError("semantic GameTree item limit exceeded")
                for variation in getattr(move, "variations", ()):
                    variation_depth = move_depth + 1
                    if variation_depth > _MAX_BOOK_SEMANTIC_DEPTH:
                        raise _BookSemanticProjectionError("semantic GameTree depth limit exceeded")
                    count += 1
                    if count > _MAX_BOOK_SEMANTIC_ITEMS:
                        raise _BookSemanticProjectionError("semantic GameTree item limit exceeded")
                    stack.append((variation, move_depth + 2))

        view = PgnTreePresenter((game,), language=self.language).view()
        if view.game_index != 0 or type(view.items) is not tuple:
            raise _BookSemanticProjectionError("semantic GameTree view is unavailable")
        if len(view.items) > _MAX_BOOK_SEMANTIC_ITEMS:
            raise _BookSemanticProjectionError("semantic GameTree item limit exceeded")

        visible_total = 0
        visible_entries = 0

        def clean(
            value: object,
            *,
            allow_empty: bool = True,
            max_units: int = _MAX_BOOK_BLOCK_VISIBLE_CHARS,
        ) -> tuple[str, int]:
            if type(max_units) is not int or not 0 <= max_units <= _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise _BookSemanticProjectionError("semantic GameTree scalar limit is invalid")
            try:
                text = _safe_text(
                    value,
                    language=self.language,
                    limit=max_units + 1,
                )
            except (TypeError, ValueError) as exc:
                raise _BookSemanticProjectionError("semantic GameTree text is invalid") from exc
            if not allow_empty and not text:
                raise _BookSemanticProjectionError("semantic GameTree text is empty")
            units = _utf16_units(text)
            if units > max_units:
                raise _BookSemanticProjectionError("semantic GameTree scalar text limit exceeded")
            return text, units

        def safe(
            value: object,
            *,
            allow_empty: bool = True,
            max_units: int = _MAX_BOOK_BLOCK_VISIBLE_CHARS,
        ) -> str:
            nonlocal visible_total, visible_entries
            text, units = clean(
                value,
                allow_empty=allow_empty,
                max_units=max_units,
            )
            visible_entries += 1
            if visible_entries > _MAX_BOOK_SEMANTIC_TEXT_ENTRIES:
                raise _BookSemanticProjectionError("semantic GameTree text-entry limit exceeded")
            visible_total += units
            if visible_total > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise _BookSemanticProjectionError("semantic GameTree text budget exceeded")
            return text

        def safe_many(values: object) -> tuple[str, ...]:
            if type(values) is not tuple:
                raise _BookSemanticProjectionError("semantic comment collection is invalid")
            rendered: list[str] = []
            for value in values:
                text = safe(value)
                if text:
                    rendered.append(text)
            return tuple(rendered)

        labels = _SEMANTIC_LABELS[self.language]
        white, _ = clean(game.tags.get("White", ""))
        black, _ = clean(game.tags.get("Black", ""))
        white = white or labels["unknown"]
        black = black or labels["unknown"]
        result = game.result
        if result not in _BOOK_SEMANTIC_RESULTS:
            raise _BookSemanticProjectionError("semantic game result is invalid")

        semantic_label = safe(
            labels["moves"],
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_SECTION_LABEL_UNITS,
        )
        players_label = safe(
            labels["players"],
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS,
        )
        players = safe(
            f"{white} — {black}",
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_PLAYERS_UNITS,
        )
        result_label = safe(
            labels["result"],
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS,
        )
        result_text = safe(
            result,
            allow_empty=False,
            max_units=_MAX_BOOK_SEMANTIC_RESULT_UNITS,
        )
        intro_comments = tuple(
            text
            for text in (safe(getattr(comment, "text", None)) for comment in game.line.leading_comments)
            if text
        )
        outro_comments = tuple(
            text
            for text in (safe(getattr(comment, "text", None)) for comment in game.line.trailing_comments)
            if text
        )

        rendered_items: list[dict[str, object]] = []
        seen: dict[str, int] = {}
        for position, item in enumerate(view.items):
            if item.kind not in {"move", "variation"}:
                raise _BookSemanticProjectionError("semantic item kind is invalid")
            if type(item.depth) is not int or not 0 <= item.depth <= _MAX_BOOK_SEMANTIC_DEPTH:
                raise _BookSemanticProjectionError("semantic item depth is invalid")
            if type(item.node_id) is not str or not item.node_id or item.node_id in seen:
                raise _BookSemanticProjectionError("semantic item identity is invalid")
            if item.depth == 0:
                if item.parent_id is not None:
                    raise _BookSemanticProjectionError("semantic root parent is invalid")
                parent_index: int | None = None
            else:
                if type(item.parent_id) is not str or item.parent_id not in seen:
                    raise _BookSemanticProjectionError("semantic parent is unavailable")
                parent_index = seen[item.parent_id]
                if rendered_items[parent_index]["depth"] != item.depth - 1:
                    raise _BookSemanticProjectionError("semantic parent depth is inconsistent")

            item_result = item.result or ""
            if item_result and item_result not in _BOOK_SEMANTIC_RESULTS:
                raise _BookSemanticProjectionError("semantic variation result is invalid")
            rendered_items.append(
                {
                    "kind": item.kind,
                    "depth": item.depth,
                    "parent_index": parent_index,
                    "label": safe(
                        item.label,
                        allow_empty=False,
                        max_units=_MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS,
                    ),
                    "leading_comments": safe_many(item.comments) if item.kind == "variation" else (),
                    "comments_before": safe_many(item.comments_before),
                    "comments_after": safe_many(item.comments_after),
                    "trailing_comments": safe_many(item.trailing_comments),
                    "result": safe(
                        item_result,
                        max_units=_MAX_BOOK_SEMANTIC_RESULT_UNITS,
                    ),
                }
            )
            seen[item.node_id] = position

        return {
            "kind": mode.value,
            "label": semantic_label,
            "players_label": players_label,
            "players": players,
            "result_label": result_label,
            "result": result_text,
            "intro_comments": intro_comments,
            "outro_comments": outro_comments,
            "items": tuple(rendered_items),
        }

    def _snapshot_from_block(self, block):
        snapshot = super()._snapshot_from_block(block)
        # Reuse the reader-owned detached revision. Never re-read the live mutable
        # BookDocument after the presenter has validated a ReadingLocation.
        semantic = self._reader.block_snapshot(block.index)
        board_active = self._workflow.active
        can_open_position = isinstance(
            semantic,
            (Position, Diagram, Exercise, VariationTree),
        )
        can_open_game = isinstance(semantic, Game)
        if isinstance(semantic, (Game, VariationTree)):
            try:
                snapshot["semantic_tree"] = self._semantic_tree_snapshot(block.index)
            except (BookBoardWorkflowError, _BookSemanticProjectionError, AttributeError, TypeError, ValueError):
                snapshot["semantic_tree"] = None
                snapshot["block"]["warning"] = _SEMANTIC_LABELS[self.language]["unavailable"]
        actions = []
        for original in snapshot["actions"]:
            action = dict(original)
            if action["command"] == "book.open_position":
                # The WebView exposes a semantic position control. Native/menu
                # compatibility may still invoke book.open_position for a Game,
                # but the browser gets one unambiguous Game-specific action.
                action["enabled"] = can_open_position and not board_active
                action["label"] = "Відкрити на шахівниці" if self.language is UILanguage.UA else "Open on board"
            elif action["command"] == "book.open_game":
                action["enabled"] = can_open_game and not board_active
            elif action["command"] == "book.return_from_board":
                action["enabled"] = board_active
            actions.append(action)
        snapshot["actions"] = tuple(actions)
        snapshot["board_active"] = board_active
        return snapshot

    def _workflow_action(self, action: str, expected: BookBoardUiEventKind) -> bool:
        result = self._dispatch(action, {})
        # A canonical router returns ActionDispatchResult; a composed callback
        # may already unwrap it. A transition is successful only when the event
        # belongs to the action we dispatched and the canonical workflow reached
        # the corresponding state. This prevents stale/misrouted success DTOs
        # from producing false NVDA success announcements.
        result = getattr(result, "value", result)
        if (
            not isinstance(result, BookBoardUiEvent)
            or result.kind is not expected
            or result.action_id != action
            or result.revision != self._workflow.revision
        ):
            return False
        if expected is BookBoardUiEventKind.BOARD_OPENED:
            return self._workflow.active
        if expected is BookBoardUiEventKind.RETURNED_TO_BOOK:
            return not self._workflow.active
        return True

    def open_position(self) -> BookWebViewEvent:
        announcement = self._result_announcement("opened")
        if not self._workflow_action("book.open_position", BookBoardUiEventKind.BOARD_OPENED):
            return self.generic_error()
        return BookWebViewEvent(
            "delegated",
            {
                "action": "book.open_position",
                "announcement": announcement,
            },
        )

    def open_game(self) -> BookWebViewEvent:
        announcement = self._result_announcement("game_opened")
        if not self._workflow_action("book.open_game", BookBoardUiEventKind.BOARD_OPENED):
            return self.generic_error()
        return BookWebViewEvent(
            "delegated",
            {
                "action": "book.open_game",
                "announcement": announcement,
            },
        )

    def return_from_board(self) -> BookWebViewEvent:
        announcement = self._result_announcement("returned")
        if not self._workflow_action("book.return", BookBoardUiEventKind.RETURNED_TO_BOOK):
            return self.generic_error()
        return self._render(
            self._presenter.current(),
            announcement=announcement,
        )


def build_version2_book_webview(reader, workflow, dispatch, *, language=UILanguage.UA) -> BookWebViewBridge:
    return BookWebViewBridge(Version2BookWebViewProjection(reader, workflow, dispatch, language=language))
