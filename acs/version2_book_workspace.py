"""Accessible Books composition over the accepted reader and Board workflow.

The V2 projection uses the workflow's return stack for both open and return.
It never creates the legacy presenter's independent Board return point.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from .book_board_workflow import BookBoardWorkflow
from .book_webview_bridge import BookWebViewBridge
from .book_webview_projection import BookWebViewEvent, BookWebViewProjection
from .bookdocument import Diagram, Exercise, Game, ListBlock, Position, VariationTree
from .bookreader import BookReader, ReadingLocation
from .full_product_presenters import BookReaderPresenter
from .full_product_ui_shell import UILanguage
from .version2_windows_book_board_adapter import BookBoardUiEvent, BookBoardUiEventKind


class Version2BookReaderPresenter(BookReaderPresenter):
    """Render the canonical List block introduced by the accepted Books core."""

    def _block_view(self, location: ReadingLocation):
        view = super()._block_view(location)
        block = self._reader.document.blocks[location.index]
        if isinstance(block, ListBlock):
            text = "\n".join(
                f"{index + (block.start or 1)}. {item}" if block.ordered else item
                for index, item in enumerate(block.items)
            )
            return replace(view, role="group", text=text)
        return view


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
        semantic = self._reader.document.blocks[block.index]
        can_open = isinstance(semantic, (Position, Diagram, Exercise, Game, VariationTree))
        actions = []
        for original in snapshot["actions"]:
            action = dict(original)
            if action["command"] == "book.open_position":
                action["enabled"] = can_open and not self._workflow.active
                action["label"] = "Відкрити на шахівниці" if self.language is UILanguage.UA else "Open on board"
            elif action["command"] == "book.return_from_board":
                action["enabled"] = self._workflow.active
            elif action["command"] == "book.next":
                action["enabled"] = block.index + 1 < len(self._reader.document.blocks)
            actions.append(action)
        snapshot["actions"] = tuple(actions)
        if isinstance(semantic, ListBlock):
            # Native list semantics are rendered by the shared Book surface.
            from .book_webview_projection import _safe_text
            snapshot["block"]["list"] = {
                "ordered": semantic.ordered,
                "start": semantic.start or 1,
                "items": tuple(_safe_text(item, language=self.language, limit=8000) for item in semantic.items),
            }
        return snapshot

    def _workflow_action(self, action: str, expected: BookBoardUiEventKind) -> bool:
        result = self._dispatch(action, {})
        # A canonical router returns ActionDispatchResult; a composed callback
        # may already unwrap it. Never treat a returned failure DTO as success.
        result = getattr(result, "value", result)
        return isinstance(result, BookBoardUiEvent) and result.kind is expected

    def open_position(self) -> BookWebViewEvent:
        if not self._workflow_action("book.open_position", BookBoardUiEventKind.BOARD_OPENED):
            return self.generic_error()
        return BookWebViewEvent("delegated", {"action": "book.open_position"})

    def return_from_board(self) -> BookWebViewEvent:
        if not self._workflow_action("book.return", BookBoardUiEventKind.RETURNED_TO_BOOK):
            return self.generic_error()
        return self._render(self._presenter.current())


def build_version2_book_webview(reader, workflow, dispatch, *, language=UILanguage.UA) -> BookWebViewBridge:
    return BookWebViewBridge(Version2BookWebViewProjection(reader, workflow, dispatch, language=language))
