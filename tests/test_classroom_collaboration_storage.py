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

    def test_v5_sequence_index_upgrades_without_leaving_legacy_index(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
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
        self.store.append_message(message)
        self.store.register_attachment(attachment)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("DROP TABLE collaboration_attachment_state_cursors")
            db.execute(
                "UPDATE collaboration_schema_meta SET value=3 "
                "WHERE key='schema_version'"
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

    def test_message_identity_and_room_sequence_cannot_overwrite(self) -> None:
        self.store.append_message(ChatMessageMetadata("m1", "room", "teacher", 0, "Hello"))
        with self.assertRaises(CollaborationConflictError):
            self.store.append_message(ChatMessageMetadata("m1", "room", "teacher", 0, "Changed"))
        with self.assertRaises(CollaborationConflictError):
            self.store.append_message(ChatMessageMetadata("m2", "room", "student", 0, "Collision"))

    def test_hidden_message_is_retained_but_removed_from_default_active_view(self) -> None:
        self.store.append_message(ChatMessageMetadata("m1", "room", "teacher", 0, "Moderated"))
        hidden = self.store.set_message_hidden("m1", True)
        self.assertTrue(hidden.hidden)
        self.assertEqual(self.store.room_messages("room"), ())
        self.assertEqual(self.store.room_messages("room", include_hidden=True), (hidden,))

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
