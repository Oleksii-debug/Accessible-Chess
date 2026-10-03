"""Accessible Books composition over the accepted reader and Board workflow.

The V2 projection uses the workflow's return stack for both open and return.
It never creates the legacy presenter's independent Board return point.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .book_board_workflow import BookBoardWorkflow
from .book_webview_bridge import BookWebViewBridge
from .book_webview_projection import BookWebViewEvent, BookWebViewProjection
from .bookdocument import Diagram, Exercise, Game, Position, VariationTree
from .bookreader import BookReader
from .full_product_presenters import BookReaderPresenter
from .full_product_ui_shell import UILanguage
from .version2_windows_book_board_adapter import BookBoardUiEvent, BookBoardUiEventKind


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
