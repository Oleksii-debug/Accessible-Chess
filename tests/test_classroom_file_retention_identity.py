from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import FileQuotaPolicy, PreparedFile, _canonical_object_key
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    CollaborationConflictError,
)
from acs.classroom_file_server import (
    ClassroomFileServerError,
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)
from tests.test_classroom_file_server import AllowMembers, FakeObjectStore, FakeScanner


class ClassroomFileRetentionIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ClassroomFileServerSQLiteStore(
            str(self.root / "file-server.sqlite3")
        )
        self.auth = AllowMembers({("student-1", "room-1")})
        self.scanner = FakeScanner()
        self.objects = FakeObjectStore()
        self.service = ClassroomFileServerService(
            store=self.store,
            authorization=self.auth,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=64),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def prepared(self, attachment_id: str, content: bytes) -> PreparedFile:
        path = self.root / f"{attachment_id}.bin"
        path.write_bytes(content)
        metadata = AttachmentMetadata(
            attachment_id,
            "room-1",
            "student-1",
            900,
            path.name,
            "application/octet-stream",
            len(content),
            hashlib.sha256(content).hexdigest(),
            _canonical_object_key("room-1", attachment_id),
            "uploading",
            "session",
            "pending",
        )
        return PreparedFile(path, metadata)

    def upload_direct(self, prepared: PreparedFile):
        return self.service.upload(
            trusted_caller_identity="student-1",
            metadata=prepared.metadata,
            content=prepared.local_path.read_bytes(),
        )

    def test_expired_ambiguous_identity_cannot_resurrect_after_bytes_are_deleted(self) -> None:
        prepared = self.prepared(
            "expired-ambiguous",
            b"expired bytes",
        )
        self.objects.raise_after_put_once = True
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.upload_direct(prepared)
        self.assertIn(prepared.metadata.object_key, self.objects.objects)

        self.assertEqual(
            self.service.expire_room_retention(
                room_id="room-1",
                retentions=("session",),
            ),
            1,
        )
        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        self.assertEqual(self.store.pending_deletions(), ())

        with self.store._connect() as db:
            expired = db.execute(
                "SELECT transfer_state, sequence_no, delete_completed "
                "FROM classroom_file_server_attachments "
                "WHERE attachment_id=?",
                (prepared.metadata.attachment_id,),
            ).fetchone()
        self.assertIsNotNone(expired)
        self.assertEqual(expired["transfer_state"], "expired")
        self.assertIsNone(expired["sequence_no"])
        self.assertEqual(expired["delete_completed"], 1)

        scan_calls = len(self.scanner.calls)
        put_calls = len(self.objects.put_calls)
        with self.assertRaisesRegex(
            CollaborationConflictError,
            "expired attachment identity",
        ):
            self.upload_direct(prepared)
        self.assertEqual(len(self.scanner.calls), scan_calls)
        self.assertEqual(len(self.objects.put_calls), put_calls)

        replacement = self.prepared(
            "replacement-after-expiry",
            b"new identity",
        )
        accepted = self.upload_direct(replacement)
        self.assertEqual(accepted.sequence_no, 0)
        self.assertEqual(accepted.transfer_state, "stored")
        self.store.integrity_check()

    def test_expired_identity_survives_delete_failure_and_recovery(self) -> None:
        prepared = self.prepared(
            "expired-delete-recovery",
            b"recover deletion",
        )
        self.objects.raise_after_put_once = True
        with self.assertRaises(ClassroomFileServerError):
            self.upload_direct(prepared)

        self.objects.delete_failures = 1
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "room retention cleanup incomplete",
        ):
            self.service.expire_room_retention(
                room_id="room-1",
                retentions=("session",),
            )

        with self.store._connect() as db:
            pending = db.execute(
                "SELECT transfer_state, sequence_no, delete_completed "
                "FROM classroom_file_server_attachments "
                "WHERE attachment_id=?",
                (prepared.metadata.attachment_id,),
            ).fetchone()
        self.assertEqual(pending["transfer_state"], "expired")
        self.assertIsNone(pending["sequence_no"])
        self.assertEqual(pending["delete_completed"], 0)
        self.assertEqual(
            self.store.pending_deletions(),
            ((prepared.metadata.attachment_id, prepared.metadata.object_key),),
        )

        self.assertEqual(self.service.drain_pending_deletions(), 1)
        self.assertEqual(self.store.pending_deletions(), ())
        with self.store._connect() as db:
            completed = db.execute(
                "SELECT transfer_state, sequence_no, delete_completed "
                "FROM classroom_file_server_attachments "
                "WHERE attachment_id=?",
                (prepared.metadata.attachment_id,),
            ).fetchone()
        self.assertEqual(completed["transfer_state"], "expired")
        self.assertIsNone(completed["sequence_no"])
        self.assertEqual(completed["delete_completed"], 1)

        with self.assertRaisesRegex(
            CollaborationConflictError,
            "expired attachment identity",
        ):
            self.upload_direct(prepared)
        self.store.integrity_check()


if __name__ == "__main__":
    unittest.main()
