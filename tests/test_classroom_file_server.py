from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import tempfile
import unittest
from pathlib import Path

from acs.classroom_collaboration import (
    FileQuotaPolicy,
    PreparedFile,
    _canonical_object_key,
)
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    CollaborationConflictError,
    CollaborationQuotaError,
)
from acs.classroom_file_server import (
    ClassroomFileServerClient,
    ClassroomFileServerError,
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)


class AllowMembers:
    def __init__(self, members):
        self.members = set(members)
        self.calls = []

    def authorize_file_action(
        self,
        *,
        trusted_caller_identity,
        room_id,
        action,
        attachment_id,
        retention,
    ):
        self.calls.append(
            (
                trusted_caller_identity,
                room_id,
                action,
                attachment_id,
                retention,
            )
        )
        return (trusted_caller_identity, room_id) in self.members


class FakeScanner:
    def __init__(self):
        self.state = "clean"
        self.calls = []

    def scan(self, **kwargs):
        self.calls.append(kwargs)
        return self.state


class FakeObjectStore:
    def __init__(self):
        self.objects = {}
        self.put_calls = []
        self.delete_calls = []
        self.token_calls = []
        self.raise_after_put_once = False
        self.delete_failures = 0

    def put(self, *, object_key, content, expected_sha256):
        self.put_calls.append((object_key, bytes(content), expected_sha256))
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise RuntimeError("hash mismatch")
        existing = self.objects.get(object_key)
        if existing is not None and existing != content:
            raise RuntimeError("object identity conflict")
        self.objects[object_key] = bytes(content)
        if self.raise_after_put_once:
            self.raise_after_put_once = False
            raise RuntimeError("write acknowledgement lost")

    def issue_read_token(self, *, object_key, participant_id, ttl_seconds):
        if object_key not in self.objects:
            raise RuntimeError("missing object")
        self.token_calls.append((object_key, participant_id, ttl_seconds))
        return f"read-{participant_id}-{ttl_seconds}"

    def delete(self, *, object_key):
        self.delete_calls.append(object_key)
        if self.delete_failures:
            self.delete_failures -= 1
            raise RuntimeError("simulated delete failure")
        self.objects.pop(object_key, None)


class ClassroomFileServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "file-server.sqlite3"
        self.store = ClassroomFileServerSQLiteStore(str(self.db_path))
        self.auth = AllowMembers(
            {
                ("student-1", "room-1"),
                ("student-2", "room-1"),
                ("teacher-1", "room-1"),
            }
        )
        self.scanner = FakeScanner()
        self.objects = FakeObjectStore()
        self.service = ClassroomFileServerService(
            store=self.store,
            authorization=self.auth,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )
        self.student1 = ClassroomFileServerClient(
            service=self.service,
            trusted_caller_identity="student-1",
        )
        self.student2 = ClassroomFileServerClient(
            service=self.service,
            trusted_caller_identity="student-2",
        )

    def tearDown(self):
        self.temp.cleanup()

    def prepared(
        self,
        *,
        attachment_id,
        sender="student-1",
        content=b"opaque\x00bytes",
        suffix=".unknown",
        sequence=900,
        retention="persistent",
    ):
        path = self.root / f"{attachment_id}{suffix}"
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        metadata = AttachmentMetadata(
            attachment_id,
            "room-1",
            sender,
            sequence,
            path.name,
            None,
            len(content),
            digest,
            _canonical_object_key("room-1", attachment_id),
            "uploading",
            retention,
            "pending",
        )
        return PreparedFile(path, metadata)

    def test_store_requires_durable_database_target_and_sanitizes_open_failure(self):
        for target in ("", ":memory:"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(
                    ClassroomFileServerError,
                    "durable file-server database path is required",
                ):
                    ClassroomFileServerSQLiteStore(target)

        missing_parent = self.root / "missing-parent" / "server.sqlite3"
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "database open failed",
        ) as raised:
            ClassroomFileServerSQLiteStore(str(missing_parent))
        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(missing_parent.exists())

    def test_external_authorization_failure_drops_sensitive_exception_cause(self):
        class BrokenAuthorization:
            def authorize_file_action(self, **_kwargs):
                raise RuntimeError("secret provider path C:/sensitive/auth.json")

        service = ClassroomFileServerService(
            store=self.store,
            authorization=BrokenAuthorization(),
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )
        client = ClassroomFileServerClient(
            service=service,
            trusted_caller_identity="student-1",
        )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "authorization failed",
        ) as raised:
            client.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=1,
            )

        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("sensitive", str(raised.exception).lower())

    def test_external_object_store_failure_drops_sensitive_exception_cause(self):
        prepared = self.prepared(
            attachment_id="sanitized-object-write",
            content=b"opaque provider bytes",
        )
        self.objects.raise_after_put_once = True

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ) as raised:
            self.student1.upload(prepared)

        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("acknowledgement", str(raised.exception).lower())

    def test_local_file_read_failure_drops_private_path_exception_cause(self):
        prepared = self.prepared(attachment_id="missing-local-source")
        prepared.local_path.unlink()

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "selected file could not be read for upload",
        ) as raised:
            self.student1.upload(prepared)

        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn(str(prepared.local_path), str(raised.exception))

    def test_arbitrary_binary_round_trip_rejoin_and_short_lived_token(self):
        prepared = self.prepared(
            attachment_id="file-a0",
            content=b"\x00\xff\x10opaque\x00",
        )

        stored = self.student1.upload(prepared)

        self.assertEqual(stored.sequence_no, 0)
        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(stored.scan_state, "clean")
        self.assertEqual(
            self.objects.objects[stored.object_key],
            b"\x00\xff\x10opaque\x00",
        )
        self.assertEqual(
            self.student2.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            ),
            (stored,),
        )
        token = self.student2.issue_read_token(
            object_key=stored.object_key,
            participant_id="student-2",
            ttl_seconds=120,
        )
        self.assertEqual(token, "read-student-2-120")
        self.assertEqual(
            self.objects.token_calls,
            [(stored.object_key, "student-2", 120)],
        )
        self.service.integrity_check()

    def test_scan_blocks_before_durable_storage_or_history(self):
        prepared = self.prepared(attachment_id="blocked-a0")
        self.scanner.state = "blocked"

        result = self.student1.upload(prepared)

        self.assertEqual(result.transfer_state, "failed")
        self.assertEqual(result.scan_state, "blocked")
        self.assertEqual(self.objects.objects, {})
        self.assertEqual(
            self.student1.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            ),
            (),
        )

    def test_scanner_failure_is_sanitized_to_retryable_failed_metadata(self):
        class BrokenScanner:
            def scan(self, **_kwargs):
                raise RuntimeError("scanner secret/path detail")

        service = ClassroomFileServerService(
            store=self.store,
            authorization=self.auth,
            scanner=BrokenScanner(),
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )
        client = ClassroomFileServerClient(
            service=service,
            trusted_caller_identity="student-1",
        )

        result = client.upload(self.prepared(attachment_id="scan-failed-a0"))

        self.assertEqual(result.transfer_state, "failed")
        self.assertEqual(result.scan_state, "failed")
        self.assertEqual(self.objects.objects, {})

    def test_authoritative_quota_counts_concurrent_reservations(self):
        first = self.prepared(
            attachment_id="quota-a0",
            content=b"a" * 60,
        )
        second = self.prepared(
            attachment_id="quota-a1",
            content=b"b" * 60,
        )

        self.student1.upload(first)
        with self.assertRaises(CollaborationQuotaError):
            self.student1.upload(second)

        self.assertEqual(
            len(
                self.student1.history_after(
                    room_id="room-1",
                    after_sequence=None,
                    limit=100,
                )
            ),
            1,
        )

    def test_ambiguous_object_write_retries_same_reservation_and_sequence(self):
        prepared = self.prepared(
            attachment_id="ambiguous-a0",
            content=b"retry exact bytes",
        )
        self.objects.raise_after_put_once = True

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.student1.upload(prepared)

        scan_calls = len(self.scanner.calls)
        self.scanner.state = "blocked"
        recovered = self.student1.retry(prepared)

        self.assertEqual(recovered.sequence_no, 0)
        self.assertEqual(recovered.transfer_state, "stored")
        self.assertEqual(len(self.scanner.calls), scan_calls)
        self.assertEqual(len(self.objects.put_calls), 2)
        self.assertEqual(
            self.student1.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            ),
            (recovered,),
        )

    def test_exact_accepted_resend_does_not_depend_on_later_scanner_result(self):
        prepared = self.prepared(attachment_id="accepted-before-scan-shift")
        accepted = self.student1.upload(prepared)
        scan_calls = len(self.scanner.calls)
        self.scanner.state = "blocked"

        recovered = self.student1.retry(prepared)

        self.assertEqual(recovered, accepted)
        self.assertEqual(len(self.scanner.calls), scan_calls)
        self.assertIn(accepted.object_key, self.objects.objects)

    def test_exact_resend_is_idempotent_and_identity_reuse_conflicts(self):
        prepared = self.prepared(attachment_id="idempotent-a0")
        first = self.student1.upload(prepared)
        second = self.student1.upload(prepared)
        self.assertEqual(first, second)

        changed_content = b"different"
        changed_path = self.root / "changed.bin"
        changed_path.write_bytes(changed_content)
        changed = PreparedFile(
            changed_path,
            replace(
                prepared.metadata,
                display_name="changed.bin",
                size_bytes=len(changed_content),
                sha256=hashlib.sha256(changed_content).hexdigest(),
            ),
        )
        with self.assertRaises(CollaborationConflictError):
            self.student1.upload(changed)

    def test_distinct_concurrent_uploads_get_gap_free_authoritative_sequences(self):
        first = self.prepared(
            attachment_id="race-a0",
            content=b"first",
        )
        second = self.prepared(
            attachment_id="race-a1",
            content=b"second",
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(
                pool.map(
                    lambda item: self.student1.upload(item),
                    (first, second),
                )
            )

        self.assertEqual(
            sorted(item.sequence_no for item in results),
            [0, 1],
        )
        history = self.student1.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=100,
        )
        self.assertEqual(
            tuple(item.sequence_no for item in history),
            (0, 1),
        )
        self.service.integrity_check()

    def test_same_attachment_concurrent_exact_retry_converges(self):
        prepared = self.prepared(
            attachment_id="same-race-a0",
            content=b"same content",
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(
                pool.map(
                    lambda _index: self.student1.upload(prepared),
                    range(2),
                )
            )

        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0].sequence_no, 0)
        self.assertEqual(
            len(
                self.student1.history_after(
                    room_id="room-1",
                    after_sequence=None,
                    limit=100,
                )
            ),
            1,
        )

    def test_cancel_after_accepted_upload_tombstones_and_is_idempotent(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="cancel-a0")
        )

        self.student1.cancel(attachment_id=stored.attachment_id)
        self.student1.cancel(attachment_id=stored.attachment_id)

        history = self.student2.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=100,
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].transfer_state, "deleted")
        updates = self.student2.state_updates_after(
            room_id="room-1",
            after_revision=None,
            limit=100,
        )
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].revision, 0)
        self.assertEqual(updates[0].attachment_id, stored.attachment_id)
        self.assertNotIn(stored.object_key, self.objects.objects)
        self.service.integrity_check()

    def test_delete_failure_keeps_tombstone_and_restart_cleanup(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="delete-recovery-a0")
        )
        self.objects.delete_failures = 1

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object deletion failed",
        ):
            self.student1.cancel(attachment_id=stored.attachment_id)

        tombstone = self.student2.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=100,
        )[0]
        self.assertEqual(tombstone.transfer_state, "deleted")
        reopened_store = ClassroomFileServerSQLiteStore(str(self.db_path))
        reopened = ClassroomFileServerService(
            store=reopened_store,
            authorization=self.auth,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )

        self.assertEqual(reopened.drain_pending_deletions(), 1)
        self.assertNotIn(stored.object_key, self.objects.objects)
        self.assertEqual(reopened.drain_pending_deletions(), 0)
        reopened.integrity_check()

    def test_ambiguous_put_then_cancel_delete_failure_recovers_after_restart(self):
        prepared = self.prepared(attachment_id="provisional-cancel-recovery")
        self.objects.raise_after_put_once = True
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.student1.upload(prepared)
        self.assertIn(prepared.metadata.object_key, self.objects.objects)

        self.objects.delete_failures = 1
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object deletion failed",
        ):
            self.student1.cancel(
                attachment_id=prepared.metadata.attachment_id,
            )

        self.assertEqual(
            self.student1.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            ),
            (),
        )
        reopened = ClassroomFileServerService(
            store=ClassroomFileServerSQLiteStore(str(self.db_path)),
            authorization=self.auth,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )
        self.assertEqual(reopened.drain_pending_deletions(), 1)
        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        reopened.integrity_check()

        rebound = ClassroomFileServerClient(
            service=reopened,
            trusted_caller_identity="student-1",
        )
        rebound.cancel(attachment_id=prepared.metadata.attachment_id)
        self.assertEqual(reopened.drain_pending_deletions(), 0)

    def test_cancel_unaccepted_identity_is_safe_idempotent_noop(self):
        self.student1.cancel(attachment_id="never-accepted")
        self.student1.cancel(attachment_id="never-accepted")
        self.assertEqual(self.objects.delete_calls, [])

    def test_download_identity_cannot_be_spoofed_by_bound_client(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="download-bound-a0")
        )
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "does not match bound caller",
        ):
            self.student2.issue_read_token(
                object_key=stored.object_key,
                participant_id="student-1",
                ttl_seconds=60,
            )

    def test_unauthorized_room_history_fails_closed(self):
        outsider = ClassroomFileServerClient(
            service=self.service,
            trusted_caller_identity="outsider",
        )
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "not authorized",
        ):
            outsider.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            )

    def test_client_rejects_file_changed_after_preparation(self):
        prepared = self.prepared(attachment_id="changed-on-disk-a0")
        prepared.local_path.write_bytes(b"mutated")
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "changed before server upload",
        ):
            self.student1.upload(prepared)
        self.assertEqual(self.objects.put_calls, [])

    def test_history_and_state_wire_bounds_fail_closed(self):
        with self.assertRaises(ClassroomFileServerError):
            self.student1.history_after(
                room_id="room-1",
                after_sequence=-1,
                limit=1,
            )
        with self.assertRaises(ClassroomFileServerError):
            self.student1.state_updates_after(
                room_id="room-1",
                after_revision=None,
                limit=0,
            )

    def test_upload_rejects_terminal_sequence_gap_before_object_write(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="gap-existing-a0")
        )
        with self.store._connect() as db, db:
            db.execute(
                "UPDATE classroom_file_server_attachments "
                "SET sequence_no=5 WHERE attachment_id=?",
                (stored.attachment_id,),
            )

        prepared = self.prepared(
            attachment_id="gap-new-a1",
            content=b"must not reach durable object store",
        )
        put_calls_before = len(self.objects.put_calls)

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "authoritative file sequence has a gap",
        ):
            self.student1.upload(prepared)

        self.assertEqual(len(self.objects.put_calls), put_calls_before)
        with self.store._connect() as db:
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (prepared.metadata.attachment_id,),
                ).fetchone()
            )

    def test_cancel_rejects_state_revision_gap_without_tombstone_or_delete(self):
        first = self.student1.upload(
            self.prepared(attachment_id="revision-gap-a0")
        )
        second = self.student1.upload(
            self.prepared(attachment_id="revision-gap-a1")
        )
        self.student1.cancel(attachment_id=first.attachment_id)
        with self.store._connect() as db, db:
            db.execute(
                "UPDATE classroom_file_server_state_updates "
                "SET revision=2 WHERE attachment_id=?",
                (first.attachment_id,),
            )
        delete_calls_before = len(self.objects.delete_calls)

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "attachment state revision has a gap",
        ):
            self.student1.cancel(attachment_id=second.attachment_id)

        self.assertEqual(len(self.objects.delete_calls), delete_calls_before)
        self.assertIn(second.object_key, self.objects.objects)
        current = self.store.attachment_for_object_key(second.object_key)
        self.assertIsNotNone(current)
        self.assertEqual(current.transfer_state, "stored")

    def test_corrupt_terminal_sequence_fails_integrity(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="corrupt-a0")
        )
        with self.store._connect() as db:
            db.execute(
                "UPDATE classroom_file_server_attachments "
                "SET sequence_no=5 WHERE attachment_id=?",
                (stored.attachment_id,),
            )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "sequence gap",
        ):
            self.service.integrity_check()


if __name__ == "__main__":
    unittest.main()
