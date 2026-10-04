from __future__ import annotations

"""D01 Windows/NVDA adapter for the canonical Version 2 Book -> Board workflow.

This module is presentation/application glue only.  It owns no Book parsing,
Library lookup, PGN/GameTree semantics, chess rules, engine provider, or return
stack.  All chess/application state is delegated to :class:`BookBoardWorkflow`.

The adapter deliberately projects only bounded semantic status and focus tokens.
FEN/PGN, filesystem paths, provider details and raw exception text never cross
this UI event boundary.  A Windows/WebView composition can obtain the canonical
Board through :meth:`board_snapshot` after a successful event instead of keeping
a second UI-owned chess position.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import logging
from typing import Any

from .book_board_workflow import (
    BookBoardCommand,
    BookBoardView,
    BookBoardWorkflow,
    BookBoardWorkflowError,
)
from .bookreader import ReadingLocation
from .engine_assisted_workflows import AudienceAnalysisResult


_LOG = logging.getLogger(__name__)


class BookBoardUiEventKind(str, Enum):
    BOARD_OPENED = "board_opened"
    BOARD_UPDATED = "board_updated"
    ANALYSIS_READY = "analysis_ready"
    ANALYSIS_STALE = "analysis_stale"
    RETURNED_TO_BOOK = "returned_to_book"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BookBoardUiEvent:
    """Bounded D01 event; intentionally contains no chess/source payload."""

    kind: BookBoardUiEventKind
    action_id: str
    focus_target: str = ""
    mode: str = ""
    book_index: int | None = None
    revision: int = 0
    analysis_line_count: int = 0
    error_code: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, BookBoardUiEventKind):
            raise TypeError("book board UI event kind is invalid")
        for name, limit in (
            ("action_id", 96),
            ("focus_target", 160),
            ("mode", 32),
            ("error_code", 96),
        ):
            value = getattr(self, name)
            if type(value) is not str:
                raise TypeError(f"{name} must be text")
            if len(value) > limit or any(ch in value for ch in ("\x00", "\r", "\n")):
                raise ValueError(f"{name} is not a bounded semantic token")
        if not self.action_id:
            raise ValueError("book board UI action id must not be empty")
        if self.book_index is not None and (
            type(self.book_index) is not int or self.book_index < 0
        ):
            raise ValueError("book_index must be a non-negative exact integer or None")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("revision must be a non-negative exact integer")
        if type(self.analysis_line_count) is not int or self.analysis_line_count < 0:
            raise ValueError("analysis_line_count must be a non-negative exact integer")


class Version2WindowsBookBoardActionDelegate:
    """Chainable D01 action adapter over one canonical ``BookBoardWorkflow``.

    ``book.open_position`` is the existing Book WebView/application action.  Its
    historical Python presenter payload (``fen`` + ``book_index``) is accepted
    only as compatibility metadata and is never used as chess state; the current
    semantic Book block is reopened by ``BookBoardWorkflow`` itself.  A future
    Book Game button may call ``book.open_game`` with no payload through the same
    canonical path.

    The additional ``book.board_*`` IDs are adapter-level intents only in this
    package.  Global ActionRegistry/native-menu registration is deliberately left
    to the active D01 registry owner so this branch does not create a competing
    catalog.
    """

    OPEN_POSITION = "book.open_position"
    OPEN_GAME = "book.open_game"
    NEXT_MOVE = "book.board_next_move"
    PREVIOUS_MOVE = "book.board_previous_move"
    ENTER_VARIATION = "book.board_enter_variation"
    LEAVE_VARIATION = "book.board_leave_variation"
    ANALYZE = "book.board_analyze"
    RETURN = "book.return"
    RETURN_FROM_BOARD = "book.return_from_board"

    OWNED_ACTIONS = frozenset(
        {
            OPEN_POSITION,
            OPEN_GAME,
            NEXT_MOVE,
            PREVIOUS_MOVE,
            ENTER_VARIATION,
            LEAVE_VARIATION,
            ANALYZE,
            RETURN,
            RETURN_FROM_BOARD,
        }
    )

    _COMMAND_BY_ACTION = {
        OPEN_POSITION: BookBoardCommand.OPEN_CURRENT,
        OPEN_GAME: BookBoardCommand.OPEN_CURRENT,
        NEXT_MOVE: BookBoardCommand.NEXT_MOVE,
        PREVIOUS_MOVE: BookBoardCommand.PREVIOUS_MOVE,
        ENTER_VARIATION: BookBoardCommand.ENTER_VARIATION,
        LEAVE_VARIATION: BookBoardCommand.LEAVE_VARIATION,
        ANALYZE: BookBoardCommand.ANALYZE,
        RETURN: BookBoardCommand.RETURN_TO_BOOK,
        RETURN_FROM_BOARD: BookBoardCommand.RETURN_TO_BOOK,
    }

    def __init__(
        self,
        workflow: BookBoardWorkflow,
        *,
        event_sink: Callable[[BookBoardUiEvent], Any],
        next_delegate: Callable[[str, Mapping[str, object]], Any],
        current_focus_provider: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(workflow, BookBoardWorkflow):
            raise TypeError("workflow must be BookBoardWorkflow")
        if not callable(event_sink):
            raise TypeError("event_sink must be callable")
        if not callable(next_delegate):
            raise TypeError("next_delegate must be callable")
        if current_focus_provider is not None and not callable(current_focus_provider):
            raise TypeError("current_focus_provider must be callable")
        self._workflow = workflow
        self._event_sink = event_sink
        self._next_delegate = next_delegate
        self._focus_provider = current_focus_provider or (lambda: "")

    @property
    def active(self) -> bool:
        return self._workflow.active

    def board_snapshot(self):
        """Return the detached canonical Board from #398; never cache UI chess state."""

        return self._workflow.board_snapshot()

    def view(self) -> BookBoardView:
        return self._workflow.view()

    def _focus(self) -> str:
        try:
            value = self._focus_provider()
        except Exception:
            return ""
        if type(value) is not str:
            return ""
        token = value.strip()
        if len(token) > 160 or any(ch in token for ch in ("\x00", "\r", "\n")):
            return ""
        return token

    def _emit(self, event: BookBoardUiEvent) -> BookBoardUiEvent:
        try:
            self._event_sink(event)
        except Exception:
            # Observer failure must not roll back canonical Book/Board state and
            # must not dump provider/path details into an accessibility surface.
            _LOG.warning("Version 2 Book Board UI event sink failed")
        return event

    @staticmethod
    def _mapping(payload: Mapping[str, object] | None) -> dict[str, object]:
        if payload is None:
            return {}
        if not isinstance(payload, Mapping):
            raise TypeError("book board action payload must be a mapping")
        if len(payload) > 3:
            raise ValueError("book board action payload has too many fields")
        out: dict[str, object] = {}
        for key, value in payload.items():
            if type(key) is not str or not key or len(key) > 64:
                raise ValueError("book board action payload key is invalid")
            if key in out:
                raise ValueError("duplicate book board action payload key")
            out[key] = value
        return out

    @classmethod
    def _command_payload(
        cls,
        action_id: str,
        payload: Mapping[str, object] | None,
    ) -> dict[str, object]:
        data = cls._mapping(payload)

        if action_id == cls.OPEN_POSITION:
            if not data:
                return {}
            # Compatibility with the existing Python BookReaderPresenter.  These
            # values are deliberately *not* forwarded to the canonical workflow.
            if set(data) != {"fen", "book_index"}:
                raise ValueError("book position compatibility payload is invalid")
            fen = data["fen"]
            index = data["book_index"]
            if type(fen) is not str or not fen.strip() or len(fen) > 512:
                raise ValueError("book position compatibility FEN is invalid")
            if type(index) is not int or index < 0:
                raise ValueError("book position compatibility index is invalid")
            return {}

        if action_id in {
            cls.OPEN_GAME,
            cls.NEXT_MOVE,
            cls.PREVIOUS_MOVE,
            cls.LEAVE_VARIATION,
            cls.RETURN,
            cls.RETURN_FROM_BOARD,
        }:
            if data:
                raise ValueError("book board action accepts no payload")
            return {}

        if action_id == cls.ENTER_VARIATION:
            if not set(data).issubset({"variation_index"}):
                raise ValueError("book variation payload is invalid")
            return data

        if action_id == cls.ANALYZE:
            if not set(data).issubset({"multipv", "depth"}):
                raise ValueError("book analysis payload is invalid")
            return data

        raise ValueError("book board action is unsupported")

    def _failed(
        self,
        action_id: str,
        error_code: str,
        *,
        focus_target: str,
    ) -> BookBoardUiEvent:
        return self._emit(
            BookBoardUiEvent(
                BookBoardUiEventKind.FAILED,
                action_id,
                focus_target=focus_target,
                error_code=error_code,
            )
        )

    @staticmethod
    def _view_event(
        kind: BookBoardUiEventKind,
        action_id: str,
        view: BookBoardView,
    ) -> BookBoardUiEvent:
        return BookBoardUiEvent(
            kind,
            action_id,
            focus_target="board",
            mode=view.mode.value,
            book_index=view.origin.index,
            revision=view.revision,
        )

    def _project_result(
        self,
        action_id: str,
        command: BookBoardCommand,
        result: object,
    ) -> BookBoardUiEvent:
        if isinstance(result, BookBoardView):
            kind = (
                BookBoardUiEventKind.BOARD_OPENED
                if command is BookBoardCommand.OPEN_CURRENT
                else BookBoardUiEventKind.BOARD_UPDATED
            )
            return self._emit(self._view_event(kind, action_id, result))

        if isinstance(result, AudienceAnalysisResult):
            if result.stale:
                return self._emit(
                    BookBoardUiEvent(
                        BookBoardUiEventKind.ANALYSIS_STALE,
                        action_id,
                        focus_target="board",
                        revision=self._workflow.revision,
                    )
                )
            if result.error is not None:
                return self._failed(
                    action_id,
                    "analysis_unavailable",
                    focus_target="board",
                )
            return self._emit(
                BookBoardUiEvent(
                    BookBoardUiEventKind.ANALYSIS_READY,
                    action_id,
                    focus_target="book-board-analysis",
                    revision=self._workflow.revision,
                    analysis_line_count=len(result.teacher_lines),
                )
            )

        if isinstance(result, ReadingLocation):
            return self._emit(
                BookBoardUiEvent(
                    BookBoardUiEventKind.RETURNED_TO_BOOK,
                    action_id,
                    focus_target=f"book-block-{result.index}",
                    book_index=result.index,
                    revision=self._workflow.revision,
                )
            )

        return self._failed(
            action_id,
            "application_contract_error",
            focus_target="board" if self._workflow.active else self._focus(),
        )

    def __call__(
        self,
        action_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> Any:
        if action_id not in self.OWNED_ACTIONS:
            return self._next_delegate(action_id, dict(payload or {}))

        previous_focus = self._focus()
        try:
            command_payload = self._command_payload(action_id, payload)
        except Exception:
            return self._failed(
                action_id,
                "invalid_action_payload",
                focus_target=previous_focus,
            )

        command = self._COMMAND_BY_ACTION[action_id]
        try:
            result = self._workflow.dispatch(command, command_payload)
        except BookBoardWorkflowError as exc:
            return self._failed(
                action_id,
                exc.code.value,
                focus_target="board" if self._workflow.active else previous_focus,
            )
        except Exception:
            return self._failed(
                action_id,
                "book_board_unavailable",
                focus_target="board" if self._workflow.active else previous_focus,
            )
        return self._project_result(action_id, command, result)
