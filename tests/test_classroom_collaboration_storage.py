from __future__ import annotations

from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.classroom_domain import MAX_WIRE_INTEGER
from acs.classroom_collaboration_storage import (
    SCHEMA_VERSION,
    AttachmentMetadata,
    AttachmentStateUpdate,
    ChatMessageMetadata,
    ChatMessageStateUpdate,
    ClassroomCollaborationSQLiteStore,
    CollaborationConflictError,
    CollaborationQuotaError,
    CollaborationSequenceGapError,
    CollaborationStorageError,
    content_sha256,
    safe_display_filename,
)


class ClassroomCollaborationSQLiteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "classroom.sqlite3"
        self.store = ClassroomCollaborationSQLiteStore(str(self.db_path))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schema_is_versioned_and_reopen_is_idempotent(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                db.execute("SELECT value FROM collaboration_schema_meta WHERE key='schema_version'").fetchone()[0], SCHEMA_VERSION
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(collaboration_messages)")}
            self.assertIn("sent_at_unix_ms", columns)
            self.assertIn("redacted", columns)
            index_row = db.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='index' AND name='uq_collaboration_attachments_authoritative_sequence'"
            ).fetchone()
            self.assertIsNotNone(index_row)
            normalized_index_sql = " ".join(index_row[0].split()).replace(", ", ",")
            self.assertIn(
                "WHERE transfer_state IN ('stored','deleted')",
                normalized_index_sql,
            )
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='index' AND name='uq_collaboration_attachments_terminal_sequence'"
                ).fetchone()
            )
        ClassroomCollaborationSQLiteStore(str(self.db_path)).integrity_check()
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertIsNotNone(
                db.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='collaboration_attachment_deletions'"
                ).fetchone()
            )
            deletion_columns = {
                row[1]
                for row in db.execute(
                    "PRAGMA table_info(collaboration_attachment_deletions)"
                )
            }
            self.assertIn("completed", deletion_columns)

    def test_partial_v9_redaction_column_must_have_safe_shape(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "ALTER TABLE collaboration_messages RENAME TO old_messages"
            )
            db.execute(
                """
                CREATE TABLE collaboration_messages(
                    message_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                    body TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    sent_at_unix_ms INTEGER
                        CHECK(sent_at_unix_ms IS NULL OR sent_at_unix_ms >= 0),
                    redacted TEXT NOT NULL DEFAULT '0',
                    UNIQUE(room_id, sequence_no)
                )
                """
            )
            db.execute("DROP TABLE old_messages")
            db.execute(
                "UPDATE collaboration_schema_meta SET value=8 "
                "WHERE key='schema_version'"
            )

        with self.assertRaisesRegex(
            CollaborationStorageError,
            "partial redaction schema is incompatible",
        ):
            ClassroomCollaborationSQLiteStore(str(self.db_path))

    def test_partial_v9_redaction_column_resumes_from_old_version_marker(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE collaboration_schema_meta SET value=8 "
                "WHERE key='schema_version'"
            )

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        reopened.integrity_check()
        with closing(sqlite3.connect(self.db_path)) as db:
            version = db.execute(
                "SELECT value FROM collaboration_schema_meta "
                "WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(SCHEMA_VERSION, version)

    def test_v7_upgrade_requeues_tombstones_without_cleanup_receipt(self) -> None:
        tombstone = AttachmentMetadata(
            "v7-missing-receipt",
            "room",
            "teacher",
            0,
            "v7.bin",
            None,
            1,
            "9" * 64,
            "rooms/room/v7-missing-receipt",
            "deleted",
            "persistent",
            "clean",
        )
        self.store.register_attachment(tombstone)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("DROP TABLE collaboration_attachment_deletions")
            db.execute(
                """
                CREATE TABLE collaboration_attachment_deletions(
                    room_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL UNIQUE,
                    object_key TEXT PRIMARY KEY
                )
                """
            )
            db.execute(
                "UPDATE collaboration_schema_meta SET value=7 "
                "WHERE key='schema_version'"
            )

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        self.assertEqual(
            reopened.pending_attachment_deletions("room"),
            (tombstone.object_key,),
        )
        reopened.integrity_check()

    def test_v6_upgrade_backfills_deleted_attachment_cleanup(self) -> None:
        tombstone = AttachmentMetadata(
            "legacy-deleted",
            "room",
            "teacher",
            0,
            "legacy.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/legacy-deleted",
            "deleted",
            "persistent",
            "clean",
        )
        self.store.register_attachment(tombstone)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("DROP TABLE collaboration_attachment_deletions")
            db.execute(
                "UPDATE collaboration_schema_meta SET value=6 "
                "WHERE key='schema_version'"
            )

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        self.assertEqual(
            reopened.pending_attachment_deletions("room"),
            (tombstone.object_key,),
        )
        reopened.integrity_check()

    def test_deleted_attachment_cleanup_intent_is_durable_and_acknowledged(self) -> None:
        tombstone = AttachmentMetadata(
            "cleanup-a0",
            "room",
            "teacher",
            0,
            "cleanup.bin",
            None,
            1,
            "b" * 64,
            "rooms/room/cleanup-a0",
            "deleted",
            "persistent",
            "clean",
        )
        self.store.register_attachment(tombstone)
        self.assertEqual(
            self.store.pending_attachment_deletions("room"),
            (tombstone.object_key,),
        )

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        self.assertEqual(
            reopened.pending_attachment_deletions("room"),
            (tombstone.object_key,),
        )
        reopened.acknowledge_attachment_deletion(
            room_id="room",
            object_key=tombstone.object_key,
        )
        self.assertEqual(reopened.pending_attachment_deletions("room"), ())
        with closing(sqlite3.connect(self.db_path)) as db:
            receipt = db.execute(
                """
                SELECT room_id, attachment_id, object_key, completed
                FROM collaboration_attachment_deletions
                WHERE attachment_id=?
                """,
                (tombstone.attachment_id,),
            ).fetchone()
        self.assertEqual(
            receipt,
            (
                tombstone.room_id,
                tombstone.attachment_id,
                tombstone.object_key,
                1,
            ),
        )

        reopened_again = ClassroomCollaborationSQLiteStore(str(self.db_path))
        reopened_again.integrity_check()
        self.assertEqual(
            reopened_again.pending_attachment_deletions("room"),
            (),
        )
        self.assertEqual(reopened_again.register_attachment(tombstone), tombstone)
        self.assertEqual(reopened_again.pending_attachment_deletions("room"), ())

    def test_schema_version_rejects_noncanonical_sqlite_real(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE collaboration_schema_meta SET value=6.5 "
                "WHERE key='schema_version'"
            )
            stored = db.execute(
                "SELECT value, typeof(value) FROM collaboration_schema_meta "
                "WHERE key='schema_version'"
            ).fetchone()
        self.assertEqual(stored[1], "real")

        with self.assertRaises(CollaborationStorageError):
            ClassroomCollaborationSQLiteStore(str(self.db_path))

        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE collaboration_schema_meta SET value=? "
                "WHERE key='schema_version'",
                (SCHEMA_VERSION,),
            )
        ClassroomCollaborationSQLiteStore(str(self.db_path)).integrity_check()

    def test_corrupt_attachment_cleanup_intent_fails_closed(self) -> None:
        tombstone = AttachmentMetadata(
            "corrupt-cleanup-a0",
            "room",
            "teacher",
            0,
            "corrupt.bin",
            None,
            1,
            "c" * 64,
            "rooms/room/corrupt-cleanup-a0",
            "deleted",
            "persistent",
            "clean",
        )
        self.store.register_attachment(tombstone)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE collaboration_attachment_deletions "
                "SET attachment_id='invalid attachment id' "
                "WHERE object_key=?",
                (tombstone.object_key,),
            )

        with self.assertRaisesRegex(
            CollaborationStorageError,
            "stored attachment deletion intent is invalid",
        ):
            self.store.pending_attachment_deletions("room")
        with self.assertRaisesRegex(
            CollaborationStorageError,
            "stored attachment deletion intent is invalid",
        ):
            self.store.integrity_check()

    def test_deleted_attachment_missing_cleanup_record_fails_integrity(self) -> None:
        tombstone = AttachmentMetadata(
            "missing-cleanup-record",
            "room",
            "teacher",
            0,
            "missing.bin",
            None,
            1,
            "e" * 64,
            "rooms/room/missing-cleanup-record",
            "deleted",
            "persistent",
            "clean",
        )
        self.store.register_attachment(tombstone)
        self.store.acknowledge_attachment_deletion(
            room_id="room",
            object_key=tombstone.object_key,
        )
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "DELETE FROM collaboration_attachment_deletions "
                "WHERE attachment_id=?",
                (tombstone.attachment_id,),
            )

        with self.assertRaisesRegex(
            CollaborationStorageError,
            "tombstone is missing durable deletion record",
        ):
            self.store.integrity_check()

    def test_cleanup_acknowledgement_cannot_cross_room_boundary(self) -> None:
        tombstone = AttachmentMetadata(
            "room-bound-cleanup",
            "room",
            "teacher",
            0,
            "room-bound.bin",
            None,
            1,
            "d" * 64,
            "rooms/room/room-bound-cleanup",
            "deleted",
            "persistent",
            "clean",
        )
        self.store.register_attachment(tombstone)

        with self.assertRaisesRegex(
            CollaborationStorageError,
            "crossed room boundary",
        ):
            self.store.acknowledge_attachment_deletion(
                room_id="other-room",
                object_key=tombstone.object_key,
            )

        self.assertEqual(
            self.store.pending_attachment_deletions("room"),
            (tombstone.object_key,),
        )

    def test_v5_sequence_index_upgrades_without_leaving_legacy_index(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "DROP INDEX uq_collaboration_attachments_authoritative_sequence"
            )
            db.execute("DROP TABLE collaboration_attachment_deletions")
            db.execute(
                """
                CREATE UNIQUE INDEX uq_collaboration_attachments_stored_sequence
                ON collaboration_attachments(room_id, sequence_no)
                WHERE transfer_state='stored'
                """
            )
            db.execute(
                "UPDATE collaboration_schema_meta SET value=5 "
                "WHERE key='schema_version'"
            )

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        reopened.integrity_check()

        with closing(sqlite3.connect(self.db_path)) as db:
            indexes = {
                row[1]
                for row in db.execute(
                    "PRAGMA index_list(collaboration_attachments)"
                )
            }
            version = db.execute(
                "SELECT value FROM collaboration_schema_meta "
                "WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIn(
            "uq_collaboration_attachments_authoritative_sequence",
            indexes,
        )
        self.assertNotIn(
            "uq_collaboration_attachments_stored_sequence",
            indexes,
        )

    def test_v5_failed_upgrade_rolls_back_schema_and_version_atomically(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("DROP TABLE collaboration_attachment_deletions")
            db.execute(
                "DROP INDEX uq_collaboration_attachments_authoritative_sequence"
            )
            db.execute(
                """
                CREATE UNIQUE INDEX uq_collaboration_attachments_stored_sequence
                ON collaboration_attachments(room_id, sequence_no)
                WHERE transfer_state='stored'
                """
            )
            db.execute(
                "UPDATE collaboration_schema_meta SET value=5 "
                "WHERE key='schema_version'"
            )
            db.execute(
                "INSERT INTO collaboration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "stored-a0",
                    "room",
                    "teacher",
                    0,
                    "stored.bin",
                    None,
                    1,
                    "a" * 64,
                    "rooms/room/stored-a0",
                    "stored",
                    "persistent",
                    "clean",
                ),
            )
            db.execute(
                "INSERT INTO collaboration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "deleted-a0",
                    "room",
                    "teacher",
                    0,
                    "deleted.bin",
                    None,
                    1,
                    "b" * 64,
                    "rooms/room/deleted-a0",
                    "deleted",
                    "persistent",
                    "clean",
                ),
            )

        with self.assertRaises(sqlite3.IntegrityError):
            ClassroomCollaborationSQLiteStore(str(self.db_path))

        with closing(sqlite3.connect(self.db_path)) as db:
            version = db.execute(
                "SELECT value FROM collaboration_schema_meta "
                "WHERE key='schema_version'"
            ).fetchone()[0]
            indexes = {
                row[1]
                for row in db.execute(
                    "PRAGMA index_list(collaboration_attachments)"
                )
            }

        self.assertEqual(version, 5)
        self.assertIn(
            "uq_collaboration_attachments_stored_sequence",
            indexes,
        )
        self.assertNotIn(
            "uq_collaboration_attachments_authoritative_sequence",
            indexes,
        )

    def test_v1_message_schema_migrates_without_inventing_historical_timestamp(self) -> None:
        self.db_path.unlink()
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executescript(
                """
                CREATE TABLE collaboration_schema_meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT INTO collaboration_schema_meta(key,value) VALUES('schema_version',1);
                CREATE TABLE collaboration_messages(
                    message_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                    body TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(room_id, sequence_no)
                );
                CREATE INDEX idx_collaboration_messages_room
                    ON collaboration_messages(room_id, sequence_no);
                CREATE TABLE collaboration_attachments(
                    attachment_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                    display_name TEXT NOT NULL,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    sha256 TEXT NOT NULL,
                    object_key TEXT NOT NULL UNIQUE,
                    transfer_state TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    scan_state TEXT NOT NULL,
                    UNIQUE(room_id, sequence_no)
                );
                CREATE INDEX idx_collaboration_attachments_room
                    ON collaboration_attachments(room_id, sequence_no);
                INSERT INTO collaboration_messages
                    VALUES('legacy-m1','room','teacher',0,'Legacy','session',0);
                INSERT INTO collaboration_attachments
                    VALUES(
                        'legacy-pending','room','teacher',0,'pending.bin',NULL,1,
                        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                        'rooms/room/legacy-pending','pending','persistent','pending'
                    );
                """
            )
        migrated = ClassroomCollaborationSQLiteStore(str(self.db_path))
        message = migrated.room_messages("room")[0]
        self.assertEqual("Legacy", message.body)
        self.assertIsNone(message.sent_at_unix_ms)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                SCHEMA_VERSION,
                db.execute(
                    "SELECT value FROM collaboration_schema_meta WHERE key='schema_version'"
                ).fetchone()[0],
            )
            cursor_tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("collaboration_chat_state_cursors", cursor_tables)
            self.assertIn("collaboration_attachment_state_cursors", cursor_tables)

        legacy_pending = migrated.room_attachments("room")[0]
        self.assertEqual(legacy_pending.attachment_id, "legacy-pending")
        authoritative = AttachmentMetadata(
            "remote-stored",
            "room",
            "student",
            0,
            "stored.bin",
            None,
            1,
            "b" * 64,
            "rooms/room/remote-stored",
            "stored",
            "persistent",
            "clean",
        )
        self.assertEqual(migrated.register_attachment(authoritative), authoritative)
        self.assertEqual(
            {item.attachment_id for item in migrated.room_attachments("room")},
            {"legacy-pending", "remote-stored"},
        )

    def test_v3_schema_upgrades_attachment_state_cursor_without_rebuilding_data(self) -> None:
        self.db_path.unlink()
        message = ChatMessageMetadata(
            "v3-message",
            "room",
            "teacher",
            0,
            "Keep me",
            sent_at_unix_ms=1700000000000,
        )
        attachment = AttachmentMetadata(
            "v3-attachment",
            "room",
            "teacher",
            0,
            "keep.bin",
            None,
            1,
            "9" * 64,
            "rooms/room/v3-attachment",
            "stored",
            "persistent",
            "clean",
        )
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "CREATE TABLE collaboration_schema_meta("
                "key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
            db.execute(
                "INSERT INTO collaboration_schema_meta(key,value) "
                "VALUES('schema_version',3)"
            )
            db.execute(
                """
                CREATE TABLE collaboration_messages(
                    message_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                    body TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    sent_at_unix_ms INTEGER
                        CHECK(sent_at_unix_ms IS NULL OR sent_at_unix_ms >= 0),
                    UNIQUE(room_id, sequence_no)
                )
                """
            )
            db.execute(
                "CREATE INDEX idx_collaboration_messages_room "
                "ON collaboration_messages(room_id, sequence_no)"
            )
            db.execute(
                """
                CREATE TABLE collaboration_attachments(
                    attachment_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                    display_name TEXT NOT NULL,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    sha256 TEXT NOT NULL,
                    object_key TEXT NOT NULL UNIQUE,
                    transfer_state TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    scan_state TEXT NOT NULL,
                    UNIQUE(room_id, sequence_no)
                )
                """
            )
            db.execute(
                "CREATE INDEX idx_collaboration_attachments_room "
                "ON collaboration_attachments(room_id, sequence_no)"
            )
            db.execute(
                """
                CREATE TABLE collaboration_chat_state_cursors(
                    room_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK(revision >= 0)
                )
                """
            )
            db.execute(
                """
                INSERT INTO collaboration_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    message.message_id,
                    message.room_id,
                    message.sender_id,
                    message.sequence_no,
                    message.body,
                    message.retention,
                    int(message.hidden),
                    message.sent_at_unix_ms,
                ),
            )
            db.execute(
                "INSERT INTO collaboration_attachments "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attachment.attachment_id,
                    attachment.room_id,
                    attachment.sender_id,
                    attachment.sequence_no,
                    attachment.display_name,
                    attachment.mime_type,
                    attachment.size_bytes,
                    attachment.sha256,
                    attachment.object_key,
                    attachment.transfer_state,
                    attachment.retention,
                    attachment.scan_state,
                ),
            )

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))

        self.assertEqual(reopened.room_messages("room"), (message,))
        self.assertEqual(reopened.room_attachments("room"), (attachment,))
        self.assertIsNone(reopened.attachment_state_revision("room"))
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM collaboration_schema_meta "
                    "WHERE key='schema_version'"
                ).fetchone()[0],
                SCHEMA_VERSION,
            )
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("collaboration_chat_state_cursors", tables)
        self.assertIn("collaboration_attachment_state_cursors", tables)
        self.assertIn("collaboration_attachment_deletions", tables)
        reopened.integrity_check()

    def test_attachment_state_cursor_is_durable_atomic_and_monotonic(self) -> None:
        record = AttachmentMetadata(
            "a-state",
            "room",
            "teacher",
            0,
            "file.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/a-state",
            "stored",
            "persistent",
            "pending",
        )
        self.store.register_attachment(record)
        self.assertIsNone(self.store.attachment_state_revision("room"))

        clean = AttachmentStateUpdate(
            "room",
            "a-state",
            0,
            "stored",
            "clean",
        )
        self.assertEqual(
            self.store.apply_attachment_state_updates(
                room_id="room",
                updates=(clean,),
            )[0].scan_state,
            "clean",
        )
        self.assertEqual(self.store.attachment_state_revision("room"), 0)

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        self.assertEqual(reopened.attachment_state_revision("room"), 0)
        self.assertEqual(
            reopened.room_attachments("room")[0].scan_state,
            "clean",
        )

        with self.assertRaises(CollaborationStorageError):
            reopened.apply_attachment_state_updates(
                room_id="room",
                updates=(
                    AttachmentStateUpdate(
                        "room",
                        "a-state",
                        1,
                        "deleted",
                        "clean",
                    ),
                    AttachmentStateUpdate(
                        "room",
                        "missing",
                        2,
                        "deleted",
                        "clean",
                    ),
                ),
            )
        self.assertEqual(reopened.attachment_state_revision("room"), 0)
        self.assertEqual(
            reopened.room_attachments("room")[0].transfer_state,
            "stored",
        )

        deleted = reopened.apply_attachment_state_updates(
            room_id="room",
            updates=(
                AttachmentStateUpdate(
                    "room",
                    "a-state",
                    1,
                    "deleted",
                    "clean",
                ),
            ),
        )
        self.assertEqual(deleted[0].transfer_state, "deleted")
        self.assertEqual(reopened.attachment_state_revision("room"), 1)

    def test_message_sync_commits_history_and_state_in_one_transaction(self) -> None:
        incoming = ChatMessageMetadata(
            "sync-message",
            "room",
            "teacher",
            0,
            "Visible briefly",
            sent_at_unix_ms=1700000000000,
        )
        hidden = ChatMessageStateUpdate(
            "room",
            incoming.message_id,
            0,
        )

        persisted = self.store.reconcile_message_sync_atomic(
            room_id="room",
            messages=(incoming,),
            updates=(hidden,),
        )

        self.assertEqual(persisted, (incoming,))
        self.assertEqual(self.store.room_messages("room"), ())
        stored = self.store.room_messages("room", include_hidden=True)
        self.assertEqual(len(stored), 1)
        self.assertTrue(stored[0].hidden)
        self.assertEqual(self.store.chat_state_revision("room"), 0)

    def test_message_sync_rolls_back_history_when_state_reconciliation_fails(self) -> None:
        incoming = ChatMessageMetadata(
            "sync-message",
            "room",
            "teacher",
            0,
            "Must roll back",
            sent_at_unix_ms=1700000000000,
        )
        unknown = ChatMessageStateUpdate(
            "room",
            "missing-message",
            0,
        )

        with self.assertRaises(CollaborationStorageError):
            self.store.reconcile_message_sync_atomic(
                room_id="room",
                messages=(incoming,),
                updates=(unknown,),
            )

        self.assertEqual(
            self.store.room_messages("room", include_hidden=True),
            (),
        )
        self.assertIsNone(self.store.chat_state_revision("room"))

    def test_message_state_cursor_is_durable_atomic_and_monotonic(self) -> None:
        message = ChatMessageMetadata(
            "m-state", "room", "teacher", 0, "Visible",
            sent_at_unix_ms=1700000000000,
        )
        self.store.append_message(message)
        self.assertIsNone(self.store.chat_state_revision("room"))
        self.store.apply_message_state_updates(
            room_id="room",
            updates=(ChatMessageStateUpdate("room", "m-state", 0),),
        )
        self.assertEqual(self.store.room_messages("room"), ())
        hidden = self.store.room_messages("room", include_hidden=True)
        self.assertTrue(hidden[0].hidden)
        self.assertEqual(self.store.chat_state_revision("room"), 0)

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        self.assertEqual(reopened.chat_state_revision("room"), 0)
        self.assertTrue(reopened.room_messages("room", include_hidden=True)[0].hidden)

        with self.assertRaises(CollaborationStorageError):
            reopened.apply_message_state_updates(
                room_id="room",
                updates=(ChatMessageStateUpdate("room", "m-state", 0),),
            )
        self.assertEqual(reopened.chat_state_revision("room"), 0)

    def test_message_state_update_failure_rolls_back_cursor_and_visibility(self) -> None:
        self.store.append_message(
            ChatMessageMetadata(
                "m1", "room", "teacher", 0, "One",
                sent_at_unix_ms=1700000000000,
            )
        )
        with self.assertRaises(CollaborationStorageError):
            self.store.apply_message_state_updates(
                room_id="room",
                updates=(
                    ChatMessageStateUpdate("room", "m1", 0),
                    ChatMessageStateUpdate("room", "missing", 1),
                ),
            )
        self.assertIsNone(self.store.chat_state_revision("room"))
        self.assertFalse(
            self.store.room_messages("room", include_hidden=True)[0].hidden
        )

    def test_messages_are_ordered_and_reconnect_is_idempotent(self) -> None:
        first = ChatMessageMetadata(
            "m1", "room", "teacher", 0, "Hello", sent_at_unix_ms=1700000000000
        )
        second = ChatMessageMetadata(
            "m2", "room", "student", 1, "Hi", sent_at_unix_ms=1700000001000
        )
        self.assertEqual(self.store.append_message(first), first)
        self.assertEqual(self.store.append_message(first), first)
        self.store.append_message(second)
        self.assertEqual(self.store.room_messages("room"), (first, second))

    def test_message_sequence_must_start_at_zero_and_remain_contiguous(self) -> None:
        with self.assertRaises(CollaborationSequenceGapError):
            self.store.append_message(
                ChatMessageMetadata("m5", "room", "teacher", 5, "Missing prefix")
            )
        self.assertEqual(self.store.room_messages("room"), ())

        first = ChatMessageMetadata("m0", "room", "teacher", 0, "First")
        self.store.append_message(first)
        with self.assertRaises(CollaborationSequenceGapError):
            self.store.append_message(
                ChatMessageMetadata("m2", "room", "teacher", 2, "Too early")
            )
        second = ChatMessageMetadata("m1", "room", "student", 1, "Recovered")
        third = ChatMessageMetadata("m2", "room", "teacher", 2, "Now valid")
        self.store.append_message(second)
        self.store.append_message(third)
        self.assertEqual(
            self.store.room_messages("room"),
            (first, second, third),
        )

    def test_live_append_rejects_sequence_after_existing_local_gap(self) -> None:
        first = ChatMessageMetadata("m0", "room", "teacher", 0, "First")
        self.store.append_message(first)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                """
                INSERT INTO collaboration_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    "m2-corrupt",
                    "room",
                    "teacher",
                    2,
                    "Corrupt tail",
                    "session",
                    0,
                    1700000000002,
                ),
            )

        with self.assertRaises(CollaborationSequenceGapError):
            self.store.append_message(
                ChatMessageMetadata(
                    "m3",
                    "room",
                    "teacher",
                    3,
                    "Must wait for recovery",
                    sent_at_unix_ms=1700000000003,
                )
            )

        second = ChatMessageMetadata(
            "m1",
            "room",
            "student",
            1,
            "Recovered gap",
            sent_at_unix_ms=1700000000001,
        )
        self.store.append_message(second)
        third = ChatMessageMetadata(
            "m3",
            "room",
            "teacher",
            3,
            "Now contiguous",
            sent_at_unix_ms=1700000000003,
        )
        self.store.append_message(third)
        self.assertEqual(
            tuple(message.sequence_no for message in self.store.room_messages("room")),
            (0, 1, 2, 3),
        )

    def test_message_identity_and_room_sequence_cannot_overwrite(self) -> None:
        self.store.append_message(ChatMessageMetadata("m1", "room", "teacher", 0, "Hello"))
        with self.assertRaises(CollaborationConflictError):
            self.store.append_message(ChatMessageMetadata("m1", "room", "teacher", 0, "Changed"))
        with self.assertRaises(CollaborationConflictError):
            self.store.append_message(ChatMessageMetadata("m2", "room", "student", 0, "Collision"))

    def test_retention_redaction_clears_body_without_breaking_room_sequence(self) -> None:
        original = ChatMessageMetadata(
            "m-redact",
            "room",
            "teacher",
            0,
            "Private session text",
            "session",
            sent_at_unix_ms=1700000000000,
        )
        self.store.append_message(original)

        self.store.apply_message_state_updates(
            room_id="room",
            updates=(
                ChatMessageStateUpdate(
                    "room",
                    original.message_id,
                    0,
                    hidden=False,
                    redacted=True,
                ),
            ),
        )

        redacted = self.store.room_messages("room", include_hidden=True)[0]
        self.assertEqual("", redacted.body)
        self.assertTrue(redacted.redacted)
        self.assertFalse(redacted.hidden)
        self.assertEqual(0, redacted.sequence_no)
        self.assertEqual(1700000000000, redacted.sent_at_unix_ms)
        self.assertEqual(0, self.store.chat_state_revision("room"))

        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        durable = reopened.room_messages("room", include_hidden=True)[0]
        self.assertEqual("", durable.body)
        self.assertTrue(durable.redacted)

        # Authoritative history replay may retain the original body upstream,
        # but a client that already applied retention redaction must never
        # resurrect expired content from that immutable-history record.
        replayed = reopened.append_message(original)
        self.assertEqual("", replayed.body)
        self.assertTrue(replayed.redacted)
        self.assertEqual(0, replayed.sequence_no)

    def test_retention_redaction_erases_payload_bytes_from_local_sqlite(self) -> None:
        secret = (
            "LOCAL-RETENTION-SECRET-"
            + "nvda-private-classroom-chat-" * 16
        )
        secret_bytes = secret.encode("utf-8")
        original = ChatMessageMetadata(
            "m-physical-redact",
            "room",
            "teacher",
            0,
            secret,
            "session",
            sent_at_unix_ms=1700000000000,
        )
        self.store.append_message(original)
        self.assertIn(secret_bytes, self.db_path.read_bytes())

        self.store.apply_message_state_updates(
            room_id="room",
            updates=(
                ChatMessageStateUpdate(
                    "room",
                    original.message_id,
                    0,
                    hidden=False,
                    redacted=True,
                ),
            ),
        )

        self.assertNotIn(secret_bytes, self.db_path.read_bytes())
        durable = self.store.room_messages("room", include_hidden=True)[0]
        self.assertTrue(durable.redacted)
        self.assertEqual("", durable.body)

    def test_persistent_message_rejects_retention_redaction_atomically(self) -> None:
        persistent = ChatMessageMetadata(
            "m-persistent",
            "room",
            "teacher",
            0,
            "Persistent classroom record",
            "persistent",
            sent_at_unix_ms=1700000000000,
        )
        self.store.append_message(persistent)
        update = ChatMessageStateUpdate(
            "room",
            persistent.message_id,
            0,
            hidden=False,
            redacted=True,
        )

        with self.assertRaisesRegex(
            CollaborationStorageError,
            "persistent chat content cannot be retention-redacted",
        ):
            self.store.apply_message_state_updates(
                room_id="room",
                updates=(update,),
            )
        self.assertEqual(
            (persistent,),
            self.store.room_messages("room", include_hidden=True),
        )
        self.assertIsNone(self.store.chat_state_revision("room"))

        with self.assertRaisesRegex(
            CollaborationStorageError,
            "persistent chat content cannot be retention-redacted",
        ):
            self.store.reconcile_message_sync_atomic(
                room_id="room",
                messages=(),
                updates=(update,),
            )
        self.assertEqual(
            (persistent,),
            self.store.room_messages("room", include_hidden=True),
        )
        self.assertIsNone(self.store.chat_state_revision("room"))

    def test_chat_state_update_can_combine_hide_and_retention_redaction(self) -> None:
        original = ChatMessageMetadata(
            "m-hide-redact",
            "room",
            "teacher",
            0,
            "Remove this content",
            "transient",
            sent_at_unix_ms=1700000000000,
        )
        self.store.append_message(original)
        self.store.apply_message_state_updates(
            room_id="room",
            updates=(
                ChatMessageStateUpdate(
                    "room",
                    original.message_id,
                    0,
                    hidden=True,
                    redacted=True,
                ),
            ),
        )
        stored = self.store.room_messages("room", include_hidden=True)[0]
        self.assertTrue(stored.hidden)
        self.assertTrue(stored.redacted)
        self.assertEqual("", stored.body)
        self.assertEqual((), self.store.room_messages("room"))

    def test_redaction_wire_shapes_fail_closed(self) -> None:
        ChatMessageMetadata(
            "m-redacted",
            "room",
            "teacher",
            0,
            "",
            "session",
            sent_at_unix_ms=1700000000000,
            redacted=True,
        )
        ChatMessageStateUpdate(
            "room",
            "m-redacted",
            0,
            hidden=False,
            redacted=True,
        )
        with self.assertRaises(ValueError):
            ChatMessageMetadata(
                "m-not-redacted",
                "room",
                "teacher",
                0,
                "",
                sent_at_unix_ms=1700000000000,
            )
        with self.assertRaises(ValueError):
            ChatMessageMetadata(
                "m-bad-redacted",
                "room",
                "teacher",
                0,
                "still present",
                sent_at_unix_ms=1700000000000,
                redacted=True,
            )
        with self.assertRaises(ValueError):
            ChatMessageStateUpdate(
                "room",
                "m-redacted",
                0,
                hidden=False,
                redacted=False,
            )
        with self.assertRaisesRegex(
            ValueError,
            "persistent chat content cannot be retention-redacted",
        ):
            ChatMessageMetadata(
                "m-persistent-redacted",
                "room",
                "teacher",
                0,
                "",
                "persistent",
                sent_at_unix_ms=1700000000000,
                redacted=True,
            )

    def test_hidden_message_is_retained_but_removed_from_default_active_view(self) -> None:
        self.store.append_message(ChatMessageMetadata("m1", "room", "teacher", 0, "Moderated"))
        hidden = self.store.set_message_hidden("m1", True)
        self.assertTrue(hidden.hidden)
        self.assertEqual(self.store.room_messages("room"), ())
        self.assertEqual(self.store.room_messages("room", include_hidden=True), (hidden,))

    def test_hidden_message_cannot_be_unhidden_outside_moderation_stream(self) -> None:
        self.store.append_message(
            ChatMessageMetadata("m1", "room", "teacher", 0, "Moderated")
        )
        hidden = self.store.set_message_hidden("m1", True)
        self.assertTrue(hidden.hidden)

        with self.assertRaises(CollaborationStorageError):
            self.store.set_message_hidden("m1", False)

        self.assertEqual(
            self.store.room_messages("room", include_hidden=True),
            (hidden,),
        )

    def test_durable_message_readback_rejects_noncanonical_sqlite_values(self) -> None:
        message = ChatMessageMetadata(
            "m-corrupt",
            "room",
            "teacher",
            0,
            "Stored strictly",
            sent_at_unix_ms=1700000000000,
        )
        self.store.append_message(message)

        corruptions = (
            ("hidden", 2, "integer", 0),
            ("sequence_no", 0.5, "real", 0),
            ("sent_at_unix_ms", 1700000000000.5, "real", 1700000000000),
        )
        for column, corrupt, storage_type, restore in corruptions:
            with self.subTest(column=column):
                with closing(sqlite3.connect(self.db_path)) as db, db:
                    db.execute(
                        f"UPDATE collaboration_messages SET {column}=? "
                        "WHERE message_id='m-corrupt'",
                        (corrupt,),
                    )
                    stored_type = db.execute(
                        f"SELECT typeof({column}) FROM collaboration_messages "
                        "WHERE message_id='m-corrupt'"
                    ).fetchone()[0]
                self.assertEqual(stored_type, storage_type)
                with self.assertRaises(CollaborationStorageError):
                    self.store.room_messages("room")
                with closing(sqlite3.connect(self.db_path)) as db, db:
                    db.execute(
                        f"UPDATE collaboration_messages SET {column}=? "
                        "WHERE message_id='m-corrupt'",
                        (restore,),
                    )

        self.assertEqual(self.store.room_messages("room"), (message,))

    def test_durable_attachment_and_revision_readback_rejects_sqlite_real(self) -> None:
        attachment = AttachmentMetadata(
            "a-corrupt",
            "room",
            "teacher",
            0,
            "strict.bin",
            None,
            8,
            "a" * 64,
            "rooms/room/a-corrupt",
            "stored",
            "persistent",
            "clean",
        )
        self.store.register_attachment(attachment)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE collaboration_attachments SET size_bytes=8.5 "
                "WHERE attachment_id='a-corrupt'"
            )
            self.assertEqual(
                db.execute(
                    "SELECT typeof(size_bytes) FROM collaboration_attachments "
                    "WHERE attachment_id='a-corrupt'"
                ).fetchone()[0],
                "real",
            )
        with self.assertRaises(CollaborationStorageError):
            self.store.room_attachments("room")
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE collaboration_attachments SET size_bytes=8 "
                "WHERE attachment_id='a-corrupt'"
            )
            db.execute(
                "INSERT INTO collaboration_chat_state_cursors(room_id, revision) "
                "VALUES('room', 0.5)"
            )
            db.execute(
                "INSERT INTO collaboration_attachment_state_cursors(room_id, revision) "
                "VALUES('room', 0.5)"
            )

        with self.assertRaises(CollaborationStorageError):
            self.store.chat_state_revision("room")
        with self.assertRaises(CollaborationStorageError):
            self.store.attachment_state_revision("room")

    def test_integrity_check_rejects_semantic_corruption_when_pragma_is_ok(self) -> None:
        self.store.append_message(
            ChatMessageMetadata(
                "m-integrity",
                "room",
                "teacher",
                0,
                "Semantic integrity",
                sent_at_unix_ms=1700000000000,
            )
        )
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE collaboration_messages SET hidden=2 "
                "WHERE message_id='m-integrity'"
            )
            self.assertEqual(
                db.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )

        with self.assertRaises(CollaborationStorageError):
            self.store.integrity_check()

        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE collaboration_messages SET hidden=0 "
                "WHERE message_id='m-integrity'"
            )
            db.execute(
                "INSERT INTO collaboration_chat_state_cursors(room_id, revision) "
                "VALUES('/invalid-room', 0)"
            )
            self.assertEqual(
                db.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )

        with self.assertRaises(CollaborationStorageError):
            self.store.integrity_check()

    def test_hidden_state_requires_strict_boolean(self) -> None:
        self.store.append_message(
            ChatMessageMetadata("m1", "room", "teacher", 0, "Moderated")
        )
        with self.assertRaises(ValueError):
            self.store.set_message_hidden("m1", 1)
        self.assertFalse(
            self.store.room_messages("room", include_hidden=True)[0].hidden
        )

    def test_replay_preserves_hide_and_backfills_legacy_timestamp_once(self) -> None:
        original = ChatMessageMetadata("m1", "room", "teacher", 0, "Moderated")
        self.store.append_message(original)
        hidden = self.store.set_message_hidden("m1", True)

        replay = ChatMessageMetadata(
            "m1",
            "room",
            "teacher",
            0,
            "Moderated",
            sent_at_unix_ms=1700000000000,
        )
        reconciled = self.store.append_message(replay)
        self.assertTrue(reconciled.hidden)
        self.assertEqual(reconciled.sent_at_unix_ms, 1700000000000)
        self.assertEqual(self.store.room_messages("room"), ())
        self.assertEqual(
            self.store.room_messages("room", include_hidden=True),
            (reconciled,),
        )
        self.assertNotEqual(hidden, reconciled)

        with self.assertRaises(CollaborationConflictError):
            self.store.append_message(
                ChatMessageMetadata(
                    "m1",
                    "room",
                    "teacher",
                    0,
                    "Moderated",
                    sent_at_unix_ms=1700000000001,
                )
            )

    def test_remote_hidden_replay_is_monotonic(self) -> None:
        original = ChatMessageMetadata(
            "m1",
            "room",
            "teacher",
            0,
            "Moderated",
            sent_at_unix_ms=1700000000000,
        )
        self.store.append_message(original)
        hidden = self.store.append_message(
            ChatMessageMetadata(
                "m1",
                "room",
                "teacher",
                0,
                "Moderated",
                hidden=True,
                sent_at_unix_ms=1700000000000,
            )
        )
        self.assertTrue(hidden.hidden)
        replay = self.store.append_message(original)
        self.assertTrue(replay.hidden)

    def test_wire_metadata_rejects_bool_sequences_oversize_chat_and_noncanonical_ids(self) -> None:
        with self.assertRaises(ValueError):
            ChatMessageMetadata("m1", "room", "teacher", True, "Hello")
        with self.assertRaises(ValueError):
            ChatMessageMetadata("bad id", "room", "teacher", 0, "Hello")
        with self.assertRaises(ValueError):
            ChatMessageMetadata("m1", "room", "teacher", 0, "x" * 4001)
        with self.assertRaises(ValueError):
            ChatMessageMetadata(
                "m1",
                "room",
                "teacher",
                0,
                "bad" + chr(0xD800),
            )
        with self.assertRaises(ValueError):
            ChatMessageMetadata("m1", "room", "teacher", 0, "Hello", sent_at_unix_ms=True)
        with self.assertRaises(ValueError):
            ChatMessageMetadata("m1", "room", "teacher", 0, "Hello", sent_at_unix_ms=-1)
        with self.assertRaises(ValueError):
            ChatMessageStateUpdate("room", "m1", -1)
        with self.assertRaises(ValueError):
            ChatMessageStateUpdate("room", "m1", 0, hidden=False)
        with self.assertRaises(ValueError):
            ChatMessageMetadata(
                "m1", "room", "teacher", 0, "Hello",
                sent_at_unix_ms=253402300800000,
            )
        with self.assertRaises(ValueError):
            AttachmentMetadata(
                "a1", "room", "teacher", 0, "safe.bin", None, True, "0" * 64,
                "rooms/room/a1", "pending"
            )

    def test_wire_numeric_metadata_uses_canonical_json_safe_integer_bound(self) -> None:
        limit = MAX_WIRE_INTEGER
        ChatMessageMetadata("m-max", "room", "teacher", limit, "ok")
        ChatMessageStateUpdate("room", "m-max", limit)
        AttachmentMetadata(
            "a-max",
            "room",
            "teacher",
            limit,
            "safe.bin",
            None,
            limit,
            "0" * 64,
            "rooms/room/a-max",
            "pending",
        )

        with self.assertRaises(ValueError):
            ChatMessageMetadata("m-over", "room", "teacher", limit + 1, "bad")
        with self.assertRaises(ValueError):
            ChatMessageStateUpdate("room", "m-max", limit + 1)
        with self.assertRaises(ValueError):
            AttachmentMetadata(
                "a-seq-over",
                "room",
                "teacher",
                limit + 1,
                "safe.bin",
                None,
                1,
                "0" * 64,
                "rooms/room/a-seq-over",
                "pending",
            )
        with self.assertRaises(ValueError):
            AttachmentMetadata(
                "a-size-over",
                "room",
                "teacher",
                0,
                "safe.bin",
                None,
                limit + 1,
                "0" * 64,
                "rooms/room/a-size-over",
                "pending",
            )

    def test_object_key_rejects_windows_absolute_colon_backslash_and_empty_segments(self) -> None:
        for key in (
            "C:/outside/a1",
            r"rooms\\room\\a1",
            "rooms//a1",
            "rooms/../a1",
            "/rooms/room/a1",
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    AttachmentMetadata(
                        "a1", "room", "teacher", 0, "safe.bin", None, 1, "0" * 64,
                        key, "pending"
                    )

    def test_filename_and_object_key_reject_traversal(self) -> None:
        for value in ("../secret.txt", "..\\secret.txt", "/tmp/secret.txt"):
            with self.assertRaises(ValueError):
                safe_display_filename(value)
        digest = "0" * 64
        with self.assertRaises(ValueError):
            self.store.register_attachment(
                AttachmentMetadata(
                    "a1", "room", "teacher", 0, "safe.txt", "text/plain", 1, digest,
                    "../outside/a1", "pending"
                )
            )

    def test_safe_filename_normalization_is_display_only(self) -> None:
        self.assertEqual(safe_display_filename("notes:lesson?.txt"), "notes_lesson_.txt")
        self.assertEqual(safe_display_filename("folder/lesson.txt"), "lesson.txt")
        self.assertEqual(
            safe_display_filename("Домашнє завдання — партія №1.pgn"),
            "Домашнє завдання — партія №1.pgn",
        )
        self.assertEqual(
            safe_display_filename("e\u0301tude.pgn"),
            "étude.pgn",
        )
        self.assertEqual(
            safe_display_filename("safe\u202Egnp.exe"),
            "safe_gnp.exe",
        )

    def test_safe_filename_requires_text(self) -> None:
        with self.assertRaises(ValueError):
            safe_display_filename(Path("lesson.pgn"))

    def test_safe_filename_rejects_reserved_windows_device_names(self) -> None:
        for value in (
            "CON",
            "con.txt",
            "PRN.pgn",
            "AUX ",
            "NUL.bin",
            "COM1.zip",
            "LPT9",
            "COM¹",
            "com².txt",
            "COM³.pgn",
            "LPT¹",
            "lpt².zip",
            "LPT³.bin",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    safe_display_filename(value)

    def test_attachment_metadata_round_trip_has_hash_scan_and_no_blob_table(self) -> None:
        content = b"opaque arbitrary bytes\x00\xff"
        record = AttachmentMetadata(
            "a1", "room", "student", 0, "lesson.bin", "application/octet-stream", len(content),
            content_sha256(content), "rooms/room/a1", "stored", "persistent", "clean"
        )
        self.assertEqual(self.store.register_attachment(record), record)
        self.assertEqual(self.store.register_attachment(record), record)
        self.assertEqual(self.store.room_attachments("room"), (record,))
        with closing(sqlite3.connect(self.db_path)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(collaboration_attachments)")}
        self.assertNotIn("content", columns)
        self.assertNotIn("blob", columns)

    def test_attachment_object_key_and_room_sequence_prevent_overwrite(self) -> None:
        base = AttachmentMetadata(
            "a1", "room", "student", 0, "one.bin", None, 1, "0" * 64,
            "rooms/room/a1", "stored", "session", "pending"
        )
        self.store.register_attachment(base)
        with self.assertRaises(CollaborationConflictError):
            self.store.register_attachment(
                AttachmentMetadata(
                    "a2", "room2", "student", 0, "two.bin", None, 1, "1" * 64,
                    "rooms/room/a1", "stored"
                )
            )
        with self.assertRaises(CollaborationConflictError):
            self.store.register_attachment(
                AttachmentMetadata(
                    "a2", "room", "student", 0, "two.bin", None, 1, "1" * 64,
                    "rooms/room/a2", "stored"
                )
            )

    def test_provisional_sequence_does_not_reserve_authoritative_room_sequence(self) -> None:
        pending = AttachmentMetadata(
            "pending-a", "room", "teacher", 0, "pending.bin", None, 1,
            "1" * 64, "rooms/room/pending-a", "pending", "persistent", "pending"
        )
        failed = AttachmentMetadata(
            "failed-a", "room", "teacher", 0, "failed.bin", None, 1,
            "2" * 64, "rooms/room/failed-a", "failed", "persistent", "pending"
        )
        authoritative = AttachmentMetadata(
            "stored-a", "room", "student", 0, "stored.bin", None, 1,
            "3" * 64, "rooms/room/stored-a", "stored", "persistent", "clean"
        )

        self.store.register_attachment(pending)
        self.store.register_attachment(failed)
        self.store.register_attachment(authoritative)
        self.assertEqual(
            tuple(item.attachment_id for item in self.store.room_attachments("room")),
            ("failed-a", "pending-a", "stored-a"),
        )

        deleted = self.store.update_attachment_state(
            authoritative.attachment_id,
            transfer_state="deleted",
        )
        self.assertEqual(deleted.sequence_no, 0)
        with self.assertRaises(CollaborationConflictError):
            self.store.register_attachment(
                AttachmentMetadata(
                    "stored-b", "room", "student", 0, "other.bin", None, 1,
                    "4" * 64, "rooms/room/stored-b", "stored", "persistent", "clean"
                )
            )

    def test_attachment_registration_enforces_room_quota_transactionally(self) -> None:
        first = AttachmentMetadata(
            "a1",
            "room",
            "student",
            0,
            "one.bin",
            None,
            4,
            "0" * 64,
            "rooms/room/a1",
            "pending",
        )
        second = AttachmentMetadata(
            "a2",
            "room",
            "student",
            1,
            "two.bin",
            None,
            3,
            "1" * 64,
            "rooms/room/a2",
            "pending",
        )
        self.assertEqual(
            self.store.register_attachment(first, max_room_bytes=6),
            first,
        )
        self.assertEqual(
            self.store.register_attachment(first, max_room_bytes=6),
            first,
        )
        with self.assertRaises(CollaborationQuotaError):
            self.store.register_attachment(second, max_room_bytes=6)
        self.assertEqual(self.store.room_attachments("room"), (first,))

    def test_windows_filename_limit_counts_utf16_units(self) -> None:
        safe = safe_display_filename("😀" * 200)
        self.assertLessEqual(len(safe.encode("utf-16-le")) // 2, 255)
        self.assertEqual(safe, "😀" * 127)

    def test_provisional_sequences_do_not_reserve_authoritative_room_sequence(self) -> None:
        first = AttachmentMetadata(
            "provisional-a",
            "room",
            "teacher",
            0,
            "first.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/provisional-a",
            "pending",
            "persistent",
            "pending",
        )
        second = AttachmentMetadata(
            "provisional-b",
            "room",
            "teacher",
            0,
            "second.bin",
            None,
            1,
            "b" * 64,
            "rooms/room/provisional-b",
            "pending",
            "persistent",
            "pending",
        )
        self.store.register_attachment(first)
        self.store.register_attachment(second)
        self.store.update_attachment_state(
            first.attachment_id,
            transfer_state="uploading",
        )
        self.store.update_attachment_state(
            second.attachment_id,
            transfer_state="uploading",
        )

        first_authoritative = AttachmentMetadata(
            first.attachment_id,
            first.room_id,
            first.sender_id,
            0,
            first.display_name,
            first.mime_type,
            first.size_bytes,
            first.sha256,
            first.object_key,
            "stored",
            first.retention,
            "clean",
        )
        second_authoritative = AttachmentMetadata(
            second.attachment_id,
            second.room_id,
            second.sender_id,
            1,
            second.display_name,
            second.mime_type,
            second.size_bytes,
            second.sha256,
            second.object_key,
            "stored",
            second.retention,
            "clean",
        )

        self.assertEqual(
            self.store.adopt_authoritative_attachment(first_authoritative),
            first_authoritative,
        )
        self.assertEqual(
            self.store.adopt_authoritative_attachment(second_authoritative),
            second_authoritative,
        )
        self.assertEqual(
            self.store.room_attachments("room"),
            (first_authoritative, second_authoritative),
        )

    def test_deleted_tombstone_keeps_authoritative_sequence_reserved(self) -> None:
        tombstone = AttachmentMetadata(
            "deleted-authority",
            "room",
            "teacher",
            0,
            "deleted.bin",
            None,
            1,
            "c" * 64,
            "rooms/room/deleted-authority",
            "deleted",
            "persistent",
            "clean",
        )
        collision = AttachmentMetadata(
            "replacement",
            "room",
            "teacher",
            0,
            "replacement.bin",
            None,
            1,
            "d" * 64,
            "rooms/room/replacement",
            "stored",
            "persistent",
            "clean",
        )
        self.store.register_attachment(tombstone)

        with self.assertRaises(CollaborationConflictError):
            self.store.register_attachment(collision)

        self.assertEqual(self.store.room_attachments("room"), (tombstone,))

    def test_authoritative_attachment_adoption_replaces_provisional_sequence(self) -> None:
        provisional = AttachmentMetadata(
            "a-authority",
            "room",
            "teacher",
            73,
            "file.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/a-authority",
            "pending",
            "persistent",
            "pending",
        )
        self.store.register_attachment(provisional)
        self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="uploading",
        )
        authoritative = AttachmentMetadata(
            provisional.attachment_id,
            provisional.room_id,
            provisional.sender_id,
            0,
            provisional.display_name,
            provisional.mime_type,
            provisional.size_bytes,
            provisional.sha256,
            provisional.object_key,
            "stored",
            provisional.retention,
            "clean",
        )

        adopted = self.store.adopt_authoritative_attachment(authoritative)

        self.assertEqual(adopted, authoritative)
        self.assertEqual(self.store.room_attachments("room"), (authoritative,))
        self.assertEqual(
            self.store.adopt_authoritative_attachment(authoritative),
            authoritative,
        )

    def test_authoritative_attachment_sequence_conflict_is_atomic(self) -> None:
        occupied = AttachmentMetadata(
            "occupied",
            "room",
            "teacher",
            0,
            "occupied.bin",
            None,
            1,
            "0" * 64,
            "rooms/room/occupied",
            "stored",
            "persistent",
            "clean",
        )
        provisional = AttachmentMetadata(
            "a-authority",
            "room",
            "teacher",
            73,
            "file.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/a-authority",
            "pending",
            "persistent",
            "pending",
        )
        self.store.register_attachment(occupied)
        self.store.register_attachment(provisional)
        uploading = self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="uploading",
        )
        authoritative = AttachmentMetadata(
            provisional.attachment_id,
            provisional.room_id,
            provisional.sender_id,
            0,
            provisional.display_name,
            provisional.mime_type,
            provisional.size_bytes,
            provisional.sha256,
            provisional.object_key,
            "stored",
            provisional.retention,
            "clean",
        )

        with self.assertRaises(CollaborationConflictError):
            self.store.adopt_authoritative_attachment(authoritative)

        self.assertEqual(
            self.store.room_attachments("room"),
            (occupied, uploading),
        )

    def test_deleted_authoritative_sequence_remains_reserved_from_reuse(self) -> None:
        original = AttachmentMetadata(
            "deleted-authority",
            "room",
            "teacher",
            0,
            "old.bin",
            None,
            1,
            "d" * 64,
            "rooms/room/deleted-authority",
            "stored",
            "persistent",
            "clean",
        )
        self.store.register_attachment(original)
        deleted = self.store.apply_attachment_state_updates(
            room_id="room",
            updates=(
                AttachmentStateUpdate(
                    "room",
                    original.attachment_id,
                    0,
                    "deleted",
                    "clean",
                ),
            ),
        )[0]
        self.assertEqual(deleted.transfer_state, "deleted")

        provisional = AttachmentMetadata(
            "replacement",
            "room",
            "teacher",
            0,
            "new.bin",
            None,
            1,
            "e" * 64,
            "rooms/room/replacement",
            "pending",
            "persistent",
            "pending",
        )
        self.assertEqual(self.store.register_attachment(provisional), provisional)
        uploading = self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="uploading",
        )
        authoritative = AttachmentMetadata(
            provisional.attachment_id,
            provisional.room_id,
            provisional.sender_id,
            0,
            provisional.display_name,
            provisional.mime_type,
            provisional.size_bytes,
            provisional.sha256,
            provisional.object_key,
            "stored",
            provisional.retention,
            "clean",
        )

        with self.assertRaises(CollaborationConflictError):
            self.store.adopt_authoritative_attachment(authoritative)

        self.assertEqual(
            self.store.room_attachments("room"),
            (deleted, uploading),
        )

    def test_remote_attachment_batch_rolls_back_on_late_sequence_conflict(self) -> None:
        occupied = AttachmentMetadata(
            "occupied",
            "room",
            "teacher",
            1,
            "occupied.bin",
            None,
            1,
            "0" * 64,
            "rooms/room/occupied",
            "stored",
            "persistent",
            "clean",
        )
        first = AttachmentMetadata(
            "remote-0",
            "room",
            "student",
            0,
            "first.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/remote-0",
            "stored",
            "persistent",
            "clean",
        )
        conflict = AttachmentMetadata(
            "remote-1",
            "room",
            "student",
            1,
            "conflict.bin",
            None,
            1,
            "b" * 64,
            "rooms/room/remote-1",
            "stored",
            "persistent",
            "clean",
        )
        self.store.register_attachment(occupied)

        with self.assertRaises(CollaborationConflictError):
            self.store.register_attachments_atomic((first, conflict))

        self.assertEqual(self.store.room_attachments("room"), (occupied,))

    def test_authoritative_file_storage_rejects_sequence_gaps(self) -> None:
        later = AttachmentMetadata(
            "gap-a1",
            "room",
            "teacher",
            1,
            "gap.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/gap-a1",
            "stored",
            "persistent",
            "clean",
        )

        with self.assertRaisesRegex(
            CollaborationSequenceGapError,
            "attachment sequence has an unresolved gap",
        ):
            self.store.register_attachments_atomic((later,))
        self.assertEqual(self.store.room_attachments("room"), ())

        with self.assertRaisesRegex(
            CollaborationSequenceGapError,
            "attachment sequence has an unresolved gap",
        ):
            self.store.reconcile_attachment_sync_atomic(
                room_id="room",
                attachments=(later,),
                updates=(),
            )
        self.assertEqual(self.store.room_attachments("room"), ())

    def test_direct_failed_upload_adoption_keeps_provisional_sequence(self) -> None:
        provisional = AttachmentMetadata(
            "failed-own",
            "room",
            "teacher",
            77,
            "failed.bin",
            None,
            1,
            "c" * 64,
            "rooms/room/failed-own",
            "pending",
            "persistent",
            "pending",
        )
        self.store.register_attachment(provisional)
        uploading = self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="uploading",
        )
        failed = AttachmentMetadata(
            uploading.attachment_id,
            uploading.room_id,
            uploading.sender_id,
            uploading.sequence_no,
            uploading.display_name,
            uploading.mime_type,
            uploading.size_bytes,
            uploading.sha256,
            uploading.object_key,
            "failed",
            uploading.retention,
            "failed",
        )

        self.assertEqual(
            self.store.adopt_authoritative_attachment(failed),
            failed,
        )
        self.assertEqual(
            self.store.room_attachments("room"),
            (failed,),
        )

    def test_direct_upload_adoption_rejects_missing_authoritative_prefix(self) -> None:
        provisional = AttachmentMetadata(
            "gap-own",
            "room",
            "teacher",
            77,
            "own.bin",
            None,
            1,
            "b" * 64,
            "rooms/room/gap-own",
            "pending",
            "persistent",
            "pending",
        )
        self.store.register_attachment(provisional)
        uploading = self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="uploading",
        )
        authoritative = AttachmentMetadata(
            provisional.attachment_id,
            provisional.room_id,
            provisional.sender_id,
            2,
            provisional.display_name,
            provisional.mime_type,
            provisional.size_bytes,
            provisional.sha256,
            provisional.object_key,
            "stored",
            provisional.retention,
            "clean",
        )

        with self.assertRaisesRegex(
            CollaborationSequenceGapError,
            "attachment sequence has an unresolved gap",
        ):
            self.store.adopt_authoritative_attachment(authoritative)

        self.assertEqual(
            self.store.room_attachments("room"),
            (uploading,),
        )

    def test_attachment_sync_adopts_authority_over_uncertain_local_transfer(self) -> None:
        for local_state in ("uploading", "failed"):
            with self.subTest(local_state=local_state):
                db_path = Path(self.temp.name) / f"uncertain-{local_state}.sqlite3"
                store = ClassroomCollaborationSQLiteStore(str(db_path))
                provisional = AttachmentMetadata(
                    "uncertain-a",
                    "room",
                    "teacher",
                    73,
                    "file.bin",
                    None,
                    1,
                    "f" * 64,
                    "rooms/room/uncertain-a",
                    "pending",
                    "persistent",
                    "pending",
                )
                store.register_attachment(provisional)
                store.update_attachment_state(
                    provisional.attachment_id,
                    transfer_state="uploading",
                )
                if local_state == "failed":
                    store.update_attachment_state(
                        provisional.attachment_id,
                        transfer_state="failed",
                    )
                authoritative = AttachmentMetadata(
                    provisional.attachment_id,
                    provisional.room_id,
                    provisional.sender_id,
                    0,
                    provisional.display_name,
                    provisional.mime_type,
                    provisional.size_bytes,
                    provisional.sha256,
                    provisional.object_key,
                    "stored",
                    provisional.retention,
                    "clean",
                )

                persisted = store.reconcile_attachment_sync_atomic(
                    room_id="room",
                    attachments=(authoritative,),
                    updates=(),
                )

                self.assertEqual(persisted, (authoritative,))
                self.assertEqual(store.room_attachments("room"), (authoritative,))

    def test_attachment_sync_never_restores_blocked_failed_file(self) -> None:
        provisional = AttachmentMetadata(
            "blocked-uncertain",
            "room",
            "teacher",
            73,
            "blocked.bin",
            None,
            1,
            "b" * 64,
            "rooms/room/blocked-uncertain",
            "pending",
            "persistent",
            "pending",
        )
        self.store.register_attachment(provisional)
        self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="uploading",
        )
        blocked = self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="failed",
            scan_state="blocked",
        )
        restored = AttachmentMetadata(
            provisional.attachment_id,
            provisional.room_id,
            provisional.sender_id,
            0,
            provisional.display_name,
            provisional.mime_type,
            provisional.size_bytes,
            provisional.sha256,
            provisional.object_key,
            "stored",
            provisional.retention,
            "clean",
        )

        with self.assertRaisesRegex(
            CollaborationConflictError,
            "blocked attachment cannot be restored",
        ):
            self.store.reconcile_attachment_sync_atomic(
                room_id="room",
                attachments=(restored,),
                updates=(),
            )
        self.assertEqual(self.store.room_attachments("room"), (blocked,))

        tombstone = AttachmentMetadata(
            provisional.attachment_id,
            provisional.room_id,
            provisional.sender_id,
            0,
            provisional.display_name,
            provisional.mime_type,
            provisional.size_bytes,
            provisional.sha256,
            provisional.object_key,
            "deleted",
            provisional.retention,
            "blocked",
        )
        self.assertEqual(
            self.store.reconcile_attachment_sync_atomic(
                room_id="room",
                attachments=(tombstone,),
                updates=(),
            ),
            (tombstone,),
        )
        self.assertEqual(self.store.room_attachments("room"), (tombstone,))

    def test_attachment_sync_rejects_authority_over_mismatched_uncertain_identity(self) -> None:
        provisional = AttachmentMetadata(
            "uncertain-a",
            "room",
            "teacher",
            73,
            "file.bin",
            None,
            1,
            "f" * 64,
            "rooms/room/uncertain-a",
            "pending",
            "persistent",
            "pending",
        )
        self.store.register_attachment(provisional)
        uploading = self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="uploading",
        )
        forged = AttachmentMetadata(
            provisional.attachment_id,
            provisional.room_id,
            provisional.sender_id,
            0,
            "different.bin",
            provisional.mime_type,
            provisional.size_bytes,
            provisional.sha256,
            provisional.object_key,
            "stored",
            provisional.retention,
            "clean",
        )

        with self.assertRaises(CollaborationConflictError):
            self.store.reconcile_attachment_sync_atomic(
                room_id="room",
                attachments=(forged,),
                updates=(),
            )

        self.assertEqual(self.store.room_attachments("room"), (uploading,))

    def test_state_updates_require_authoritative_attachment_history(self) -> None:
        provisional = AttachmentMetadata(
            "state-only-a1",
            "room-a",
            "teacher-1",
            77,
            "state-only.bin",
            "application/octet-stream",
            4,
            content_sha256(b"data"),
            "rooms/room-a/state-only-a1",
            "pending",
            "persistent",
            "pending",
        )
        self.store.register_attachment(provisional)
        uploading = self.store.update_attachment_state(
            provisional.attachment_id,
            transfer_state="uploading",
        )
        update = AttachmentStateUpdate(
            room_id="room-a",
            attachment_id=provisional.attachment_id,
            revision=0,
            transfer_state="stored",
            scan_state="clean",
        )

        for apply_update in (
            lambda: self.store.apply_attachment_state_updates(
                room_id="room-a",
                updates=(update,),
            ),
            lambda: self.store.reconcile_attachment_sync_atomic(
                room_id="room-a",
                attachments=(),
                updates=(update,),
            ),
        ):
            with self.assertRaisesRegex(
                CollaborationStorageError,
                "attachment state update requires authoritative history",
            ):
                apply_update()
            self.assertEqual(
                self.store.room_attachments("room-a"),
                (uploading,),
            )
            self.assertIsNone(self.store.attachment_state_revision("room-a"))

    def test_attachment_sync_commits_history_and_state_in_one_transaction(self) -> None:
        incoming = AttachmentMetadata(
            "remote-sync",
            "room",
            "teacher",
            0,
            "sync.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/remote-sync",
            "stored",
            "persistent",
            "clean",
        )
        deleted = AttachmentStateUpdate(
            room_id="room",
            attachment_id=incoming.attachment_id,
            revision=0,
            transfer_state="deleted",
            scan_state="clean",
        )

        persisted = self.store.reconcile_attachment_sync_atomic(
            room_id="room",
            attachments=(incoming,),
            updates=(deleted,),
        )

        self.assertEqual(persisted, (incoming,))
        current = self.store.room_attachments("room")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].transfer_state, "deleted")
        self.assertEqual(self.store.attachment_state_revision("room"), 0)

    def test_attachment_sync_rolls_back_history_when_state_reconciliation_fails(self) -> None:
        incoming = AttachmentMetadata(
            "remote-sync",
            "room",
            "teacher",
            0,
            "sync.bin",
            None,
            1,
            "a" * 64,
            "rooms/room/remote-sync",
            "stored",
            "persistent",
            "clean",
        )
        unknown = AttachmentStateUpdate(
            room_id="room",
            attachment_id="missing-attachment",
            revision=0,
            transfer_state="deleted",
            scan_state="clean",
        )

        with self.assertRaises(CollaborationStorageError):
            self.store.reconcile_attachment_sync_atomic(
                room_id="room",
                attachments=(incoming,),
                updates=(unknown,),
            )

        self.assertEqual(self.store.room_attachments("room"), ())
        self.assertIsNone(self.store.attachment_state_revision("room"))

    def test_transfer_state_machine_rejects_resurrection_and_invalid_scan_reversal(self) -> None:
        record = AttachmentMetadata(
            "a1", "room", "teacher", 0, "file.bin", None, 1,
            "0" * 64, "rooms/room/a1", "pending", "persistent", "pending"
        )
        self.store.register_attachment(record)
        self.store.update_attachment_state("a1", transfer_state="uploading")
        self.store.update_attachment_state("a1", transfer_state="stored", scan_state="clean")
        with self.assertRaises(Exception):
            self.store.update_attachment_state("a1", transfer_state="uploading")
        with self.assertRaises(Exception):
            self.store.update_attachment_state("a1", transfer_state="stored", scan_state="pending")

    def test_rejoin_reads_durable_persistent_attachment_metadata(self) -> None:
        record = AttachmentMetadata(
            "a1", "room", "teacher", 4, "homework.pgn", "application/x-chess-pgn", 12,
            "a" * 64, "rooms/room/a1", "stored", "persistent", "clean"
        )
        self.store.register_attachment(record)
        reopened = ClassroomCollaborationSQLiteStore(str(self.db_path))
        self.assertEqual(reopened.room_attachments("room"), (record,))

    def test_transfer_and_scan_state_updates_preserve_identity_and_hash(self) -> None:
        record = AttachmentMetadata(
            "a1", "room", "teacher", 0, "file.zip", "application/zip", 10,
            "b" * 64, "rooms/room/a1", "uploading", "persistent", "pending"
        )
        self.store.register_attachment(record)
        updated = self.store.update_attachment_state("a1", transfer_state="stored", scan_state="clean")
        self.assertEqual(updated.attachment_id, record.attachment_id)
        self.assertEqual(updated.sha256, record.sha256)
        self.assertEqual(updated.transfer_state, "stored")
        self.assertEqual(updated.scan_state, "clean")


if __name__ == "__main__":
    unittest.main()
