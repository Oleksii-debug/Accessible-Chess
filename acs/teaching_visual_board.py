"""Teacher visual-board presentation controls over canonical TeachingSession state.

This module owns no renderer and no chess rules.  D01 can bind these explicit
presentation actions to Windows/WebView controls.  Legal-move highlights are
computed by the canonical chess ``Board`` and written only to PresentationState.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from .chesscore import Board
from .interaction_contracts import ContractValidationError, SquareHighlight
from .squares import normalize_square, parse_square, square_name
from .teaching_session import (
    LessonSession,
    TeachingSessionError,
    TeachingSessionPhase,
    TeachingSessionState,
    current_step,
)


SET_COORDINATES_ACTION_ID = "teacher.set_coordinates"
HIGHLIGHT_LEGAL_MOVES_ACTION_ID = "teacher.highlight_legal_moves"
CLEAR_LEGAL_MOVES_ACTION_ID = "teacher.clear_legal_moves"
LEGAL_MOVE_HIGHLIGHT_PURPOSE = "legal_move"

TEACHER_VISUAL_BOARD_ACTIONS = frozenset(
    {
        SET_COORDINATES_ACTION_ID,
        HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
        CLEAR_LEGAL_MOVES_ACTION_ID,
    }
)


class TeachingVisualBoardError(ValueError):
    """Stable, concise failure at the teacher presentation boundary."""


def apply_teacher_visual_board_action(
    plan: LessonSession,
    state: TeachingSessionState,
    action_id: str,
    payload: Mapping[str, object] | None,
    *,
    expected_revision: int,
    actor_student_id: str | None = None,
) -> TeachingSessionState:
    """Map one closed-world teacher action into presentation-only session state.

    A student-authenticated context can never acquire teacher presentation
    authority.  No action in this function may mutate ``position_fen``.
    """

    _preflight_teacher(plan, state, expected_revision, actor_student_id)
    if type(action_id) is not str or action_id not in TEACHER_VISUAL_BOARD_ACTIONS:
        raise TeachingVisualBoardError("unsupported teacher visual-board action")
    if payload is None:
        data: Mapping[str, object] = {}
    elif isinstance(payload, Mapping) and all(type(key) is str for key in payload):
        data = payload
    else:
        raise TeachingVisualBoardError("teacher visual-board payload must be an object")

    if action_id == SET_COORDINATES_ACTION_ID:
        _exact_keys(data, {"visible"})
        visible = data["visible"]
        if type(visible) is not bool:
            raise TeachingVisualBoardError("coordinate visibility must be boolean")
        return _presentation_replace(
            state,
            replace(state.presentation, coordinate_labels_visible=visible),
        )

    if action_id == CLEAR_LEGAL_MOVES_ACTION_ID:
        _exact_keys(data, set())
        retained = tuple(
            item
            for item in state.presentation.highlights
            if item.purpose != LEGAL_MOVE_HIGHLIGHT_PURPOSE
        )
        return _presentation_replace(
            state,
            replace(state.presentation, highlights=retained),
        )

    _exact_keys(data, {"square"})
    source = _canonical_square(data["square"])
    try:
        board = Board(state.position_fen)
        source_index = parse_square(source)
        piece = board.board[source_index]
        target_indexes = sorted(
            {
                move.to
                for move in board.legal_moves()
                if move.frm == source_index
            }
        )
        legal_targets = tuple(square_name(index) for index in target_indexes)
    except (TypeError, ValueError) as exc:
        raise TeachingVisualBoardError("teaching position is unavailable") from exc
    if piece is None:
        raise TeachingVisualBoardError("legal-move highlight requires an occupied square")

    # Replace only the semantic legal-move layer.  Manual teacher highlights,
    # arrows, pointer, hover history, permissions and engine policy survive.
    retained = tuple(
        item
        for item in state.presentation.highlights
        if item.purpose != LEGAL_MOVE_HIGHLIGHT_PURPOSE
    )
    try:
        generated = tuple(
            SquareHighlight(target, LEGAL_MOVE_HIGHLIGHT_PURPOSE)
            for target in legal_targets
        )
        presentation = replace(
            state.presentation,
            highlights=retained + generated,
        )
    except ContractValidationError as exc:
        raise TeachingVisualBoardError("legal-move highlights exceed presentation limits") from exc
    return _presentation_replace(state, presentation)


def legal_move_highlight_squares(state: TeachingSessionState) -> tuple[str, ...]:
    """Return the current renderer-neutral legal-move overlay in stable board order."""

    if type(state) is not TeachingSessionState:
        raise TeachingVisualBoardError("teaching state is unavailable")
    return tuple(
        item.square
        for item in state.presentation.highlights
        if item.purpose == LEGAL_MOVE_HIGHLIGHT_PURPOSE
    )


def _preflight_teacher(
    plan: LessonSession,
    state: TeachingSessionState,
    expected_revision: int,
    actor_student_id: str | None,
) -> None:
    if type(plan) is not LessonSession or type(state) is not TeachingSessionState:
        raise TeachingVisualBoardError("teaching session is unavailable")
    if actor_student_id is not None:
        raise TeachingVisualBoardError("teacher visual-board action must not carry student identity")
    if type(expected_revision) is not int or expected_revision < 0:
        raise TeachingVisualBoardError("expected teaching revision is invalid")
    try:
        current_step(plan, state)
    except (TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingVisualBoardError("teaching session cannot be used safely") from exc
    if state.revision != expected_revision:
        raise TeachingVisualBoardError("stale teaching session revision")
    if state.phase is TeachingSessionPhase.COMPLETED:
        raise TeachingVisualBoardError("completed session cannot change visual-board presentation")


def _presentation_replace(state: TeachingSessionState, presentation) -> TeachingSessionState:
    before_fen = state.position_fen
    before_response = state.last_response
    before_active_student = state.active_student_id
    try:
        updated = replace(
            state,
            presentation=presentation,
            revision=state.revision + 1,
        )
    except (ContractValidationError, TeachingSessionError, TypeError, ValueError) as exc:
        raise TeachingVisualBoardError("teacher visual-board action could not be applied") from exc
    if (
        updated.position_fen != before_fen
        or updated.last_response != before_response
        or updated.active_student_id != before_active_student
    ):
        raise TeachingVisualBoardError("visual-board presentation mutated teaching chess state")
    return updated


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise TeachingVisualBoardError("teacher visual-board payload shape is invalid")


def _canonical_square(value: object) -> str:
    if type(value) is not str or value != value.strip():
        raise TeachingVisualBoardError("visual-board square is invalid")
    try:
        square = normalize_square(value)
    except ValueError as exc:
        raise TeachingVisualBoardError("visual-board square is invalid") from exc
    if square != value:
        raise TeachingVisualBoardError("visual-board square must be canonical lowercase algebraic text")
    return square
