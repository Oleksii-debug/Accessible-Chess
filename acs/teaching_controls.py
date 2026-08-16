from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class PointerAction(str, Enum):
    POINT = "point"
    CLICK = "click"
    FOCUS = "focus"


class AnnotationKind(str, Enum):
    SQUARE = "square"
    ARROW = "arrow"


@dataclass(frozen=True)
class PointerCommit:
    square: str
    clear_input: bool = True
    keep_focus: bool = True


@dataclass(frozen=True)
class StudentPointerEvent:
    participant_id: str
    display_name: str
    square: str
    action: PointerAction = PointerAction.POINT

    def __post_init__(self) -> None:
        participant_id = str(self.participant_id).strip()
        display_name = str(self.display_name).strip()
        if not participant_id:
            raise ValueError("participant_id must not be empty")
        if not display_name:
            raise ValueError("display_name must not be empty")
        object.__setattr__(self, "participant_id", participant_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "square", normalize_square(self.square))

    def accessible_text(self) -> str:
        return f"{self.display_name}: {spoken_square(self.square)}."


@dataclass(frozen=True)
class TeachingAnnotation:
    annotation_id: str
    kind: AnnotationKind
    source: str
    target: str | None = None
    style_id: str = "primary"
    owner_participant_id: str | None = None

    def __post_init__(self) -> None:
        annotation_id = str(self.annotation_id).strip()
        style_id = str(self.style_id).strip().lower()
        if not annotation_id:
            raise ValueError("annotation_id must not be empty")
        if not style_id:
            raise ValueError("style_id must not be empty")
        source = normalize_square(self.source)
        target = normalize_square(self.target) if self.target is not None else None
        if self.kind is AnnotationKind.ARROW and target is None:
            raise ValueError("arrow annotation requires target")
        if self.kind is AnnotationKind.SQUARE and target is not None:
            raise ValueError("square annotation cannot have target")
        object.__setattr__(self, "annotation_id", annotation_id)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "style_id", style_id)


class CoachPointerService:
    """Presentation-neutral pointer state for keyboard-first teaching.

    The semantic pointer is authoritative. A Windows adapter may optionally
    mirror it to the OS mouse cursor, but that is never required by this
    service and cannot change chess state.
    """

    def __init__(self, *, history_limit: int = 50) -> None:
        if history_limit <= 0:
            raise ValueError("history_limit must be positive")
        self._square: str | None = None
        self._generation = 0
        self._student_history: deque[StudentPointerEvent] = deque(maxlen=history_limit)

    @property
    def square(self) -> str | None:
        return self._square

    @property
    def generation(self) -> int:
        return self._generation

    def commit_text(self, value: str) -> PointerCommit:
        square = normalize_square(value)
        self._square = square
        self._generation += 1
        return PointerCommit(square)

    def clear(self) -> None:
        if self._square is not None:
            self._square = None
            self._generation += 1

    def record_student_pointer(self, event: StudentPointerEvent) -> StudentPointerEvent:
        self._student_history.append(event)
        return event

    def student_history(self) -> tuple[StudentPointerEvent, ...]:
        return tuple(self._student_history)

    def clear_student_history(self) -> None:
        self._student_history.clear()

    def recent_accessible_text(self, *, limit: int = 10) -> str:
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows: Iterable[StudentPointerEvent] = tuple(self._student_history)[-limit:]
        return "\n".join(event.accessible_text() for event in rows)


def normalize_square(value: object) -> str:
    text = "".join(str(value).strip().lower().split())
    if len(text) != 2 or text[0] not in "abcdefgh" or text[1] not in "12345678":
        raise ValueError("square must be a1..h8")
    return text


def spoken_square(square: str) -> str:
    square = normalize_square(square)
    return f"{square[0]} {square[1]}"
