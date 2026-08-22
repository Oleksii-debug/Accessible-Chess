from __future__ import annotations

import unittest

from acs.classroom_presentation import (
    ManagementListPresenter,
    ManagementRecord,
    RecordKind,
    RemoteLessonPresenter,
)
from acs.classroom_webview_projection import ClassroomWebViewProjection
from acs.full_product_ui_shell import UILanguage


class ClassroomWebViewProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]):
            self.calls.append((action_id, dict(payload)))
            return {"accepted": action_id}

        self.dispatch = dispatch
        self.remote_state: dict[str, object] = {
            "status": "connected",
            "session_id": "opaque-session-123",
            "teacher_label": "Coach",
            "student_label": "Student 7",
            "last_sequence": 12,
        }
        self.management = {
            RecordKind.CLASS: ManagementListPresenter(RecordKind.CLASS),
            RecordKind.STUDENT: ManagementListPresenter(RecordKind.STUDENT),
            RecordKind.LESSON: ManagementListPresenter(RecordKind.LESSON),
            RecordKind.ASSIGNMENT: ManagementListPresenter(RecordKind.ASSIGNMENT),
        }
        self.management[RecordKind.CLASS].replace(
            (
                ManagementRecord("class/private-alpha", RecordKind.CLASS, "Beginners", "Monday", "active"),
                ManagementRecord("class/private-beta", RecordKind.CLASS, "Advanced"),
            )
        )
        self.management[RecordKind.STUDENT].replace(
            (ManagementRecord("student/77", RecordKind.STUDENT, "Student 7", "pseudonym"),)
        )
        self.management[RecordKind.LESSON].replace(
            (ManagementRecord("lesson/9", RecordKind.LESSON, "Lesson 9"),)
        )
        self.management[RecordKind.ASSIGNMENT].replace(
            (ManagementRecord("assignment/3", RecordKind.ASSIGNMENT, "Homework 3"),)
        )
        self.remote = RemoteLessonPresenter(lambda: dict(self.remote_state), dispatch)
        self.projection = ClassroomWebViewProjection(
            self.management,
            self.remote,
            dispatch,
            language=UILanguage.EN,
        )

    def test_snapshot_exposes_all_management_surfaces_without_raw_dom_identity(self) -> None:
        snapshot = self.projection.snapshot()
        self.assertEqual("en", snapshot["document"]["lang"])
        sections = snapshot["management"]
        self.assertEqual(["class", "student", "lesson", "assignment"], [s["kind"] for s in sections])
        first = sections[0]["items"][0]
        self.assertEqual("class/private-alpha", first["record_id"])
        self.assertTrue(first["dom_id"].startswith("management-class-"))
        self.assertNotIn("private-alpha", first["dom_id"])
        self.assertEqual(first["dom_id"], sections[0]["focus_target"])
        self.assertTrue(first["selected"])

    def test_remote_browser_snapshot_never_exposes_session_or_chess_state(self) -> None:
        snapshot = self.projection.remote_snapshot()
        self.assertEqual("connected", snapshot["status"])
        self.assertEqual("Coach", snapshot["teacher_label"])
        self.assertEqual("Student 7", snapshot["student_label"])
        self.assertNotIn("session_id", snapshot)
        serialized = repr(snapshot).casefold()
        self.assertNotIn("opaque-session-123", serialized)
        self.assertNotIn("fen", serialized)
        self.assertNotIn("position", serialized)
        self.assertNotIn("token", serialized)

    def test_management_selection_is_ui_local_and_open_delegates_stable_action(self) -> None:
        event = self.projection.move_selection(RecordKind.CLASS, 1)
        self.assertEqual("selection", event.kind)
        self.assertEqual("", event.payload["announcement"])
        self.assertEqual([], self.calls)
        opened = self.projection.open_selected("class")
        self.assertEqual("delegated", opened.kind)
        self.assertEqual(
            [("classes.open", {"record_id": "class/private-beta"})],
            self.calls,
        )

    def test_explicit_click_selection_may_announce_once_but_does_not_dispatch_domain_action(self) -> None:
        event = self.projection.select("class", "class/private-beta")
        self.assertEqual("selection", event.kind)
        self.assertEqual("Selected", event.payload["announcement"])
        self.assertEqual([], self.calls)

    def test_remote_actions_keep_session_identity_inside_presenter_boundary(self) -> None:
        reconnect = self.projection.reconnect()
        self.assertEqual("remote-action", reconnect.kind)
        self.assertEqual(
            [("remote.reconnect", {"session_id": "opaque-session-123"})],
            self.calls,
        )
        self.assertNotIn("opaque-session-123", repr(reconnect.payload))

    def test_connect_uses_explicit_lesson_id_and_leave_uses_internal_session(self) -> None:
        connect = self.projection.connect("lesson-public-9")
        self.assertEqual("remote-action", connect.kind)
        leave = self.projection.leave()
        self.assertEqual("remote-action", leave.kind)
        self.assertEqual(
            [
                ("remote.connect", {"lesson_id": "lesson-public-9"}),
                ("remote.leave", {"session_id": "opaque-session-123"}),
            ],
            self.calls,
        )

    def test_malformed_or_secret_remote_provider_state_projects_generic_error_only(self) -> None:
        self.remote_state = {
            "status": "connected",
            "token": "SECRET",
            "fen": "8/8/8/8/8/8/8/8 w - - 0 1",
            "session_id": "private-session",
        }
        snapshot = self.projection.remote_snapshot()
        self.assertEqual("error", snapshot["status"])
        self.assertEqual("The action could not be completed.", snapshot["message"])
        text = repr(snapshot)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("private-session", text)
        self.assertNotIn("8/8/8", text)

    def test_language_switch_changes_labels_not_record_identity(self) -> None:
        before = self.projection.management_snapshot("student")
        event = self.projection.set_language(UILanguage.UA)
        self.assertEqual("render", event.kind)
        after = self.projection.management_snapshot("student")
        self.assertEqual("Students", before["heading"])
        self.assertEqual("Учні", after["heading"])
        self.assertEqual(before["items"][0]["record_id"], after["items"][0]["record_id"])
        self.assertEqual(before["items"][0]["dom_id"], after["items"][0]["dom_id"])

    def test_errors_are_sanitized_before_browser_projection(self) -> None:
        event = self.projection.open_selected("unsupported-kind")
        self.assertEqual("error", event.kind)
        message = str(event.payload["message"])
        self.assertNotIn("unsupported-kind", message)
        self.assertNotIn("Traceback", message)

    def test_constructor_requires_exact_four_presenter_kinds(self) -> None:
        incomplete = dict(self.management)
        incomplete.pop(RecordKind.ASSIGNMENT)
        with self.assertRaises(ValueError):
            ClassroomWebViewProjection(incomplete, self.remote, self.dispatch)


if __name__ == "__main__":
    unittest.main()
