from __future__ import annotations

import unittest

from acs.classroom_presentation import (
    ManagementListPresenter,
    ManagementRecord,
    RecordKind,
    RemoteLessonPresenter,
)
from acs.classroom_webview_projection import ClassroomWebViewProjection


class ClassroomWebViewPrivacyTests(unittest.TestCase):
    def test_backend_return_payload_never_crosses_webview_boundary(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]):
            calls.append((action_id, dict(payload)))
            return {
                "token": "SECRET-TOKEN",
                "session_id": "private-session",
                "fen": "8/8/8/8/8/8/8/8 w - - 0 1",
                "path": "C:/Users/private/database.acsdb",
            }

        management = {
            kind: ManagementListPresenter(kind)
            for kind in (
                RecordKind.CLASS,
                RecordKind.STUDENT,
                RecordKind.LESSON,
                RecordKind.ASSIGNMENT,
            )
        }
        management[RecordKind.CLASS].replace(
            (ManagementRecord("class-1", RecordKind.CLASS, "Class 1"),)
        )
        management[RecordKind.STUDENT].replace(
            (ManagementRecord("student-1", RecordKind.STUDENT, "Student 1"),)
        )
        management[RecordKind.LESSON].replace(
            (ManagementRecord("lesson-1", RecordKind.LESSON, "Lesson 1"),)
        )
        management[RecordKind.ASSIGNMENT].replace(
            (ManagementRecord("assignment-1", RecordKind.ASSIGNMENT, "Assignment 1"),)
        )
        remote_state = {
            "status": "connected",
            "session_id": "private-session",
            "teacher_label": "Teacher",
            "student_label": "Student 1",
            "last_sequence": 1,
        }
        remote = RemoteLessonPresenter(lambda: dict(remote_state), dispatch)
        projection = ClassroomWebViewProjection(management, remote, dispatch)

        events = [
            projection.open_selected("class"),
            projection.new_class(),
            projection.connect("lesson-public"),
        ]
        remote_state["status"] = "error"
        events.append(projection.reconnect())
        remote_state["status"] = "connected"
        events.append(projection.leave())

        self.assertEqual(5, len(calls))
        self.assertTrue(all(event.kind != "error" for event in events))
        serialized = repr(tuple(event.payload for event in events))
        for forbidden in (
            "SECRET-TOKEN",
            "private-session",
            "8/8/8",
            "C:/Users/private",
            "token",
            "session_id",
            "fen",
            "path",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
