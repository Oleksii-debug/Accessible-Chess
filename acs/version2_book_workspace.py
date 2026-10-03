"""Accessible Books composition over the accepted reader and Board workflow.

The V2 projection uses the workflow's return stack for both open and return.
It never creates the legacy presenter's independent Board return point.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .book_board_workflow import (
    BookBoardWorkflow,
    BookBoardWorkflowCode,
    BookBoardWorkflowError,
)
from .book_webview_bridge import BookWebViewBridge
from .book_webview_projection import (
    BookWebViewEvent,
    BookWebViewProjection,
    _MAX_BOOK_BLOCK_VISIBLE_CHARS,
    _safe_text,
)
from .bookdocument import Diagram, Exercise, Game, Position, VariationTree
from .bookreader import BookReader
from .full_product_presenters import BookReaderPresenter, PgnTreePresenter
from .full_product_ui_shell import UILanguage
from .version2_windows_book_board_adapter import BookBoardUiEvent, BookBoardUiEventKind


_SEMANTIC_TREE_LABELS = {
    UILanguage.UA: {
        "moves": "Ходи та варіанти",
        "result": "Результат",
        "comments": "Коментарі",
        "warnings": "Попередження відновлення",
        "unavailable": "Вміст партії недоступний або некоректний; ходи не показано.",
    },
    UILanguage.EN: {
        "moves": "Moves and variations",
        "result": "Result",
        "comments": "Comments",
        "warnings": "Recovery warnings",
        "unavailable": "Game content is unavailable or invalid; moves are not shown.",
    },
}


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
        mode, game, workflow_warnings = self._workflow.semantic_game_snapshot(index)
        view = PgnTreePresenter((game,), language=self.language).view()
        if view.game_index != 0:
            raise ValueError("book semantic GameTree projection is unavailable")

        visible_total = 0

        def safe(value: object) -> str:
            nonlocal visible_total
            text = _safe_text(
                value,
                language=self.language,
                limit=_MAX_BOOK_BLOCK_VISIBLE_CHARS + 1,
            )
            visible_total += len(text)
            if visible_total > _MAX_BOOK_BLOCK_VISIBLE_CHARS:
                raise ValueError("book semantic GameTree exceeds the visible-text budget")
            return text

        rendered_items: list[dict[str, object]] = []
        previous_depth = 0
        for position, item in enumerate(view.items):
            if item.kind not in {"move", "variation"}:
                raise ValueError("book semantic GameTree item kind is invalid")
            if type(item.depth) is not int or item.depth < 0:
                raise ValueError("book semantic GameTree depth is invalid")
            if position == 0 and item.depth != 0:
                raise ValueError("book semantic GameTree root depth is invalid")
            if position > 0 and item.depth > previous_depth + 1:
                raise ValueError("book semantic GameTree depth jumps unexpectedly")
            label = safe(item.label)
            if not label:
                raise ValueError("book semantic GameTree item label is empty")
            comments = tuple(
                comment
                for comment in (safe(raw) for raw in item.comments)
                if comment
            )
            rendered_items.append(
                {
                    "kind": item.kind,
                    "depth": item.depth,
                    "label": label,
                    "comments": comments,
                }
            )
            previous_depth = item.depth

        labels = _SEMANTIC_TREE_LABELS[self.language]
        warnings = tuple(
            warning
            for warning in (safe(raw) for raw in workflow_warnings)
            if warning
        )
        return {
            "kind": mode.value,
            "label": labels["moves"],
            "result_label": labels["result"],
            "result": safe(view.result),
            "comments_label": labels["comments"],
            "warnings_label": labels["warnings"],
            "warnings": warnings,
            "items": tuple(rendered_items),
        }

    def _snapshot_from_block(self, block):
        snapshot = super()._snapshot_from_block(block)
        # Reuse the reader-owned detached revision. Never re-read the live mutable
        # BookDocument after the presenter has validated a ReadingLocation.
        semantic = self._reader.block_snapshot(block.index)
        can_open = isinstance(semantic, (Position, Diagram, Exercise, Game, VariationTree))
        if isinstance(semantic, (Game, VariationTree)):
            try:
                snapshot["block"]["semantic_tree"] = self._semantic_tree_snapshot(block.index)
            except BookBoardWorkflowError as error:
                if error.code not in {
                    BookBoardWorkflowCode.CONTENT_UNAVAILABLE,
                    BookBoardWorkflowCode.INVALID_GAME,
                }:
                    raise
                # Invalid/unresolvable chess content is a content state, not a
                # reason to crash the whole V2 application snapshot. Publish no
                # invented moves and disable Board open for this exact block.
                can_open = False
                snapshot["block"]["warning"] = _SEMANTIC_TREE_LABELS[
                    self.language
                ]["unavailable"]
        actions = []
        for original in snapshot["actions"]:
            action = dict(original)
            if action["command"] == "book.open_position":
                action["enabled"] = can_open and not self._workflow.active
                action["label"] = "Відкрити на шахівниці" if self.language is UILanguage.UA else "Open on board"
            elif action["command"] == "book.return_from_board":
                action["enabled"] = self._workflow.active
            actions.append(action)
        snapshot["actions"] = tuple(actions)
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
        if not self._workflow_action("book.open_position", BookBoardUiEventKind.BOARD_OPENED):
            return self.generic_error()
        return BookWebViewEvent(
            "delegated",
            {
                "action": "book.open_position",
                "announcement": self._result_announcement("opened"),
            },
        )

    def return_from_board(self) -> BookWebViewEvent:
        if not self._workflow_action("book.return", BookBoardUiEventKind.RETURNED_TO_BOOK):
            return self.generic_error()
        return self._render(
            self._presenter.current(),
            announcement=self._result_announcement("returned"),
        )


def build_version2_book_webview(reader, workflow, dispatch, *, language=UILanguage.UA) -> BookWebViewBridge:
    return BookWebViewBridge(Version2BookWebViewProjection(reader, workflow, dispatch, language=language))
