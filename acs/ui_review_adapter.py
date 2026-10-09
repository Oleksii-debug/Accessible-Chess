from __future__ import annotations

from dataclasses import dataclass

from .history import HistoryError, ReviewHistory, ReviewSelection


@dataclass(frozen=True)
class ReviewView:
    fen: str
    ply: int
    node_id: int
    at_start: bool
    at_end: bool
    status: str
    last_move: str | None


@dataclass(frozen=True)
class ReviewCommandResult:
    ok: bool
    announcement: str
    view: ReviewView


class ReviewPresentationAdapter:
    """Presentation-only adapter for non-destructive history review.

    The adapter never reconstructs or replaces the live chess board. It moves
    only ReviewHistory's independent cursor and returns an immutable FEN/view
    projection for WebView rendering. Destructive undo/redo therefore remains
    owned by the live game state.
    """

    def __init__(self, history: ReviewHistory, *, language: str = "uk") -> None:
        self.history = history
        self.language = language if language in {"uk", "en"} else "uk"

    def current(self) -> ReviewView:
        return self._view(self.history.current())

    def previous(self) -> ReviewCommandResult:
        return self._run(self.history.previous)

    def next(self) -> ReviewCommandResult:
        return self._run(self.history.next)

    def jump(self, target: str | int) -> ReviewCommandResult:
        return self._run(lambda: self.history.jump(target))

    def select_node(self, node_id: int) -> ReviewCommandResult:
        return self._run(lambda: self.history.select_node(node_id))

    def _run(self, operation) -> ReviewCommandResult:
        try:
            selection = operation()
            view = self._view(selection)
            return ReviewCommandResult(True, view.status, view)
        except HistoryError as exc:
            view = self.current()
            return ReviewCommandResult(False, self._error_message(exc, view), view)

    def _view(self, selection: ReviewSelection) -> ReviewView:
        status = self._status(selection)
        return ReviewView(
            fen=selection.snapshot.fen,
            ply=selection.ply,
            node_id=selection.node_id,
            at_start=selection.at_start,
            at_end=selection.at_end,
            status=status,
            last_move=selection.snapshot.last_move or selection.snapshot.san,
        )

    def _status(self, selection: ReviewSelection) -> str:
        if self.language == "uk":
            if selection.at_start:
                return "Початкова позиція."
            label = self._move_label(selection.ply, uk=True)
            if selection.at_end:
                return f"{label}; кінець історії."
            return label + "."
        if selection.at_start:
            return "Initial position."
        label = self._move_label(selection.ply, uk=False)
        if selection.at_end:
            return f"{label}; end of history."
        return label + "."

    @staticmethod
    def _move_label(ply: int, *, uk: bool) -> str:
        fullmove = (ply + 1) // 2
        if ply % 2:
            return (
                f"Позиція після {fullmove}-го ходу білих"
                if uk
                else f"Position after White's move {fullmove}"
            )
        return (
            f"Позиція після {fullmove}..."
            if uk
            else f"Position after {fullmove}..."
        )

    def _error_message(self, exc: HistoryError, view: ReviewView) -> str:
        text = str(exc)
        if self.language == "uk":
            if "initial position" in text:
                return "Ви вже на початковій позиції."
            if "end of the active line" in text:
                return "Ви вже в кінці історії."
            return "Не вдалося перейти до запитаної позиції. " + text
        if "initial position" in text:
            return "Already at the initial position."
        if "end of the active line" in text:
            return "Already at the end of history."
        return "Could not select the requested history position. " + text
