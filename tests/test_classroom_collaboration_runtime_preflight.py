from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import CollaborationError
from acs.classroom_collaboration_runtime import (
    ClassroomCollaborationRuntime,
    build_classroom_collaboration_http_runtime,
)
from acs.full_product_ui_shell import UILanguage
from tests.test_classroom_collaboration import FakeRoster


CHAT_URL = "http://127.0.0.1/v1/classroom/chat"
FILE_URL = "http://127.0.0.1/v1/classroom/files"


class ClassroomCollaborationRuntimePreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.chat_token_calls = 0
        self.file_token_calls = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def chat_token(self) -> str:
        self.chat_token_calls += 1
        return "chat-secret-token"

    def file_token(self) -> str:
        self.file_token_calls += 1
        return "file-secret-token"

    def build(self, *, roster, participant_id: str = "student-1", path: Path):
        return build_classroom_collaboration_http_runtime(
            room_id="room-1",
            participant_id=participant_id,
            roster=roster,
            store_path=path,
            chat_endpoint_url=CHAT_URL,
            file_endpoint_url=FILE_URL,
            chat_bearer_token_provider=self.chat_token,
            file_bearer_token_provider=self.file_token,
            participant_label=lambda participant: participant,
            language=UILanguage.EN,
            allow_insecure_loopback=True,
        )

    def assert_no_persistence_or_credentials(self, path: Path) -> None:
        self.assertFalse(path.exists())
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)

    def test_non_member_fails_before_durable_store_creation(self) -> None:
        roster = FakeRoster()
        roster.roles.pop("student-1")
        path = self.root / "non-member.sqlite3"

        with self.assertRaisesRegex(
            CollaborationError,
            "participant is not present in canonical room roster",
        ):
            self.build(roster=roster, path=path)

        self.assert_no_persistence_or_credentials(path)

    def test_malformed_roster_fails_before_durable_store_creation(self) -> None:
        class MalformedRoster(FakeRoster):
            def participant_ids(self):
                return list(super().participant_ids())

        path = self.root / "malformed-roster.sqlite3"
        with self.assertRaisesRegex(
            CollaborationError,
            "canonical room roster is invalid or too large",
        ):
            self.build(roster=MalformedRoster(), path=path)

        self.assert_no_persistence_or_credentials(path)

    def test_roster_provider_failure_does_not_materialize_store(self) -> None:
        class FailingRoster(FakeRoster):
            def participant_ids(self):
                raise RuntimeError("roster authority unavailable")

        path = self.root / "roster-failure.sqlite3"
        with self.assertRaisesRegex(RuntimeError, "roster authority unavailable"):
            self.build(roster=FailingRoster(), path=path)

        self.assert_no_persistence_or_credentials(path)

    def test_successful_binding_materializes_store_and_proxy_forwards(self) -> None:
        path = self.root / "valid.sqlite3"
        runtime = self.build(roster=FakeRoster(), path=path)

        self.assertIsInstance(runtime, ClassroomCollaborationRuntime)
        self.assertTrue(path.exists())
        self.assertEqual(runtime.controller.room_id, "room-1")
        self.assertEqual(runtime.controller.local_participant_id, "student-1")
        self.assertEqual(runtime.controller._store.path, str(path))
        self.assertEqual(runtime.store.path, str(path))
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)


if __name__ == "__main__":
    unittest.main()
