"""Unified D09 application boundary for Teacher/Classroom interaction.

D01 rendering binds to this module rather than inferring command meaning from
payload text.  D02 remains the sole chess-rules owner; D10 remains the classroom
persistence owner.  This adapter composes the existing canonical TeachingSession
adapter with D09 reverse-channel and visual-presentation services.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .classroom_domain import ClassroomSnapshot
from .teaching_reverse_channel import (
    STUDENT_HOVER_ACTION_ID,
    StudentPointerView,
    TeachingReverseChannelError,
    apply_student_hover_action,
    pointer_history_to_payload,
    project_teacher_pointer_history,
)
from .teaching_session import (
    LessonSession,
    TeachingSessionError,
    TeachingSessionState,
    validate_lesson_session_scope,
)
from .teaching_session_adapter import (
    TEACHING_SESSION_ACTIONS,
    TeachingAdapterError,
    TeachingAudience,
    TeachingSessionView,
    apply_teaching_action,
    project_teaching_session,
    teaching_view_to_payload,
)
from .teaching_visual_board import (
    TEACHER_VISUAL_BOARD_ACTIONS,
    TeachingVisualBoardError,
    apply_teacher_visual_board_action,
)


CLASSROOM_ACTIONS = frozenset(
    set(TEACHING_SESSION_ACTIONS)
    | {STUDENT_HOVER_ACTION_ID}
    | set(TEACHER_VISUAL_BOARD_ACTIONS)
)


class TeachingClassroomAdapterError(ValueError):
    """Stable closed-world classroom boundary failure."""


@dataclass(frozen=True, slots=True)
class ClassroomHighlightView:
    square: str
    purpose: str


@dataclass(frozen=True, slots=True)
class ClassroomArrowView:
    start_square: str
    end_square: str
    purpose: str


@dataclass(frozen=True, slots=True)
class TeachingClassroomView:
    """Audience-safe projection over one canonical TeachingSession state."""

    session: TeachingSessionView
    teacher_pointer_square: str | None
    coordinate_labels_visible: bool
    highlights: tuple[ClassroomHighlightView, ...]
    arrows: tuple[ClassroomArrowView, ...]
    student_pointer_history: tuple[StudentPointerView, ...]


def apply_classroom_action(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
    action_id: str,
    payload: Mapping[str, object] | None,
    *,
    expected_revision: int,
    actor_student_id: str | None = None,
) -> TeachingSessionState:
    """Dispatch an explicitly identified classroom action without intent guessing."""

    _validate_scope(plan, state, classroom)
    if type(action_id) is not str or action_id not in CLASSROOM_ACTIONS:
        raise TeachingClassroomAdapterError("unsupported classroom action")
    try:
        if action_id == STUDENT_HOVER_ACTION_ID:
            return apply_student_hover_action(
                plan,
                state,
                classroom,
                payload,
                expected_revision=expected_revision,
                actor_student_id=actor_student_id,
            )
        if action_id in TEACHER_VISUAL_BOARD_ACTIONS:
            return apply_teacher_visual_board_action(
                plan,
                state,
                action_id,
                payload,
                expected_revision=expected_revision,
                actor_student_id=actor_student_id,
            )
        return apply_teaching_action(
            plan,
            state,
            action_id,
            payload,
            expected_revision=expected_revision,
            actor_student_id=actor_student_id,
        )
    except (
        TeachingAdapterError,
        TeachingReverseChannelError,
        TeachingVisualBoardError,
        TeachingSessionError,
        TypeError,
        ValueError,
    ) as exc:
        raise TeachingClassroomAdapterError("classroom action could not be applied") from exc


def project_classroom_view(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
    *,
    audience: TeachingAudience,
    viewer_student_id: str | None = None,
    pointer_history_limit: int = 20,
) -> TeachingClassroomView:
    """Project visual lesson state for teacher or student without role leakage."""

    _validate_scope(plan, state, classroom)
    try:
        session = project_teaching_session(
            plan,
            state,
            classroom,
            audience=audience,
            viewer_student_id=viewer_student_id,
        )
        history = (
            project_teacher_pointer_history(
                plan,
                state,
                classroom,
                limit=pointer_history_limit,
            )
            if audience is TeachingAudience.TEACHER
            else ()
        )
        highlights = tuple(
            ClassroomHighlightView(item.square, item.purpose)
            for item in state.presentation.highlights
        )
        arrows = tuple(
            ClassroomArrowView(item.start_square, item.end_square, item.purpose)
            for item in state.presentation.arrows
        )
    except (
        TeachingAdapterError,
        TeachingReverseChannelError,
        TeachingSessionError,
        TypeError,
        ValueError,
    ) as exc:
        raise TeachingClassroomAdapterError("classroom view could not be projected") from exc

    return TeachingClassroomView(
        session=session,
        teacher_pointer_square=state.presentation.pointer.square,
        coordinate_labels_visible=state.presentation.coordinate_labels_visible,
        highlights=highlights,
        arrows=arrows,
        student_pointer_history=history,
    )


def classroom_view_to_payload(view: TeachingClassroomView) -> dict[str, object]:
    """Serialize an already role-minimized view with an explicit field allowlist."""

    if type(view) is not TeachingClassroomView:
        raise TeachingClassroomAdapterError("classroom view is invalid")
    return {
        "session": teaching_view_to_payload(view.session),
        "teacher_pointer_square": view.teacher_pointer_square,
        "coordinate_labels_visible": view.coordinate_labels_visible,
        "highlights": [
            {"square": item.square, "purpose": item.purpose}
            for item in view.highlights
        ],
        "arrows": [
            {
                "start_square": item.start_square,
                "end_square": item.end_square,
                "purpose": item.purpose,
            }
            for item in view.arrows
        ],
        "student_pointer_history": pointer_history_to_payload(view.student_pointer_history),
    }


def _validate_scope(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
) -> None:
    if type(plan) is not LessonSession or type(state) is not TeachingSessionState:
        raise TeachingClassroomAdapterError("teaching session is unavailable")
    if type(classroom) is not ClassroomSnapshot:
        raise TeachingClassroomAdapterError("classroom context is unavailable")
    try:
        validate_lesson_session_scope(plan, classroom)
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingClassroomAdapterError("classroom scope is invalid") from exc
