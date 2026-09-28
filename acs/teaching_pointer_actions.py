from __future__ import annotations

"""Teacher-only presentation actions for the semantic teaching pointer and overlays.

The canonical pointer/highlight/arrow state already lives in PresentationState.
This module only supplies the teacher action boundary used by keyboard/WebView
surfaces. It never owns chess position state, legality, renderer state, or OS mouse
cursor position.
"""

from dataclasses import dataclass, replace

from .interaction_contracts import (
    AnnotationCommand,
    AnnotationOperation,
    ContractValidationError,
    SquareHighlight,
    TeacherPointerCommand,
    TeacherPointerState,
    VisualArrow,
)
from .teaching_session import (
    LessonSession,
    TeachingSessionError,
    TeachingSessionPhase,
    TeachingSessionState,
    current_step,
)
from .teaching_visual_board import LEGAL_MOVE_HIGHLIGHT_PURPOSE


TEACHING_POINTER_INPUT_ACTION_ID = "teaching.pointer_input"
TEACHER_ANNOTATION_ACTION_ID = "teaching.annotation"
DEFAULT_TEACHER_ANNOTATION_PURPOSE = "teacher"
_RESERVED_ANNOTATION_PURPOSES = frozenset({LEGAL_MOVE_HIGHLIGHT_PURPOSE})


class TeachingPointerActionError(ValueError):
    """Stable boundary error for presentation-only teacher actions."""


@dataclass(frozen=True, slots=True)
class TeacherPointerInputCommit:
    """UI consequence of a successfully committed coordinate entry."""

    square: str
    clear_input: bool = True
    keep_focus: bool = True

    def __post_init__(self) -> None:
        try:
            square = TeacherPointerCommand(self.square).square
        except (ContractValidationError, TypeError, ValueError) as exc:
            raise TeachingPointerActionError("pointer commit square is invalid") from exc
        if type(self.clear_input) is not bool or type(self.keep_focus) is not bool:
            raise TeachingPointerActionError("pointer input focus flags must be boolean")
        object.__setattr__(self, "square", square)


def commit_teacher_pointer_input(
    plan: LessonSession,
    state: TeachingSessionState,
    text: str,
    *,
    expected_revision: int,
    actor_student_id: str | None = None,
) -> tuple[TeachingSessionState, TeacherPointerInputCommit]:
    """Commit one typed square and request clear+focus retention from the UI.

    User-facing keyboard input is intentionally forgiving about surrounding
    whitespace/case. The committed semantic square is canonical lowercase text.
    Invalid input fails atomically and leaves the immutable session untouched.
    """

    _preflight_teacher(plan, state, expected_revision, actor_student_id)
    if type(text) is not str:
        raise TeachingPointerActionError("teaching pointer input must be text")
    try:
        command = TeacherPointerCommand(text)
        presentation = replace(
            state.presentation,
            pointer=TeacherPointerState(command.square),
        )
        updated = _presentation_replace(state, presentation)
        commit = TeacherPointerInputCommit(command.square)
    except TeachingPointerActionError:
        raise
    except (ContractValidationError, TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingPointerActionError("teaching pointer square is invalid") from exc
    return updated, commit


def clear_teacher_pointer(
    plan: LessonSession,
    state: TeachingSessionState,
    *,
    expected_revision: int,
    actor_student_id: str | None = None,
) -> TeachingSessionState:
    """Clear only the semantic teacher pointer, preserving all other overlays."""

    _preflight_teacher(plan, state, expected_revision, actor_student_id)
    if state.presentation.pointer.square is None:
        return state
    try:
        presentation = replace(state.presentation, pointer=TeacherPointerState())
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise TeachingPointerActionError("teacher pointer could not be cleared") from exc
    return _presentation_replace(state, presentation)


def apply_teacher_annotation(
    plan: LessonSession,
    state: TeachingSessionState,
    command: AnnotationCommand,
    *,
    expected_revision: int,
    actor_student_id: str | None = None,
) -> TeachingSessionState:
    """Apply one manual square highlight/arrow command to presentation state only.

    AnnotationCommand.CLEAR clears manual annotation layers. With no tag it
    clears all manual highlights/arrows while preserving the canonical legal-move
    highlight layer. With a tag it clears only that manual purpose.
    """

    _preflight_teacher(plan, state, expected_revision, actor_student_id)
    if not isinstance(command, AnnotationCommand):
        raise TeachingPointerActionError("teacher annotation command is invalid")

    purpose = command.tag or DEFAULT_TEACHER_ANNOTATION_PURPOSE
    if purpose in _RESERVED_ANNOTATION_PURPOSES:
        raise TeachingPointerActionError(
            "annotation purpose is reserved by canonical presentation"
        )

    highlights = state.presentation.highlights
    arrows = state.presentation.arrows
    try:
        if command.operation is AnnotationOperation.SET_HIGHLIGHT:
            if command.start_square is None:
                raise TeachingPointerActionError("highlight square is unavailable")
            generated = SquareHighlight(command.start_square, purpose)
            highlights = tuple(
                item
                for item in highlights
                if not (item.square == generated.square and item.purpose == purpose)
            ) + (generated,)
        elif command.operation is AnnotationOperation.ADD_ARROW:
            if command.start_square is None or command.end_square is None:
                raise TeachingPointerActionError("arrow squares are unavailable")
            generated_arrow = VisualArrow(
                command.start_square,
                command.end_square,
                purpose,
            )
            arrows = tuple(
                item
                for item in arrows
                if not (
                    item.start_square == generated_arrow.start_square
                    and item.end_square == generated_arrow.end_square
                    and item.purpose == purpose
                )
            ) + (generated_arrow,)
        elif command.operation is AnnotationOperation.CLEAR:
            if command.tag is None:
                highlights = tuple(
                    item
                    for item in highlights
                    if item.purpose in _RESERVED_ANNOTATION_PURPOSES
                )
                arrows = ()
            else:
                highlights = tuple(
                    item for item in highlights if item.purpose != purpose
                )
                arrows = tuple(item for item in arrows if item.purpose != purpose)
        else:
            raise TeachingPointerActionError(
                "unsupported teacher annotation operation"
            )

        presentation = replace(
            state.presentation,
            highlights=highlights,
            arrows=arrows,
        )
    except TeachingPointerActionError:
        raise
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise TeachingPointerActionError(
            "teacher annotation exceeds presentation bounds"
        ) from exc
    return _presentation_replace(state, presentation)


def _preflight_teacher(
    plan: LessonSession,
    state: TeachingSessionState,
    expected_revision: int,
    actor_student_id: str | None,
) -> None:
    if type(plan) is not LessonSession or type(state) is not TeachingSessionState:
        raise TeachingPointerActionError("teaching session is unavailable")
    if actor_student_id is not None:
        raise TeachingPointerActionError(
            "teacher presentation action must not carry student identity"
        )
    if type(expected_revision) is not int or expected_revision < 0:
        raise TeachingPointerActionError("expected teaching revision is invalid")
    try:
        current_step(plan, state)
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingPointerActionError(
            "teaching session cannot be used safely"
        ) from exc
    if state.revision != expected_revision:
        raise TeachingPointerActionError("stale teaching session revision")
    if state.phase is TeachingSessionPhase.COMPLETED:
        raise TeachingPointerActionError(
            "completed session cannot change teacher presentation"
        )


def _presentation_replace(
    state: TeachingSessionState,
    presentation,
) -> TeachingSessionState:
    before = (
        state.position_fen,
        state.last_response,
        state.active_student_id,
        state.presentation.board_permission,
        state.presentation.engine_visibility,
        state.presentation.student_pointer_history,
    )
    try:
        updated = replace(
            state,
            presentation=presentation,
            revision=state.revision + 1,
        )
    except (ContractValidationError, TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingPointerActionError(
            "teacher presentation action could not be applied"
        ) from exc
    after = (
        updated.position_fen,
        updated.last_response,
        updated.active_student_id,
        updated.presentation.board_permission,
        updated.presentation.engine_visibility,
        updated.presentation.student_pointer_history,
    )
    if after != before:
        raise TeachingPointerActionError(
            "teacher presentation action mutated protected teaching state"
        )
    return updated
