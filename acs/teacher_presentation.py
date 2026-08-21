"""Presentation-only Teacher/Classroom interaction state.

Pointer, highlights, arrows, hover and selection are deliberately distinct from
Move Input and never mutate canonical chess Position state.  An adapter may bind
these events to a visual board and concise NVDA feedback.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

_SQUARE = re.compile(r"^[a-h][1-8]$", re.IGNORECASE)


class StudentEventKind(str, Enum):
    HOVER = "hover"
    SELECT = "select"
    MOVE_REQUEST = "move_request"


@dataclass(frozen=True, slots=True)
class VisualArrow:
    start: str
    end: str
    style: str = "default"


@dataclass(frozen=True, slots=True)
class StudentBoardEvent:
    kind: StudentEventKind
    square: str
    piece_name: str = ""


class TeacherPresentationState:
    def __init__(self, *, pointer_history_limit: int = 20) -> None:
        if pointer_history_limit < 1:
            raise ValueError("pointer history limit must be positive")
        self.pointer_square: str | None = None
        self.pointer_history: list[str] = []
        self.highlights: dict[str, str] = {}
        self.arrows: list[VisualArrow] = []
        self.student_events: list[StudentBoardEvent] = []
        self._history_limit = pointer_history_limit
        self._pointer_buffer = ""

    @staticmethod
    def normalize_square(square: str) -> str:
        value = square.strip().lower()
        if not _SQUARE.fullmatch(value):
            raise ValueError("invalid square")
        return value

    @property
    def pointer_input_buffer(self) -> str:
        return self._pointer_buffer

    def type_pointer_character(self, character: str) -> str | None:
        """Accept f3/c7/a1 style input and auto-clear once a square completes."""
        if len(character) != 1:
            raise ValueError("pointer editor accepts one character at a time")
        candidate = (self._pointer_buffer + character.lower()).strip()
        if len(candidate) == 1:
            if candidate not in "abcdefgh":
                self._pointer_buffer = ""
                raise ValueError("pointer coordinate must start with a file")
            self._pointer_buffer = candidate
            return None
        if len(candidate) == 2:
            try:
                square = self.normalize_square(candidate)
            except ValueError:
                self._pointer_buffer = ""
                raise
            self.set_pointer(square)
            self._pointer_buffer = ""
            return square
        self._pointer_buffer = ""
        raise ValueError("pointer coordinate is too long")

    def clear_pointer_input(self) -> None:
        self._pointer_buffer = ""

    def set_pointer(self, square: str) -> None:
        value = self.normalize_square(square)
        self.pointer_square = value
        if not self.pointer_history or self.pointer_history[-1] != value:
            self.pointer_history.append(value)
            del self.pointer_history[:-self._history_limit]

    def clear_pointer(self) -> None:
        self.pointer_square = None
        self._pointer_buffer = ""

    def set_highlight(self, square: str, *, style: str = "target") -> None:
        self.highlights[self.normalize_square(square)] = style.strip() or "target"

    def clear_highlight(self, square: str) -> None:
        self.highlights.pop(self.normalize_square(square), None)

    def replace_highlights(self, squares: Iterable[str], *, style: str = "target") -> None:
        normalized = [self.normalize_square(square) for square in squares]
        self.highlights = {square: style.strip() or "target" for square in normalized}

    def add_arrow(self, start: str, end: str, *, style: str = "default") -> VisualArrow:
        arrow = VisualArrow(self.normalize_square(start), self.normalize_square(end), style.strip() or "default")
        if arrow not in self.arrows:
            self.arrows.append(arrow)
        return arrow

    def clear_annotations(self) -> None:
        self.highlights.clear()
        self.arrows.clear()

    def record_student_event(self, kind: StudentEventKind, square: str, *, piece_name: str = "") -> StudentBoardEvent:
        event = StudentBoardEvent(kind, self.normalize_square(square), piece_name.strip())
        self.student_events.append(event)
        del self.student_events[:-50]
        return event

    @staticmethod
    def concise_student_event(event: StudentBoardEvent, *, language: str = "uk") -> str:
        piece = f", {event.piece_name}" if event.piece_name else ""
        if language == "en":
            verbs = {
                StudentEventKind.HOVER: "Hover",
                StudentEventKind.SELECT: "Selected",
                StudentEventKind.MOVE_REQUEST: "Move requested",
            }
        else:
            verbs = {
                StudentEventKind.HOVER: "Навів",
                StudentEventKind.SELECT: "Вибрав",
                StudentEventKind.MOVE_REQUEST: "Запросив хід",
            }
        return f"{verbs[event.kind]} {event.square}{piece}"

    def presentation_snapshot(self) -> dict[str, object]:
        return {
            "pointer": self.pointer_square,
            "pointer_history": tuple(self.pointer_history),
            "highlights": dict(self.highlights),
            "arrows": tuple(self.arrows),
        }
