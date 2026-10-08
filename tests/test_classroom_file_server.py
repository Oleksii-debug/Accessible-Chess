from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from acs.classroom_collaboration import (
    AttachmentHistoryPage,
    ClassroomCollaborationController,
    FileQuotaPolicy,
    PreparedFile,
    _canonical_object_key,
)
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    ClassroomCollaborationSQLiteStore,
    CollaborationConflictError,
    CollaborationQuotaError,
)
from acs.classroom_realtime_media import ClassroomRole
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


class SingleStudentRoster:
    def participant_ids(self):
        return ("student-1",)

    def role_for(self, participant_id):
        if participant_id != "student-1":
            raise KeyError(participant_id)
        return ClassroomRole.STUDENT

    def board_control_allowed(self, participant_id):
        return participant_id == "student-1"


class UnusedChat:
    def send_message(self, _draft):
        raise AssertionError("chat transport must not be used by file integration")

    def history_after(self, **_kwargs):
        raise AssertionError("chat transport must not be used by file integration")

    def state_updates_after(self, **_kwargs):
        raise AssertionError("chat transport must not be used by file integration")

    def apply_moderation(self, _commands):
        raise AssertionError("chat transport must not be used by file integration")


class FakeScanner:
    def __init__(self):
        self.state = "clean"
        self.calls = []
        self.after_scan = None

    def scan(self, **kwargs):
        self.calls.append(kwargs)
        if self.after_scan is not None:
            self.after_scan()
        return self.state


class FakeObjectStore:
    def __init__(self):
        self.objects = {}
        self.put_calls = []
        self.status_calls = []
        self.delete_calls = []
        self.token_calls = []
        self.raise_before_put_once = False
        self.raise_after_put_once = False
        self.status_failures = 0
        self.after_status = None
        self.delete_failures = 0

    def stored_sha256(self, *, object_key):
        self.status_calls.append(object_key)
        if self.status_failures:
            self.status_failures -= 1
            raise RuntimeError("status unavailable")
        content = self.objects.get(object_key)
        result = None if content is None else hashlib.sha256(content).hexdigest()
        if self.after_status is not None:
            self.after_status()
        return result

    def put(self, *, object_key, content, expected_sha256):
        self.put_calls.append((object_key, bytes(content), expected_sha256))
        if self.raise_before_put_once:
            self.raise_before_put_once = False
            raise RuntimeError("write failed before storage")
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

    def test_store_releases_sqlite_file_handle_after_operation(self):
        # Windows refuses this rename while any SQLite connection still owns
        # the database file. This is a direct regression for WinError 32.
        renamed = self.root / "file-server-renamed.sqlite3"
        self.assertEqual(self.store.history_after("room-1", None, limit=1).items, ())
        self.db_path.rename(renamed)
        renamed.rename(self.db_path)
        self.assertTrue(self.db_path.exists())

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

    def test_store_rejects_versioned_but_incompatible_schema_on_restart(self):
        path = self.root / "incompatible-v1.sqlite3"
        with sqlite3.connect(path) as db:
            db.executescript(
                """
                CREATE TABLE classroom_file_server_meta(
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                INSERT INTO classroom_file_server_meta(key,value)
                VALUES('schema_version',1);
                CREATE TABLE classroom_file_server_attachments(
                    attachment_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sequence_no INTEGER,
                    transfer_state TEXT NOT NULL
                );
                CREATE UNIQUE INDEX uq_classroom_file_server_room_sequence
                ON classroom_file_server_attachments(room_id, sequence_no)
                WHERE transfer_state IN ('stored','deleted');
                CREATE TABLE classroom_file_server_state_updates(
                    room_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    attachment_id TEXT NOT NULL,
                    transfer_state TEXT NOT NULL,
                    scan_state TEXT NOT NULL,
                    PRIMARY KEY(room_id, revision),
                    FOREIGN KEY(attachment_id)
                        REFERENCES classroom_file_server_attachments(attachment_id)
                );
                """
            )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "schema columns are incompatible",
        ):
            ClassroomFileServerSQLiteStore(str(path))

    def test_store_sanitizes_partial_schema_migration_failure(self):
        path = self.root / "partial-v1.sqlite3"
        with sqlite3.connect(path) as db:
            db.executescript(
                """
                CREATE TABLE classroom_file_server_meta(
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                CREATE TABLE classroom_file_server_attachments(
                    attachment_id TEXT PRIMARY KEY
                );
                """
            )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "schema migration failed",
        ) as raised:
            ClassroomFileServerSQLiteStore(str(path))
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("already exists", str(raised.exception).lower())

    def test_service_rejects_object_store_without_reconciliation_status(self):
        class CanonicalOnlyObjectStore:
            def put(self, *, object_key, content, expected_sha256):
                pass

            def issue_read_token(self, *, object_key, participant_id, ttl_seconds):
                return "token"

            def delete(self, *, object_key):
                pass

        with self.assertRaisesRegex(
            TypeError,
            "stored_sha256 reconciliation",
        ):
            ClassroomFileServerService(
                store=self.store,
                authorization=self.auth,
                scanner=self.scanner,
                object_store=CanonicalOnlyObjectStore(),
                quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
            )

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
            ).attachments

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
            ).attachments,
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
            ).attachments,
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

    def test_oversized_upload_is_rejected_before_server_scan(self):
        prepared = self.prepared(
            attachment_id="oversized-before-scan",
            content=b"x" * 65,
        )

        with self.assertRaises(CollaborationQuotaError):
            self.student1.upload(prepared)

        self.assertEqual(self.scanner.calls, [])
        self.assertEqual(self.objects.put_calls, [])
        self.assertEqual(
            self.student1.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            ).attachments,
            (),
        )

    def test_membership_revoked_during_scan_cannot_reserve_or_store(self):
        prepared = self.prepared(
            attachment_id="revoked-during-scan-a0",
            content=b"must never become durable",
        )
        self.scanner.after_scan = lambda: self.auth.members.discard(
            ("student-1", "room-1")
        )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "not authorized",
        ):
            self.student1.upload(prepared)

        self.assertEqual(self.objects.put_calls, [])
        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        with self.store._connect() as db:
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (prepared.metadata.attachment_id,),
                ).fetchone()
            )

    def test_membership_revoked_during_status_reconciliation_cannot_finalize(self):
        prepared = self.prepared(
            attachment_id="revoked-during-status-a0",
            content=b"already durable but not finalized",
        )
        self.objects.raise_after_put_once = True
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.student1.upload(prepared)

        self.objects.after_status = lambda: self.auth.members.discard(
            ("student-1", "room-1")
        )
        put_calls = len(self.objects.put_calls)
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "not authorized",
        ):
            self.student1.retry(prepared)

        self.assertEqual(len(self.objects.put_calls), put_calls)
        self.assertIn(prepared.metadata.object_key, self.objects.objects)
        self.assertEqual(
            self.student1._service._store.existing_upload(prepared.metadata),
            (None, True),
        )

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
                ).attachments
            ),
            1,
        )

    def test_pending_deleted_bytes_continue_to_count_against_room_quota(self):
        first = self.prepared(
            attachment_id="pending-delete-quota-a0",
            content=b"a" * 60,
        )
        second = self.prepared(
            attachment_id="pending-delete-quota-a1",
            content=b"b" * 60,
        )
        stored = self.student1.upload(first)
        self.objects.delete_failures = 1

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object deletion failed",
        ):
            self.student1.cancel(attachment_id=stored.attachment_id)

        put_calls = len(self.objects.put_calls)
        with self.assertRaises(CollaborationQuotaError):
            self.student1.upload(second)
        self.assertEqual(len(self.objects.put_calls), put_calls)

        self.assertEqual(self.service.drain_pending_deletions(), 1)
        replacement = self.student1.upload(second)
        self.assertEqual(replacement.sequence_no, 1)
        self.assertEqual(replacement.transfer_state, "stored")
        self.service.integrity_check()

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
        # Retry observes the already durable object and finalizes metadata;
        # it must not blindly execute a second PUT after lost acknowledgement.
        self.assertEqual(len(self.objects.put_calls), 1)
        self.assertGreaterEqual(
            self.objects.status_calls.count(prepared.metadata.object_key),
            2,
        )
        self.assertEqual(
            self.student1.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            ).attachments,
            (recovered,),
        )

    def test_ambiguous_put_definitely_absent_retries_exact_bytes_once(self):
        prepared = self.prepared(
            attachment_id="ambiguous-absent-a0",
            content=b"retry after known absent",
        )
        self.objects.raise_before_put_once = True

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.student1.upload(prepared)

        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        recovered = self.student1.retry(prepared)

        self.assertEqual(recovered.transfer_state, "stored")
        self.assertEqual(len(self.objects.put_calls), 2)
        self.assertEqual(
            self.objects.objects[prepared.metadata.object_key],
            b"retry after known absent",
        )

    def test_ambiguous_retry_fails_closed_when_object_status_is_unknown(self):
        prepared = self.prepared(
            attachment_id="ambiguous-status-a0",
            content=b"provider may already have bytes",
        )
        self.objects.raise_after_put_once = True

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.student1.upload(prepared)

        put_calls = len(self.objects.put_calls)
        self.objects.status_failures = 1
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage status is unavailable",
        ) as raised:
            self.student1.retry(prepared)

        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(len(self.objects.put_calls), put_calls)

    def test_ambiguous_retry_rejects_conflicting_durable_object_without_put(self):
        prepared = self.prepared(
            attachment_id="ambiguous-conflict-a0",
            content=b"expected bytes",
        )
        self.objects.raise_before_put_once = True

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.student1.upload(prepared)

        self.objects.objects[prepared.metadata.object_key] = b"different bytes"
        put_calls = len(self.objects.put_calls)
        with self.assertRaisesRegex(
            CollaborationConflictError,
            "durable object identity conflicts",
        ):
            self.student1.retry(prepared)

        self.assertEqual(len(self.objects.put_calls), put_calls)

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
        ).attachments
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
                ).attachments
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
        ).attachments
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
        ).attachments[0]
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

    def test_deletion_recovery_failure_does_not_block_later_tombstones(self):
        first = self.student1.upload(
            self.prepared(attachment_id="drain-first-a0")
        )
        second = self.student1.upload(
            self.prepared(attachment_id="drain-second-a1")
        )
        self.store.cancel(
            trusted_sender_id="student-1",
            attachment_id=first.attachment_id,
        )
        self.store.cancel(
            trusted_sender_id="student-1",
            attachment_id=second.attachment_id,
        )
        self.objects.delete_failures = 1

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "deletion recovery incomplete",
        ) as raised:
            self.service.drain_pending_deletions()

        self.assertIsNone(raised.exception.__cause__)
        self.assertIn(first.object_key, self.objects.objects)
        self.assertNotIn(second.object_key, self.objects.objects)
        self.assertEqual(
            self.store.pending_deletions(),
            ((first.attachment_id, first.object_key),),
        )

        self.assertEqual(self.service.drain_pending_deletions(), 1)
        self.assertNotIn(first.object_key, self.objects.objects)
        self.assertEqual(self.store.pending_deletions(), ())

    def test_restart_rollback_removes_abandoned_upload_without_client_retry(self):
        prepared = self.prepared(
            attachment_id="restart-rollback-a0",
            content=b"durable but not authoritative",
        )
        self.objects.raise_after_put_once = True
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.student1.upload(prepared)
        self.assertIn(prepared.metadata.object_key, self.objects.objects)

        reopened_store = ClassroomFileServerSQLiteStore(str(self.db_path))
        reopened = ClassroomFileServerService(
            store=reopened_store,
            authorization=self.auth,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )

        self.assertEqual(reopened.rollback_pending_uploads(), 1)
        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        self.assertEqual(reopened_store.pending_deletions(), ())
        with reopened_store._connect() as db:
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (prepared.metadata.attachment_id,),
                ).fetchone()
            )

        rebound = ClassroomFileServerClient(
            service=reopened,
            trusted_caller_identity="student-1",
        )
        stored = rebound.upload(prepared)
        self.assertEqual(stored.sequence_no, 0)
        self.assertEqual(stored.transfer_state, "stored")
        reopened.integrity_check()

    def test_restart_upload_rollback_failure_remains_durable_for_cleanup(self):
        prepared = self.prepared(
            attachment_id="restart-rollback-failure-a0",
            content=b"cleanup later",
        )
        self.objects.raise_after_put_once = True
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable object storage write failed",
        ):
            self.student1.upload(prepared)

        reopened_store = ClassroomFileServerSQLiteStore(str(self.db_path))
        reopened = ClassroomFileServerService(
            store=reopened_store,
            authorization=self.auth,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )
        self.objects.delete_failures = 1

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "durable upload rollback incomplete",
        ) as raised:
            reopened.rollback_pending_uploads()

        self.assertIsNone(raised.exception.__cause__)
        self.assertIn(prepared.metadata.object_key, self.objects.objects)
        self.assertEqual(
            reopened_store.pending_deletions(),
            ((prepared.metadata.attachment_id, prepared.metadata.object_key),),
        )
        self.assertEqual(reopened.drain_pending_deletions(), 1)
        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        reopened.integrity_check()

    def test_unconfirmed_finalize_preserves_already_committed_upload(self):
        prepared = self.prepared(
            attachment_id="finalize-ack-lost-a0",
            content=b"committed before acknowledgement loss",
        )
        original_finalize = self.store.finalize_upload

        def finalize_then_lose_ack(attachment_id):
            original_finalize(attachment_id)
            raise RuntimeError("finalize acknowledgement lost")

        with patch.object(
            self.store,
            "finalize_upload",
            side_effect=finalize_then_lose_ack,
        ):
            recovered = self.student1.upload(prepared)

        self.assertEqual(recovered.transfer_state, "stored")
        self.assertEqual(recovered.sequence_no, 0)
        self.assertIn(recovered.object_key, self.objects.objects)
        self.assertEqual(self.store.pending_deletions(), ())
        self.assertEqual(
            self.student1.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            ).attachments,
            (recovered,),
        )
        self.service.integrity_check()

    def test_cancel_racing_slow_put_cleans_late_object_without_orphan(self):
        prepared = self.prepared(
            attachment_id="cancel-races-put-a0",
            content=b"late durable bytes",
        )
        put_started = threading.Event()
        release_put = threading.Event()
        original_put = self.objects.put

        def delayed_put(**kwargs):
            put_started.set()
            if not release_put.wait(5):
                raise AssertionError("test did not release delayed PUT")
            return original_put(**kwargs)

        with patch.object(self.objects, "put", side_effect=delayed_put):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.student1.upload, prepared)
                self.assertTrue(put_started.wait(5))
                self.student1.cancel(
                    attachment_id=prepared.metadata.attachment_id,
                )
                release_put.set()
                with self.assertRaisesRegex(
                    ClassroomFileServerError,
                    "cancelled before finalization",
                ):
                    future.result(timeout=5)

        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        self.assertEqual(self.store.pending_deletions(), ())
        with self.store._connect() as db:
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (prepared.metadata.attachment_id,),
                ).fetchone()
            )
        self.service.integrity_check()

        # No authoritative history was published, so exact identity reuse is
        # safe after the late bytes were conclusively cleaned.
        stored = self.student1.retry(prepared)
        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(stored.sequence_no, 0)

    def test_cancel_racing_slow_put_persists_late_cleanup_failure(self):
        prepared = self.prepared(
            attachment_id="cancel-races-put-delete-failure-a0",
            content=b"late cleanup must survive",
        )
        put_started = threading.Event()
        release_put = threading.Event()
        original_put = self.objects.put

        def delayed_put(**kwargs):
            put_started.set()
            if not release_put.wait(5):
                raise AssertionError("test did not release delayed PUT")
            return original_put(**kwargs)

        with patch.object(self.objects, "put", side_effect=delayed_put):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.student1.upload, prepared)
                self.assertTrue(put_started.wait(5))
                self.student1.cancel(
                    attachment_id=prepared.metadata.attachment_id,
                )
                self.objects.delete_failures = 1
                release_put.set()
                with self.assertRaisesRegex(
                    ClassroomFileServerError,
                    "cleanup is pending",
                ):
                    future.result(timeout=5)

        self.assertIn(prepared.metadata.object_key, self.objects.objects)
        self.assertEqual(
            self.store.pending_deletions(),
            ((prepared.metadata.attachment_id, prepared.metadata.object_key),),
        )
        reopened_store = ClassroomFileServerSQLiteStore(str(self.db_path))
        reopened = ClassroomFileServerService(
            store=reopened_store,
            authorization=self.auth,
            scanner=self.scanner,
            object_store=self.objects,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )
        self.assertEqual(reopened.drain_pending_deletions(), 1)
        self.assertNotIn(prepared.metadata.object_key, self.objects.objects)
        self.assertEqual(reopened_store.pending_deletions(), ())
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
            ).attachments,
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

    def test_tombstone_committed_during_download_status_blocks_new_token(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="download-tombstone-status-a0")
        )

        def tombstone_only():
            self.store.cancel(
                trusted_sender_id="student-1",
                attachment_id=stored.attachment_id,
            )

        self.objects.after_status = tombstone_only
        token_calls = len(self.objects.token_calls)

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "no longer cleared for download",
        ):
            self.student2.issue_read_token(
                object_key=stored.object_key,
                participant_id="student-2",
                ttl_seconds=60,
            )

        self.assertEqual(len(self.objects.token_calls), token_calls)
        self.assertIn(stored.object_key, self.objects.objects)
        self.assertEqual(self.service.drain_pending_deletions(), 1)

    def test_membership_revoked_during_download_status_cannot_mint_token(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="download-revoked-status-a0")
        )
        self.objects.after_status = lambda: self.auth.members.discard(
            ("student-2", "room-1")
        )
        token_calls = len(self.objects.token_calls)

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "not authorized",
        ):
            self.student2.issue_read_token(
                object_key=stored.object_key,
                participant_id="student-2",
                ttl_seconds=60,
            )

        self.assertEqual(len(self.objects.token_calls), token_calls)

    def test_resource_actions_reject_mismatched_authenticated_room_before_effects(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="room-bound-resource-a0")
        )
        token_calls = len(self.objects.token_calls)
        delete_calls = len(self.objects.delete_calls)

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "crossed authenticated room",
        ):
            self.service.issue_read_token(
                trusted_caller_identity="student-1",
                object_key=stored.object_key,
                ttl_seconds=60,
                expected_room_id="room-2",
            )
        self.assertEqual(token_calls, len(self.objects.token_calls))

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "crossed authenticated room",
        ):
            self.service.cancel(
                trusted_caller_identity="student-1",
                attachment_id=stored.attachment_id,
                expected_room_id="room-2",
            )
        current = self.store.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=10,
        ).attachments[0]
        self.assertEqual("stored", current.transfer_state)
        self.assertIn(stored.object_key, self.objects.objects)
        self.assertEqual(delete_calls, len(self.objects.delete_calls))

        delete_target = self.student1.upload(
            self.prepared(attachment_id="room-bound-delete-a1")
        )
        tombstone, pending_key = self.store.cancel(
            trusted_sender_id="student-1",
            attachment_id=delete_target.attachment_id,
        )
        self.assertIsNotNone(tombstone)
        self.assertEqual(delete_target.object_key, pending_key)
        delete_calls = len(self.objects.delete_calls)

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "crossed authenticated room",
        ):
            self.service.delete_object(
                trusted_caller_identity="student-1",
                object_key=delete_target.object_key,
                expected_room_id="room-2",
            )
        self.assertIn(delete_target.object_key, self.objects.objects)
        self.assertEqual(delete_calls, len(self.objects.delete_calls))

    def test_read_token_rejects_durable_bytes_that_no_longer_match_metadata(self):
        stored = self.student1.upload(
            self.prepared(
                attachment_id="download-integrity-a0",
                content=b"original clean bytes",
            )
        )
        self.objects.objects[stored.object_key] = b"tampered after scan"
        token_calls = len(self.objects.token_calls)

        with self.assertRaisesRegex(
            CollaborationConflictError,
            "durable object integrity conflicts",
        ):
            self.student2.issue_read_token(
                object_key=stored.object_key,
                participant_id="student-2",
                ttl_seconds=60,
            )

        self.assertEqual(len(self.objects.token_calls), token_calls)

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
            ).attachments

    def test_canonical_controller_uses_file_server_for_progress_and_download(self):
        collaboration_store = ClassroomCollaborationSQLiteStore(
            str(self.root / "controller-collaboration.sqlite3")
        )
        controller = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-1",
            roster=SingleStudentRoster(),
            chat=UnusedChat(),
            files=self.student1,
            store=collaboration_store,
            file_store=self.student1,
            quota=FileQuotaPolicy(max_file_bytes=64, max_room_bytes=96),
        )
        payload = b"controller-server-progress"
        source = self.root / "controller-server-progress.bin"
        source.write_bytes(payload)
        prepared = controller.prepare_file(
            attachment_id="controller-server-progress-a0",
            local_path=source,
            sequence_no=47,
            retention="persistent",
        )
        observed = []

        stored = controller.upload_file(
            prepared,
            on_progress=observed.append,
        )

        self.assertEqual(
            tuple(
                (item.transferred_bytes, item.total_bytes, item.complete)
                for item in observed
            ),
            (
                (0, len(payload), False),
                (len(payload), len(payload), False),
                (len(payload), len(payload), True),
            ),
        )
        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(stored.sequence_no, 0)
        self.assertEqual(
            collaboration_store.room_attachments("room-1"),
            (stored,),
        )
        token = controller.issue_download_token(
            attachment_id=stored.attachment_id,
            ttl_seconds=60,
        )
        self.assertEqual(token, "read-student-1-60")

    def test_client_upload_and_retry_report_canonical_provider_progress(self):
        prepared = self.prepared(
            attachment_id="client-progress-a0",
            content=b"provider progress",
        )
        upload_progress = []

        stored = self.student1.upload(
            prepared,
            on_progress=upload_progress.append,
        )

        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(len(upload_progress), 1)
        self.assertEqual(upload_progress[0].attachment_id, stored.attachment_id)
        self.assertEqual(
            (upload_progress[0].transferred_bytes, upload_progress[0].total_bytes),
            (prepared.metadata.size_bytes, prepared.metadata.size_bytes),
        )
        self.assertFalse(upload_progress[0].complete)

        retry_progress = []
        replayed = self.student1.retry(
            prepared,
            on_progress=retry_progress.append,
        )

        self.assertEqual(replayed, stored)
        self.assertEqual(len(retry_progress), 1)
        self.assertEqual(
            (
                retry_progress[0].attachment_id,
                retry_progress[0].transferred_bytes,
                retry_progress[0].total_bytes,
                retry_progress[0].complete,
            ),
            (
                stored.attachment_id,
                prepared.metadata.size_bytes,
                prepared.metadata.size_bytes,
                False,
            ),
        )

    def test_client_reports_monotonic_progress_for_multiple_read_chunks(self):
        payload = b"abcdefghijkl"
        prepared = self.prepared(
            attachment_id="client-progress-chunks-a0",
            content=payload,
        )
        observed = []

        with patch("acs.classroom_file_server._FILE_READ_CHUNK_BYTES", 4):
            stored = self.student1.upload(
                prepared,
                on_progress=observed.append,
            )

        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(
            tuple(
                (item.transferred_bytes, item.total_bytes, item.complete)
                for item in observed
            ),
            (
                (4, len(payload), False),
                (8, len(payload), False),
                (12, len(payload), False),
            ),
        )

    def test_client_rejects_invalid_progress_consumer_before_server_effect(self):
        prepared = self.prepared(
            attachment_id="client-progress-invalid-a0",
            content=b"must not upload",
        )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "progress consumer must be callable",
        ):
            self.student1.upload(
                prepared,
                on_progress=object(),
            )

        self.assertEqual(self.objects.put_calls, [])
        self.assertEqual(self.scanner.calls, [])

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
            ).attachments
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

    def test_history_read_rejects_authoritative_sequence_gap(self):
        first = self.student1.upload(
            self.prepared(attachment_id="read-gap-a0")
        )
        second = self.student1.upload(
            self.prepared(attachment_id="read-gap-a1")
        )
        with self.store._connect() as db, db:
            db.execute(
                "UPDATE classroom_file_server_attachments "
                "SET sequence_no=2 WHERE attachment_id=?",
                (second.attachment_id,),
            )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "history has a sequence gap",
        ):
            self.student2.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            ).attachments
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "history has a sequence gap",
        ):
            self.student2.history_after(
                room_id="room-1",
                after_sequence=first.sequence_no,
                limit=100,
            ).attachments

    def test_history_page_carries_current_state_watermark(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="watermark-a0")
        )

        initial = self.student2.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=100,
        )
        self.assertIsInstance(initial, AttachmentHistoryPage)
        self.assertEqual(initial.attachments, (stored,))
        self.assertIsNone(initial.snapshot_state_revision)

        self.student1.cancel(attachment_id=stored.attachment_id)

        tombstoned = self.student2.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=100,
        )
        self.assertEqual(len(tombstoned.attachments), 1)
        self.assertEqual(tombstoned.attachments[0].transfer_state, "deleted")
        self.assertEqual(tombstoned.snapshot_state_revision, 0)
        self.assertEqual(
            self.student2.state_updates_after(
                room_id="room-1",
                after_revision=tombstoned.snapshot_state_revision,
                limit=100,
            ),
            (),
        )

    def test_history_page_is_atomic_across_concurrent_cancellation(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="watermark-race-a0")
        )
        writer_store = ClassroomFileServerSQLiteStore(str(self.db_path))
        snapshot_rows_read = threading.Event()
        writer_done = threading.Event()
        original_connect = self.store._connect

        class CoordinatedCursor:
            def __init__(self, cursor, after_fetch=None):
                self._cursor = cursor
                self._after_fetch = after_fetch

            def fetchall(self):
                rows = self._cursor.fetchall()
                if self._after_fetch is not None:
                    callback = self._after_fetch
                    self._after_fetch = None
                    callback()
                return rows

            def fetchone(self):
                return self._cursor.fetchone()

            def __getattr__(self, name):
                return getattr(self._cursor, name)

        class CoordinatedConnection:
            def __init__(self, db):
                self._db = db

            def execute(self, sql, parameters=()):
                cursor = self._db.execute(sql, parameters)
                normalized = " ".join(str(sql).split())
                after_fetch = (
                    pause_after_attachment_snapshot
                    if normalized.startswith(
                        "SELECT * FROM classroom_file_server_attachments"
                    )
                    and "transfer_state IN ('stored','deleted')" in normalized
                    else None
                )
                return CoordinatedCursor(cursor, after_fetch)

            def commit(self):
                return self._db.commit()

            def rollback(self):
                return self._db.rollback()

            def close(self):
                return self._db.close()

        def pause_after_attachment_snapshot():
            snapshot_rows_read.set()
            if not writer_done.wait(5):
                raise AssertionError("concurrent cancellation did not complete")

        def cancel_concurrently():
            if not snapshot_rows_read.wait(5):
                raise AssertionError("history snapshot did not begin")
            try:
                writer_store.cancel(
                    trusted_sender_id="student-1",
                    attachment_id=stored.attachment_id,
                )
            finally:
                writer_done.set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(cancel_concurrently)
            with patch.object(
                self.store,
                "_connect",
                side_effect=lambda: CoordinatedConnection(original_connect()),
            ):
                during_race = self.store.history_after(
                    room_id="room-1",
                    after_sequence=None,
                    limit=100,
                )
            future.result(timeout=5)

        # The page must describe one database snapshot: because attachment rows
        # were read before the concurrent cancellation committed, the watermark
        # must also remain pre-cancellation rather than jumping to revision 0.
        self.assertEqual(during_race.attachments, (stored,))
        self.assertIsNone(during_race.snapshot_state_revision)

        after = self.student2.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=100,
        )
        self.assertEqual(after.attachments[0].transfer_state, "deleted")
        self.assertEqual(after.snapshot_state_revision, 0)

    def test_state_update_read_rejects_authoritative_revision_gap(self):
        first = self.student1.upload(
            self.prepared(attachment_id="read-revision-gap-a0")
        )
        second = self.student1.upload(
            self.prepared(attachment_id="read-revision-gap-a1")
        )
        self.student1.cancel(attachment_id=first.attachment_id)
        self.student1.cancel(attachment_id=second.attachment_id)
        with self.store._connect() as db, db:
            db.execute(
                "UPDATE classroom_file_server_state_updates "
                "SET revision=2 WHERE attachment_id=?",
                (second.attachment_id,),
            )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "state revision has a gap",
        ):
            self.student2.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=100,
            )

        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "state has a revision gap",
        ):
            self.student2.state_updates_after(
                room_id="room-1",
                after_revision=None,
                limit=100,
            )
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "state has a revision gap",
        ):
            self.student2.state_updates_after(
                room_id="room-1",
                after_revision=0,
                limit=100,
            )

    def test_corrupt_pending_deletion_namespace_fails_before_object_delete(self):
        stored = self.student1.upload(
            self.prepared(attachment_id="corrupt-delete-namespace-a0")
        )
        self.store.cancel(
            trusted_sender_id="student-1",
            attachment_id=stored.attachment_id,
        )
        with self.store._connect() as db, db:
            db.execute(
                "UPDATE classroom_file_server_attachments "
                "SET object_key=? WHERE attachment_id=?",
                ("rooms/room-1/not-the-attachment", stored.attachment_id),
            )

        delete_calls = len(self.objects.delete_calls)
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "stored attachment namespace is invalid",
        ):
            self.service.drain_pending_deletions()

        self.assertEqual(len(self.objects.delete_calls), delete_calls)
        self.assertIn(stored.object_key, self.objects.objects)
        with self.assertRaisesRegex(
            ClassroomFileServerError,
            "stored attachment namespace is invalid",
        ):
            self.service.integrity_check()

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
