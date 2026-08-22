"""Presentation-only Teacher/Classroom interaction state.

Pointer, highlights, arrows, hover, selection and move requests are deliberately
separate from Move Input and never mutate canonical chess Position state. This
module stores only visual/interaction presentation facts for the Windows/WebView2
surface and concise NVDA projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

_SQUARE = re.compile(r"^[a-h][1-8]$", re.IGNORECASE)
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class StudentEventKind(str, Enum):
    HOVER = "hover"
    SELECT = "select"
    MOVE_REQUEST = "move_request"


class TeachingMode(str, Enum):
    TEACHER_EXPLAINS = "teacher_explains"
    STUDENT_RESPONDS = "student_responds"
    SHOW_SQUARE = "show_square"
    SHOW_PIECE = "show_piece"
    MAKE_MOVE = "make_move"
    PIECE_MOVES = "piece_moves"
    ATTACK_DEFENCE = "attack_defence"


class EngineVisibility(str, Enum):
    TEACHER = "teacher"
    STUDENT = "student"
    BOTH = "both"
    HIDDEN = "hidden"


class BoardOrientation(str, Enum):
    WHITE = "white"
    BLACK = "black"


@dataclass(frozen=True, slots=True)
class AnnotationStyle:
    name: str
    color: str

    def __post_init__(self) -> None:
        clean = self.name.strip().lower()
        if not clean or not re.fullmatch(r"[a-z0-9_-]{1,32}", clean):
            raise ValueError("annotation style name must be a safe token")
        if not _HEX_COLOR.fullmatch(self.color):
            raise ValueError("annotation color must be #RRGGBB")
        object.__setattr__(self, "name", clean)
        object.__setattr__(self, "color", self.color.lower())


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
    allowed: bool = True


class TeacherPresentationState:
    DEFAULT_STYLES = (
        AnnotationStyle("target", "#ffd54f"),
        AnnotationStyle("legal", "#66bb6a"),
        AnnotationStyle("attack", "#ef5350"),
        AnnotationStyle("defence", "#42a5f5"),
        AnnotationStyle("selected", "#ab47bc"),
        AnnotationStyle("last-move", "#26a69a"),
        AnnotationStyle("idea", "#ffa726"),
        AnnotationStyle("default", "#ffee58"),
    )

    def __init__(self, *, pointer_history_limit: int = 20) -> None:
        if type(pointer_history_limit) is not int or pointer_history_limit < 1:
            raise ValueError("pointer history limit must be positive")
        self.pointer_square: str | None = None
        self.pointer_history: list[str] = []
        self.highlights: dict[str, str] = {}
        self.arrows: list[VisualArrow] = []
        self.student_events: list[StudentBoardEvent] = []
        self.selected_square: str | None = None
        self.last_move_squares: tuple[str, str] | None = None
        self.show_coordinates = True
        self.orientation = BoardOrientation.WHITE
        self.board_locked = False
        self.student_moves_allowed = False
        self.teaching_mode = TeachingMode.TEACHER_EXPLAINS
        self.engine_visibility = EngineVisibility.HIDDEN
        self._history_limit = pointer_history_limit
        self._pointer_buffer = ""
        self._styles: dict[str, AnnotationStyle] = {
            item.name: item for item in self.DEFAULT_STYLES
        }

    @staticmethod
    def normalize_square(square: str) -> str:
        if not isinstance(square, str):
            raise TypeError("square must be text")
        value = square.strip().lower()
        if not _SQUARE.fullmatch(value):
            raise ValueError("invalid square")
        return value

    @property
    def pointer_input_buffer(self) -> str:
        return self._pointer_buffer

    def type_pointer_character(self, character: str) -> str | None:
        """Accept f3/c7/a1 style input and auto-clear once a square completes."""
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError("pointer editor accepts one character at a time")
        candidate = self._pointer_buffer + character.lower()
        if len(candidate) == 1:
            if candidate not in "abcdefgh":
                self._pointer_buffer = ""
                raise ValueError("pointer coordinate must start with a file")
            self._pointer_buffer = candidate
            return None
        if len(candidate) == 2:
            try:
                square = self.normalize_square(candidate)
            except (TypeError, ValueError):
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

    def register_style(self, style: AnnotationStyle) -> None:
        if not isinstance(style, AnnotationStyle):
            raise TypeError("style must be AnnotationStyle")
        self._styles[style.name] = style

    def style(self, name: str) -> AnnotationStyle:
        token = str(name).strip().lower()
        try:
            return self._styles[token]
        except KeyError as exc:
            raise LookupError(f"unknown annotation style: {token}") from exc

    def set_highlight(self, square: str, *, style: str = "target") -> None:
        style_token = self.style(style).name
        self.highlights[self.normalize_square(square)] = style_token

    def clear_highlight(self, square: str) -> None:
        self.highlights.pop(self.normalize_square(square), None)

    def replace_highlights(self, squares: Iterable[str], *, style: str = "target") -> None:
        style_token = self.style(style).name
        normalized = [self.normalize_square(square) for square in squares]
        self.highlights = {square: style_token for square in normalized}

    def set_selected_square(self, square: str | None) -> None:
        self.selected_square = None if square is None else self.normalize_square(square)

    def set_last_move(self, start: str | None, end: str | None = None) -> None:
        if start is None and end is None:
            self.last_move_squares = None
            return
        if start is None or end is None:
            raise ValueError("last move requires both start and end squares")
        self.last_move_squares = (
            self.normalize_square(start),
            self.normalize_square(end),
        )

    def add_arrow(self, start: str, end: str, *, style: str = "default") -> VisualArrow:
        style_token = self.style(style).name
        arrow = VisualArrow(
            self.normalize_square(start),
            self.normalize_square(end),
            style_token,
        )
        if arrow.start == arrow.end:
            raise ValueError("teaching arrow must connect two different squares")
        if arrow not in self.arrows:
            self.arrows.append(arrow)
        return arrow

    def clear_annotations(self) -> None:
        self.highlights.clear()
        self.arrows.clear()
        self.selected_square = None
        self.last_move_squares = None

    def set_orientation(self, orientation: BoardOrientation) -> None:
        if not isinstance(orientation, BoardOrientation):
            raise TypeError("orientation must be BoardOrientation")
        self.orientation = orientation

    def toggle_orientation(self) -> BoardOrientation:
        self.orientation = (
            BoardOrientation.BLACK
            if self.orientation is BoardOrientation.WHITE
            else BoardOrientation.WHITE
        )
        return self.orientation

    def set_teaching_mode(self, mode: TeachingMode) -> None:
        if not isinstance(mode, TeachingMode):
            raise TypeError("mode must be TeachingMode")
        self.teaching_mode = mode

    def set_engine_visibility(self, visibility: EngineVisibility) -> None:
        if not isinstance(visibility, EngineVisibility):
            raise TypeError("visibility must be EngineVisibility")
        self.engine_visibility = visibility

    def set_board_locked(self, locked: bool) -> None:
        if type(locked) is not bool:
            raise TypeError("board lock state must be boolean")
        self.board_locked = locked

    def set_student_moves_allowed(self, allowed: bool) -> None:
        if type(allowed) is not bool:
            raise TypeError("student move permission must be boolean")
        self.student_moves_allowed = allowed

    def record_student_event(
        self,
        kind: StudentEventKind,
        square: str,
        *,
        piece_name: str = "",
    ) -> StudentBoardEvent:
        if not isinstance(kind, StudentEventKind):
            raise TypeError("student event kind must be StudentEventKind")
        allowed = True
        if kind is StudentEventKind.MOVE_REQUEST:
            allowed = self.student_moves_allowed and not self.board_locked
        event = StudentBoardEvent(
            kind,
            self.normalize_square(square),
            str(piece_name).strip(),
            allowed,
        )
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
            blocked = " blocked" if event.kind is StudentEventKind.MOVE_REQUEST and not event.allowed else ""
        else:
            verbs = {
                StudentEventKind.HOVER: "Навів",
                StudentEventKind.SELECT: "Вибрав",
                StudentEventKind.MOVE_REQUEST: "Запросив хід",
            }
            blocked = " заблоковано" if event.kind is StudentEventKind.MOVE_REQUEST and not event.allowed else ""
        return f"{verbs[event.kind]} {event.square}{piece}{blocked}"

    def feedback_events(self, *, limit: int = 10) -> tuple[StudentBoardEvent, ...]:
        """Return bounded feedback with consecutive hover duplicates coalesced."""
        if type(limit) is not int or limit < 1:
            raise ValueError("feedback limit must be positive")
        out: list[StudentBoardEvent] = []
        for event in self.student_events:
            if (
                out
                and event.kind is StudentEventKind.HOVER
                and out[-1].kind is StudentEventKind.HOVER
                and out[-1].square == event.square
                and out[-1].piece_name == event.piece_name
            ):
                out[-1] = event
            else:
                out.append(event)
        return tuple(out[-limit:])

    def accessible_annotation_summary(self, *, language: str = "uk") -> str:
        parts: list[str] = []
        if self.pointer_square:
            parts.append(
                f"Pointer {self.pointer_square}"
                if language == "en"
                else f"Вказівник {self.pointer_square}"
            )
        if self.selected_square:
            parts.append(
                f"Selected {self.selected_square}"
                if language == "en"
                else f"Вибрано {self.selected_square}"
            )
        if self.last_move_squares:
            start, end = self.last_move_squares
            parts.append(
                f"Last move {start}–{end}"
                if language == "en"
                else f"Останній хід {start}–{end}"
            )
        if self.highlights:
            body = ", ".join(f"{square} {style}" for square, style in self.highlights.items())
            parts.append(
                f"Highlights: {body}"
                if language == "en"
                else f"Підсвічування: {body}"
            )
        if self.arrows:
            body = ", ".join(f"{arrow.start}–{arrow.end} {arrow.style}" for arrow in self.arrows)
            parts.append(
                f"Arrows: {body}"
                if language == "en"
                else f"Стрілки: {body}"
            )
        if not parts:
            return "No teaching annotations." if language == "en" else "Навчальних позначок немає."
        return ". ".join(parts) + "."

    def presentation_snapshot(self) -> dict[str, object]:
        return {
            "pointer": self.pointer_square,
            "pointer_history": tuple(self.pointer_history),
            "highlights": dict(self.highlights),
            "arrows": tuple(self.arrows),
            "selected_square": self.selected_square,
            "last_move_squares": self.last_move_squares,
            "show_coordinates": self.show_coordinates,
            "orientation": self.orientation.value,
            "board_locked": self.board_locked,
            "student_moves_allowed": self.student_moves_allowed,
            "teaching_mode": self.teaching_mode.value,
            "engine_visibility": self.engine_visibility.value,
        }
