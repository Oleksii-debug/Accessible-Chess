from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping

from .chesscore import Board
from .classroom_domain import ClassroomSnapshot
from .interaction_contracts import (
    AnnotationCommand,
    AnnotationOperation,
    BoardPermissionState,
    EngineVisibilityPolicy,
    PresentationState,
    SquareHighlight,
    StudentSelectionEvent,
    TeacherPointerState,
    VisualArrow,
    presentation_state_from_payload,
    presentation_state_to_payload,
)
from .squares import normalize_square

TEACHING_SESSION_VERSION = 1
MAX_TEACHING_STEPS = 512
MAX_SESSION_STUDENTS = 2000
MAX_TEACHING_JSON_BYTES = 1_000_000
MAX_TIMER_SECONDS = 24 * 60 * 60
MAX_TEXT = 2048
MAX_WIRE_INTEGER = (1 << 53) - 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PIECES = frozenset("PNBRQKpnbrqk")


class TeachingSessionError(ValueError):
    """Stable failure for teaching-session contracts and transactions."""


class TeachingActivity(str, Enum):
    TEACHER_EXPLAINS = "teacher_explains"
    STUDENT_RESPONDS = "student_responds"
    SHOW_SQUARE = "show_square"
    SHOW_PIECE = "show_piece"
    MAKE_MOVE = "make_move"
    WHERE_CAN_PIECE_MOVE = "where_can_piece_move"
    ATTACK_DEFENCE = "attack_defence"
    SOLUTION_REVEAL = "solution_reveal"


class TeachingInputKind(str, Enum):
    NONE = "none"
    SELECTION = "selection"
    MOVE = "move"


class PositionSourceKind(str, Enum):
    START = "start"
    FEN = "fen"
    PGN = "pgn"
    BOOK = "book"
    DATABASE = "database"


class TeachingSessionPhase(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass(frozen=True)
class TeachingInputPolicy:
    input_kind: TeachingInputKind
    board_permission: BoardPermissionState
    engine_visibility: EngineVisibilityPolicy = EngineVisibilityPolicy.HIDDEN
    solution_visible: bool = False
    timer_seconds: int | None = None

    def __post_init__(self) -> None:
        input_kind = _enum(self.input_kind, TeachingInputKind, "input kind")
        permission = _enum(self.board_permission, BoardPermissionState, "board permission")
        visibility = _enum(self.engine_visibility, EngineVisibilityPolicy, "engine visibility")
        if type(self.solution_visible) is not bool:
            raise TeachingSessionError("solution_visible must be boolean")
        timer = _optional_timer(self.timer_seconds)
        required_permission = {
            TeachingInputKind.NONE: BoardPermissionState.LOCKED,
            TeachingInputKind.SELECTION: BoardPermissionState.SELECT_ONLY,
            TeachingInputKind.MOVE: BoardPermissionState.MOVE_ALLOWED,
        }[input_kind]
        if permission is not required_permission:
            raise TeachingSessionError("input kind and board permission are inconsistent")
        object.__setattr__(self, "input_kind", input_kind)
        object.__setattr__(self, "board_permission", permission)
        object.__setattr__(self, "engine_visibility", visibility)
        object.__setattr__(self, "timer_seconds", timer)


def default_policy(
    activity: TeachingActivity | str,
    *,
    timer_seconds: int | None = None,
    engine_visibility: EngineVisibilityPolicy | str | None = None,
) -> TeachingInputPolicy:
    activity = _enum(activity, TeachingActivity, "teaching activity")
    input_kind = {
        TeachingActivity.TEACHER_EXPLAINS: TeachingInputKind.NONE,
        TeachingActivity.STUDENT_RESPONDS: TeachingInputKind.SELECTION,
        TeachingActivity.SHOW_SQUARE: TeachingInputKind.SELECTION,
        TeachingActivity.SHOW_PIECE: TeachingInputKind.SELECTION,
        TeachingActivity.MAKE_MOVE: TeachingInputKind.MOVE,
        TeachingActivity.WHERE_CAN_PIECE_MOVE: TeachingInputKind.SELECTION,
        TeachingActivity.ATTACK_DEFENCE: TeachingInputKind.SELECTION,
        TeachingActivity.SOLUTION_REVEAL: TeachingInputKind.NONE,
    }[activity]
    permission = {
        TeachingInputKind.NONE: BoardPermissionState.LOCKED,
        TeachingInputKind.SELECTION: BoardPermissionState.SELECT_ONLY,
        TeachingInputKind.MOVE: BoardPermissionState.MOVE_ALLOWED,
    }[input_kind]
    if engine_visibility is None:
        visibility = (
            EngineVisibilityPolicy.VISIBLE_TO_STUDENT
            if activity is TeachingActivity.SOLUTION_REVEAL
            else EngineVisibilityPolicy.HIDDEN
        )
    else:
        visibility = _enum(engine_visibility, EngineVisibilityPolicy, "engine visibility")
    return TeachingInputPolicy(
        input_kind=input_kind,
        board_permission=permission,
        engine_visibility=visibility,
        solution_visible=activity is TeachingActivity.SOLUTION_REVEAL,
        timer_seconds=timer_seconds,
    )


@dataclass(frozen=True)
class TeachingPositionSource:
    kind: PositionSourceKind
    fen: str = Board.START
    source_ref: str | None = None
    source_index: int | None = None

    def __post_init__(self) -> None:
        kind = _enum(self.kind, PositionSourceKind, "position source kind")
        fen = _fen(self.fen)
        source_ref = _optional_id(self.source_ref, "position source ref")
        source_index = _optional_index(self.source_index, "position source index")
        if kind is PositionSourceKind.START:
            if fen != Board.START or source_ref is not None or source_index is not None:
                raise TeachingSessionError("start source must be the canonical initial position without provenance fields")
        elif kind is PositionSourceKind.FEN:
            if source_ref is not None or source_index is not None:
                raise TeachingSessionError("FEN source must not invent external provenance")
        elif kind is PositionSourceKind.PGN:
            if source_ref is None or source_index is None:
                raise TeachingSessionError("PGN source requires opaque source_ref and source_index")
        else:
            if source_ref is None or source_index is not None:
                raise TeachingSessionError(f"{kind.value} source requires one opaque source_ref")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "fen", fen)
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "source_index", source_index)


@dataclass(frozen=True)
class TeachingStep:
    step_id: str
    activity: TeachingActivity
    prompt: str
    policy: TeachingInputPolicy
    target_square: str | None = None
    target_piece: str | None = None
    solution_text: str | None = None

    def __post_init__(self) -> None:
        step_id = _id(self.step_id, "teaching step id")
        activity = _enum(self.activity, TeachingActivity, "teaching activity")
        prompt = _text(self.prompt, "teaching prompt")
        if type(self.policy) is not TeachingInputPolicy:
            raise TeachingSessionError("teaching step policy must be TeachingInputPolicy")
        square = _optional_square(self.target_square, "target square")
        piece = self.target_piece
        if piece is not None and (type(piece) is not str or piece not in _PIECES):
            raise TeachingSessionError("target piece must be one canonical chess piece symbol")
        solution = _optional_text(self.solution_text, "solution text", max_len=MAX_TEXT)

        expected_input = {
            TeachingActivity.TEACHER_EXPLAINS: TeachingInputKind.NONE,
            TeachingActivity.STUDENT_RESPONDS: TeachingInputKind.SELECTION,
            TeachingActivity.SHOW_SQUARE: TeachingInputKind.SELECTION,
            TeachingActivity.SHOW_PIECE: TeachingInputKind.SELECTION,
            TeachingActivity.MAKE_MOVE: TeachingInputKind.MOVE,
            TeachingActivity.WHERE_CAN_PIECE_MOVE: TeachingInputKind.SELECTION,
            TeachingActivity.ATTACK_DEFENCE: TeachingInputKind.SELECTION,
            TeachingActivity.SOLUTION_REVEAL: TeachingInputKind.NONE,
        }[activity]
        if self.policy.input_kind is not expected_input:
            raise TeachingSessionError("teaching activity and input policy are inconsistent")

        requires_square = activity in {
            TeachingActivity.SHOW_SQUARE,
            TeachingActivity.SHOW_PIECE,
            TeachingActivity.WHERE_CAN_PIECE_MOVE,
            TeachingActivity.ATTACK_DEFENCE,
        }
        if requires_square != (square is not None):
            raise TeachingSessionError("teaching activity target-square shape is inconsistent")
        if activity is TeachingActivity.SHOW_PIECE:
            if piece is None:
                raise TeachingSessionError("show_piece requires target_piece")
        elif piece is not None:
            raise TeachingSessionError("target_piece is only valid for show_piece")
        if activity is TeachingActivity.SOLUTION_REVEAL:
            if solution is None or not self.policy.solution_visible:
                raise TeachingSessionError("solution_reveal requires visible solution text")
        elif solution is not None or self.policy.solution_visible:
            raise TeachingSessionError("solution content is only valid for solution_reveal")

        object.__setattr__(self, "step_id", step_id)
        object.__setattr__(self, "activity", activity)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "target_square", square)
        object.__setattr__(self, "target_piece", piece)
        object.__setattr__(self, "solution_text", solution)


@dataclass(frozen=True)
class LessonSession:
    session_id: str
    lesson_id: str
    source: TeachingPositionSource
    steps: tuple[TeachingStep, ...]
    student_ids: tuple[str, ...] = ()
    cohort_id: str | None = None
    version: int = TEACHING_SESSION_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        _id(self.session_id, "teaching session id")
        _id(self.lesson_id, "lesson id")
        if type(self.source) is not TeachingPositionSource:
            raise TeachingSessionError("lesson session source must be TeachingPositionSource")
        if type(self.steps) is not tuple or not self.steps or len(self.steps) > MAX_TEACHING_STEPS:
            raise TeachingSessionError("lesson session requires a bounded non-empty tuple of steps")
        if any(type(step) is not TeachingStep for step in self.steps):
            raise TeachingSessionError("lesson session steps contain invalid record type")
        step_ids = tuple(step.step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise TeachingSessionError("lesson session step ids must be unique")
        students = _id_tuple(self.student_ids, "lesson session student ids", MAX_SESSION_STUDENTS)
        cohort = _optional_id(self.cohort_id, "lesson session cohort id")
        object.__setattr__(self, "student_ids", students)
        object.__setattr__(self, "cohort_id", cohort)

    @property
    def digest(self) -> str:
        return _digest(_lesson_body(self))

    def to_record(self) -> dict[str, Any]:
        body = _lesson_body(self)
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        return _bounded_json(self.to_record(), "lesson session")

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "LessonSession":
        data = _mapping(value, "lesson session")
        _exact_keys(
            data,
            {"version", "session_id", "lesson_id", "source", "steps", "student_ids", "cohort_id", "digest"},
            "lesson session",
        )
        supplied = _digest_text(data["digest"], "lesson session digest")
        source = _source_from_record(data["source"])
        raw_steps = data["steps"]
        raw_students = data["student_ids"]
        if type(raw_steps) is not list or not raw_steps or len(raw_steps) > MAX_TEACHING_STEPS:
            raise TeachingSessionError("lesson session steps must be a bounded non-empty JSON array")
        if type(raw_students) is not list or len(raw_students) > MAX_SESSION_STUDENTS:
            raise TeachingSessionError("lesson session students must be a bounded JSON array")
        plan = cls(
            session_id=data["session_id"],
            lesson_id=data["lesson_id"],
            source=source,
            steps=tuple(_step_from_record(item) for item in raw_steps),
            student_ids=tuple(raw_students),
            cohort_id=data["cohort_id"],
            version=data["version"],
        )
        if plan.digest != supplied:
            raise TeachingSessionError("lesson session digest mismatch")
        return plan

    @classmethod
    def from_json(cls, text: str) -> "LessonSession":
        return cls.from_record(_parse_bounded_json(text, "lesson session"))


@dataclass(frozen=True)
class TeachingResponse:
    student_id: str
    step_id: str
    input_kind: TeachingInputKind
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "student_id", _id(self.student_id, "response student id"))
        object.__setattr__(self, "step_id", _id(self.step_id, "response step id"))
        object.__setattr__(self, "input_kind", _enum(self.input_kind, TeachingInputKind, "response input kind"))
        object.__setattr__(self, "value", _text(self.value, "response value"))
        if self.input_kind is TeachingInputKind.NONE:
            raise TeachingSessionError("response input kind cannot be none")


@dataclass(frozen=True)
class TeachingSessionState:
    session_id: str
    plan_digest: str
    phase: TeachingSessionPhase
    step_index: int
    position_fen: str
    presentation: PresentationState
    remaining_seconds: int | None
    active_student_id: str | None = None
    last_response: TeachingResponse | None = None
    revision: int = 0
    version: int = TEACHING_SESSION_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        object.__setattr__(self, "session_id", _id(self.session_id, "teaching session id"))
        object.__setattr__(self, "plan_digest", _digest_text(self.plan_digest, "plan digest"))
        object.__setattr__(self, "phase", _enum(self.phase, TeachingSessionPhase, "session phase"))
        if type(self.step_index) is not int or not 0 <= self.step_index < MAX_TEACHING_STEPS:
            raise TeachingSessionError("step_index must be an exact bounded non-negative integer")
        object.__setattr__(self, "position_fen", _fen(self.position_fen))
        if type(self.presentation) is not PresentationState:
            raise TeachingSessionError("presentation must be PresentationState")
        object.__setattr__(self, "remaining_seconds", _optional_remaining(self.remaining_seconds))
        object.__setattr__(self, "active_student_id", _optional_id(self.active_student_id, "active student id"))
        if self.last_response is not None and type(self.last_response) is not TeachingResponse:
            raise TeachingSessionError("last_response must be TeachingResponse or null")
        _revision(self.revision, "teaching session revision")
        if self.phase is TeachingSessionPhase.COMPLETED:
            if self.remaining_seconds is not None:
                raise TeachingSessionError("completed session cannot retain a live timer")
            if self.presentation.board_permission is not BoardPermissionState.LOCKED:
                raise TeachingSessionError("completed session board must be locked")

    @property
    def digest(self) -> str:
        return _digest(_state_body(self))

    def to_record(self) -> dict[str, Any]:
        body = _state_body(self)
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        return _bounded_json(self.to_record(), "teaching session state")

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "TeachingSessionState":
        data = _mapping(value, "teaching session state")
        _exact_keys(
            data,
            {
                "version", "session_id", "plan_digest", "phase", "step_index", "position_fen",
                "presentation", "remaining_seconds", "active_student_id", "last_response", "revision", "digest",
            },
            "teaching session state",
        )
        supplied = _digest_text(data["digest"], "teaching state digest")
        response = None if data["last_response"] is None else _response_from_record(data["last_response"])
        state = cls(
            session_id=data["session_id"],
            plan_digest=data["plan_digest"],
            phase=data["phase"],
            step_index=data["step_index"],
            position_fen=data["position_fen"],
            presentation=presentation_state_from_payload(_mapping(data["presentation"], "presentation")),
            remaining_seconds=data["remaining_seconds"],
            active_student_id=data["active_student_id"],
            last_response=response,
            revision=data["revision"],
            version=data["version"],
        )
        if state.digest != supplied:
            raise TeachingSessionError("teaching session state digest mismatch")
        return state

    @classmethod
    def from_json(cls, text: str) -> "TeachingSessionState":
        return cls.from_record(_parse_bounded_json(text, "teaching session state"))


TeachingSession = TeachingSessionState


def validate_lesson_session_scope(plan: LessonSession, classroom: ClassroomSnapshot) -> None:
    if type(plan) is not LessonSession or type(classroom) is not ClassroomSnapshot:
        raise TeachingSessionError("scope validation requires LessonSession and ClassroomSnapshot")
    lesson = next((item for item in classroom.lessons if item.lesson_id == plan.lesson_id), None)
    if lesson is None:
        raise TeachingSessionError("lesson session references unknown classroom lesson")
    active_students = {item.student_id for item in classroom.students if not item.deleted}
    if any(student_id not in active_students for student_id in plan.student_ids):
        raise TeachingSessionError("lesson session contains unavailable student")
    if plan.cohort_id is not None:
        cohort = next((item for item in classroom.cohorts if item.cohort_id == plan.cohort_id), None)
        if cohort is None:
            raise TeachingSessionError("lesson session references unknown cohort")
        if cohort.course_id != lesson.course_id:
            raise TeachingSessionError("lesson session cohort and lesson belong to different courses")
        if any(student_id not in cohort.student_ids for student_id in plan.student_ids):
            raise TeachingSessionError("lesson session student is outside the selected cohort")


def start_session(plan: LessonSession) -> TeachingSessionState:
    _plan(plan)
    step = plan.steps[0]
    return TeachingSessionState(
        session_id=plan.session_id,
        plan_digest=plan.digest,
        phase=TeachingSessionPhase.ACTIVE,
        step_index=0,
        position_fen=plan.source.fen,
        presentation=_presentation_for_step(step),
        remaining_seconds=step.policy.timer_seconds,
        revision=0,
    )


def current_step(plan: LessonSession, state: TeachingSessionState) -> TeachingStep:
    _match(plan, state)
    if state.step_index >= len(plan.steps):
        raise TeachingSessionError("session step index is outside lesson plan")
    return plan.steps[state.step_index]


def pause_session(plan: LessonSession, state: TeachingSessionState, expected_revision: int) -> TeachingSessionState:
    step = _mutable(plan, state, expected_revision)
    if state.phase is not TeachingSessionPhase.ACTIVE:
        raise TeachingSessionError("only active session can be paused")
    presentation = _replace_presentation_policy(
        state.presentation,
        board_permission=BoardPermissionState.LOCKED,
        engine_visibility=EngineVisibilityPolicy.HIDDEN,
    )
    return replace(state, phase=TeachingSessionPhase.PAUSED, presentation=presentation, revision=state.revision + 1)


def resume_session(plan: LessonSession, state: TeachingSessionState, expected_revision: int) -> TeachingSessionState:
    step = _mutable(plan, state, expected_revision)
    if state.phase is not TeachingSessionPhase.PAUSED:
        raise TeachingSessionError("only paused session can be resumed")
    presentation = _replace_presentation_policy(
        state.presentation,
        board_permission=step.policy.board_permission,
        engine_visibility=step.policy.engine_visibility,
    )
    return replace(state, phase=TeachingSessionPhase.ACTIVE, presentation=presentation, revision=state.revision + 1)


def advance_step(plan: LessonSession, state: TeachingSessionState, expected_revision: int) -> TeachingSessionState:
    _mutable(plan, state, expected_revision)
    if state.phase is not TeachingSessionPhase.ACTIVE:
        raise TeachingSessionError("only active session can advance")
    if state.step_index + 1 >= len(plan.steps):
        presentation = _replace_presentation_policy(
            state.presentation,
            board_permission=BoardPermissionState.LOCKED,
            engine_visibility=EngineVisibilityPolicy.HIDDEN,
            clear_transient=True,
        )
        return replace(
            state,
            phase=TeachingSessionPhase.COMPLETED,
            presentation=presentation,
            remaining_seconds=None,
            revision=state.revision + 1,
        )
    next_index = state.step_index + 1
    step = plan.steps[next_index]
    presentation = _presentation_for_step(step, active_student_id=state.active_student_id)
    return replace(
        state,
        step_index=next_index,
        presentation=presentation,
        remaining_seconds=step.policy.timer_seconds,
        last_response=None,
        revision=state.revision + 1,
    )


def submit_selection(
    plan: LessonSession,
    state: TeachingSessionState,
    student_id: str,
    square: str,
    expected_revision: int,
) -> TeachingSessionState:
    step = _mutable(plan, state, expected_revision)
    _active(state)
    student_id = _session_student(plan, student_id)
    if step.policy.input_kind is not TeachingInputKind.SELECTION:
        raise TeachingSessionError("current teaching step does not accept board selection")
    square = _square(square, "student selection square")
    history = state.presentation.student_pointer_history + (
        StudentSelectionEvent(square=square, student_id=student_id, sequence=state.revision + 1),
    )
    presentation = replace(
        state.presentation,
        student_pointer_history=history,
        active_student_id=student_id,
    )
    response = TeachingResponse(student_id, step.step_id, TeachingInputKind.SELECTION, square)
    return replace(
        state,
        presentation=presentation,
        active_student_id=student_id,
        last_response=response,
        revision=state.revision + 1,
    )


def submit_move(
    plan: LessonSession,
    state: TeachingSessionState,
    student_id: str,
    move_text: str,
    expected_revision: int,
) -> TeachingSessionState:
    step = _mutable(plan, state, expected_revision)
    _active(state)
    student_id = _session_student(plan, student_id)
    if step.policy.input_kind is not TeachingInputKind.MOVE:
        raise TeachingSessionError("current teaching step does not accept chess moves")
    move_text = _text(move_text, "student move", max_len=64)
    board = Board(state.position_fen)
    try:
        san = board.push_text(move_text)
    except ValueError as exc:
        raise TeachingSessionError("student move is not legal in the canonical session position") from exc
    response = TeachingResponse(student_id, step.step_id, TeachingInputKind.MOVE, san)
    presentation = replace(state.presentation, active_student_id=student_id)
    return replace(
        state,
        position_fen=board.fen(),
        presentation=presentation,
        active_student_id=student_id,
        last_response=response,
        revision=state.revision + 1,
    )


def set_teacher_pointer(
    plan: LessonSession,
    state: TeachingSessionState,
    square: str | None,
    expected_revision: int,
) -> TeachingSessionState:
    _mutable(plan, state, expected_revision)
    if state.phase is TeachingSessionPhase.COMPLETED:
        raise TeachingSessionError("completed session cannot change teacher pointer")
    pointer = TeacherPointerState(None if square is None else _square(square, "teacher pointer square"))
    presentation = replace(state.presentation, pointer=pointer)
    return replace(state, presentation=presentation, revision=state.revision + 1)


def apply_annotation(
    plan: LessonSession,
    state: TeachingSessionState,
    command: AnnotationCommand,
    expected_revision: int,
) -> TeachingSessionState:
    _mutable(plan, state, expected_revision)
    if state.phase is TeachingSessionPhase.COMPLETED:
        raise TeachingSessionError("completed session cannot change annotations")
    if type(command) is not AnnotationCommand:
        raise TeachingSessionError("annotation operation requires canonical AnnotationCommand")
    presentation = state.presentation
    if command.operation is AnnotationOperation.CLEAR:
        presentation = replace(presentation, highlights=(), arrows=())
    elif command.operation is AnnotationOperation.SET_HIGHLIGHT:
        highlight = SquareHighlight(command.start_square, command.tag or "teacher")
        items = tuple(item for item in presentation.highlights if item.square != highlight.square) + (highlight,)
        presentation = replace(presentation, highlights=items)
    elif command.operation is AnnotationOperation.ADD_ARROW:
        arrow = VisualArrow(command.start_square, command.end_square, command.tag or "teacher")
        items = presentation.arrows if arrow in presentation.arrows else presentation.arrows + (arrow,)
        presentation = replace(presentation, arrows=items)
    else:
        raise TeachingSessionError("unsupported teaching annotation operation")
    return replace(state, presentation=presentation, revision=state.revision + 1)


def tick_timer(
    plan: LessonSession,
    state: TeachingSessionState,
    elapsed_seconds: int,
    expected_revision: int,
) -> TeachingSessionState:
    _mutable(plan, state, expected_revision)
    _active(state)
    if state.remaining_seconds is None:
        raise TeachingSessionError("current teaching step has no timer")
    elapsed = _positive_int(elapsed_seconds, "elapsed seconds", maximum=MAX_TIMER_SECONDS)
    remaining = max(0, state.remaining_seconds - elapsed)
    return replace(state, remaining_seconds=remaining, revision=state.revision + 1)


def _plan(value: object) -> LessonSession:
    if type(value) is not LessonSession:
        raise TeachingSessionError("operation requires LessonSession")
    return value


def _match(plan: LessonSession, state: TeachingSessionState) -> None:
    _plan(plan)
    if type(state) is not TeachingSessionState:
        raise TeachingSessionError("operation requires TeachingSessionState")
    if state.session_id != plan.session_id or state.plan_digest != plan.digest:
        raise TeachingSessionError("teaching state does not belong to this lesson session plan")


def _mutable(plan: LessonSession, state: TeachingSessionState, expected_revision: int) -> TeachingStep:
    _match(plan, state)
    expected = _revision(expected_revision, "expected teaching revision")
    if state.revision != expected:
        raise TeachingSessionError("stale teaching session revision")
    return current_step(plan, state)


def _active(state: TeachingSessionState) -> None:
    if state.phase is not TeachingSessionPhase.ACTIVE:
        raise TeachingSessionError("student input requires active teaching session")


def _session_student(plan: LessonSession, value: object) -> str:
    student_id = _id(value, "student id")
    if student_id not in plan.student_ids:
        raise TeachingSessionError("student is not assigned to this lesson session")
    return student_id


def _presentation_for_step(step: TeachingStep, active_student_id: str | None = None) -> PresentationState:
    return PresentationState(
        active_student_id=active_student_id,
        engine_visibility=step.policy.engine_visibility,
        board_permission=step.policy.board_permission,
    )


def _replace_presentation_policy(
    presentation: PresentationState,
    *,
    board_permission: BoardPermissionState,
    engine_visibility: EngineVisibilityPolicy,
    clear_transient: bool = False,
) -> PresentationState:
    kwargs: dict[str, Any] = {
        "board_permission": board_permission,
        "engine_visibility": engine_visibility,
    }
    if clear_transient:
        kwargs.update(pointer=TeacherPointerState(), highlights=(), arrows=(), student_pointer_history=())
    return replace(presentation, **kwargs)


def _lesson_body(plan: LessonSession) -> dict[str, Any]:
    return {
        "version": plan.version,
        "session_id": plan.session_id,
        "lesson_id": plan.lesson_id,
        "source": _source_record(plan.source),
        "steps": [_step_record(step) for step in plan.steps],
        "student_ids": list(plan.student_ids),
        "cohort_id": plan.cohort_id,
    }


def _state_body(state: TeachingSessionState) -> dict[str, Any]:
    return {
        "version": state.version,
        "session_id": state.session_id,
        "plan_digest": state.plan_digest,
        "phase": state.phase.value,
        "step_index": state.step_index,
        "position_fen": state.position_fen,
        "presentation": presentation_state_to_payload(state.presentation),
        "remaining_seconds": state.remaining_seconds,
        "active_student_id": state.active_student_id,
        "last_response": None if state.last_response is None else _response_record(state.last_response),
        "revision": state.revision,
    }


def _source_record(source: TeachingPositionSource) -> dict[str, Any]:
    return {
        "kind": source.kind.value,
        "fen": source.fen,
        "source_ref": source.source_ref,
        "source_index": source.source_index,
    }


def _source_from_record(value: object) -> TeachingPositionSource:
    data = _mapping(value, "position source")
    _exact_keys(data, {"kind", "fen", "source_ref", "source_index"}, "position source")
    return TeachingPositionSource(data["kind"], data["fen"], data["source_ref"], data["source_index"])


def _policy_record(policy: TeachingInputPolicy) -> dict[str, Any]:
    return {
        "input_kind": policy.input_kind.value,
        "board_permission": policy.board_permission.value,
        "engine_visibility": policy.engine_visibility.value,
        "solution_visible": policy.solution_visible,
        "timer_seconds": policy.timer_seconds,
    }


def _policy_from_record(value: object) -> TeachingInputPolicy:
    data = _mapping(value, "teaching input policy")
    _exact_keys(
        data,
        {"input_kind", "board_permission", "engine_visibility", "solution_visible", "timer_seconds"},
        "teaching input policy",
    )
    return TeachingInputPolicy(
        data["input_kind"], data["board_permission"], data["engine_visibility"], data["solution_visible"], data["timer_seconds"]
    )


def _step_record(step: TeachingStep) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "activity": step.activity.value,
        "prompt": step.prompt,
        "policy": _policy_record(step.policy),
        "target_square": step.target_square,
        "target_piece": step.target_piece,
        "solution_text": step.solution_text,
    }


def _step_from_record(value: object) -> TeachingStep:
    data = _mapping(value, "teaching step")
    _exact_keys(
        data,
        {"step_id", "activity", "prompt", "policy", "target_square", "target_piece", "solution_text"},
        "teaching step",
    )
    return TeachingStep(
        data["step_id"], data["activity"], data["prompt"], _policy_from_record(data["policy"]),
        data["target_square"], data["target_piece"], data["solution_text"]
    )


def _response_record(response: TeachingResponse) -> dict[str, Any]:
    return {
        "student_id": response.student_id,
        "step_id": response.step_id,
        "input_kind": response.input_kind.value,
        "value": response.value,
    }


def _response_from_record(value: object) -> TeachingResponse:
    data = _mapping(value, "teaching response")
    _exact_keys(data, {"student_id", "step_id", "input_kind", "value"}, "teaching response")
    return TeachingResponse(data["student_id"], data["step_id"], data["input_kind"], data["value"])


def _bounded_json(value: object, label: str) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        size = len(text.encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise TeachingSessionError(f"{label} cannot be serialized canonically") from exc
    if size > MAX_TEACHING_JSON_BYTES:
        raise TeachingSessionError(f"{label} exceeds JSON size limit")
    return text


def _parse_bounded_json(text: object, label: str) -> Mapping[str, Any]:
    if type(text) is not str:
        raise TeachingSessionError(f"{label} JSON must be exact text")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise TeachingSessionError(f"{label} JSON contains invalid Unicode scalar value") from exc
    if size > MAX_TEACHING_JSON_BYTES:
        raise TeachingSessionError(f"{label} exceeds JSON size limit")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_int=_parse_wire_integer,
        )
    except json.JSONDecodeError as exc:
        raise TeachingSessionError(f"invalid {label} JSON") from exc
    except RecursionError as exc:
        raise TeachingSessionError(f"{label} JSON exceeds nesting limit") from exc
    return _mapping(value, label)


def _digest(value: object) -> str:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise TeachingSessionError("teaching domain value cannot be hashed canonically") from exc
    return hashlib.sha256(data).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TeachingSessionError(f"{label} must be an exact-key object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise TeachingSessionError(
            f"{label} schema mismatch; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise TeachingSessionError(f"{label} must be a canonical opaque identifier")
    return value


def _optional_id(value: object, label: str) -> str | None:
    return None if value is None else _id(value, label)


def _id_tuple(value: object, label: str, limit: int) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > limit:
        raise TeachingSessionError(f"{label} must be a bounded tuple")
    checked = tuple(_id(item, label) for item in value)
    if len(set(checked)) != len(checked):
        raise TeachingSessionError(f"{label} contains duplicate identifiers")
    return checked


def _text(value: object, label: str, *, max_len: int = MAX_TEXT) -> str:
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > max_len or "\x00" in value:
        raise TeachingSessionError(f"{label} violates exact text boundary")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise TeachingSessionError(f"{label} contains invalid Unicode scalar value")
    return value


def _optional_text(value: object, label: str, *, max_len: int = MAX_TEXT) -> str | None:
    return None if value is None else _text(value, label, max_len=max_len)


def _square(value: object, label: str) -> str:
    if type(value) is not str:
        raise TeachingSessionError(f"{label} must be canonical algebraic text")
    try:
        square = normalize_square(value)
    except ValueError as exc:
        raise TeachingSessionError(f"invalid {label}") from exc
    if value != square:
        raise TeachingSessionError(f"{label} must use canonical lowercase algebraic form")
    return square


def _optional_square(value: object, label: str) -> str | None:
    return None if value is None else _square(value, label)


def _fen(value: object) -> str:
    if type(value) is not str:
        raise TeachingSessionError("teaching position FEN must be exact text")
    try:
        return Board(value).fen()
    except (TypeError, ValueError) as exc:
        raise TeachingSessionError("invalid canonical teaching position FEN") from exc


def _enum(value: object, enum_type, label: str):
    if isinstance(value, enum_type):
        return value
    if type(value) is not str:
        raise TeachingSessionError(f"{label} must be exact text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise TeachingSessionError(f"unsupported {label}: {value!r}") from exc


def _optional_timer(value: object) -> int | None:
    if value is None:
        return None
    return _positive_int(value, "timer_seconds", maximum=MAX_TIMER_SECONDS)


def _optional_remaining(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_TIMER_SECONDS:
        raise TeachingSessionError("remaining_seconds must be a bounded non-negative exact integer")
    return value


def _positive_int(value: object, label: str, *, maximum: int = MAX_WIRE_INTEGER) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise TeachingSessionError(f"{label} must be an exact positive bounded integer")
    return value


def _optional_index(value: object, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise TeachingSessionError(f"{label} must be an exact non-negative bounded integer")
    return value


def _revision(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise TeachingSessionError(f"{label} must be a JSON-safe non-negative exact integer")
    return value


def _version(value: object) -> int:
    if type(value) is not int or value != TEACHING_SESSION_VERSION:
        raise TeachingSessionError(f"unsupported teaching session version: {value!r}")
    return value


def _digest_text(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise TeachingSessionError(f"{label} must be lowercase SHA-256 hex")
    return value


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise TeachingSessionError("teaching JSON integer exceeds exact wire bounds")
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise TeachingSessionError("invalid teaching JSON integer") from exc
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise TeachingSessionError("teaching JSON integer exceeds exact wire bounds")
    return parsed


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TeachingSessionError(f"duplicate teaching JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise TeachingSessionError(f"non-finite teaching JSON constant is not allowed: {value}")
