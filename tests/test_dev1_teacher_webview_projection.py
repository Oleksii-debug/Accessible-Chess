import unittest

from acs.teacher_presentation import (
    BoardOrientation,
    TeacherPresentationState,
)
from acs.teacher_webview_projection import TeacherWebViewProjection


class TeacherWebViewProjectionTests(unittest.TestCase):
    def make_projection(self, state=None):
        calls = []
        canonical = dict(
            state
            or {
                "pointer_square": "f3",
                "highlights": ({"square": "c7", "purpose": "target"},),
                "arrows": (
                    {
                        "start_square": "a1",
                        "end_square": "h8",
                        "purpose": "custom",
                    },
                ),
                "coordinates_visible": True,
                "board_permission": "select_only",
                "engine_visibility": "hidden",
            }
        )

        def dispatch(action_id, payload):
            calls.append((action_id, dict(payload)))
            if action_id == "teacher.pointer_input":
                canonical["pointer_square"] = payload["square"]
            return {"ok": True}

        teacher = TeacherPresentationState(dispatch, lambda: canonical)
        return TeacherWebViewProjection(teacher), teacher, canonical, calls

    def test_snapshot_projects_visual_and_accessible_state(self):
        projection, _, _, _ = self.make_projection()
        snapshot = projection.snapshot()
        self.assertEqual(snapshot["pointer"]["square"], "f3")
        self.assertEqual(snapshot["highlights"][0]["square"], "c7")
        self.assertEqual(snapshot["arrows"][0]["start_square"], "a1")
        self.assertIn("Вказівник f3", snapshot["accessible_summary"])

    def test_white_orientation_maps_a1_to_bottom_left(self):
        projection, _, canonical, _ = self.make_projection()
        canonical["pointer_square"] = "a1"
        cell = projection.snapshot()["pointer"]["cell"]
        self.assertEqual(cell, {"row": 8, "column": 1})

    def test_black_orientation_maps_a1_to_top_right(self):
        projection, teacher, canonical, _ = self.make_projection()
        teacher.set_orientation(BoardOrientation.BLACK)
        canonical["pointer_square"] = "a1"
        cell = projection.snapshot()["pointer"]["cell"]
        self.assertEqual(cell, {"row": 1, "column": 8})

    def test_pointer_text_dispatches_immediately_and_clears_editor(self):
        projection, teacher, _, calls = self.make_projection()
        event = projection.type_pointer_text("c7")
        self.assertEqual(calls[-1], ("teacher.pointer_input", {"square": "c7"}))
        self.assertEqual(event.payload["square"], "c7")
        self.assertTrue(event.payload["clear_editor"])
        self.assertEqual(teacher.pointer_input_buffer, "")

    def test_pointer_text_rejects_partial_coordinate(self):
        projection, _, _, calls = self.make_projection()
        with self.assertRaises(ValueError):
            projection.type_pointer_text("f")
        self.assertEqual(calls, [])

    def test_hover_never_live_announces(self):
        projection, _, _, _ = self.make_projection()
        event = projection.record_student_event("hover", "e4", piece_name="pawn")
        self.assertEqual(event.payload["announcement"], "")
        self.assertFalse(event.payload["live_region"])

    def test_selection_announces_once(self):
        projection, _, _, _ = self.make_projection()
        event = projection.record_student_event("select", "e4", piece_name="pawn")
        self.assertIn("e4", event.payload["announcement"])
        self.assertTrue(event.payload["live_region"])

    def test_hover_and_selection_stay_distinct(self):
        projection, _, _, _ = self.make_projection()
        hover = projection.record_student_event("hover", "d5")
        select = projection.record_student_event("select", "d5")
        self.assertEqual(hover.payload["event_kind"], "hover")
        self.assertEqual(select.payload["event_kind"], "select")

    def test_snapshot_rejects_chess_state_leak(self):
        projection, _, _, _ = self.make_projection({"fen": "secret"})
        with self.assertRaises(ValueError):
            projection.snapshot()

    def test_snapshot_rejects_bad_permission(self):
        projection, _, _, _ = self.make_projection({"board_permission": "move_anywhere"})
        with self.assertRaises(ValueError):
            projection.snapshot()

    def test_snapshot_rejects_bad_engine_visibility(self):
        projection, _, _, _ = self.make_projection({"engine_visibility": "everyone"})
        with self.assertRaises(ValueError):
            projection.snapshot()

    def test_snapshot_rejects_non_boolean_coordinates(self):
        projection, _, _, _ = self.make_projection({"coordinates_visible": "yes"})
        with self.assertRaises(ValueError):
            projection.snapshot()

    def test_snapshot_rejects_malformed_highlight(self):
        projection, _, _, _ = self.make_projection({"highlights": ("e4",)})
        with self.assertRaises(ValueError):
            projection.snapshot()

    def test_snapshot_rejects_zero_length_arrow(self):
        projection, _, _, _ = self.make_projection(
            {
                "arrows": (
                    {
                        "start_square": "e4",
                        "end_square": "e4",
                        "purpose": "custom",
                    },
                )
            }
        )
        with self.assertRaises(ValueError):
            projection.snapshot()

    def test_toggle_orientation_returns_render_snapshot(self):
        projection, teacher, _, _ = self.make_projection()
        event = projection.toggle_orientation()
        self.assertEqual(teacher.orientation, BoardOrientation.BLACK)
        self.assertEqual(event.kind, "render")
        self.assertEqual(event.payload["orientation"], "black")
        self.assertEqual(event.payload["snapshot"]["board"]["orientation"], "black")

    def test_feedback_history_is_bounded_by_teacher_controller(self):
        calls = []
        canonical = {}
        teacher = TeacherPresentationState(
            lambda action_id, payload: calls.append((action_id, dict(payload))),
            lambda: canonical,
            feedback_limit=2,
        )
        projection = TeacherWebViewProjection(teacher)
        projection.record_student_event("hover", "a1")
        projection.record_student_event("hover", "b1")
        projection.record_student_event("select", "c1")
        self.assertEqual(len(teacher.feedback_events(limit=10)), 2)

    def test_english_summary_is_supported(self):
        projection, _, _, _ = self.make_projection()
        snapshot = projection.snapshot(language="en")
        self.assertIn("Pointer f3", snapshot["accessible_summary"])

    def test_unknown_student_event_kind_is_rejected(self):
        projection, _, _, _ = self.make_projection()
        with self.assertRaises(ValueError):
            projection.record_student_event("move", "e4")

    def test_visual_projection_does_not_dispatch(self):
        projection, _, _, calls = self.make_projection()
        projection.snapshot()
        self.assertEqual(calls, [])

    def test_snapshot_is_json_friendly_primitives(self):
        projection, _, _, _ = self.make_projection()
        snapshot = projection.snapshot()
        self.assertIsInstance(snapshot["board"], dict)
        self.assertIsInstance(snapshot["highlights"], tuple)
        self.assertIsInstance(snapshot["arrows"], tuple)

    def test_snapshot_reads_canonical_provider_once(self):
        calls = []
        states = iter((
            {"pointer_square": "f3"},
            {"pointer_square": "c7"},
        ))

        def provider():
            calls.append("read")
            return next(states)

        teacher = TeacherPresentationState(lambda action_id, payload: None, provider)
        projection = TeacherWebViewProjection(teacher)
        snapshot = projection.snapshot()
        self.assertEqual(calls, ["read"])
        self.assertEqual(snapshot["pointer"]["square"], "f3")
        self.assertIn("f3", snapshot["accessible_summary"])
        self.assertNotIn("c7", snapshot["accessible_summary"])


if __name__ == "__main__":
    unittest.main()
