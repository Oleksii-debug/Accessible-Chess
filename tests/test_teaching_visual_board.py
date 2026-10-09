from __future__ import annotations

from dataclasses import replace
import unittest

from acs.chesscore import Board
from acs.interaction_contracts import (
    EngineVisibilityPolicy,
    SquareHighlight,
    TeacherPointerState,
    VisualArrow,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    advance_step,
    default_policy,
    pause_session,
    start_session,
)
from acs.teaching_visual_board import (
    CLEAR_LEGAL_MOVES_ACTION_ID,
    HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
    LEGAL_MOVE_HIGHLIGHT_PURPOSE,
    SET_COORDINATES_ACTION_ID,
    TeachingVisualBoardError,
    apply_teacher_visual_board_action,
    legal_move_highlight_squares,
)


class TeachingVisualBoardTests(unittest.TestCase):
    def plan(
        self,
        *,
        activity: TeachingActivity = TeachingActivity.TEACHER_EXPLAINS,
        fen: str | None = None,
    ) -> LessonSession:
        source = (
            TeachingPositionSource(PositionSourceKind.START)
            if fen is None
            else TeachingPositionSource(PositionSourceKind.FEN, fen=fen)
        )
        return LessonSession(
            "session-visual",
            "lesson-visual",
            source,
            (TeachingStep("step-1", activity, "Explain", default_policy(activity)),),
            ("student-1",),
        )

    def test_initial_knight_legal_highlight_uses_canonical_legality_only(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        after = apply_teacher_visual_board_action(
            plan,
            before,
            HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
            {"square": "g1"},
            expected_revision=0,
        )
        self.assertEqual(legal_move_highlight_squares(after), ("f3", "h3"))
        self.assertEqual(after.position_fen, before.position_fen)
        self.assertIsNone(after.last_response)
        self.assertIsNone(after.active_student_id)
        self.assertEqual(after.revision, 1)

    def test_pinned_piece_highlight_filters_pseudo_moves_through_board_legal_moves(self) -> None:
        # White rook e2 is pinned to king e1 by black rook e8. Horizontal rook
        # pseudo-moves are illegal; canonical Board.legal_moves filters them.
        fen = "4r2k/8/8/8/8/8/4R3/4K3 w - - 0 1"
        plan = self.plan(fen=fen)
        before = start_session(plan)
        after = apply_teacher_visual_board_action(
            plan,
            before,
            HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
            {"square": "e2"},
            expected_revision=0,
        )
        targets = legal_move_highlight_squares(after)
        self.assertTrue(targets)
        self.assertTrue(all(target[0] == "e" for target in targets))
        self.assertNotIn("d2", targets)
        self.assertNotIn("f2", targets)
        self.assertEqual(after.position_fen, before.position_fen)

    def test_wrong_side_piece_is_not_given_fake_legal_moves(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        after = apply_teacher_visual_board_action(
            plan,
            before,
            HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
            {"square": "g8"},
            expected_revision=0,
        )
        self.assertEqual(legal_move_highlight_squares(after), ())
        self.assertEqual(after.position_fen, Board.START)

    def test_empty_square_is_explicit_error_and_atomic(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        with self.assertRaisesRegex(TeachingVisualBoardError, "occupied"):
            apply_teacher_visual_board_action(
                plan,
                before,
                HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
                {"square": "e4"},
                expected_revision=0,
            )
        self.assertEqual(before.presentation.highlights, ())
        self.assertEqual(before.position_fen, Board.START)
        self.assertEqual(before.revision, 0)

    def test_legal_overlay_replaces_only_previous_legal_layer(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        state = replace(
            state,
            presentation=replace(
                state.presentation,
                pointer=TeacherPointerState("e4"),
                highlights=(SquareHighlight("d4", "teacher"),),
                arrows=(VisualArrow("e2", "e4", "plan"),),
                engine_visibility=EngineVisibilityPolicy.VISIBLE_TO_TEACHER,
            ),
        )
        first = apply_teacher_visual_board_action(
            plan,
            state,
            HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
            {"square": "b1"},
            expected_revision=0,
        )
        second = apply_teacher_visual_board_action(
            plan,
            first,
            HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
            {"square": "g1"},
            expected_revision=1,
        )
        self.assertIn(SquareHighlight("d4", "teacher"), second.presentation.highlights)
        legal = tuple(
            item.square
            for item in second.presentation.highlights
            if item.purpose == LEGAL_MOVE_HIGHLIGHT_PURPOSE
        )
        self.assertEqual(legal, ("f3", "h3"))
        self.assertEqual(second.presentation.pointer.square, "e4")
        self.assertEqual(second.presentation.arrows, (VisualArrow("e2", "e4", "plan"),))
        self.assertIs(second.presentation.engine_visibility, EngineVisibilityPolicy.VISIBLE_TO_TEACHER)
        self.assertEqual(second.position_fen, state.position_fen)

    def test_clear_legal_overlay_preserves_manual_annotations(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        state = replace(
            state,
            presentation=replace(
                state.presentation,
                highlights=(
                    SquareHighlight("d4", "teacher"),
                    SquareHighlight("f3", LEGAL_MOVE_HIGHLIGHT_PURPOSE),
                ),
            ),
        )
        after = apply_teacher_visual_board_action(
            plan,
            state,
            CLEAR_LEGAL_MOVES_ACTION_ID,
            {},
            expected_revision=0,
        )
        self.assertEqual(after.presentation.highlights, (SquareHighlight("d4", "teacher"),))
        self.assertEqual(after.position_fen, state.position_fen)

    def test_coordinate_toggle_is_boolean_presentation_state_only(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        hidden = apply_teacher_visual_board_action(
            plan,
            before,
            SET_COORDINATES_ACTION_ID,
            {"visible": False},
            expected_revision=0,
        )
        shown = apply_teacher_visual_board_action(
            plan,
            hidden,
            SET_COORDINATES_ACTION_ID,
            {"visible": True},
            expected_revision=1,
        )
        self.assertFalse(hidden.presentation.coordinate_labels_visible)
        self.assertTrue(shown.presentation.coordinate_labels_visible)
        self.assertEqual(shown.position_fen, before.position_fen)
        self.assertEqual(shown.revision, 2)

    def test_coordinate_toggle_rejects_scalar_coercion_atomically(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        for value in (0, 1, "false", None):
            with self.subTest(value=value):
                with self.assertRaises(TeachingVisualBoardError):
                    apply_teacher_visual_board_action(
                        plan,
                        before,
                        SET_COORDINATES_ACTION_ID,
                        {"visible": value},
                        expected_revision=0,
                    )
        self.assertTrue(before.presentation.coordinate_labels_visible)
        self.assertEqual(before.revision, 0)

    def test_browser_payloads_are_closed_world_and_square_is_canonical(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        bad = (
            (HIGHLIGHT_LEGAL_MOVES_ACTION_ID, {"square": "G1"}),
            (HIGHLIGHT_LEGAL_MOVES_ACTION_ID, {"square": "g1", "move": "Nf3"}),
            (SET_COORDINATES_ACTION_ID, {"visible": True, "student_id": "student-1"}),
            (CLEAR_LEGAL_MOVES_ACTION_ID, {"all": True}),
        )
        for action, payload in bad:
            with self.subTest(action=action, payload=payload):
                with self.assertRaises(TeachingVisualBoardError):
                    apply_teacher_visual_board_action(
                        plan,
                        before,
                        action,
                        payload,
                        expected_revision=0,
                    )
        self.assertEqual(before.position_fen, Board.START)
        self.assertEqual(before.revision, 0)

    def test_student_identity_cannot_gain_teacher_visual_authority(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        for action, payload in (
            (SET_COORDINATES_ACTION_ID, {"visible": False}),
            (HIGHLIGHT_LEGAL_MOVES_ACTION_ID, {"square": "g1"}),
            (CLEAR_LEGAL_MOVES_ACTION_ID, {}),
        ):
            with self.subTest(action=action):
                with self.assertRaisesRegex(TeachingVisualBoardError, "student identity"):
                    apply_teacher_visual_board_action(
                        plan,
                        before,
                        action,
                        payload,
                        expected_revision=0,
                        actor_student_id="student-1",
                    )

    def test_stale_revision_is_atomic(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        with self.assertRaisesRegex(TeachingVisualBoardError, "stale"):
            apply_teacher_visual_board_action(
                plan,
                before,
                HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
                {"square": "g1"},
                expected_revision=1,
            )
        self.assertEqual(before.presentation.highlights, ())
        self.assertEqual(before.revision, 0)

    def test_paused_session_allows_teacher_presentation_without_unlocking_student_board(self) -> None:
        plan = self.plan()
        active = start_session(plan)
        paused = pause_session(plan, active, 0)
        updated = apply_teacher_visual_board_action(
            plan,
            paused,
            HIGHLIGHT_LEGAL_MOVES_ACTION_ID,
            {"square": "g1"},
            expected_revision=1,
        )
        self.assertEqual(legal_move_highlight_squares(updated), ("f3", "h3"))
        self.assertEqual(updated.presentation.board_permission, paused.presentation.board_permission)
        self.assertEqual(updated.position_fen, paused.position_fen)

    def test_completed_session_rejects_visual_state_changes(self) -> None:
        plan = self.plan()
        active = start_session(plan)
        completed = advance_step(plan, active, 0)
        for action, payload in (
            (SET_COORDINATES_ACTION_ID, {"visible": False}),
            (HIGHLIGHT_LEGAL_MOVES_ACTION_ID, {"square": "g1"}),
            (CLEAR_LEGAL_MOVES_ACTION_ID, {}),
        ):
            with self.subTest(action=action):
                with self.assertRaisesRegex(TeachingVisualBoardError, "completed"):
                    apply_teacher_visual_board_action(
                        plan,
                        completed,
                        action,
                        payload,
                        expected_revision=1,
                    )
        self.assertEqual(completed.position_fen, Board.START)


if __name__ == "__main__":
    unittest.main()
