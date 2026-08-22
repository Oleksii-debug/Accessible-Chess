import unittest

from acs.classroom_presentation import (
    ManagementListPresenter,
    ManagementRecord,
    RecordKind,
    RemoteLessonPresenter,
    RemoteStatus,
)
from acs.full_product_ui_shell import UILanguage


class ManagementListPresenterTests(unittest.TestCase):
    def test_selection_survives_refresh_by_stable_id_and_open_uses_neutral_payload(self):
        presenter = ManagementListPresenter(RecordKind.STUDENT, language=UILanguage.EN)
        presenter.replace(
            (
                ManagementRecord("s1", RecordKind.STUDENT, "Student One", "Group A", "active"),
                ManagementRecord("s2", RecordKind.STUDENT, "Student Two", "Group A", "active"),
            )
        )
        presenter.select("s2")
        presenter.replace(
            (
                ManagementRecord("s2", RecordKind.STUDENT, "Student Two", "Group A", "active"),
                ManagementRecord("s3", RecordKind.STUDENT, "Student Three", "Group B", "active"),
            )
        )
        self.assertEqual("s2", presenter.selected_id)
        calls = []
        result = presenter.open_selected(lambda action, payload: calls.append((action, dict(payload))) or "opened")
        self.assertEqual("opened", result)
        self.assertEqual([("classes.student_open", {"record_id": "s2"})], calls)

    def test_keyboard_boundaries_are_explicit_and_empty_list_is_not_fake_selection(self):
        presenter = ManagementListPresenter(RecordKind.ASSIGNMENT)
        self.assertIsNone(presenter.replace(()).selected_id)
        with self.assertRaises(LookupError):
            presenter.move_selection(1)
        presenter.replace(
            (
                ManagementRecord("a1", RecordKind.ASSIGNMENT, "Assignment 1"),
                ManagementRecord("a2", RecordKind.ASSIGNMENT, "Assignment 2"),
            )
        )
        self.assertEqual("a2", presenter.move_selection(1).selected_id)
        with self.assertRaises(LookupError):
            presenter.move_selection(1)

    def test_wrong_record_kind_and_duplicate_ids_fail_closed(self):
        presenter = ManagementListPresenter(RecordKind.CLASS)
        with self.assertRaises(ValueError):
            presenter.replace((ManagementRecord("s1", RecordKind.STUDENT, "Student"),))
        with self.assertRaises(ValueError):
            presenter.replace(
                (
                    ManagementRecord("c1", RecordKind.CLASS, "Class A"),
                    ManagementRecord("c1", RecordKind.CLASS, "Class B"),
                )
            )

    def test_internal_failure_is_projected_without_path_noise(self):
        presenter = ManagementListPresenter(RecordKind.LESSON, language=UILanguage.EN)
        view = presenter.set_error(r"PermissionError: C:\\private\\lesson.db")
        self.assertEqual("The action could not be completed.", view.message)
        self.assertNotIn("private", view.message)


class FakeRemoteBackend:
    def __init__(self):
        self.state = {
            "status": "disconnected",
            "session_id": None,
            "teacher_label": "Teacher",
            "student_label": "Student",
            "last_sequence": None,
        }
        self.calls = []

    def snapshot(self):
        return dict(self.state)

    def dispatch(self, action_id, payload):
        payload = dict(payload)
        self.calls.append((action_id, payload))
        if action_id == "remote.connect":
            self.state.update(status="connected", session_id="session-17", last_sequence=0)
        elif action_id == "remote.reconnect":
            self.state["status"] = "connected"
        elif action_id == "remote.leave":
            self.state.update(status="disconnected", session_id=None)
        return action_id


class RemoteLessonPresenterTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeRemoteBackend()
        self.presenter = RemoteLessonPresenter(
            self.backend.snapshot,
            self.backend.dispatch,
            language=UILanguage.EN,
        )

    def test_connect_and_leave_are_explicit_backend_actions(self):
        initial = self.presenter.view()
        self.assertEqual(RemoteStatus.DISCONNECTED, initial.status)
        self.assertTrue(initial.can_connect)
        self.assertEqual("remote.connect", self.presenter.connect(lesson_id="lesson-4"))
        connected = self.presenter.view()
        self.assertEqual(RemoteStatus.CONNECTED, connected.status)
        self.assertTrue(connected.can_leave)
        self.assertEqual("remote.leave", self.presenter.leave())
        self.assertEqual(RemoteStatus.DISCONNECTED, self.presenter.view().status)
        self.assertEqual(
            [
                ("remote.connect", {"lesson_id": "lesson-4"}),
                ("remote.leave", {"session_id": "session-17"}),
            ],
            self.backend.calls,
        )

    def test_reconnect_requires_error_state_with_session_identity(self):
        self.backend.state.update(status="error", session_id="session-old", last_sequence=44)
        view = self.presenter.view()
        self.assertTrue(view.can_reconnect)
        self.assertEqual("remote.reconnect", self.presenter.reconnect())
        self.assertEqual(RemoteStatus.CONNECTED, self.presenter.view().status)

    def test_secret_or_chess_state_in_provider_is_rejected_from_presentation(self):
        for leak in (
            {"status": "connected", "session_id": "s", "token": "secret"},
            {"status": "connected", "session_id": "s", "fen": "8/8/8/8/8/8/8/8"},
        ):
            presenter = RemoteLessonPresenter(lambda leak=leak: leak, self.backend.dispatch, language=UILanguage.EN)
            view = presenter.view()
            self.assertEqual(RemoteStatus.ERROR, view.status)
            self.assertEqual("The action could not be completed.", view.message)
            self.assertIsNone(view.session_id)

    def test_transport_failure_message_is_concise_and_recovery_preserves_public_identity(self):
        self.backend.state.update(status="connected", session_id="session-9", last_sequence=12)
        view = self.presenter.project_failure(
            r"HRESULT 0x80004005 at C:\\private\\remote_transport.py"
        )
        self.assertEqual(RemoteStatus.ERROR, view.status)
        self.assertEqual("session-9", view.session_id)
        self.assertTrue(view.can_reconnect)
        self.assertEqual("The action could not be completed.", view.message)


if __name__ == "__main__":
    unittest.main()
