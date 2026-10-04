from __future__ import annotations

import unittest

from acs.full_product_ui_shell import UILanguage
from acs.teacher_presentation import TeacherPresentationState
from acs.teacher_webview_bridge import TeacherWebViewBridge
from acs.teacher_webview_projection import TeacherWebViewProjection


class TeacherWebViewBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []
        self.state = {
            "pointer_square": None,
            "highlights": (),
            "arrows": (),
            "coordinates_visible": True,
            "board_permission": "select_only",
            "engine_visibility": "hidden",
        }

        def dispatch(action_id, payload):
            self.calls.append((action_id, dict(payload)))
            if action_id == "teacher.pointer_input":
                self.state["pointer_square"] = payload["square"]
            return {"path": r"C:\\private\\lesson.sqlite"}

        teacher = TeacherPresentationState(dispatch, lambda: dict(self.state))
        self.bridge = TeacherWebViewBridge(
            TeacherWebViewProjection(teacher),
            language=UILanguage.EN,
        )

    def test_pointer_f3_dispatches_only_pointer_clears_and_restores_editor(self) -> None:
        event = self.bridge.dispatch("teacher.pointer_input", {"coordinate": "f3"})
        self.assertEqual([("teacher.pointer_input", {"square": "f3"})], self.calls)
        self.assertEqual("render-pointer", event.kind)
        self.assertEqual("f3", event.payload["snapshot"]["pointer"]["square"])
        self.assertTrue(event.payload["clear_editor"])
        self.assertEqual("teacher-pointer-input", event.payload["focus_target"])
        self.assertNotIn("private", repr(event).lower())

    def test_hover_and_selection_are_feedback_not_move_commands(self) -> None:
        hover = self.bridge.dispatch(
            "teacher.student_event",
            {"kind": "hover", "square": "e4", "piece_name": "pawn"},
        )
        selected = self.bridge.dispatch(
            "teacher.student_event",
            {"kind": "select", "square": "e4", "piece_name": "pawn"},
        )
        self.assertEqual("", hover.payload["announcement"])
        self.assertIn("e4", selected.payload["announcement"])
        self.assertEqual([], self.calls)
        self.assertNotIn("move", repr((hover, selected)).lower())

    def test_browser_cannot_supply_move_fen_student_identity_or_sequence(self) -> None:
        attempts = (
            ("teacher.pointer_input", {"coordinate": "f3", "fen": "secret"}),
            ("teacher.student_event", {"kind": "select", "square": "e4", "piece_name": "", "student_id": "secret"}),
            ("teacher.student_event", {"kind": "select", "square": "e4", "piece_name": "", "sequence": 4}),
            ("student.move", {"square": "e4"}),
            ("board.input", {"move": "e4"}),
        )
        for command, payload in attempts:
            with self.subTest(command=command, payload=payload):
                event = self.bridge.dispatch(command, payload)
                self.assertEqual("error", event.kind)
                self.assertNotIn("secret", repr(event).lower())
        self.assertEqual([], self.calls)

    def test_orientation_and_snapshot_are_bounded_presentation_events(self) -> None:
        before = self.bridge.dispatch("teacher.snapshot", {})
        turned = self.bridge.dispatch("teacher.orientation.toggle", {})
        self.assertEqual("white", before.payload["snapshot"]["board"]["orientation"])
        self.assertEqual("black", turned.payload["snapshot"]["board"]["orientation"])
        self.assertEqual("teacher-orientation-toggle", turned.payload["focus_target"])
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()
