"""Windows/WebView2 Teacher presentation controller over canonical contracts.

This module deliberately owns only UI-local concerns: the two-character pointer
editor buffer, visual theme/orientation preferences and bounded feedback used to
avoid screen-reader flooding. Canonical pointer/highlight/arrow/permission state
must come from ``state_provider``; mutations are emitted through ``dispatch``.
It therefore cannot become a second source of chess or presentation truth.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

_SQUARE = re.compile(r"^[a-h][1-8]$", re.IGNORECASE)
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class StudentEventKind(str, Enum):
    HOVER = "hover"
    SELECT = "select"


class TeachingMode(str, Enum):
    TEACHER_EXPLAINS = "teacher_explains"
    STUDENT_RESPONDS = "student_responds"
    SHOW_SQUARE = "show_square"
    SHOW_PIECE = "show_piece"
    MAKE_MOVE = "make_move"
    PIECE_MOVES = "piece_moves"
    ATTACK_DEFENCE = "attack_defence"


class BoardOrientation(str, Enum):
    WHITE = "white"
    BLACK = "black"


@dataclass(frozen=True, slots=True)
class AnnotationStyle:
    """UI theme only; canonical contracts keep semantic annotation purpose."""

    purpose: str
    color: str

    def __post_init__(self) -> None:
        clean = self.purpose.strip().lower()
        if not clean or not re.fullmatch(r"[a-z0-9_-]{1,32}", clean):
            raise ValueError("annotation purpose must be a safe token")
        if not _HEX_COLOR.fullmatch(self.color):
            raise ValueError("annotation color must be #RRGGBB")
        object.__setattr__(self, "purpose", clean)
        object.__setattr__(self, "color", self.color.lower())


@dataclass(frozen=True, slots=True)
class StudentFeedbackEvent:
    kind: StudentEventKind
    square: str
    piece_name: str = ""
    student_id: str = ""
    sequence: int | None = None


class TeacherPresentationState:
    """UI controller retaining the historical public name for DEV1 continuity.

    Despite the name, authoritative presentation state is not stored here.
    ``snapshot()`` always reads the canonical provider. All presentation changes
    dispatch stable actions for the application/interaction router to validate.
    """

    DEFAULT_STYLES = (
        AnnotationStyle("target", "#ffd54f"),
        AnnotationStyle("legal", "#66bb6a"),
        AnnotationStyle("attack", "#ef5350"),
        AnnotationStyle("defence", "#42a5f5"),
        AnnotationStyle("selected", "#ab47bc"),
        AnnotationStyle("last-move", "#26a69a"),
        AnnotationStyle("idea", "#ffa726"),
        AnnotationStyle("custom", "#ffee58"),
    )

    _FORBIDDEN_STATE_KEYS = frozenset(
        {"position", "fen", "move_history", "history", "board_fen", "moves"}
    )

    def __init__(
        self,
        dispatch: Callable[[str, Mapping[str, object]], Any],
        state_provider: Callable[[], Mapping[str, object]],
        *,
        feedback_limit: int = 50,
    ) -> None:
        if not callable(dispatch):
            raise TypeError("teacher presentation dispatcher must be callable")
        if not callable(state_provider):
            raise TypeError("teacher canonical state provider must be callable")
        if type(feedback_limit) is not int or feedback_limit < 1:
            raise ValueError("feedback limit must be positive")
        self._dispatch = dispatch
        self._state_provider = state_provider
        self._pointer_buffer = ""
        self._feedback_limit = feedback_limit
        self._student_feedback: list[StudentFeedbackEvent] = []
        self._orientation = BoardOrientation.WHITE
        self._teaching_mode = TeachingMode.TEACHER_EXPLAINS
        self._styles: dict[str, AnnotationStyle] = {
            item.purpose: item for item in self.DEFAULT_STYLES
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

    @property
    def orientation(self) -> BoardOrientation:
        return self._orientation

    @property
    def teaching_mode(self) -> TeachingMode:
        return self._teaching_mode

    def snapshot(self) -> dict[str, object]:
        raw = self._state_provider()
        if not isinstance(raw, Mapping):
            raise TypeError("canonical teacher presentation state must be a mapping")
        snapshot = dict(raw)
        forbidden = self._FORBIDDEN_STATE_KEYS.intersection(snapshot)
        if forbidden:
            raise ValueError(
                f"teacher presentation provider leaked chess-state field(s): {sorted(forbidden)!r}"
            )
        return snapshot

    @property
    def pointer_square(self) -> str | None:
        value = self.snapshot().get("pointer_square")
        if value is None:
            return None
        return self.normalize_square(value)

    def type_pointer_character(self, character: str) -> str | None:
        """Accept f3/c7/a1 and dispatch immediately when coordinate completes."""
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
            self._dispatch("teacher.pointer_input", {"square": square})
            self._pointer_buffer = ""
            return square
        self._pointer_buffer = ""
        raise ValueError("pointer coordinate is too long")

    def clear_pointer_input(self) -> None:
        self._pointer_buffer = ""

    def clear_pointer(self) -> Any:
        self._pointer_buffer = ""
        return self._dispatch("teacher.pointer_clear", {})

    def register_style(self, style: AnnotationStyle) -> None:
        if not isinstance(style, AnnotationStyle):
            raise TypeError("style must be AnnotationStyle")
        self._styles[style.purpose] = style

    def style(self, purpose: str) -> AnnotationStyle:
        token = str(purpose).strip().lower()
        try:
            return self._styles[token]
        except KeyError as exc:
            raise LookupError(f"unknown annotation purpose: {token}") from exc

    def set_highlight(self, square: str, *, purpose: str = "target") -> Any:
        token = self.style(purpose).purpose
        return self._dispatch(
            "teacher.highlight",
            {"square": self.normalize_square(square), "purpose": token},
        )

    def add_arrow(self, start: str, end: str, *, purpose: str = "custom") -> Any:
        start_square = self.normalize_square(start)
        end_square = self.normalize_square(end)
        if start_square == end_square:
            raise ValueError("teaching arrow must connect two different squares")
        token = self.style(purpose).purpose
        return self._dispatch(
            "teacher.arrow",
            {
                "start_square": start_square,
                "end_square": end_square,
                "purpose": token,
            },
        )

    def clear_annotations(self) -> Any:
        return self._dispatch("teacher.clear_annotations", {})

    def toggle_coordinates(self) -> Any:
        return self._dispatch("teacher.coordinates_toggle", {})

    def set_board_permission(self, permission: str) -> Any:
        token = str(permission).strip().lower()
        if token not in {"locked", "select_only", "move_allowed"}:
            raise ValueError("unsupported board permission")
        return self._dispatch("teacher.board_permission", {"permission": token})

    def set_engine_visibility(self, visibility: str) -> Any:
        token = str(visibility).strip().lower()
        if token not in {"visible_to_teacher", "visible_to_student", "hidden"}:
            raise ValueError("unsupported engine visibility")
        return self._dispatch("teacher.engine_visibility", {"visibility": token})

    def request_student_move(self, raw_text: str) -> Any:
        text = str(raw_text).strip()
        if not text:
            raise ValueError("student move request must not be empty")
        # This is deliberately a separate action. The application router alone
        # decides whether policy permits conversion to a canonical MoveCommand.
        return self._dispatch("student.move", {"raw_text": text})

    def set_orientation(self, orientation: BoardOrientation) -> None:
        if not isinstance(orientation, BoardOrientation):
            raise TypeError("orientation must be BoardOrientation")
        self._orientation = orientation

    def toggle_orientation(self) -> BoardOrientation:
        self._orientation = (
            BoardOrientation.BLACK
            if self._orientation is BoardOrientation.WHITE
            else BoardOrientation.WHITE
        )
        return self._orientation

    def set_teaching_mode(self, mode: TeachingMode) -> None:
        if not isinstance(mode, TeachingMode):
            raise TypeError("mode must be TeachingMode")
        self._teaching_mode = mode

    def record_student_event(
        self,
        kind: StudentEventKind,
        square: str,
        *,
        piece_name: str = "",
        student_id: str = "",
        sequence: int | None = None,
    ) -> StudentFeedbackEvent:
        """Record only bounded spoken-feedback cache, never canonical policy/state."""
        if not isinstance(kind, StudentEventKind):
            raise TypeError("student event kind must be StudentEventKind")
        if sequence is not None and (type(sequence) is not int or sequence < 0):
            raise ValueError("student event sequence must be non-negative")
        event = StudentFeedbackEvent(
            kind,
            self.normalize_square(square),
            str(piece_name).strip(),
            str(student_id).strip(),
            sequence,
        )
        self._student_feedback.append(event)
        del self._student_feedback[:-self._feedback_limit]
        return event

    @staticmethod
    def concise_student_event(event: StudentFeedbackEvent, *, language: str = "uk") -> str:
        piece = f", {event.piece_name}" if event.piece_name else ""
        if language == "en":
            verb = "Hover" if event.kind is StudentEventKind.HOVER else "Selected"
        else:
            verb = "Навів" if event.kind is StudentEventKind.HOVER else "Вибрав"
        return f"{verb} {event.square}{piece}"

    def feedback_events(self, *, limit: int = 10) -> tuple[StudentFeedbackEvent, ...]:
        """Return bounded feedback with consecutive hover duplicates coalesced."""
        if type(limit) is not int or limit < 1:
            raise ValueError("feedback limit must be positive")
        out: list[StudentFeedbackEvent] = []
        for event in self._student_feedback:
            if (
                out
                and event.kind is StudentEventKind.HOVER
                and out[-1].kind is StudentEventKind.HOVER
                and out[-1].square == event.square
                and out[-1].piece_name == event.piece_name
                and out[-1].student_id == event.student_id
            ):
                out[-1] = event
            else:
                out.append(event)
        return tuple(out[-limit:])

    def accessible_annotation_summary(self, *, language: str = "uk") -> str:
        state = self.snapshot()
        parts: list[str] = []
        pointer = state.get("pointer_square")
        if pointer:
            pointer = self.normalize_square(pointer)
            parts.append(
                f"Pointer {pointer}"
                if language == "en"
                else f"Вказівник {pointer}"
            )
        highlights = state.get("highlights") or ()
        if highlights:
            rendered = []
            for item in highlights:
                if isinstance(item, Mapping):
                    square = self.normalize_square(item.get("square"))
                    purpose = str(item.get("purpose") or "custom")
                    rendered.append(f"{square} {purpose}")
            if rendered:
                body = ", ".join(rendered)
                parts.append(
                    f"Highlights: {body}"
                    if language == "en"
                    else f"Підсвічування: {body}"
                )
        arrows = state.get("arrows") or ()
        if arrows:
            rendered = []
            for item in arrows:
                if isinstance(item, Mapping):
                    start = self.normalize_square(item.get("start_square"))
                    end = self.normalize_square(item.get("end_square"))
                    purpose = str(item.get("purpose") or "custom")
                    rendered.append(f"{start}–{end} {purpose}")
            if rendered:
                body = ", ".join(rendered)
                parts.append(
                    f"Arrows: {body}"
                    if language == "en"
                    else f"Стрілки: {body}"
                )
        if not parts:
            return "No teaching annotations." if language == "en" else "Навчальних позначок немає."
        return ". ".join(parts) + "."

    def presentation_snapshot(self) -> dict[str, object]:
        """Compatibility alias: always returns the provider-owned canonical state."""
        return self.snapshot()
