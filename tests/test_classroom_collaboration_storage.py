from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
    CollaborationConflictError,
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
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(
                db.execute("SELECT value FROM collaboration_schema_meta WHERE key='schema_version'").fetchone()[0], 1
            )
        ClassroomCollaborationSQLiteStore(str(self.db_path)).integrity_check()

    def test_messages_are_ordered_and_reconnect_is_idempotent(self) -> None:
        first = ChatMessageMetadata("m1", "room", "teacher", 0, "Hello")
        second = ChatMessageMetadata("m2", "room", "student", 1, "Hi")
        self.assertEqual(self.store.append_message(first), first)
        self.assertEqual(self.store.append_message(first), first)
        self.store.append_message(second)
        self.assertEqual(self.store.room_messages("room"), (first, second))

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

    def test_attachment_metadata_round_trip_has_hash_scan_and_no_blob_table(self) -> None:
        content = b"opaque arbitrary bytes\x00\xff"
        record = AttachmentMetadata(
            "a1", "room", "student", 0, "lesson.bin", "application/octet-stream", len(content),
            content_sha256(content), "rooms/room/a1", "stored", "persistent", "clean"
        )
        self.assertEqual(self.store.register_attachment(record), record)
        self.assertEqual(self.store.register_attachment(record), record)
        self.assertEqual(self.store.room_attachments("room"), (record,))
        with sqlite3.connect(self.db_path) as db:
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
