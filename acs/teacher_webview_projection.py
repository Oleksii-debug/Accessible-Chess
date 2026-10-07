"""WebView-facing Teacher/Classroom visual projection over canonical presentation state.

DEV1 owns only projection, focus/keyboard semantics and bounded NVDA feedback.
Authoritative pointer/highlight/arrow/permission state remains external and is
read through :class:`TeacherPresentationState`; no chess position is stored here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .teacher_presentation import (
    BoardOrientation,
    StudentEventKind,
    TeacherPresentationState,
)

_ALLOWED_PERMISSIONS = frozenset({"locked", "select_only", "move_allowed"})
_ALLOWED_ENGINE_VISIBILITY = frozenset(
    {"visible_to_teacher", "visible_to_student", "hidden"}
)


@dataclass(frozen=True, slots=True)
class TeacherWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class TeacherWebViewProjection:
    """JSON-ready Teacher board projection without owning canonical state."""

    def __init__(self, teacher: TeacherPresentationState) -> None:
        if not isinstance(teacher, TeacherPresentationState):
            raise TypeError("teacher must be TeacherPresentationState")
        self._teacher = teacher

    @staticmethod
    def _visual_cell(square: str, orientation: BoardOrientation) -> dict[str, int]:
        file_index = ord(square[0]) - ord("a")
        rank_index = int(square[1]) - 1
        if orientation is BoardOrientation.WHITE:
            row = 8 - rank_index
            column = file_index + 1
        else:
            row = rank_index + 1
            column = 8 - file_index
        return {"row": row, "column": column}

    def _square_item(
        self,
        square: object,
        *,
        purpose: object = "custom",
    ) -> dict[str, object]:
        normalized = self._teacher.normalize_square(square)
        token = str(purpose or "custom").strip().lower()
        style = self._teacher.style(token)
        return {
            "square": normalized,
            "purpose": style.purpose,
            "color": style.color,
            "cell": self._visual_cell(normalized, self._teacher.orientation),
        }

    @staticmethod
    def _accessible_summary(
        *,
        pointer: Mapping[str, object] | None,
        highlights: tuple[Mapping[str, object], ...],
        arrows: tuple[Mapping[str, object], ...],
        language: str,
    ) -> str:
        parts: list[str] = []
        if pointer is not None:
            square = str(pointer["square"])
            parts.append(f"Pointer {square}" if language == "en" else f"Вказівник {square}")
        if highlights:
            body = ", ".join(
                f"{item['square']} {item['purpose']}" for item in highlights
            )
            parts.append(
                f"Highlights: {body}"
                if language == "en"
                else f"Підсвічування: {body}"
            )
        if arrows:
            body = ", ".join(
                f"{item['start_square']}–{item['end_square']} {item['purpose']}"
                for item in arrows
            )
            parts.append(f"Arrows: {body}" if language == "en" else f"Стрілки: {body}")
        if not parts:
            return "No teaching annotations." if language == "en" else "Навчальних позначок немає."
        return ". ".join(parts) + "."

    def snapshot(self, *, language: str = "uk") -> dict[str, object]:
        # Read canonical presentation state exactly once so visual and accessible
        # projections can never describe different concurrent snapshots.
        state = self._teacher.snapshot()
        lang = "en" if str(language).lower() == "en" else "uk"

        pointer = state.get("pointer_square")
        pointer_item = None
        if pointer:
            pointer_item = self._square_item(pointer, purpose="selected")

        highlights: list[dict[str, object]] = []
        for item in state.get("highlights") or ():
            if not isinstance(item, Mapping):
                raise ValueError("invalid teacher highlight state")
            highlights.append(
                self._square_item(
                    item.get("square"),
                    purpose=item.get("purpose") or "custom",
                )
            )

        arrows: list[dict[str, object]] = []
        for item in state.get("arrows") or ():
            if not isinstance(item, Mapping):
                raise ValueError("invalid teacher arrow state")
            start = self._square_item(
                item.get("start_square"),
                purpose=item.get("purpose") or "custom",
            )
            end = self._square_item(
                item.get("end_square"),
                purpose=item.get("purpose") or "custom",
            )
            if start["square"] == end["square"]:
                raise ValueError("invalid zero-length teacher arrow state")
            arrows.append(
                {
                    "start_square": start["square"],
                    "end_square": end["square"],
                    "purpose": start["purpose"],
                    "color": start["color"],
                    "start_cell": start["cell"],
                    "end_cell": end["cell"],
                }
            )

        permission = str(state.get("board_permission") or "locked").strip().lower()
        if permission not in _ALLOWED_PERMISSIONS:
            raise ValueError("invalid teacher board permission state")
        engine_visibility = str(
            state.get("engine_visibility") or "hidden"
        ).strip().lower()
        if engine_visibility not in _ALLOWED_ENGINE_VISIBILITY:
            raise ValueError("invalid teacher engine visibility state")

        coordinates_visible = state.get("coordinates_visible", True)
        if type(coordinates_visible) is not bool:
            raise ValueError("invalid teacher coordinates state")

        highlight_items = tuple(highlights)
        arrow_items = tuple(arrows)
        return {
            "board": {
                "orientation": self._teacher.orientation.value,
                "coordinates_visible": coordinates_visible,
                "permission": permission,
                "engine_visibility": engine_visibility,
            },
            "pointer": pointer_item,
            "highlights": highlight_items,
            "arrows": arrow_items,
            "mode": self._teacher.teaching_mode.value,
            "accessible_summary": self._accessible_summary(
                pointer=pointer_item,
                highlights=highlight_items,
                arrows=arrow_items,
                language=lang,
            ),
            "feedback": tuple(
                self._teacher.concise_student_event(event, language=lang)
                for event in self._teacher.feedback_events(limit=10)
            ),
        }

    def type_pointer_text(self, text: str) -> TeacherWebViewEvent:
        value = str(text)
        if len(value) != 2:
            raise ValueError("teacher pointer coordinate must contain two characters")
        dispatched = None
        for character in value:
            dispatched = self._teacher.type_pointer_character(character)
        return TeacherWebViewEvent(
            "pointer-input",
            {"square": dispatched or "", "clear_editor": True},
        )

    def toggle_orientation(self) -> TeacherWebViewEvent:
        orientation = self._teacher.toggle_orientation()
        return TeacherWebViewEvent(
            "render",
            {"orientation": orientation.value, "snapshot": self.snapshot()},
        )

    def record_student_event(
        self,
        kind: str,
        square: str,
        *,
        piece_name: str = "",
        student_id: str = "",
        sequence: int | None = None,
        language: str = "uk",
    ) -> TeacherWebViewEvent:
        try:
            parsed = StudentEventKind(str(kind).strip().lower())
        except ValueError:
            raise ValueError("unsupported student event kind") from None
        event = self._teacher.record_student_event(
            parsed,
            square,
            piece_name=piece_name,
            student_id=student_id,
            sequence=sequence,
        )
        # Hover updates the visual/history channel but never live-announces: rapid
        # mouse movement must not flood NVDA. Explicit selection may announce once.
        announcement = (
            self._teacher.concise_student_event(event, language=language)
            if parsed is StudentEventKind.SELECT
            else ""
        )
        return TeacherWebViewEvent(
            "student-event",
            {
                "event_kind": parsed.value,
                "square": event.square,
                "announcement": announcement,
                "live_region": bool(announcement),
            },
        )
