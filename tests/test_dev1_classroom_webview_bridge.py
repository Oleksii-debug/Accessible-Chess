from __future__ import annotations

import unittest

from acs.classroom_presentation import (
    ManagementListPresenter,
    ManagementRecord,
    RecordKind,
    RemoteLessonPresenter,
)
from acs.classroom_webview_bridge import ClassroomWebViewBridge
from acs.classroom_webview_projection import ClassroomWebViewProjection
from acs.full_product_ui_shell import UILanguage


class ClassroomWebViewBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]):
            self.calls.append((action_id, dict(payload)))
            return {"secret": "must-not-cross-browser-boundary"}

        management = {
            kind: ManagementListPresenter(kind, language=UILanguage.EN)
            for kind in (
                RecordKind.CLASS,
                RecordKind.STUDENT,
                RecordKind.LESSON,
                RecordKind.ASSIGNMENT,
            )
        }
        management[RecordKind.CLASS].replace(
            (ManagementRecord("c1", RecordKind.CLASS, "Class one"),)
        )
        management[RecordKind.STUDENT].replace(
            (ManagementRecord("s1", RecordKind.STUDENT, "Student one"),)
        )
        management[RecordKind.LESSON].replace(
            (ManagementRecord("l1", RecordKind.LESSON, "Lesson one"),)
        )
        management[RecordKind.ASSIGNMENT].replace(
            (ManagementRecord("a1", RecordKind.ASSIGNMENT, "Assignment one"),)
        )
        state = {
            "status": "connected",
            "session_id": "private-session-id",
            "teacher_label": "Teacher",
            "student_label": "Student one",
            "last_sequence": 4,
        }
        remote = RemoteLessonPresenter(lambda: dict(state), dispatch, language=UILanguage.EN)
        projection = ClassroomWebViewProjection(
            management,
            remote,
            dispatch,
            language=UILanguage.EN,
        )
        self.bridge = ClassroomWebViewBridge(projection)

    def test_exact_management_commands_route_without_generic_action_dispatch(self) -> None:
        selected = self.bridge.dispatch(
            "management.select", {"kind": "class", "record_id": "c1"}
        )
        self.assertEqual("selection", selected.kind)
        self.assertEqual([], self.calls)

        opened = self.bridge.dispatch("management.open", {"kind": "class"})
        self.assertEqual("delegated", opened.kind)
        self.assertEqual([("classes.open", {"record_id": "c1"})], self.calls)
        self.assertNotIn("must-not-cross-browser-boundary", repr(opened.payload))

    def test_remote_commands_keep_private_session_inside_presenter(self) -> None:
        event = self.bridge.dispatch("remote.reconnect", {})
        self.assertEqual("remote-action", event.kind)
        self.assertEqual(
            [("remote.reconnect", {"session_id": "private-session-id"})], self.calls
        )
        self.assertNotIn("private-session-id", repr(event.payload))

    def test_connect_requires_exact_bounded_lesson_identifier(self) -> None:
        good = self.bridge.dispatch("remote.connect", {"lesson_id": "lesson-public"})
        self.assertEqual("remote-action", good.kind)
        self.assertEqual(("remote.connect", {"lesson_id": "lesson-public"}), self.calls[-1])
        before = list(self.calls)
        bad = self.bridge.dispatch("remote.connect", {"lesson_id": "x" * 257})
        self.assertEqual("error", bad.kind)
        self.assertEqual(before, self.calls)

    def test_unknown_command_and_extra_fields_fail_closed_without_echo(self) -> None:
        for command, payload in (
            ("board.make_move e4 SECRET", {}),
            ("remote.leave", {"token": "SECRET"}),
            ("management.open", {"kind": "class", "path": "C:/private"}),
        ):
            with self.subTest(command=command):
                before = list(self.calls)
                event = self.bridge.dispatch(command, payload)
                self.assertEqual("error", event.kind)
                message = str(event.payload["message"])
                self.assertNotIn("SECRET", message)
                self.assertNotIn("C:/private", message)
                self.assertNotIn("board.make_move", message)
                self.assertEqual(before, self.calls)

    def test_scalar_payload_and_boolean_delta_are_rejected_without_mutation(self) -> None:
        scalar = self.bridge.dispatch("management.open", "class")  # type: ignore[arg-type]
        self.assertEqual("error", scalar.kind)
        boolean_delta = self.bridge.dispatch(
            "management.move", {"kind": "class", "delta": True}
        )
        self.assertEqual("error", boolean_delta.kind)
        self.assertEqual([], self.calls)

    def test_browser_bridge_does_not_offer_arbitrary_domain_dispatch(self) -> None:
        for command in ("pgn.open", "student.move", "teacher.pointer_input", "library.search"):
            event = self.bridge.dispatch(command, {})
            self.assertEqual("error", event.kind)
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()
