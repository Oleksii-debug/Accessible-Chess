from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.classroom_collaboration import (
    MAX_SYNC_MESSAGES,
    ChatDraft,
    ChatModerationAction,
    ChatModerationCommand,
    ClassroomCollaborationController,
)
from acs.classroom_collaboration_chat_server import (
    ClassroomChatServerError,
    ClassroomChatServerSQLiteStore,
    ClassroomChatServerService,
    MAX_SERVER_HISTORY_MESSAGES,
    MAX_SERVER_MODERATION_COMMANDS,
)
from acs.classroom_collaboration_storage import ClassroomCollaborationSQLiteStore
from acs.classroom_domain import MAX_WIRE_INTEGER
from acs.classroom_realtime_media import ClassroomRole


ROOM = "room-1"
TEACHER = "teacher-1"
STUDENT = "student-1"
CHAT_SERVER_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "classroom-collaboration-chat-server.yml"
)


class FakeAuthorization:
    def __init__(self) -> None:
        self.send_calls = []
        self.history_calls = []
        self.moderation_calls = []
        self.reject_send = False
        self.reject_history = False
        self.reject_moderation = False
        self.send_result = None
        self.history_result = None
        self.moderation_result = None

    def authorize_chat_send(self, *, room_id, caller_identity, sender_id):
        self.send_calls.append((room_id, caller_identity, sender_id))
        if self.reject_send:
            raise RuntimeError("sensitive membership detail")
        return self.send_result

    def authorize_chat_history(self, *, room_id, caller_identity):
        self.history_calls.append((room_id, caller_identity))
        if self.reject_history:
            raise RuntimeError("sensitive history detail")
        return self.history_result

    def authorize_chat_moderation(self, *, room_id, caller_identity, commands):
        self.moderation_calls.append((room_id, caller_identity, commands))
        if self.reject_moderation:
            raise RuntimeError("sensitive role detail")
        return self.moderation_result


class BoundChatTransport:
    """Bind one trusted transport identity to the provider-neutral server service."""

    def __init__(self, service, participant_id):
        self.service = service
        self.participant_id = participant_id

    def send_message(self, draft):
        return self.service.send_message(
            trusted_caller_identity=self.participant_id,
            draft=draft,
        )

    def history_after(self, *, room_id, after_sequence, limit):
        return self.service.history_after(
            trusted_caller_identity=self.participant_id,
            room_id=room_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def state_updates_after(self, *, room_id, after_revision, limit):
        return self.service.state_updates_after(
            trusted_caller_identity=self.participant_id,
            room_id=room_id,
            after_revision=after_revision,
            limit=limit,
        )

    def apply_moderation(self, commands):
        return self.service.apply_moderation(
            trusted_caller_identity=self.participant_id,
            commands=commands,
        )


class SharedRoster:
    def __init__(self):
        self.roles = {
            TEACHER: ClassroomRole.TEACHER,
            STUDENT: ClassroomRole.STUDENT,
        }

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]


class Clock:
    def __init__(self, value: int = 1700000000000) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> int:
        result = self.value
        self.value += 1000
        self.calls += 1
        return result


class ClassroomChatServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "server.sqlite3"
        self.store = ClassroomChatServerSQLiteStore(self.path)
        self.auth = FakeAuthorization()
        self.clock = Clock()
        self.service = ClassroomChatServerService(
            store=self.store,
            authorization=self.auth,
            clock_unix_ms=self.clock,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def draft(
        self,
        message_id: str,
        body: str = "Hello",
        *,
        sender: str = STUDENT,
        room: str = ROOM,
    ) -> ChatDraft:
        return ChatDraft(message_id, room, sender, body)

    def moderation(
        self,
        operation_id: str,
        *,
        actor: str = TEACHER,
        target: str | None = STUDENT,
        action: ChatModerationAction = ChatModerationAction.SET_SEND_PERMISSION,
        allowed: bool | None = False,
        message_id: str | None = None,
        room: str = ROOM,
    ) -> ChatModerationCommand:
        return ChatModerationCommand(
            operation_id=operation_id,
            room_id=room,
            actor_id=actor,
            target_id=target,
            action=action,
            allowed=allowed,
            message_id=message_id,
        )

    def send(self, draft: ChatDraft):
        return self.service.send_message(
            trusted_caller_identity=draft.sender_id,
            draft=draft,
        )

    def _downgrade_to_legacy_schema(
        self,
        path: Path,
        *,
        version: int,
        keep_state_table: bool,
    ) -> None:
        """Build a real pre-v4 table shape instead of relabelling v4 metadata."""

        if version not in {1, 2, 3}:
            raise AssertionError("legacy fixture version must be 1, 2 or 3")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DROP INDEX IF EXISTS idx_classroom_chat_server_messages_room")
            db.execute(
                "ALTER TABLE classroom_chat_server_messages "
                "RENAME TO classroom_chat_server_messages_v4"
            )
            db.execute(
                """
                CREATE TABLE classroom_chat_server_messages(
                    message_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                    body TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
                    sent_at_unix_ms INTEGER NOT NULL CHECK(sent_at_unix_ms >= 0),
                    UNIQUE(room_id, sequence_no)
                )
                """
            )
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                )
                SELECT
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                FROM classroom_chat_server_messages_v4
                """
            )
            db.execute("DROP TABLE classroom_chat_server_messages_v4")
            db.execute(
                """
                CREATE INDEX idx_classroom_chat_server_messages_room
                ON classroom_chat_server_messages(room_id, sequence_no)
                """
            )

            db.execute(
                "DROP INDEX IF EXISTS "
                "idx_classroom_chat_server_state_updates_message"
            )
            if keep_state_table:
                db.execute(
                    "ALTER TABLE classroom_chat_server_state_updates "
                    "RENAME TO classroom_chat_server_state_updates_v4"
                )
                redaction_rows = db.execute(
                    """
                    SELECT COUNT(*)
                    FROM classroom_chat_server_state_updates_v4
                    WHERE redacted != 0
                    """
                ).fetchone()[0]
                if redaction_rows:
                    raise AssertionError(
                        "cannot downgrade fixture containing redaction state"
                    )
                db.execute(
                    """
                    CREATE TABLE classroom_chat_server_state_updates(
                        room_id TEXT NOT NULL,
                        revision INTEGER NOT NULL CHECK(revision >= 0),
                        message_id TEXT NOT NULL,
                        hidden INTEGER NOT NULL CHECK(hidden = 1),
                        PRIMARY KEY(room_id, revision)
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO classroom_chat_server_state_updates(
                        room_id, revision, message_id, hidden
                    )
                    SELECT room_id, revision, message_id, hidden
                    FROM classroom_chat_server_state_updates_v4
                    """
                )
                db.execute("DROP TABLE classroom_chat_server_state_updates_v4")
                db.execute(
                    """
                    CREATE INDEX idx_classroom_chat_server_state_updates_message
                    ON classroom_chat_server_state_updates(room_id, message_id)
                    """
                )
            else:
                db.execute("DROP TABLE classroom_chat_server_state_updates")

            db.execute(
                """
                UPDATE classroom_chat_server_meta
                SET value=?
                WHERE key='schema_version'
                """,
                (version,),
            )

    def test_store_rejects_ephemeral_database_targets(self) -> None:
        for target in ("", ":memory:"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(
                    ClassroomChatServerError,
                    "durable classroom chat server database path is required",
                ):
                    ClassroomChatServerSQLiteStore(target)

    def test_store_sanitizes_database_open_failure(self) -> None:
        missing_parent = Path(self.tmp.name) / "missing-parent" / "server.sqlite3"
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "database open failed",
        ) as raised:
            ClassroomChatServerSQLiteStore(missing_parent)

        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(missing_parent.exists())

    def test_schema_is_durable_and_integrity_checked(self) -> None:
        self.store.integrity_check()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                4,
                db.execute(
                    "SELECT value FROM classroom_chat_server_meta "
                    "WHERE key='schema_version'"
                ).fetchone()[0],
            )
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertTrue(
            {
                "classroom_chat_server_messages",
                "classroom_chat_server_permissions",
                "classroom_chat_server_moderation_ops",
                "classroom_chat_server_state_updates",
            }.issubset(tables)
        )

    def test_semantic_integrity_rejects_message_sequence_gap(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,0,?)
                """,
                (
                    "gapped-message",
                    ROOM,
                    STUDENT,
                    1,
                    "Gap",
                    "session",
                    1700000000000,
                ),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "message sequence is not contiguous",
        ):
            self.store.integrity_check()

    def test_semantic_integrity_rejects_orphan_moderation_state(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 0, "unknown-message"),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "moderation state references unknown message",
        ):
            self.store.integrity_check()

    def test_semantic_integrity_rejects_hidden_message_without_state_event(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,1,?)
                """,
                (
                    "hidden-without-event",
                    ROOM,
                    STUDENT,
                    0,
                    "Hidden without state event",
                    "session",
                    1700000000000,
                ),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "hidden message state is inconsistent",
        ):
            self.store.integrity_check()

    def test_live_history_rejects_hidden_message_without_state_event(self) -> None:
        sent = self.send(self.draft("hidden-history-without-state"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                UPDATE classroom_chat_server_messages
                SET hidden=1
                WHERE message_id=?
                """,
                (sent.message_id,),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored hidden message state is inconsistent",
        ):
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored hidden message state is inconsistent",
        ):
            self.send(self.draft("hidden-history-without-state"))

    def test_live_state_history_rejects_orphan_moderation_event(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 0, "orphan-live-state"),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored moderation state is inconsistent",
        ):
            self.store.state_updates_after(
                room_id=ROOM,
                after_revision=None,
                limit=10,
            )

    def test_hide_rejects_hidden_target_without_state_event(self) -> None:
        sent = self.send(self.draft("hidden-without-write-event"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                UPDATE classroom_chat_server_messages
                SET hidden=1
                WHERE message_id=?
                """,
                (sent.message_id,),
            )

        hide = self.moderation(
            "hide-corrupt-hidden-target",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored hidden message state is inconsistent",
        ):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(hide,),
            )

        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_moderation_ops
                    WHERE room_id=? AND operation_id=?
                    """,
                    (ROOM, hide.operation_id),
                ).fetchone()
            )
            self.assertEqual(
                0,
                db.execute(
                    """
                    SELECT COUNT(*) FROM classroom_chat_server_state_updates
                    WHERE room_id=?
                    """,
                    (ROOM,),
                ).fetchone()[0],
            )

    def test_hide_rejects_visible_target_with_orphan_state_event(self) -> None:
        sent = self.send(self.draft("visible-with-orphan-state"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 0, sent.message_id),
            )

        hide = self.moderation(
            "hide-corrupt-visible-target",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored visible message state is inconsistent",
        ):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(hide,),
            )

        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                0,
                db.execute(
                    """
                    SELECT hidden FROM classroom_chat_server_messages
                    WHERE message_id=?
                    """,
                    (sent.message_id,),
                ).fetchone()[0],
            )
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_moderation_ops
                    WHERE room_id=? AND operation_id=?
                    """,
                    (ROOM, hide.operation_id),
                ).fetchone()
            )
            self.assertEqual(
                1,
                db.execute(
                    """
                    SELECT COUNT(*) FROM classroom_chat_server_state_updates
                    WHERE room_id=?
                    """,
                    (ROOM,),
                ).fetchone()[0],
            )

    def test_semantic_integrity_accepts_atomic_hide_state(self) -> None:
        sent = self.send(self.draft("integrity-hide-message"))
        hide = self.moderation(
            "integrity-hide-operation",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(hide,),
        )

        self.store.integrity_check()

    def test_corrupt_persisted_message_and_permission_flags_fail_closed(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    "corrupt-hidden",
                    ROOM,
                    STUDENT,
                    0,
                    "Corrupt hidden flag",
                    "session",
                    2,
                    1700000000000,
                ),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored message hidden flag is invalid",
        ) as raised:
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )
        self.assertIsNone(raised.exception.__cause__)

        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM classroom_chat_server_messages")
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                """
                INSERT INTO classroom_chat_server_permissions(
                    room_id, target_id, allowed
                ) VALUES(?,?,?)
                """,
                (ROOM, STUDENT, 2),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored chat permission flag is invalid",
        ) as permission_error:
            self.send(self.draft("blocked-by-corruption"))
        self.assertIsNone(permission_error.exception.__cause__)
        self.assertEqual(
            (),
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            ),
        )

    def test_corrupt_message_numeric_metadata_is_sanitized(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,0,?)
                """,
                (
                    "wire-overflow",
                    ROOM,
                    STUDENT,
                    MAX_WIRE_INTEGER + 1,
                    "Unsafe numeric metadata",
                    "session",
                    1700000000000,
                ),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored message sequence is invalid",
        ) as raised:
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )
        self.assertIsNone(raised.exception.__cause__)

    def test_fractional_persisted_numeric_metadata_fails_closed(self) -> None:
        cases = (
            ("sequence_no", 0.5, "stored message sequence is invalid"),
            (
                "sent_at_unix_ms",
                1700000000000.5,
                "stored message timestamp is invalid",
            ),
        )
        for column, corrupt_value, expected_error in cases:
            with self.subTest(column=column):
                values = {
                    "sequence_no": 0,
                    "sent_at_unix_ms": 1700000000000,
                }
                values[column] = corrupt_value
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute("PRAGMA ignore_check_constraints=ON")
                    db.execute(
                        """
                        INSERT INTO classroom_chat_server_messages(
                            message_id, room_id, sender_id, sequence_no, body,
                            retention, hidden, sent_at_unix_ms
                        ) VALUES(?,?,?,?,?,?,0,?)
                        """,
                        (
                            f"fractional-{column}",
                            ROOM,
                            STUDENT,
                            values["sequence_no"],
                            "Fractional durable metadata",
                            "session",
                            values["sent_at_unix_ms"],
                        ),
                    )

                with self.assertRaisesRegex(
                    ClassroomChatServerError,
                    expected_error,
                ) as raised:
                    self.store.history_after(
                        room_id=ROOM,
                        after_sequence=None,
                        limit=10,
                    )
                self.assertIsNone(raised.exception.__cause__)

                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute(
                        "DELETE FROM classroom_chat_server_messages WHERE room_id=?",
                        (ROOM,),
                    )

    def test_fractional_state_revision_is_not_truncated(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 0.5, "fractional-state",),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored moderation revision is invalid",
        ) as raised:
            self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=None,
                limit=10,
            )
        self.assertIsNone(raised.exception.__cause__)

    def test_corrupt_state_update_and_hide_target_fail_without_partial_moderation(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,?)
                """,
                (ROOM, 0, "corrupt-state", 2),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored moderation hidden flag is invalid",
        ):
            self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=None,
                limit=10,
            )

        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM classroom_chat_server_state_updates")
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    "corrupt-target",
                    ROOM,
                    STUDENT,
                    0,
                    "Corrupt target",
                    "session",
                    2,
                    1700000000000,
                ),
            )

        hide = self.moderation(
            "hide-corrupt-target",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id="corrupt-target",
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored message hidden flag is invalid",
        ):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(hide,),
            )

        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_moderation_ops
                    WHERE room_id=? AND operation_id=?
                    """,
                    (ROOM, hide.operation_id),
                ).fetchone()
            )
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_state_updates
                    WHERE room_id=? AND message_id=?
                    """,
                    (ROOM, hide.message_id),
                ).fetchone()
            )

    def test_gapped_message_stream_blocks_new_send_without_partial_insert(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,0,?)
                """,
                (
                    "gapped-before-send",
                    ROOM,
                    STUDENT,
                    1,
                    "Gap before write",
                    "session",
                    1700000000000,
                ),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored message sequence is not contiguous",
        ):
            self.send(self.draft("must-not-append-after-gap"))

        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_messages
                    WHERE message_id=?
                    """,
                    ("must-not-append-after-gap",),
                ).fetchone()
            )
            self.assertEqual(
                1,
                db.execute(
                    """
                    SELECT COUNT(*) FROM classroom_chat_server_messages
                    WHERE room_id=?
                    """,
                    (ROOM,),
                ).fetchone()[0],
            )

    def test_gapped_message_stream_is_not_served_as_authoritative_history(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            for message_id, sequence in (("read-gap-0", 0), ("read-gap-2", 2)):
                db.execute(
                    """
                    INSERT INTO classroom_chat_server_messages(
                        message_id, room_id, sender_id, sequence_no, body,
                        retention, hidden, sent_at_unix_ms
                    ) VALUES(?,?,?,?,?,?,0,?)
                    """,
                    (
                        message_id,
                        ROOM,
                        STUDENT,
                        sequence,
                        "Corrupt read stream",
                        "session",
                        1700000000000 + sequence,
                    ),
                )

        for after_sequence in (None, 1):
            with self.subTest(after_sequence=after_sequence):
                with self.assertRaisesRegex(
                    ClassroomChatServerError,
                    "stored message sequence is not contiguous",
                ):
                    self.store.history_after(
                        room_id=ROOM,
                        after_sequence=after_sequence,
                        limit=10,
                    )

    def test_corrupt_sequence_counter_blocks_new_send_without_partial_insert(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,0,?)
                """,
                (
                    "corrupt-sequence-counter",
                    ROOM,
                    STUDENT,
                    "not-a-sequence",
                    "Corrupt sequence counter",
                    "session",
                    1700000000000,
                ),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored message sequence is invalid",
        ) as raised:
            self.send(self.draft("message-after-corrupt-sequence"))
        self.assertIsNone(raised.exception.__cause__)

        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_messages
                    WHERE message_id=?
                    """,
                    ("message-after-corrupt-sequence",),
                ).fetchone()
            )
            self.assertEqual(
                1,
                db.execute(
                    """
                    SELECT COUNT(*) FROM classroom_chat_server_messages
                    WHERE room_id=?
                    """,
                    (ROOM,),
                ).fetchone()[0],
            )

    def test_gapped_revision_stream_rolls_back_hide_and_operation(self) -> None:
        represented = self.send(self.draft("represented-before-gap"))
        target = self.send(self.draft("target-after-gap"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                UPDATE classroom_chat_server_messages
                SET hidden=1
                WHERE message_id=?
                """,
                (represented.message_id,),
            )
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 1, represented.message_id),
            )

        hide = self.moderation(
            "hide-after-revision-gap",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=target.message_id,
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored moderation revision is not contiguous",
        ):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(hide,),
            )

        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                0,
                db.execute(
                    """
                    SELECT hidden FROM classroom_chat_server_messages
                    WHERE message_id=?
                    """,
                    (target.message_id,),
                ).fetchone()[0],
            )
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_moderation_ops
                    WHERE room_id=? AND operation_id=?
                    """,
                    (ROOM, hide.operation_id),
                ).fetchone()
            )
            self.assertEqual(
                1,
                db.execute(
                    """
                    SELECT COUNT(*) FROM classroom_chat_server_state_updates
                    WHERE room_id=?
                    """,
                    (ROOM,),
                ).fetchone()[0],
            )

    def test_gapped_moderation_stream_is_not_served_as_authoritative_state(self) -> None:
        first = self.send(self.draft("state-read-gap-0"))
        second = self.send(self.draft("state-read-gap-2"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                UPDATE classroom_chat_server_messages
                SET hidden=1
                WHERE message_id IN (?,?)
                """,
                (first.message_id, second.message_id),
            )
            for revision, message_id in ((0, first.message_id), (2, second.message_id)):
                db.execute(
                    """
                    INSERT INTO classroom_chat_server_state_updates(
                        room_id, revision, message_id, hidden
                    ) VALUES(?,?,?,1)
                    """,
                    (ROOM, revision, message_id),
                )

        for after_revision in (None, 1):
            with self.subTest(after_revision=after_revision):
                with self.assertRaisesRegex(
                    ClassroomChatServerError,
                    "stored moderation revision is not contiguous",
                ):
                    self.store.state_updates_after(
                        room_id=ROOM,
                        after_revision=after_revision,
                        limit=10,
                    )

    def test_corrupt_revision_counter_rolls_back_hide_and_operation(self) -> None:
        sent = self.send(self.draft("message-before-corrupt-revision"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, "not-a-revision", sent.message_id),
            )

        hide = self.moderation(
            "hide-after-corrupt-revision",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored moderation revision is invalid",
        ) as raised:
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(hide,),
            )
        self.assertIsNone(raised.exception.__cause__)

        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                0,
                db.execute(
                    """
                    SELECT hidden FROM classroom_chat_server_messages
                    WHERE message_id=?
                    """,
                    (sent.message_id,),
                ).fetchone()[0],
            )
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_moderation_ops
                    WHERE room_id=? AND operation_id=?
                    """,
                    (ROOM, hide.operation_id),
                ).fetchone()
            )
            self.assertEqual(
                1,
                db.execute(
                    """
                    SELECT COUNT(*) FROM classroom_chat_server_state_updates
                    WHERE room_id=?
                    """,
                    (ROOM,),
                ).fetchone()[0],
            )

    def test_corrupt_schema_version_is_sanitized_and_never_auto_repaired(self) -> None:
        for value in ("not-an-integer", 0, 1.5, 5):
            with self.subTest(value=value):
                path = Path(self.tmp.name) / f"schema-{str(value).replace(' ', '-')}.sqlite3"
                ClassroomChatServerSQLiteStore(path)
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(
                        """
                        UPDATE classroom_chat_server_meta
                        SET value=?
                        WHERE key='schema_version'
                        """,
                        (value,),
                    )

                with self.assertRaises(ClassroomChatServerError) as raised:
                    ClassroomChatServerSQLiteStore(path)
                self.assertIsNone(raised.exception.__cause__)

                with closing(sqlite3.connect(path)) as db:
                    persisted = db.execute(
                        """
                        SELECT value FROM classroom_chat_server_meta
                        WHERE key='schema_version'
                        """
                    ).fetchone()[0]
                self.assertEqual(value, persisted)

    def test_invalid_schema_version_does_not_recreate_missing_tables(self) -> None:
        path = Path(self.tmp.name) / "schema-no-repair.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DROP TABLE classroom_chat_server_state_updates")
            db.execute(
                """
                UPDATE classroom_chat_server_meta
                SET value=0
                WHERE key='schema_version'
                """
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "invalid classroom chat server schema version",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='table'
                      AND name='classroom_chat_server_state_updates'
                    """
                ).fetchone()
            )
            self.assertEqual(
                0,
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()[0],
            )

    def test_missing_schema_version_is_not_backfilled(self) -> None:
        path = Path(self.tmp.name) / "schema-missing-version.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                DELETE FROM classroom_chat_server_meta
                WHERE key='schema_version'
                """
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "invalid classroom chat server schema version",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()
            )

    def test_missing_schema_metadata_table_is_not_recreated_over_existing_state(self) -> None:
        path = Path(self.tmp.name) / "schema-missing-meta.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DROP TABLE classroom_chat_server_meta")

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "schema metadata is missing",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='table'
                      AND name='classroom_chat_server_meta'
                    """
                ).fetchone()
            )
            self.assertIsNotNone(
                db.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='table'
                      AND name='classroom_chat_server_messages'
                    """
                ).fetchone()
            )

    def test_current_schema_rejects_persistent_authority_table_trigger(self) -> None:
        path = Path(self.tmp.name) / "schema-trigger.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                CREATE TRIGGER mutate_chat_body_after_insert
                AFTER INSERT ON classroom_chat_server_messages
                BEGIN
                    UPDATE classroom_chat_server_messages
                    SET body='tampered by trigger'
                    WHERE message_id=NEW.message_id;
                END
                """
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "schema contains unsupported trigger",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            self.assertIsNotNone(
                db.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='trigger'
                      AND name='mutate_chat_body_after_insert'
                    """
                ).fetchone()
            )
            self.assertEqual(
                0,
                db.execute(
                    "SELECT COUNT(*) FROM classroom_chat_server_messages"
                ).fetchone()[0],
            )

    def test_live_store_rechecks_trigger_free_authority_before_writes(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                CREATE TRIGGER late_chat_body_mutator
                AFTER INSERT ON classroom_chat_server_messages
                BEGIN
                    UPDATE classroom_chat_server_messages
                    SET body='late tamper'
                    WHERE message_id=NEW.message_id;
                END
                """
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "schema contains unsupported trigger",
        ):
            self.send(self.draft("must-not-cross-late-trigger"))

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "schema contains unsupported trigger",
        ):
            self.store.integrity_check()

        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_messages
                    WHERE message_id='must-not-cross-late-trigger'
                    """
                ).fetchone()
            )

    def test_current_schema_rejects_wrong_permission_primary_key(self) -> None:
        path = Path(self.tmp.name) / "schema-wrong-permission-key.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("ALTER TABLE classroom_chat_server_permissions RENAME TO old_permissions")
            db.execute(
                """
                CREATE TABLE classroom_chat_server_permissions(
                    room_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    allowed INTEGER NOT NULL CHECK(allowed IN (0,1))
                )
                """
            )
            db.execute("DROP TABLE old_permissions")

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "schema shape is incompatible",
        ):
            ClassroomChatServerSQLiteStore(path)

    def test_current_schema_rejects_missing_message_ordering_constraint(self) -> None:
        path = Path(self.tmp.name) / "schema-missing-message-order.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DROP INDEX idx_classroom_chat_server_messages_room")
            db.execute("ALTER TABLE classroom_chat_server_messages RENAME TO old_messages")
            db.execute(
                """
                CREATE TABLE classroom_chat_server_messages(
                    message_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                    body TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
                    sent_at_unix_ms INTEGER NOT NULL CHECK(sent_at_unix_ms >= 0),
                    redacted INTEGER NOT NULL DEFAULT 0 CHECK(redacted IN (0,1))
                )
                """
            )
            db.execute("DROP TABLE old_messages")

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "message ordering constraint is missing",
        ):
            ClassroomChatServerSQLiteStore(path)

    def test_current_schema_does_not_recreate_missing_authority_table(self) -> None:
        path = Path(self.tmp.name) / "schema-incomplete-current.sqlite3"
        store = ClassroomChatServerSQLiteStore(path)
        store.apply_moderation(
            (
                self.moderation(
                    "persisted-send-lock",
                    allowed=False,
                ),
            )
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DROP TABLE classroom_chat_server_permissions")

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "schema is incomplete",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='table'
                      AND name='classroom_chat_server_permissions'
                    """
                ).fetchone()
            )
            self.assertEqual(
                4,
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()[0],
            )

    def test_version_three_upgrade_rebuilds_state_table_for_redaction_only_events(self) -> None:
        path = Path(self.tmp.name) / "schema-v3-redaction-upgrade.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        self._downgrade_to_legacy_schema(
            path,
            version=3,
            keep_state_table=True,
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,0,?)
                """,
                (
                    "v3-session-message",
                    ROOM,
                    STUDENT,
                    0,
                    "Must be redaction-capable after migration",
                    "session",
                    1700000000000,
                ),
            )

        migrated = ClassroomChatServerSQLiteStore(path)
        updates = migrated.redact_retention(
            room_id=ROOM,
            retentions=("session",),
        )

        self.assertEqual(1, len(updates))
        self.assertFalse(updates[0].hidden)
        self.assertTrue(updates[0].redacted)
        self.assertEqual(0, updates[0].revision)
        redacted = migrated.history_after(
            room_id=ROOM,
            after_sequence=None,
            limit=10,
        )[0]
        self.assertTrue(redacted.redacted)
        self.assertEqual("", redacted.body)
        migrated.integrity_check()

        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                4,
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()[0],
            )
            state_columns = {
                row[1]
                for row in db.execute(
                    "PRAGMA table_info(classroom_chat_server_state_updates)"
                )
            }
            self.assertIn("redacted", state_columns)

    def test_version_two_upgrade_repairs_missing_hidden_state_at_stream_tail(self) -> None:
        path = Path(self.tmp.name) / "schema-v2-hidden-repair.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        self._downgrade_to_legacy_schema(
            path,
            version=2,
            keep_state_table=True,
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,1,?)
                """,
                (
                    "missing-v2-state",
                    ROOM,
                    STUDENT,
                    0,
                    "Missing old migration event",
                    "session",
                    1700000000000,
                ),
            )
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,1,?)
                """,
                (
                    "existing-v2-state",
                    ROOM,
                    STUDENT,
                    1,
                    "Already represented",
                    "session",
                    1700000001000,
                ),
            )
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 0, "existing-v2-state"),
            )
            db.execute(
                """
                UPDATE classroom_chat_server_meta
                SET value=2
                WHERE key='schema_version'
                """
            )

        repaired = ClassroomChatServerSQLiteStore(path)
        updates = repaired.state_updates_after(
            room_id=ROOM,
            after_revision=None,
            limit=10,
        )

        self.assertEqual(
            [
                (0, "existing-v2-state"),
                (1, "missing-v2-state"),
            ],
            [(item.revision, item.message_id) for item in updates],
        )
        repaired.integrity_check()
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                4,
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()[0],
            )

    def test_version_two_upgrade_rejects_state_for_visible_message(self) -> None:
        path = Path(self.tmp.name) / "schema-v2-visible-state.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        self._downgrade_to_legacy_schema(
            path,
            version=2,
            keep_state_table=True,
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,0,?)
                """,
                (
                    "visible-v2-message",
                    ROOM,
                    STUDENT,
                    0,
                    "Still visible",
                    "session",
                    1700000000000,
                ),
            )
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 0, "visible-v2-message"),
            )
            db.execute(
                """
                UPDATE classroom_chat_server_meta
                SET value=2
                WHERE key='schema_version'
                """
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "legacy moderation state references visible message",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                2,
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()[0],
            )

    def test_version_two_upgrade_rejects_inconsistent_existing_state(self) -> None:
        path = Path(self.tmp.name) / "schema-v2-inconsistent-state.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        self._downgrade_to_legacy_schema(
            path,
            version=2,
            keep_state_table=True,
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 0, "unknown-v2-message"),
            )
            db.execute(
                """
                UPDATE classroom_chat_server_meta
                SET value=2
                WHERE key='schema_version'
                """
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "legacy moderation state references unknown message",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                2,
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()[0],
            )

    def test_version_one_migration_backfills_hidden_message_state_stream(self) -> None:
        path = Path(self.tmp.name) / "schema-v1-hidden-backfill.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        self._downgrade_to_legacy_schema(
            path,
            version=1,
            keep_state_table=False,
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,1,?)
                """,
                (
                    "legacy-hidden-message",
                    ROOM,
                    STUDENT,
                    0,
                    "Hidden before state stream existed",
                    "session",
                    1700000000000,
                ),
            )

        migrated = ClassroomChatServerSQLiteStore(path)
        updates = migrated.state_updates_after(
            room_id=ROOM,
            after_revision=None,
            limit=10,
        )

        self.assertEqual(1, len(updates))
        self.assertEqual("legacy-hidden-message", updates[0].message_id)
        self.assertEqual(0, updates[0].revision)
        self.assertTrue(updates[0].hidden)
        migrated.integrity_check()

    def test_failed_version_one_upgrade_rolls_back_created_state_schema(self) -> None:
        path = Path(self.tmp.name) / "schema-v1-atomic-failure.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        self._downgrade_to_legacy_schema(
            path,
            version=1,
            keep_state_table=False,
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,1,?)
                """,
                (
                    "legacy-gap-message",
                    ROOM,
                    STUDENT,
                    1,
                    "Gap must abort migration atomically",
                    "session",
                    1700000000000,
                ),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "legacy server message sequence is not contiguous",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            version = db.execute(
                """
                SELECT value FROM classroom_chat_server_meta
                WHERE key='schema_version'
                """
            ).fetchone()[0]
            state_table = db.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table'
                  AND name='classroom_chat_server_state_updates'
                """
            ).fetchone()
            state_index = db.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='index'
                  AND name='idx_classroom_chat_server_state_updates_message'
                """
            ).fetchone()

        self.assertEqual(1, version)
        self.assertIsNone(state_table)
        self.assertIsNone(state_index)

    def test_version_one_migration_rejects_nonempty_partial_state_stream(self) -> None:
        path = Path(self.tmp.name) / "schema-v1-partial-state.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        self._downgrade_to_legacy_schema(
            path,
            version=1,
            keep_state_table=True,
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,1,?)
                """,
                (
                    "partial-hidden-message",
                    ROOM,
                    STUDENT,
                    0,
                    "Partially migrated",
                    "session",
                    1700000000000,
                ),
            )
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, 0, "partial-hidden-message"),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "version one chat state migration is partial",
        ):
            ClassroomChatServerSQLiteStore(path)

        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                1,
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                db.execute(
                    """
                    SELECT COUNT(*) FROM classroom_chat_server_state_updates
                    WHERE room_id=?
                    """,
                    (ROOM,),
                ).fetchone()[0],
            )

    def test_version_one_migration_creates_current_state_table(self) -> None:
        path = Path(self.tmp.name) / "schema-v1-migration.sqlite3"
        ClassroomChatServerSQLiteStore(path)
        self._downgrade_to_legacy_schema(
            path,
            version=1,
            keep_state_table=False,
        )

        migrated = ClassroomChatServerSQLiteStore(path)
        migrated.integrity_check()

        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                4,
                db.execute(
                    """
                    SELECT value FROM classroom_chat_server_meta
                    WHERE key='schema_version'
                    """
                ).fetchone()[0],
            )
            self.assertIsNotNone(
                db.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='table'
                      AND name='classroom_chat_server_state_updates'
                    """
                ).fetchone()
            )
            self.assertIsNotNone(
                db.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='index'
                      AND name='idx_classroom_chat_server_state_updates_message'
                    """
                ).fetchone()
            )

    def test_two_client_controller_composition_reconnects_and_reconciles_hide(self) -> None:
        roster = SharedRoster()
        teacher_store = ClassroomCollaborationSQLiteStore(
            str(Path(self.tmp.name) / "teacher-client.sqlite3")
        )
        student_store = ClassroomCollaborationSQLiteStore(
            str(Path(self.tmp.name) / "student-client.sqlite3")
        )
        teacher = ClassroomCollaborationController(
            room_id=ROOM,
            local_participant_id=TEACHER,
            roster=roster,
            chat=BoundChatTransport(self.service, TEACHER),
            files=object(),
            store=teacher_store,
        )
        student = ClassroomCollaborationController(
            room_id=ROOM,
            local_participant_id=STUDENT,
            roster=roster,
            chat=BoundChatTransport(self.service, STUDENT),
            files=object(),
            store=student_store,
        )

        sent = student.send_chat(
            message_id="two-client-message",
            body="Shared room message",
        )
        self.assertEqual((sent,), teacher.sync_chat())
        self.assertEqual(
            (sent,),
            teacher_store.room_messages(ROOM),
        )

        hidden = teacher.hide_message(
            actor_id=TEACHER,
            message_id=sent.message_id,
            operation_id="two-client-hide",
        )
        self.assertTrue(hidden.hidden)
        self.assertEqual((), teacher_store.room_messages(ROOM))

        # The sender already has the message locally, so reconnect receives only
        # the server moderation-state stream and must hide it without reannounce.
        self.assertEqual((), student.sync_chat())
        self.assertEqual((), student_store.room_messages(ROOM))
        durable = student_store.room_messages(ROOM, include_hidden=True)
        self.assertEqual(1, len(durable))
        self.assertTrue(durable[0].hidden)
        self.assertEqual(0, student_store.chat_state_revision(ROOM))

        reopened = ClassroomCollaborationSQLiteStore(
            str(Path(self.tmp.name) / "student-client.sqlite3")
        )
        self.assertTrue(reopened.room_messages(ROOM, include_hidden=True)[0].hidden)
        self.assertEqual(0, reopened.chat_state_revision(ROOM))

    def test_two_client_controller_mute_is_server_authoritative(self) -> None:
        roster = SharedRoster()
        teacher = ClassroomCollaborationController(
            room_id=ROOM,
            local_participant_id=TEACHER,
            roster=roster,
            chat=BoundChatTransport(self.service, TEACHER),
            files=object(),
            store=ClassroomCollaborationSQLiteStore(
                str(Path(self.tmp.name) / "teacher-mute-client.sqlite3")
            ),
        )
        student_store = ClassroomCollaborationSQLiteStore(
            str(Path(self.tmp.name) / "student-mute-client.sqlite3")
        )
        student = ClassroomCollaborationController(
            room_id=ROOM,
            local_participant_id=STUDENT,
            roster=roster,
            chat=BoundChatTransport(self.service, STUDENT),
            files=object(),
            store=student_store,
        )

        teacher.set_chat_send_permission(
            actor_id=TEACHER,
            target_id=STUDENT,
            allowed=False,
            operation_id="two-client-mute",
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "disabled",
        ):
            student.send_chat(
                message_id="blocked-by-server",
                body="Must not be accepted",
            )
        self.assertEqual((), student_store.room_messages(ROOM))
        self.assertEqual(
            (),
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            ),
        )

        teacher.set_chat_send_permission(
            actor_id=TEACHER,
            target_id=STUDENT,
            allowed=True,
            operation_id="two-client-unmute",
        )
        sent = student.send_chat(
            message_id="allowed-by-server",
            body="Allowed again",
        )
        self.assertEqual("allowed-by-server", sent.message_id)
        self.assertEqual((sent,), student_store.room_messages(ROOM))
        self.assertEqual(
            (sent,),
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            ),
        )

    def test_send_assigns_server_sequence_and_time_and_retry_is_stable(self) -> None:
        draft = self.draft("m1")
        first = self.send(draft)
        second = self.send(draft)

        self.assertEqual(first, second)
        self.assertEqual(0, first.sequence_no)
        self.assertEqual(1700000000000, first.sent_at_unix_ms)
        self.assertFalse(first.hidden)
        self.assertEqual(1, self.clock.calls)
        self.assertEqual(
            [(ROOM, STUDENT, STUDENT), (ROOM, STUDENT, STUDENT)],
            self.auth.send_calls,
        )

        reopened = ClassroomChatServerSQLiteStore(self.path)
        self.assertEqual(
            (first,),
            reopened.history_after(room_id=ROOM, after_sequence=None, limit=10),
        )

        retry_without_clock = ClassroomChatServerService(
            store=reopened,
            authorization=self.auth,
            clock_unix_ms=lambda: (_ for _ in ()).throw(RuntimeError("clock down")),
        )
        self.assertEqual(
            first,
            retry_without_clock.send_message(
                trusted_caller_identity=STUDENT,
                draft=draft,
            ),
        )

    def test_same_message_id_cannot_change_content_or_cross_room(self) -> None:
        self.send(self.draft("m1", "Original"))
        for conflicting in (
            self.draft("m1", "Changed"),
            self.draft("m1", "Original", room="room-2"),
            self.draft("m1", "Original", sender="student-2"),
        ):
            with self.subTest(conflicting=conflicting):
                with self.assertRaisesRegex(
                    ClassroomChatServerError,
                    "different immutable content",
                ):
                    self.service.send_message(
                        trusted_caller_identity=conflicting.sender_id,
                        draft=conflicting,
                    )

    def test_trusted_transport_identity_cannot_spoof_sender(self) -> None:
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "trusted caller",
        ):
            self.service.send_message(
                trusted_caller_identity="student-2",
                draft=self.draft("m1", sender=STUDENT),
            )
        self.assertEqual([], self.auth.send_calls)

    def test_authorization_failures_are_sanitized_before_storage_effects(self) -> None:
        self.auth.reject_send = True
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "not authorized",
        ) as raised:
            self.send(self.draft("m1"))
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("sensitive", str(raised.exception).lower())
        self.assertEqual(
            (),
            self.store.history_after(room_id=ROOM, after_sequence=None, limit=10),
        )

        self.auth.reject_history = True
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "history is not authorized",
        ) as history_error:
            self.service.history_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )
        self.assertIsNone(history_error.exception.__cause__)

    def test_authorization_ports_reject_boolean_denial_results_fail_closed(self) -> None:
        self.auth.send_result = False
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "chat send is not authorized",
        ):
            self.send(self.draft("false-send-authorization"))
        self.assertEqual(0, self.clock.calls)

        self.auth.send_result = None
        self.auth.history_result = False
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "chat history is not authorized",
        ):
            self.service.history_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "chat state history is not authorized",
        ):
            self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=None,
                limit=10,
            )

        self.auth.history_result = None
        self.auth.moderation_result = False
        command = self.moderation(
            "false-moderation-authorization",
            allowed=False,
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "chat moderation is not authorized",
        ):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(command,),
            )

        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(
                db.execute(
                    """
                    SELECT 1 FROM classroom_chat_server_moderation_ops
                    WHERE room_id=? AND operation_id=?
                    """,
                    (ROOM, command.operation_id),
                ).fetchone()
            )

    def test_server_permission_lock_is_enforced_even_without_client_local_state(self) -> None:
        lock = self.moderation("lock-student", allowed=False)
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(lock,),
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "disabled",
        ):
            self.send(self.draft("blocked"))

        unlock = self.moderation("unlock-student", allowed=True)
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(unlock,),
        )
        sent = self.send(self.draft("allowed"))
        self.assertEqual("allowed", sent.message_id)

    def test_moderation_is_atomic_idempotent_and_rejects_semantic_reuse(self) -> None:
        lock = self.moderation("op-1", allowed=False)
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(lock,),
        )
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(lock,),
        )
        self.assertEqual(2, len(self.auth.moderation_calls))

        conflict = self.moderation("op-1", allowed=True)
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "reused with different semantics",
        ):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(conflict,),
            )

        with self.assertRaisesRegex(ClassroomChatServerError, "disabled"):
            self.send(self.draft("still-blocked"))

    def test_hide_message_is_durable_and_history_preserves_authoritative_identity(self) -> None:
        sent = self.send(self.draft("m-hide", "Moderate me"))
        hide = self.moderation(
            "hide-1",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(hide,),
        )

        history = self.service.history_after(
            trusted_caller_identity=STUDENT,
            room_id=ROOM,
            after_sequence=None,
            limit=10,
        )
        self.assertEqual(1, len(history))
        self.assertTrue(history[0].hidden)
        self.assertEqual(sent.sequence_no, history[0].sequence_no)
        self.assertEqual(sent.sent_at_unix_ms, history[0].sent_at_unix_ms)

        updates = self.service.state_updates_after(
            trusted_caller_identity=STUDENT,
            room_id=ROOM,
            after_revision=None,
            limit=10,
        )
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].message_id, sent.message_id)
        self.assertEqual(updates[0].revision, 0)
        self.assertTrue(updates[0].hidden)
        self.assertEqual(
            self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=0,
                limit=10,
            ),
            (),
        )

    def test_exact_resend_after_hide_preserves_identity_and_mutable_hidden_state(self) -> None:
        draft = self.draft("m-hide-resend", "Accepted before moderation")
        sent = self.send(draft)
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(
                self.moderation(
                    "hide-before-resend",
                    target=None,
                    action=ChatModerationAction.HIDE_MESSAGE,
                    allowed=None,
                    message_id=sent.message_id,
                ),
            ),
        )

        recovered = self.send(draft)

        self.assertEqual(sent.message_id, recovered.message_id)
        self.assertEqual(sent.sequence_no, recovered.sequence_no)
        self.assertEqual(sent.sent_at_unix_ms, recovered.sent_at_unix_ms)
        self.assertEqual(sent.body, recovered.body)
        self.assertTrue(recovered.hidden)
        self.assertEqual(1, self.clock.calls)
        self.assertEqual(
            1,
            len(
                self.store.history_after(
                    room_id=ROOM,
                    after_sequence=None,
                    limit=10,
                )
            ),
        )

    def test_repeated_hide_with_new_operation_does_not_duplicate_state_event(self) -> None:
        sent = self.send(self.draft("m-repeat-hide"))
        first = self.moderation(
            "hide-first",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )
        second = self.moderation(
            "hide-second",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(first,),
        )
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(second,),
        )
        updates = self.store.state_updates_after(
            room_id=ROOM,
            after_revision=None,
            limit=10,
        )
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].revision, 0)

    def test_state_update_history_is_bounded_validated_and_authorized(self) -> None:
        sent = self.send(self.draft("m-state-history"))
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(
                self.moderation(
                    "hide-state-history",
                    target=None,
                    action=ChatModerationAction.HIDE_MESSAGE,
                    allowed=None,
                    message_id=sent.message_id,
                ),
            ),
        )
        self.assertEqual(
            self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=None,
                limit=1,
            )[0].message_id,
            sent.message_id,
        )
        for after, limit in ((True, 1), (-1, 1), (None, 0), (None, True)):
            with self.subTest(after=after, limit=limit):
                with self.assertRaises(ClassroomChatServerError):
                    self.service.state_updates_after(
                        trusted_caller_identity=STUDENT,
                        room_id=ROOM,
                        after_revision=after,
                        limit=limit,
                    )
        self.auth.reject_history = True
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "state history is not authorized",
        ):
            self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=None,
                limit=1,
            )

    def test_hide_unknown_message_rolls_back_operation_id_for_retry(self) -> None:
        hide = self.moderation(
            "hide-missing",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id="missing",
        )
        with self.assertRaisesRegex(ClassroomChatServerError, "does not exist"):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(hide,),
            )
        self.send(self.draft("missing"))
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(hide,),
        )
        self.assertTrue(
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )[0].hidden
        )

    def test_moderation_actor_room_and_authorization_fail_closed(self) -> None:
        command = self.moderation("op")
        with self.assertRaisesRegex(ClassroomChatServerError, "trusted caller"):
            self.service.apply_moderation(
                trusted_caller_identity="teacher-2",
                commands=(command,),
            )
        cross_room = self.moderation("op-2", room="room-2")
        with self.assertRaisesRegex(ClassroomChatServerError, "crossed room"):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(command, cross_room),
            )

        self.auth.reject_moderation = True
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "not authorized",
        ) as raised:
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(self.moderation("op-denied"),),
            )
        self.assertIsNone(raised.exception.__cause__)

    def test_workflow_scope_uses_live_stacked_base_with_event_ancestry_guard(self) -> None:
        workflow = CHAT_SERVER_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$EVENT_BASE_SHA" HEAD',
            workflow,
        )
        self.assertIn(
            'LIVE_BASE_SHA="$(git rev-parse "refs/remotes/origin/$PR_BASE_REF")"',
            workflow,
        )
        self.assertIn(
            'git diff --name-only "$LIVE_BASE_SHA...HEAD"',
            workflow,
        )
        self.assertIn(
            'git diff --check "$LIVE_BASE_SHA...HEAD"',
            workflow,
        )

    def test_server_history_bound_matches_canonical_client_sync_page(self) -> None:
        self.assertEqual(MAX_SYNC_MESSAGES, MAX_SERVER_HISTORY_MESSAGES)
        self.assertEqual(
            (),
            self.service.history_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_sequence=None,
                limit=MAX_SYNC_MESSAGES,
            ),
        )
        self.assertEqual(
            (),
            self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=None,
                limit=MAX_SYNC_MESSAGES,
            ),
        )

    def test_server_moderation_batch_supports_large_canonical_roster(self) -> None:
        self.assertEqual(5000, MAX_SERVER_MODERATION_COMMANDS)
        commands = tuple(
            self.moderation(
                f"bulk-{index}",
                target=f"student-{index}",
                allowed=False,
            )
            for index in range(501)
        )

        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=commands,
        )

        with closing(sqlite3.connect(self.path)) as db:
            permission_count = db.execute(
                """
                SELECT COUNT(*) FROM classroom_chat_server_permissions
                WHERE room_id=?
                """,
                (ROOM,),
            ).fetchone()[0]
        self.assertEqual(501, permission_count)

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "batch is invalid",
        ):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(commands[0],) * (MAX_SERVER_MODERATION_COMMANDS + 1),
            )

    def test_history_is_strictly_ordered_bounded_and_authorized(self) -> None:
        sent = [self.send(self.draft(f"m{index}", str(index))) for index in range(4)]
        page = self.service.history_after(
            trusted_caller_identity=STUDENT,
            room_id=ROOM,
            after_sequence=sent[0].sequence_no,
            limit=2,
        )
        self.assertEqual(["m1", "m2"], [item.message_id for item in page])
        self.assertEqual([1, 2], [item.sequence_no for item in page])
        self.assertEqual([(ROOM, STUDENT)], self.auth.history_calls)

        for after, limit in (
            (True, 1),
            (-1, 1),
            (None, 0),
            (None, True),
            (None, MAX_SERVER_HISTORY_MESSAGES + 1),
        ):
            with self.subTest(after=after, limit=limit):
                with self.assertRaises(ClassroomChatServerError):
                    self.service.history_after(
                        trusted_caller_identity=STUDENT,
                        room_id=ROOM,
                        after_sequence=after,
                        limit=limit,
                    )

    def test_history_and_state_cursors_reject_json_unsafe_integers(self) -> None:
        over = MAX_WIRE_INTEGER + 1
        calls = (
            lambda: self.store.history_after(
                room_id=ROOM,
                after_sequence=over,
                limit=1,
            ),
            lambda: self.service.history_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_sequence=over,
                limit=1,
            ),
            lambda: self.store.state_updates_after(
                room_id=ROOM,
                after_revision=over,
                limit=1,
            ),
            lambda: self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=over,
                limit=1,
            ),
        )
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(ClassroomChatServerError) as raised:
                    call()
                self.assertIsNone(raised.exception.__cause__)

        self.assertEqual(
            (),
            self.service.history_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_sequence=MAX_WIRE_INTEGER,
                limit=1,
            ),
        )
        self.assertEqual(
            (),
            self.service.state_updates_after(
                trusted_caller_identity=STUDENT,
                room_id=ROOM,
                after_revision=MAX_WIRE_INTEGER,
                limit=1,
            ),
        )

    def test_server_sequence_exhaustion_fails_without_partial_insert(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,0,?)
                """,
                (
                    "max-sequence",
                    ROOM,
                    STUDENT,
                    MAX_WIRE_INTEGER,
                    "Existing max sequence",
                    "session",
                    1700000000000,
                ),
            )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "sequence exhausted",
        ):
            self.send(self.draft("after-max"))

        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                """
                SELECT message_id FROM classroom_chat_server_messages
                WHERE room_id=? ORDER BY sequence_no
                """,
                (ROOM,),
            ).fetchall()
        self.assertEqual([("max-sequence",)], rows)

    def test_moderation_revision_exhaustion_rolls_back_hide_and_operation(self) -> None:
        sent = self.send(self.draft("revision-target"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO classroom_chat_server_messages(
                    message_id, room_id, sender_id, sequence_no, body,
                    retention, hidden, sent_at_unix_ms
                ) VALUES(?,?,?,?,?,?,1,?)
                """,
                (
                    "historical-max-revision",
                    ROOM,
                    STUDENT,
                    1,
                    "Already hidden at maximum revision",
                    "session",
                    1700000001000,
                ),
            )
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (ROOM, MAX_WIRE_INTEGER, "historical-max-revision"),
            )
        hide = self.moderation(
            "hide-after-max-revision",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "revision exhausted",
        ):
            self.service.apply_moderation(
                trusted_caller_identity=TEACHER,
                commands=(hide,),
            )

        current = self.store.history_after(
            room_id=ROOM,
            after_sequence=None,
            limit=10,
        )[0]
        self.assertFalse(current.hidden)

        with closing(sqlite3.connect(self.path)) as db:
            op = db.execute(
                """
                SELECT 1 FROM classroom_chat_server_moderation_ops
                WHERE room_id=? AND operation_id=?
                """,
                (ROOM, hide.operation_id),
            ).fetchone()
        self.assertIsNone(op)

    def test_default_server_retention_rejects_client_persistence_escalation(self) -> None:
        draft = ChatDraft(
            "retention-escalation",
            ROOM,
            STUDENT,
            "Do not persist me",
            retention="persistent",
        )

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "retention does not match server policy",
        ):
            self.service.send_message(
                trusted_caller_identity=STUDENT,
                draft=draft,
            )

        self.assertEqual(0, self.clock.calls)
        self.assertEqual(
            (),
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            ),
        )

    def test_trusted_room_retention_policy_can_select_transient_storage(self) -> None:
        service = ClassroomChatServerService(
            store=self.store,
            authorization=self.auth,
            clock_unix_ms=self.clock,
            retention_policy=lambda room_id: (
                "transient" if room_id == ROOM else "session"
            ),
        )
        draft = ChatDraft(
            "transient-message",
            ROOM,
            STUDENT,
            "Transient by trusted policy",
            retention="transient",
        )

        delivered = service.send_message(
            trusted_caller_identity=STUDENT,
            draft=draft,
        )

        self.assertEqual("transient", delivered.retention)
        self.assertEqual(1, self.clock.calls)

    def test_exact_resend_survives_later_retention_policy_change(self) -> None:
        persistent_clock = Clock()
        persistent = ClassroomChatServerService(
            store=self.store,
            authorization=self.auth,
            clock_unix_ms=persistent_clock,
            retention_policy=lambda _room_id: "persistent",
        )
        draft = ChatDraft(
            "persistent-before-policy-change",
            ROOM,
            STUDENT,
            "Already accepted",
            retention="persistent",
        )
        first = persistent.send_message(
            trusted_caller_identity=STUDENT,
            draft=draft,
        )
        replacement_clock = Clock(1800000000000)
        session_only = ClassroomChatServerService(
            store=self.store,
            authorization=self.auth,
            clock_unix_ms=replacement_clock,
        )

        recovered = session_only.send_message(
            trusted_caller_identity=STUDENT,
            draft=draft,
        )

        self.assertEqual(first, recovered)
        self.assertEqual(0, replacement_clock.calls)

    def test_session_retention_redaction_clears_body_and_preserves_history_identity(self) -> None:
        draft = self.draft(
            "session-retention-redaction",
            "Session-only content",
        )
        sent = self.send(draft)

        updates = self.service.redact_retention(
            room_id=ROOM,
            retentions=("session",),
        )

        self.assertEqual(1, len(updates))
        self.assertEqual(sent.message_id, updates[0].message_id)
        self.assertEqual(0, updates[0].revision)
        self.assertFalse(updates[0].hidden)
        self.assertTrue(updates[0].redacted)

        history = self.store.history_after(
            room_id=ROOM,
            after_sequence=None,
            limit=10,
        )
        self.assertEqual(1, len(history))
        redacted = history[0]
        self.assertEqual("", redacted.body)
        self.assertTrue(redacted.redacted)
        self.assertFalse(redacted.hidden)
        self.assertEqual(sent.message_id, redacted.message_id)
        self.assertEqual(sent.sender_id, redacted.sender_id)
        self.assertEqual(sent.sequence_no, redacted.sequence_no)
        self.assertEqual(sent.sent_at_unix_ms, redacted.sent_at_unix_ms)
        self.assertEqual(sent.retention, redacted.retention)

        streamed = self.service.state_updates_after(
            trusted_caller_identity=STUDENT,
            room_id=ROOM,
            after_revision=None,
            limit=10,
        )
        self.assertEqual(updates, streamed)
        self.assertEqual(
            (),
            self.service.redact_retention(
                room_id=ROOM,
                retentions=("session",),
            ),
        )
        self.store.integrity_check()

        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "content was already redacted",
        ):
            self.service.send_message(
                trusted_caller_identity=STUDENT,
                draft=draft,
            )
        self.assertEqual(
            "",
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )[0].body,
        )

    def test_retention_redaction_erases_payload_bytes_from_sqlite_free_space(self) -> None:
        secret = (
            "PHYSICAL-RETENTION-SECRET-"
            + "blind-chess-private-session-" * 16
        )
        secret_bytes = secret.encode("utf-8")
        self.send(
            self.draft(
                "physical-retention-redaction",
                secret,
            )
        )
        before = self.path.read_bytes()
        self.assertIn(secret_bytes, before)

        self.service.redact_retention(
            room_id=ROOM,
            retentions=("session",),
        )

        after = self.path.read_bytes()
        self.assertNotIn(secret_bytes, after)
        self.assertEqual(
            "",
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )[0].body,
        )

    def test_hide_then_retention_redaction_preserves_both_monotonic_states(self) -> None:
        sent = self.send(
            self.draft(
                "hidden-then-redacted",
                "Moderated before session end",
            )
        )
        hide = self.moderation(
            "hide-before-redaction",
            target=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            allowed=None,
            message_id=sent.message_id,
        )
        self.service.apply_moderation(
            trusted_caller_identity=TEACHER,
            commands=(hide,),
        )

        redaction = self.service.redact_retention(
            room_id=ROOM,
            retentions=("session",),
        )

        self.assertEqual(1, len(redaction))
        self.assertEqual(1, redaction[0].revision)
        updates = self.store.state_updates_after(
            room_id=ROOM,
            after_revision=None,
            limit=10,
        )
        self.assertEqual(2, len(updates))
        self.assertTrue(updates[0].hidden)
        self.assertFalse(updates[0].redacted)
        self.assertFalse(updates[1].hidden)
        self.assertTrue(updates[1].redacted)
        final = self.store.history_after(
            room_id=ROOM,
            after_sequence=None,
            limit=10,
        )[0]
        self.assertTrue(final.hidden)
        self.assertTrue(final.redacted)
        self.assertEqual("", final.body)
        self.store.integrity_check()

    def test_retention_redaction_is_selective_and_persistent_policy_is_forbidden(self) -> None:
        transient_service = ClassroomChatServerService(
            store=self.store,
            authorization=self.auth,
            clock_unix_ms=self.clock,
            retention_policy=lambda _room_id: "transient",
        )
        transient = transient_service.send_message(
            trusted_caller_identity=STUDENT,
            draft=ChatDraft(
                "transient-to-redact",
                ROOM,
                STUDENT,
                "Transient content",
                retention="transient",
            ),
        )
        session = self.send(
            self.draft(
                "session-to-keep",
                "Session content",
            )
        )

        updates = self.service.redact_retention(
            room_id=ROOM,
            retentions=("transient",),
        )
        self.assertEqual((transient.message_id,), tuple(x.message_id for x in updates))
        history = self.store.history_after(
            room_id=ROOM,
            after_sequence=None,
            limit=10,
        )
        by_id = {message.message_id: message for message in history}
        self.assertTrue(by_id[transient.message_id].redacted)
        self.assertEqual("", by_id[transient.message_id].body)
        self.assertFalse(by_id[session.message_id].redacted)
        self.assertEqual("Session content", by_id[session.message_id].body)

        for invalid in (
            ("persistent",),
            ("session", "session"),
            (),
            ["session"],
            (object(),),
        ):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaisesRegex(
                    ClassroomChatServerError,
                    "retention redaction policy is invalid",
                ):
                    self.service.redact_retention(
                        room_id=ROOM,
                        retentions=invalid,
                    )

    def test_corrupt_redaction_body_or_duplicate_transition_fails_closed(self) -> None:
        sent = self.send(self.draft("redaction-corruption", "Erase me"))
        self.service.redact_retention(
            room_id=ROOM,
            retentions=("session",),
        )
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                UPDATE classroom_chat_server_messages
                SET body='resurrected'
                WHERE message_id=?
                """,
                (sent.message_id,),
            )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "stored message redaction state is invalid",
        ):
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            )

        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                UPDATE classroom_chat_server_messages
                SET body=''
                WHERE message_id=?
                """,
                (sent.message_id,),
            )
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden, redacted
                ) VALUES(?,?,?,?,?)
                """,
                (ROOM, 1, sent.message_id, 0, 1),
            )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "state transition is duplicated",
        ):
            self.store.state_updates_after(
                room_id=ROOM,
                after_revision=None,
                limit=10,
            )

    def test_retention_policy_failure_is_sanitized_before_storage(self) -> None:
        def broken_policy(_room_id):
            raise RuntimeError("sensitive deployment policy detail")

        service = ClassroomChatServerService(
            store=self.store,
            authorization=self.auth,
            clock_unix_ms=self.clock,
            retention_policy=broken_policy,
        )
        with self.assertRaisesRegex(
            ClassroomChatServerError,
            "retention policy lookup failed",
        ) as raised:
            service.send_message(
                trusted_caller_identity=STUDENT,
                draft=self.draft("retention-policy-failure"),
            )
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(0, self.clock.calls)
        self.assertEqual(
            (),
            self.store.history_after(
                room_id=ROOM,
                after_sequence=None,
                limit=10,
            ),
        )

    def test_invalid_clock_is_rejected_without_persisting(self) -> None:
        for value in (True, -1, 253402300800000):
            service = ClassroomChatServerService(
                store=self.store,
                authorization=self.auth,
                clock_unix_ms=lambda value=value: value,
            )
            with self.subTest(value=value):
                with self.assertRaisesRegex(ClassroomChatServerError, "clock"):
                    service.send_message(
                        trusted_caller_identity=STUDENT,
                        draft=self.draft(f"bad-{str(value).replace('-', 'n')}"),
                    )
        self.assertEqual(
            (),
            self.store.history_after(room_id=ROOM, after_sequence=None, limit=10),
        )

    def test_concurrent_distinct_sends_receive_unique_gap_free_sequence(self) -> None:
        first_store = ClassroomChatServerSQLiteStore(self.path)
        second_store = ClassroomChatServerSQLiteStore(self.path)
        first = ClassroomChatServerService(
            store=first_store,
            authorization=FakeAuthorization(),
            clock_unix_ms=lambda: 1700000000000,
        )
        second = ClassroomChatServerService(
            store=second_store,
            authorization=FakeAuthorization(),
            clock_unix_ms=lambda: 1700000000000,
        )

        def send(service, message_id):
            return service.send_message(
                trusted_caller_identity=STUDENT,
                draft=self.draft(message_id),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(send, first, "race-a")
            right = pool.submit(send, second, "race-b")
            results = (left.result(), right.result())

        self.assertEqual([0, 1], sorted(item.sequence_no for item in results))
        history = self.store.history_after(
            room_id=ROOM,
            after_sequence=None,
            limit=10,
        )
        self.assertEqual([0, 1], [item.sequence_no for item in history])
        self.assertEqual({"race-a", "race-b"}, {item.message_id for item in history})

    def test_concurrent_exact_resend_keeps_one_identity_and_timestamp(self) -> None:
        stores = (
            ClassroomChatServerSQLiteStore(self.path),
            ClassroomChatServerSQLiteStore(self.path),
        )
        services = tuple(
            ClassroomChatServerService(
                store=store,
                authorization=FakeAuthorization(),
                clock_unix_ms=lambda: 1700000000000,
            )
            for store in stores
        )
        draft = self.draft("same-race")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    service.send_message,
                    trusted_caller_identity=STUDENT,
                    draft=draft,
                )
                for service in services
            ]
            results = tuple(future.result() for future in futures)

        self.assertEqual(results[0], results[1])
        self.assertEqual(0, results[0].sequence_no)
        self.assertEqual(1700000000000, results[0].sent_at_unix_ms)
        self.assertEqual(
            1,
            len(
                self.store.history_after(
                    room_id=ROOM,
                    after_sequence=None,
                    limit=10,
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
