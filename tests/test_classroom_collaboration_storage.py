from __future__ import annotations

from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.classroom_domain import MAX_WIRE_INTEGER
from acs.classroom_collaboration_storage import (
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
                db.execute("SELECT value FROM collaboration_schema_meta WHERE key='schema_version'").fetchone()[0], 4
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(collaboration_messages)")}
            self.assertIn("sent_at_unix_ms", columns)
        ClassroomCollaborationSQLiteStore(str(self.db_path)).integrity_check()

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
                """
            )
        migrated = ClassroomCollaborationSQLiteStore(str(self.db_path))
        message = migrated.room_messages("room")[0]
        self.assertEqual("Legacy", message.body)
        self.assertIsNone(message.sent_at_unix_ms)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                4,
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
