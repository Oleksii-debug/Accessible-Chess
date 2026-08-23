"""Role-safe application/presentation adapter for canonical teaching sessions.

This module deliberately does not own chess rules, TeachingSession persistence,
Classroom persistence, WebView state, authentication, or transport.  It joins
already-canonical ``LessonSession`` / ``TeachingSessionState`` values with an
already-canonical ``ClassroomSnapshot`` at one strict presentation boundary.

Two invariants are particularly important:

* a student projection never contains answer targets, another student's
  response, raw student identifiers, FEN/source references, plan digests, or
  session identifiers;
* browser/student identity is supplied out-of-band to ``apply_teaching_action``
  and is never accepted from the untrusted action payload.

All state-changing actions delegate to the canonical teaching-session functions.
No second chess/application state machine is implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .classroom_domain import ClassroomSnapshot
from .interaction_contracts import AnnotationCommand, AnnotationOperation, EngineVisibilityPolicy
from .teaching_session import (
    LessonSession,
    TeachingActivity,
    TeachingInputKind,
    TeachingResponse,
    TeachingSessionError,
    TeachingSessionPhase,
    TeachingSessionState,
    advance_step,
    apply_annotation,
    current_step,
    pause_session,
    resume_session,
    set_teacher_pointer,
    submit_move,
    submit_selection,
    tick_timer,
    validate_lesson_session_scope,
)


class TeachingAdapterError(ValueError):
    """Stable boundary failure that does not echo internal domain details."""


class TeachingAudience(str, Enum):
    TEACHER = "teacher"
    STUDENT = "student"


@dataclass(frozen=True, slots=True)
class TeachingResponseView:
    student_label: str
    input_kind: str
    value: str


@dataclass(frozen=True, slots=True)
class TeachingSessionView:
    """Data-minimized view safe for an accessibility/WebView presentation."""

    audience: TeachingAudience
    phase: str
    step_number: int
    step_count: int
    activity: str
    prompt: str
    board_permission: str
    engine_visible: bool
    remaining_seconds: int | None
    active_student_label: str
    viewer_is_active: bool
    target_square: str | None
    target_piece: str | None
    solution_text: str | None
    last_response: TeachingResponseView | None
    can_submit_selection: bool
    can_submit_move: bool
    can_pause: bool
    can_resume: bool
    can_advance: bool


_TEACHER_ACTIONS = frozenset(
    {
        "teaching.pause",
        "teaching.resume",
        "teaching.advance",
        "teaching.tick",
        "teacher.pointer_input",
        "teacher.pointer_clear",
        "teacher.highlight",
        "teacher.arrow",
        "teacher.clear_annotations",
    }
)
_STUDENT_ACTIONS = frozenset({"student.select", "student.move"})
TEACHING_SESSION_ACTIONS = _TEACHER_ACTIONS | _STUDENT_ACTIONS


def project_teaching_session(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
    *,
    audience: TeachingAudience,
    viewer_student_id: str | None = None,
) -> TeachingSessionView:
    """Project one canonical teaching state without answer/identity leakage.

    ``viewer_student_id`` is required only for a student view.  The identifier is
    used for authorization and is deliberately not copied into the returned DTO.
    """

    if type(plan) is not LessonSession or type(state) is not TeachingSessionState:
        raise TeachingAdapterError("teaching session is unavailable")
    if type(classroom) is not ClassroomSnapshot:
        raise TeachingAdapterError("classroom context is unavailable")
    if not isinstance(audience, TeachingAudience):
        raise TeachingAdapterError("unsupported teaching audience")

    try:
        validate_lesson_session_scope(plan, classroom)
        step = current_step(plan, state)
        students = {
            item.student_id: item
            for item in classroom.students
            if not item.deleted
        }
        _validate_runtime_identity(plan, state, students)
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingAdapterError("teaching session cannot be projected safely") from exc

    viewer_id: str | None = None
    if audience is TeachingAudience.STUDENT:
        if type(viewer_student_id) is not str or viewer_student_id not in plan.student_ids:
            raise TeachingAdapterError("student is not authorized for this lesson")
        if viewer_student_id not in students:
            raise TeachingAdapterError("student is not authorized for this lesson")
        viewer_id = viewer_student_id
    elif viewer_student_id is not None:
        # Do not silently accept an irrelevant student identity on a teacher view.
        raise TeachingAdapterError("teacher projection must not include student viewer identity")

    active_label = ""
    viewer_is_active = False
    if state.active_student_id is not None:
        if audience is TeachingAudience.TEACHER:
            active_label = students[state.active_student_id].pseudonym
        else:
            viewer_is_active = state.active_student_id == viewer_id

    response = _project_response(
        state.last_response,
        students,
        audience=audience,
        viewer_student_id=viewer_id,
    )

    teacher_view = audience is TeachingAudience.TEACHER
    active = state.phase is TeachingSessionPhase.ACTIVE
    paused = state.phase is TeachingSessionPhase.PAUSED
    input_kind = step.policy.input_kind

    return TeachingSessionView(
        audience=audience,
        phase=state.phase.value,
        step_number=state.step_index + 1,
        step_count=len(plan.steps),
        activity=step.activity.value,
        prompt=step.prompt,
        board_permission=state.presentation.board_permission.value,
        engine_visible=_engine_visible(state.presentation.engine_visibility, audience),
        remaining_seconds=state.remaining_seconds,
        active_student_label=active_label,
        viewer_is_active=viewer_is_active,
        target_square=step.target_square if teacher_view else None,
        target_piece=step.target_piece if teacher_view else None,
        solution_text=(step.solution_text if step.policy.solution_visible else None),
        last_response=response,
        can_submit_selection=(
            not teacher_view
            and active
            and input_kind is TeachingInputKind.SELECTION
        ),
        can_submit_move=(
            not teacher_view
            and active
            and input_kind is TeachingInputKind.MOVE
        ),
        can_pause=teacher_view and active,
        can_resume=teacher_view and paused,
        can_advance=teacher_view and active,
    )


def teaching_view_to_payload(view: TeachingSessionView) -> dict[str, object]:
    """Return an explicit closed-world payload; never serialize ``__dict__``."""

    if type(view) is not TeachingSessionView:
        raise TeachingAdapterError("teaching view is invalid")
    response = None
    if view.last_response is not None:
        response = {
            "student_label": view.last_response.student_label,
            "input_kind": view.last_response.input_kind,
            "value": view.last_response.value,
        }
    return {
        "audience": view.audience.value,
        "phase": view.phase,
        "step_number": view.step_number,
        "step_count": view.step_count,
        "activity": view.activity,
        "prompt": view.prompt,
        "board_permission": view.board_permission,
        "engine_visible": view.engine_visible,
        "remaining_seconds": view.remaining_seconds,
        "active_student_label": view.active_student_label,
        "viewer_is_active": view.viewer_is_active,
        "target_square": view.target_square,
        "target_piece": view.target_piece,
        "solution_text": view.solution_text,
        "last_response": response,
        "can_submit_selection": view.can_submit_selection,
        "can_submit_move": view.can_submit_move,
        "can_pause": view.can_pause,
        "can_resume": view.can_resume,
        "can_advance": view.can_advance,
    }


def accessible_teaching_summary(view: TeachingSessionView, *, language: str = "uk") -> str:
    """Produce bounded concise speech text from the already-minimized DTO."""

    if type(view) is not TeachingSessionView:
        raise TeachingAdapterError("teaching view is invalid")
    if language not in {"uk", "en"}:
        raise TeachingAdapterError("unsupported teaching summary language")

    activity = _ACTIVITY_LABELS[language][view.activity]
    if language == "uk":
        parts = [
            f"Крок {view.step_number} з {view.step_count}",
            activity,
            view.prompt,
        ]
        if view.remaining_seconds is not None:
            parts.append(f"Залишилось {view.remaining_seconds} с")
        if view.active_student_label:
            parts.append(f"Активний учень: {view.active_student_label}")
        if view.viewer_is_active:
            parts.append("Зараз ваша черга")
        if view.target_square is not None:
            parts.append(f"Цільова клітинка: {view.target_square}")
        if view.target_piece is not None:
            parts.append(f"Цільова фігура: {view.target_piece}")
        if view.solution_text is not None:
            parts.append(f"Розв'язок: {view.solution_text}")
        if view.last_response is not None:
            label = f" {view.last_response.student_label}" if view.last_response.student_label else ""
            parts.append(f"Відповідь{label}: {view.last_response.value}")
    else:
        parts = [
            f"Step {view.step_number} of {view.step_count}",
            activity,
            view.prompt,
        ]
        if view.remaining_seconds is not None:
            parts.append(f"{view.remaining_seconds} seconds remaining")
        if view.active_student_label:
            parts.append(f"Active student: {view.active_student_label}")
        if view.viewer_is_active:
            parts.append("It is your turn")
        if view.target_square is not None:
            parts.append(f"Target square: {view.target_square}")
        if view.target_piece is not None:
            parts.append(f"Target piece: {view.target_piece}")
        if view.solution_text is not None:
            parts.append(f"Solution: {view.solution_text}")
        if view.last_response is not None:
            label = f" {view.last_response.student_label}" if view.last_response.student_label else ""
            parts.append(f"Response{label}: {view.last_response.value}")
    return ". ".join(parts) + "."


def apply_teaching_action(
    plan: LessonSession,
    state: TeachingSessionState,
    action_id: str,
    payload: Mapping[str, object] | None,
    *,
    expected_revision: int,
    actor_student_id: str | None = None,
) -> TeachingSessionState:
    """Strictly map presentation actions to canonical TeachingSession mutations.

    Student identity is an out-of-band trusted context argument.  A browser
    payload containing ``student_id`` is rejected as an extra field rather than
    trusted.  Teacher and student actions are mutually exclusive by actor shape.
    """

    if type(action_id) is not str or action_id not in TEACHING_SESSION_ACTIONS:
        raise TeachingAdapterError("unsupported teaching action")
    if payload is None:
        data: Mapping[str, object] = {}
    elif isinstance(payload, Mapping) and all(type(key) is str for key in payload):
        data = payload
    else:
        raise TeachingAdapterError("teaching action payload must be an object")

    try:
        if action_id in _STUDENT_ACTIONS:
            if type(actor_student_id) is not str:
                raise TeachingAdapterError("student action requires authenticated lesson identity")
            if action_id == "student.select":
                _exact_keys(data, {"square"})
                square = _exact_text(data["square"], "square", maximum=2)
                return submit_selection(plan, state, actor_student_id, square, expected_revision)
            _exact_keys(data, {"raw_text"})
            raw_text = _exact_text(data["raw_text"], "move", maximum=64)
            return submit_move(plan, state, actor_student_id, raw_text, expected_revision)

        if actor_student_id is not None:
            raise TeachingAdapterError("teacher action must not carry student identity")

        if action_id == "teaching.pause":
            _exact_keys(data, set())
            return pause_session(plan, state, expected_revision)
        if action_id == "teaching.resume":
            _exact_keys(data, set())
            return resume_session(plan, state, expected_revision)
        if action_id == "teaching.advance":
            _exact_keys(data, set())
            return advance_step(plan, state, expected_revision)
        if action_id == "teaching.tick":
            _exact_keys(data, {"elapsed_seconds"})
            elapsed = data["elapsed_seconds"]
            if type(elapsed) is not int:
                raise TeachingAdapterError("elapsed_seconds must be an exact integer")
            return tick_timer(plan, state, elapsed, expected_revision)
        if action_id == "teacher.pointer_input":
            _exact_keys(data, {"square"})
            square = _exact_text(data["square"], "square", maximum=2)
            return set_teacher_pointer(plan, state, square, expected_revision)
        if action_id == "teacher.pointer_clear":
            _exact_keys(data, set())
            return set_teacher_pointer(plan, state, None, expected_revision)
        if action_id == "teacher.highlight":
            _exact_keys(data, {"square", "purpose"})
            command = AnnotationCommand(
                AnnotationOperation.SET_HIGHLIGHT,
                start_square=_exact_text(data["square"], "square", maximum=2),
                tag=_exact_text(data["purpose"], "purpose", maximum=64),
            )
            return apply_annotation(plan, state, command, expected_revision)
        if action_id == "teacher.arrow":
            _exact_keys(data, {"start_square", "end_square", "purpose"})
            command = AnnotationCommand(
                AnnotationOperation.ADD_ARROW,
                start_square=_exact_text(data["start_square"], "start_square", maximum=2),
                end_square=_exact_text(data["end_square"], "end_square", maximum=2),
                tag=_exact_text(data["purpose"], "purpose", maximum=64),
            )
            return apply_annotation(plan, state, command, expected_revision)
        if action_id == "teacher.clear_annotations":
            _exact_keys(data, set())
            return apply_annotation(
                plan,
                state,
                AnnotationCommand(AnnotationOperation.CLEAR),
                expected_revision,
            )
    except TeachingAdapterError:
        raise
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingAdapterError("teaching action could not be applied") from exc

    # Defensive: TEACHING_SESSION_ACTIONS and branches above must stay closed-world.
    raise TeachingAdapterError("unsupported teaching action")


def _validate_runtime_identity(
    plan: LessonSession,
    state: TeachingSessionState,
    students: Mapping[str, object],
) -> None:
    active = state.active_student_id
    if active is not None and (active not in plan.student_ids or active not in students):
        raise TeachingSessionError("teaching state contains an unavailable active student")
    response = state.last_response
    if response is None:
        return
    if response.student_id not in plan.student_ids or response.student_id not in students:
        raise TeachingSessionError("teaching response contains an unavailable student")
    step = plan.steps[state.step_index]
    if response.step_id != step.step_id:
        raise TeachingSessionError("teaching response belongs to another step")
    if response.input_kind is not step.policy.input_kind:
        raise TeachingSessionError("teaching response kind does not match current step")


def _project_response(
    response: TeachingResponse | None,
    students: Mapping[str, Any],
    *,
    audience: TeachingAudience,
    viewer_student_id: str | None,
) -> TeachingResponseView | None:
    if response is None:
        return None
    if audience is TeachingAudience.STUDENT and response.student_id != viewer_student_id:
        return None
    label = students[response.student_id].pseudonym if audience is TeachingAudience.TEACHER else ""
    return TeachingResponseView(
        student_label=label,
        input_kind=response.input_kind.value,
        value=response.value,
    )


def _engine_visible(policy: EngineVisibilityPolicy, audience: TeachingAudience) -> bool:
    if audience is TeachingAudience.TEACHER:
        return policy is EngineVisibilityPolicy.VISIBLE_TO_TEACHER
    return policy is EngineVisibilityPolicy.VISIBLE_TO_STUDENT


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise TeachingAdapterError("teaching action payload shape is invalid")


def _exact_text(value: object, label: str, *, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or "\x00" in value
        or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    ):
        raise TeachingAdapterError(f"{label} is invalid")
    return value


_ACTIVITY_LABELS = {
    "uk": {
        TeachingActivity.TEACHER_EXPLAINS.value: "Пояснення викладача",
        TeachingActivity.STUDENT_RESPONDS.value: "Відповідь учня",
        TeachingActivity.SHOW_SQUARE.value: "Покажи клітинку",
        TeachingActivity.SHOW_PIECE.value: "Покажи фігуру",
        TeachingActivity.MAKE_MOVE.value: "Зроби хід",
        TeachingActivity.WHERE_CAN_PIECE_MOVE.value: "Куди може ходити фігура",
        TeachingActivity.ATTACK_DEFENCE.value: "Атака і захист",
        TeachingActivity.SOLUTION_REVEAL.value: "Показ розв'язку",
    },
    "en": {
        TeachingActivity.TEACHER_EXPLAINS.value: "Teacher explains",
        TeachingActivity.STUDENT_RESPONDS.value: "Student responds",
        TeachingActivity.SHOW_SQUARE.value: "Show square",
        TeachingActivity.SHOW_PIECE.value: "Show piece",
        TeachingActivity.MAKE_MOVE.value: "Make a move",
        TeachingActivity.WHERE_CAN_PIECE_MOVE.value: "Where can this piece move",
        TeachingActivity.ATTACK_DEFENCE.value: "Attack and defence",
        TeachingActivity.SOLUTION_REVEAL.value: "Solution reveal",
    },
}
