import unittest

from acs.chesscore import Board
from acs.interaction_contracts import (
    BoardPermissionState,
    EngineVisibilityPolicy,
    PresentationState,
    SquareHighlight,
    TeacherPointerState,
    VisualArrow,
)
from acs.teacher_webview_projection import TeacherWebViewProjection
from acs.teaching_session import TeachingSessionPhase, TeachingSessionState


class TeacherCanonicalWebViewCompositionTests(unittest.TestCase):
    @staticmethod
    def canonical_state(*, coordinates_visible=False):
        return TeachingSessionState(
            session_id="session-1",
            plan_digest="0" * 64,
            phase=TeachingSessionPhase.ACTIVE,
            step_index=0,
            position_fen=Board.START,
            presentation=PresentationState(
                pointer=TeacherPointerState("f3"),
                highlights=(SquareHighlight("c7", "target"),),
                arrows=(VisualArrow("a1", "h8", "idea"),),
                coordinate_labels_visible=coordinates_visible,
                board_permission=BoardPermissionState.SELECT_ONLY,
                engine_visibility=EngineVisibilityPolicy.HIDDEN,
            ),
            remaining_seconds=None,
        )

    def test_one_canonical_revision_drives_pieces_and_overlays(self):
        reads = []
        state = self.canonical_state(coordinates_visible=False)

        def state_provider():
            reads.append("read")
            return state

        projection = TeacherWebViewProjection.from_teaching_session(
            lambda action_id, payload: None,
            state_provider,
        )
        snapshot = projection.snapshot(language="en")
        self.assertEqual(["read"], reads)
        self.assertEqual(32, len(snapshot["pieces"]))
        self.assertEqual("f3", snapshot["pointer"]["square"])
        self.assertEqual("c7", snapshot["highlights"][0]["square"])
        self.assertEqual("a1", snapshot["arrows"][0]["start_square"])
        self.assertFalse(snapshot["board"]["coordinates_visible"])
        self.assertEqual("select_only", snapshot["board"]["permission"])
        self.assertNotIn("rnbqkbnr", repr(snapshot).lower())

    def test_pointer_editor_dispatch_stays_separate_from_chess_move(self):
        calls = []
        projection = TeacherWebViewProjection.from_teaching_session(
            lambda action_id, payload: calls.append((action_id, dict(payload))),
            lambda: self.canonical_state(),
        )
        event = projection.type_pointer_text("e4")
        self.assertEqual(
            [("teacher.pointer_input", {"square": "e4"})],
            calls,
        )
        self.assertEqual("pointer-input", event.kind)
        self.assertNotEqual("board.input", calls[0][0])
        self.assertNotEqual("student.move", calls[0][0])

    def test_provider_type_is_fail_closed(self):
        projection = TeacherWebViewProjection.from_teaching_session(
            lambda action_id, payload: None,
            lambda: {"position_fen": Board.START},
        )
        with self.assertRaises(TypeError):
            projection.snapshot()

    def test_legacy_fen_provider_and_canonical_session_provider_are_mutually_exclusive(self):
        projection = TeacherWebViewProjection.from_teaching_session(
            lambda action_id, payload: None,
            lambda: self.canonical_state(),
        )
        with self.assertRaises(ValueError):
            TeacherWebViewProjection(
                projection._teacher,
                position_fen_provider=lambda: Board.START,
                teaching_state_provider=lambda: self.canonical_state(),
            )


if __name__ == "__main__":
    unittest.main()
