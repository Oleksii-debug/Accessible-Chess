from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import FileQuotaPolicy
from acs.classroom_file_server import (
    ClassroomFileServerClient,
    ClassroomFileServerError,
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)
from acs.classroom_http_server_runtime import (
    ClassroomCollaborationHttpServerRuntime,
    build_classroom_collaboration_http_server_runtime,
)
from tests.test_classroom_collaboration_chat_server import FakeAuthorization
from tests.test_classroom_file_server import AllowMembers, FakeObjectStore, FakeScanner


class Authenticator:
    def __init__(self) -> None:
        self.calls = []

    async def authenticate_bearer(self, bearer_token: str):
        self.calls.append(bearer_token)
        return ("room-1", "student-1")


class ClassroomHttpServerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.authenticator = Authenticator()
        self.chat_authorization = FakeAuthorization()
        self.file_authorization = AllowMembers({("student-1", "room-1")})
        self.scanner = FakeScanner()
        self.objects = FakeObjectStore()
        self.clock_calls = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def clock(self) -> int:
        self.clock_calls += 1
        return 1700000000000 + self.clock_calls

    def build(self, **overrides) -> ClassroomCollaborationHttpServerRuntime:
        arguments = {
            "chat_database_path": self.root / "chat.sqlite3",
            "file_database_path": self.root / "files.sqlite3",
            "authenticator": self.authenticator,
            "chat_authorization": self.chat_authorization,
            "file_authorization": self.file_authorization,
            "file_scanner": self.scanner,
            "file_object_store": self.objects,
            "clock_unix_ms": self.clock,
            "file_quota": FileQuotaPolicy(
                max_file_bytes=64,
                max_room_bytes=256,
            ),
        }
        arguments.update(overrides)
        return build_classroom_collaboration_http_server_runtime(**arguments)

    def test_build_composes_recovered_authorities_and_shared_authenticator(self) -> None:
        runtime = self.build()

        self.assertTrue((self.root / "chat.sqlite3").exists())
        self.assertTrue((self.root / "files.sqlite3").exists())
        self.assertIs(runtime.chat_service._store, runtime.chat_store)
        self.assertIs(runtime.file_service._store, runtime.file_store)
        self.assertIs(runtime.chat_rpc._backend, runtime.chat_service)
        self.assertIs(runtime.file_rpc._backend, runtime.file_service)
        self.assertIs(runtime.application._authenticator, self.authenticator)
        self.assertIs(runtime.application._chat._authenticator, self.authenticator)
        self.assertIs(runtime.application._files._authenticator, self.authenticator)
        runtime.chat_store.integrity_check()
        runtime.file_store.integrity_check()
        self.assertEqual(
            repr(runtime),
            "ClassroomCollaborationHttpServerRuntime(<bound>)",
        )
        self.assertNotIn("token", repr(runtime).lower())

    def test_invalid_inputs_fail_before_any_database_is_created(self) -> None:
        chat_path = self.root / "must-not-exist-chat.sqlite3"
        missing_file = self.root / "missing-parent" / "files.sqlite3"

        with self.assertRaisesRegex(ValueError, "parent directory"):
            self.build(
                chat_database_path=chat_path,
                file_database_path=missing_file,
            )
        self.assertFalse(chat_path.exists())
        self.assertFalse(missing_file.exists())

        same = self.root / "same.sqlite3"
        with self.assertRaisesRegex(ValueError, "distinct paths"):
            self.build(
                chat_database_path=same,
                file_database_path=same,
            )
        self.assertFalse(same.exists())

        oversized = FileQuotaPolicy(
            max_file_bytes=100 * 1024 * 1024 + 1,
            max_room_bytes=100 * 1024 * 1024 + 1,
        )
        quota_chat = self.root / "quota-chat.sqlite3"
        quota_file = self.root / "quota-file.sqlite3"
        with self.assertRaisesRegex(ValueError, "RPC upload limit"):
            self.build(
                chat_database_path=quota_chat,
                file_database_path=quota_file,
                file_quota=oversized,
            )
        self.assertFalse(quota_chat.exists())
        self.assertFalse(quota_file.exists())

    def test_startup_rolls_back_ambiguous_upload_before_exposing_application(self) -> None:
        file_path = self.root / "recover-files.sqlite3"
        store = ClassroomFileServerSQLiteStore(str(file_path))
        service = ClassroomFileServerService(
            store=store,
            authorization=self.file_authorization,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=256),
        )
        client = ClassroomFileServerClient(
            service=service,
            trusted_caller_identity="student-1",
        )
        source = self.root / "ambiguous.bin"
        source.write_bytes(b"ambiguous startup recovery")
        from acs.classroom_collaboration import PreparedFile, _canonical_object_key
        from acs.classroom_collaboration_storage import AttachmentMetadata
        import hashlib

        content = source.read_bytes()
        prepared = PreparedFile(
            source,
            AttachmentMetadata(
                "ambiguous-startup",
                "room-1",
                "student-1",
                99,
                source.name,
                "application/octet-stream",
                len(content),
                hashlib.sha256(content).hexdigest(),
                _canonical_object_key("room-1", "ambiguous-startup"),
                "uploading",
                "session",
                "pending",
            ),
        )
        self.objects.raise_after_put_once = True
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            client.upload(prepared)
        self.assertIn(prepared.metadata.object_key, self.objects.objects)

        runtime = self.build(file_database_path=file_path)

        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        self.assertEqual(runtime.file_store.pending_deletions(), ())
        self.assertEqual(
            runtime.file_store.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            ).attachments,
            (),
        )
        runtime.file_store.integrity_check()

    def test_incomplete_startup_recovery_fails_closed_and_remains_durable(self) -> None:
        file_path = self.root / "blocked-recovery-files.sqlite3"
        store = ClassroomFileServerSQLiteStore(str(file_path))
        service = ClassroomFileServerService(
            store=store,
            authorization=self.file_authorization,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=256),
        )
        client = ClassroomFileServerClient(
            service=service,
            trusted_caller_identity="student-1",
        )
        source = self.root / "blocked-recovery.bin"
        source.write_bytes(b"pending deletion")
        from acs.classroom_collaboration import PreparedFile, _canonical_object_key
        from acs.classroom_collaboration_storage import AttachmentMetadata
        import hashlib

        content = source.read_bytes()
        prepared = PreparedFile(
            source,
            AttachmentMetadata(
                "blocked-startup",
                "room-1",
                "student-1",
                17,
                source.name,
                "application/octet-stream",
                len(content),
                hashlib.sha256(content).hexdigest(),
                _canonical_object_key("room-1", "blocked-startup"),
                "uploading",
                "session",
                "pending",
            ),
        )
        self.objects.raise_after_put_once = True
        with self.assertRaises(ClassroomFileServerError):
            client.upload(prepared)
        self.objects.delete_failures = 1

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "rollback incomplete",
        ):
            self.build(file_database_path=file_path)

        reopened = ClassroomFileServerSQLiteStore(str(file_path))
        self.assertEqual(
            reopened.pending_deletions(),
            ((prepared.metadata.attachment_id, prepared.metadata.object_key),),
        )
        self.assertIn(prepared.metadata.object_key, self.objects.objects)
        reopened.integrity_check()


if __name__ == "__main__":
    unittest.main()
