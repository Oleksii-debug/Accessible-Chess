from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import FileQuotaPolicy, PreparedFile, _canonical_object_key
from acs.classroom_collaboration_storage import AttachmentMetadata
from acs.classroom_file_server import (
    ClassroomFileServerClient,
    ClassroomFileServerError,
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)
from tests.test_classroom_file_server import AllowMembers, FakeObjectStore, FakeScanner


class ClassroomFileRetentionCleanupTests(unittest.TestCase):
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
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=256),
        )
        self.client = ClassroomFileServerClient(
            service=self.service,
            trusted_caller_identity="student-1",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def prepared(
        self,
        attachment_id: str,
        *,
        retention: str,
        content: bytes,
    ) -> PreparedFile:
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
            retention,
            "pending",
        )
        return PreparedFile(path, metadata)

    def upload(self, attachment_id: str, retention: str, content: bytes):
        return self.client.upload(
            self.prepared(
                attachment_id,
                retention=retention,
                content=content,
            )
        )

    def test_room_cleanup_tombstones_selected_retention_and_preserves_persistent(self) -> None:
        transient = self.upload("retention-transient", "transient", b"transient")
        session = self.upload("retention-session", "session", b"session")
        persistent = self.upload("retention-persistent", "persistent", b"persistent")
        auth_calls_before = len(self.auth.calls)

        # Lifecycle cleanup remains possible after participant credentials/membership
        # disappear; it is a trusted server/operator boundary, not a client action.
        self.auth.members.clear()
        completed = self.service.expire_room_retention(
            room_id="room-1",
            retentions=("transient", "session"),
        )

        self.assertEqual(completed, 2)
        self.assertEqual(len(self.auth.calls), auth_calls_before)
        self.assertNotIn(transient.object_key, self.objects.objects)
        self.assertNotIn(session.object_key, self.objects.objects)
        self.assertIn(persistent.object_key, self.objects.objects)

        history = self.store.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=100,
        )
        self.assertEqual(
            [item.transfer_state for item in history.attachments],
            ["deleted", "deleted", "stored"],
        )
        self.assertEqual(
            [item.retention for item in history.attachments],
            ["transient", "session", "persistent"],
        )
        updates = self.store.state_updates_after(
            room_id="room-1",
            after_revision=None,
            limit=100,
        )
        self.assertEqual([item.revision for item in updates], [0, 1])
        self.assertEqual(
            [item.attachment_id for item in updates],
            [transient.attachment_id, session.attachment_id],
        )
        self.assertEqual(self.store.pending_deletions(), ())
        self.assertEqual(
            self.service.expire_room_retention(
                room_id="room-1",
                retentions=("transient", "session"),
            ),
            0,
        )
        self.store.integrity_check()

    def test_cleanup_scope_is_exact_and_persistent_is_never_swept(self) -> None:
        transient = self.upload("scope-transient", "transient", b"t")
        session = self.upload("scope-session", "session", b"s")
        persistent = self.upload("scope-persistent", "persistent", b"p")

        self.assertEqual(
            self.service.expire_room_retention(
                room_id="room-1",
                retentions=("transient",),
            ),
            1,
        )
        self.assertNotIn(transient.object_key, self.objects.objects)
        self.assertIn(session.object_key, self.objects.objects)
        self.assertIn(persistent.object_key, self.objects.objects)

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "cannot delete persistent",
        ):
            self.service.expire_room_retention(
                room_id="room-1",
                retentions=("persistent",),
            )
        self.assertIn(session.object_key, self.objects.objects)
        self.assertIn(persistent.object_key, self.objects.objects)

        self.assertEqual(
            self.service.expire_room_retention(
                room_id="room-1",
                retentions=("session",),
            ),
            1,
        )
        self.assertNotIn(session.object_key, self.objects.objects)
        self.assertIn(persistent.object_key, self.objects.objects)
        self.store.integrity_check()

    def test_cleanup_rejects_ambiguous_or_malformed_scope_before_mutation(self) -> None:
        stored = self.upload("scope-safe", "session", b"safe")
        delete_calls = len(self.objects.delete_calls)

        for retentions in (
            (),
            ("session", "session"),
            ("transient", "session", "persistent"),
            ["session"],
            (1,),
        ):
            with self.subTest(retentions=retentions):
                with self.assertRaisesRegex(
                    ClassroomFileServerError,
                    "retention cleanup",
                ):
                    self.service.expire_room_retention(
                        room_id="room-1",
                        retentions=retentions,
                    )

        self.assertEqual(len(self.objects.delete_calls), delete_calls)
        self.assertIn(stored.object_key, self.objects.objects)
        current = self.store.attachment_for_object_key(stored.object_key)
        self.assertIsNotNone(current)
        self.assertEqual(current.transfer_state, "stored")

    def test_delete_failure_keeps_tombstone_for_existing_recovery_path(self) -> None:
        stored = self.upload("retention-delete-failure", "session", b"recover")
        self.objects.delete_failures = 1

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "room retention cleanup incomplete",
        ) as raised:
            self.service.expire_room_retention(
                room_id="room-1",
                retentions=("session",),
            )

        self.assertIsNone(raised.exception.__cause__)
        self.assertIn(stored.object_key, self.objects.objects)
        current = self.store.attachment_for_object_key(stored.object_key)
        self.assertIsNotNone(current)
        self.assertEqual(current.transfer_state, "deleted")
        self.assertEqual(
            self.store.pending_deletions(),
            ((stored.attachment_id, stored.object_key),),
        )

        self.assertEqual(self.service.drain_pending_deletions(), 1)
        self.assertNotIn(stored.object_key, self.objects.objects)
        self.assertEqual(self.store.pending_deletions(), ())
        self.store.integrity_check()

    def test_cleanup_retires_ambiguous_upload_without_creating_history_item(self) -> None:
        prepared = self.prepared(
            "retention-ambiguous-upload",
            retention="session",
            content=b"durable-before-ack",
        )
        self.objects.raise_after_put_once = True
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.client.upload(prepared)

        self.assertIn(prepared.metadata.object_key, self.objects.objects)
        with self.store._connect() as db:
            row = db.execute(
                "SELECT transfer_state, sequence_no, retention "
                "FROM classroom_file_server_attachments WHERE attachment_id=?",
                (prepared.metadata.attachment_id,),
            ).fetchone()
        self.assertEqual(row["transfer_state"], "uploading")
        self.assertIsNone(row["sequence_no"])
        self.assertEqual(row["retention"], "session")

        self.assertEqual(
            self.service.expire_room_retention(
                room_id="room-1",
                retentions=("session",),
            ),
            1,
        )
        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        with self.store._connect() as db:
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (prepared.metadata.attachment_id,),
                ).fetchone()
            )
        history = self.store.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=100,
        )
        self.assertEqual(history.attachments, ())
        self.assertEqual(self.store.pending_deletions(), ())
        self.store.integrity_check()


if __name__ == "__main__":
    unittest.main()
