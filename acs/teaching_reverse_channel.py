"""Role-safe student pointer reverse channel for TeachingSession.

The reverse channel is presentation state only.  It never owns chess legality,
never turns hover/selection into a move, and never trusts browser-supplied
student identity or piece information.  The current piece (when any) is read
from the canonical chess Board at the current TeachingSession FEN.

D01/Windows rendering may bind ``apply_student_hover_action`` to mouse hover and
``apply_student_click_action`` to an explicit answer-selection click.  Both UI
adapters must still supply authenticated student identity out-of-band.  A click
never becomes a chess move here; the distinct ``student.move`` path remains the
only move-capable classroom action and is admitted only by canonical MOVE policy.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping

from .chesscore import Board
from .classroom_domain import ClassroomSnapshot
from .interaction_contracts import (
    ContractValidationError,
    StudentHoverEvent,
    StudentSelectionEvent,
)
from .squares import normalize_square, parse_square
from .teaching_session import (
    LessonSession,
    TeachingInputKind,
    TeachingSessionError,
    TeachingSessionPhase,
    TeachingSessionState,
    current_step,
    submit_selection,
    validate_lesson_session_scope,
)


STUDENT_HOVER_ACTION_ID = "student.hover"
STUDENT_CLICK_ACTION_ID = "student.click"
DEFAULT_POINTER_HISTORY_LIMIT = 20
MAX_POINTER_HISTORY_VIEW = 64


class TeachingReverseChannelError(ValueError):
    """Stable boundary error that does not expose internal state or paths."""


class StudentPointerKind(str, Enum):
    HOVER = "hover"
    SELECTION = "selection"


@dataclass(frozen=True, slots=True)
class StudentPointerView:
    """Data-minimized pointer event safe for the blind teacher UI."""

    kind: StudentPointerKind
    student_label: str
    square: str
    piece_symbol: str | None
    sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StudentPointerKind):
            raise TeachingReverseChannelError("student pointer kind is invalid")
        if type(self.student_label) is not str or not self.student_label.strip():
            raise TeachingReverseChannelError("student pointer label is invalid")
        if type(self.square) is not str or normalize_square(self.square) != self.square:
            raise TeachingReverseChannelError("student pointer square is invalid")
        if self.piece_symbol is not None and (
            type(self.piece_symbol) is not str
            or self.piece_symbol not in "PNBRQKpnbrqk"
        ):
            raise TeachingReverseChannelError("student pointer piece is invalid")
        if type(self.sequence) is not int or self.sequence <= 0:
            raise TeachingReverseChannelError("student pointer sequence is invalid")


def apply_student_hover_action(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
    payload: Mapping[str, object] | None,
    *,
    expected_revision: int,
    actor_student_id: str | None,
) -> TeachingSessionState:
    """Apply one untrusted UI hover payload using trusted actor context.

    The payload is intentionally closed-world and contains only ``square``.
    ``student_id`` and ``piece`` are rejected if supplied by the browser.
    """

    square = _square_from_payload(payload, "student hover")
    return record_student_hover(
        plan,
        state,
        classroom,
        actor_student_id=actor_student_id,
        square=square,
        expected_revision=expected_revision,
    )


def apply_student_click_action(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
    payload: Mapping[str, object] | None,
    *,
    expected_revision: int,
    actor_student_id: str | None,
) -> TeachingSessionState:
    """Map a sighted-student click to an explicit selection answer only.

    ``student.click`` is a physical input gesture, not a new chess command.  It
    is accepted only while the canonical current step has SELECTION input
    policy.  Locked/NONE and MOVE steps fail closed, so a one-square click can
    never be guessed into a chess move.  The canonical ``submit_selection``
    transaction remains the source of answer/session semantics.
    """

    square = _square_from_payload(payload, "student click")
    _validate_common(plan, state, classroom)
    student_id = _authorized_student(plan, classroom, actor_student_id)
    square = _canonical_square(square)
    step = current_step(plan, state)
    if step.policy.input_kind is not TeachingInputKind.SELECTION:
        raise TeachingReverseChannelError("student click is not an answer in the current teaching mode")

    # Capture only presentation metadata from the canonical position.  Legality
    # and Position mutation remain outside this reverse-channel adapter.
    try:
        board = Board(state.position_fen)
        piece = board.board[parse_square(square)]
    except (TypeError, ValueError) as exc:
        raise TeachingReverseChannelError("teaching position is unavailable") from exc

    before_fen = state.position_fen
    try:
        updated = submit_selection(
            plan,
            state,
            student_id,
            square,
            expected_revision,
        )
        history = updated.presentation.student_pointer_history
        if not history:
            raise TeachingReverseChannelError("student click selection history is unavailable")
        event = history[-1]
        if (
            type(event) is not StudentSelectionEvent
            or event.student_id != student_id
            or event.square != square
            or event.sequence != updated.revision
        ):
            raise TeachingReverseChannelError("student click selection history is inconsistent")
        enriched = StudentSelectionEvent(
            square=event.square,
            piece=piece,
            student_id=event.student_id,
            sequence=event.sequence,
        )
        presentation = replace(
            updated.presentation,
            student_pointer_history=history[:-1] + (enriched,),
        )
        updated = replace(updated, presentation=presentation)
    except TeachingReverseChannelError:
        raise
    except (ContractValidationError, TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingReverseChannelError("student click could not be applied") from exc

    if updated.position_fen != before_fen:
        raise TeachingReverseChannelError("student click violated selection-only semantics")
    return updated


def record_student_hover(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
    *,
    actor_student_id: str | None,
    square: str,
    expected_revision: int,
) -> TeachingSessionState:
    """Record a hover observation without changing Position or answer state."""

    _validate_common(plan, state, classroom)
    if state.phase is not TeachingSessionPhase.ACTIVE:
        raise TeachingReverseChannelError("student hover requires an active teaching session")
    if type(expected_revision) is not int or expected_revision < 0:
        raise TeachingReverseChannelError("expected teaching revision is invalid")
    if state.revision != expected_revision:
        raise TeachingReverseChannelError("stale teaching session revision")

    student_id = _authorized_student(plan, classroom, actor_student_id)
    square = _canonical_square(square)

    # Read only from canonical chess state.  The browser cannot assert which
    # piece is on the square, and no legality/move logic is duplicated here.
    try:
        board = Board(state.position_fen)
        piece = board.board[parse_square(square)]
    except (TypeError, ValueError) as exc:
        raise TeachingReverseChannelError("teaching position is unavailable") from exc

    event = StudentHoverEvent(
        square=square,
        piece=piece,
        student_id=student_id,
        sequence=state.revision + 1,
    )
    before_fen = state.position_fen
    before_response = state.last_response
    before_active_student = state.active_student_id
    try:
        presentation = replace(
            state.presentation,
            student_pointer_history=state.presentation.student_pointer_history + (event,),
        )
        updated = replace(
            state,
            presentation=presentation,
            revision=state.revision + 1,
        )
    except (ContractValidationError, TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingReverseChannelError("student hover could not be recorded") from exc

    # Defensive invariants: hover is observation only, not answer/selection/move.
    if (
        updated.position_fen != before_fen
        or updated.last_response != before_response
        or updated.active_student_id != before_active_student
        or updated.presentation.board_permission is not state.presentation.board_permission
        or updated.presentation.engine_visibility is not state.presentation.engine_visibility
    ):
        raise TeachingReverseChannelError("student hover violated presentation-only semantics")
    return updated


def project_teacher_pointer_history(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
    *,
    limit: int = DEFAULT_POINTER_HISTORY_LIMIT,
) -> tuple[StudentPointerView, ...]:
    """Return ordered, pseudonymized hover/selection history for the teacher."""

    _validate_common(plan, state, classroom)
    if type(limit) is not int or not 1 <= limit <= MAX_POINTER_HISTORY_VIEW:
        raise TeachingReverseChannelError("pointer history limit is invalid")

    students = {
        item.student_id: item
        for item in classroom.students
        if not item.deleted
    }
    projected: list[StudentPointerView] = []
    previous_sequence = 0
    for event in state.presentation.student_pointer_history:
        if type(event) not in {StudentHoverEvent, StudentSelectionEvent}:
            raise TeachingReverseChannelError("pointer history contains an unsupported event")
        if (
            type(event.student_id) is not str
            or event.student_id not in plan.student_ids
            or event.student_id not in students
        ):
            raise TeachingReverseChannelError("pointer history contains an unavailable student")
        if type(event.sequence) is not int or event.sequence <= previous_sequence:
            raise TeachingReverseChannelError("pointer history sequence is invalid")
        previous_sequence = event.sequence
        square = _canonical_square(event.square)
        piece = event.piece
        if piece is not None and (type(piece) is not str or piece not in "PNBRQKpnbrqk"):
            raise TeachingReverseChannelError("pointer history piece is invalid")
        projected.append(
            StudentPointerView(
                kind=(
                    StudentPointerKind.HOVER
                    if type(event) is StudentHoverEvent
                    else StudentPointerKind.SELECTION
                ),
                student_label=students[event.student_id].pseudonym,
                square=square,
                piece_symbol=piece,
                sequence=event.sequence,
            )
        )
    return tuple(projected[-limit:])


def pointer_history_to_payload(
    items: tuple[StudentPointerView, ...],
) -> list[dict[str, object]]:
    """Serialize the already-minimized teacher history as a closed-world list."""

    if type(items) is not tuple or any(type(item) is not StudentPointerView for item in items):
        raise TeachingReverseChannelError("pointer history view is invalid")
    return [
        {
            "kind": item.kind.value,
            "student_label": item.student_label,
            "square": item.square,
            "piece_symbol": item.piece_symbol,
            "sequence": item.sequence,
        }
        for item in items
    ]


def accessible_student_pointer_summary(
    item: StudentPointerView,
    *,
    language: str = "uk",
) -> str:
    """Concise one-event announcement for NVDA; no live-region policy is owned here."""

    if type(item) is not StudentPointerView:
        raise TeachingReverseChannelError("student pointer view is invalid")
    if language not in {"uk", "en"}:
        raise TeachingReverseChannelError("unsupported student pointer language")
    piece = _PIECE_LABELS[language].get(item.piece_symbol) if item.piece_symbol else None
    if language == "uk":
        verb = "показує" if item.kind is StudentPointerKind.HOVER else "вибрав"
        suffix = f", {piece}" if piece else ""
        return f"Учень {item.student_label} {verb}: {item.square}{suffix}."
    verb = "points to" if item.kind is StudentPointerKind.HOVER else "selected"
    suffix = f", {piece}" if piece else ""
    return f"Student {item.student_label} {verb}: {item.square}{suffix}."


def _square_from_payload(
    payload: Mapping[str, object] | None,
    label: str,
) -> str:
    if payload is None or not isinstance(payload, Mapping):
        raise TeachingReverseChannelError(f"{label} payload must be an object")
    if any(type(key) is not str for key in payload) or set(payload) != {"square"}:
        raise TeachingReverseChannelError(f"{label} payload shape is invalid")
    square = payload["square"]
    if type(square) is not str or square != square.strip() or len(square) != 2:
        raise TeachingReverseChannelError(f"{label} square is invalid")
    return square


def _validate_common(
    plan: LessonSession,
    state: TeachingSessionState,
    classroom: ClassroomSnapshot,
) -> None:
    if type(plan) is not LessonSession or type(state) is not TeachingSessionState:
        raise TeachingReverseChannelError("teaching session is unavailable")
    if type(classroom) is not ClassroomSnapshot:
        raise TeachingReverseChannelError("classroom context is unavailable")
    try:
        validate_lesson_session_scope(plan, classroom)
        current_step(plan, state)
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingReverseChannelError("teaching session cannot be used safely") from exc


def _authorized_student(
    plan: LessonSession,
    classroom: ClassroomSnapshot,
    student_id: str | None,
) -> str:
    if type(student_id) is not str or student_id not in plan.student_ids:
        raise TeachingReverseChannelError("student is not authorized for this lesson")
    if not any(item.student_id == student_id and not item.deleted for item in classroom.students):
        raise TeachingReverseChannelError("student is not authorized for this lesson")
    return student_id


def _canonical_square(value: object) -> str:
    if type(value) is not str or value != value.strip():
        raise TeachingReverseChannelError("student pointer square is invalid")
    try:
        square = normalize_square(value)
    except ValueError as exc:
        raise TeachingReverseChannelError("student pointer square is invalid") from exc
    if square != value:
        raise TeachingReverseChannelError("student pointer square must be canonical lowercase algebraic text")
    return square


_PIECE_LABELS = {
    "uk": {
        "P": "білий пішак",
        "N": "білий кінь",
        "B": "білий слон",
        "R": "біла тура",
        "Q": "білий ферзь",
        "K": "білий король",
        "p": "чорний пішак",
        "n": "чорний кінь",
        "b": "чорний слон",
        "r": "чорна тура",
        "q": "чорний ферзь",
        "k": "чорний король",
    },
    "en": {
        "P": "white pawn",
        "N": "white knight",
        "B": "white bishop",
        "R": "white rook",
        "Q": "white queen",
        "K": "white king",
        "p": "black pawn",
        "n": "black knight",
        "b": "black bishop",
        "r": "black rook",
        "q": "black queen",
        "k": "black king",
    },
}
