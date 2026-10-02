from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.classroom_collaboration import (
    ChatDraft,
    ChatModerationAction,
    ChatModerationCommand,
)
from acs.classroom_collaboration_chat_server import (
    ClassroomChatServerError,
    ClassroomChatServerSQLiteStore,
    ClassroomChatServerService,
    MAX_SERVER_HISTORY_MESSAGES,
)


ROOM = "room-1"
TEACHER = "teacher-1"
STUDENT = "student-1"


class FakeAuthorization:
    def __init__(self) -> None:
        self.send_calls = []
        self.history_calls = []
        self.moderation_calls = []
        self.reject_send = False
        self.reject_history = False
        self.reject_moderation = False

    def authorize_chat_send(self, *, room_id, caller_identity, sender_id):
        self.send_calls.append((room_id, caller_identity, sender_id))
        if self.reject_send:
            raise RuntimeError("sensitive membership detail")

    def authorize_chat_history(self, *, room_id, caller_identity):
        self.history_calls.append((room_id, caller_identity))
        if self.reject_history:
            raise RuntimeError("sensitive history detail")

    def authorize_chat_moderation(self, *, room_id, caller_identity, commands):
        self.moderation_calls.append((room_id, caller_identity, commands))
        if self.reject_moderation:
            raise RuntimeError("sensitive role detail")


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

    def test_schema_is_durable_and_integrity_checked(self) -> None:
        self.store.integrity_check()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                1,
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
            }.issubset(tables)
        )

    def test_send_assigns_server_sequence_and_time_and_retry_is_stable(self) -> None:
        draft = self.draft("m1")
        first = self.send(draft)
        second = self.send(draft)

        self.assertEqual(first, second)
        self.assertEqual(0, first.sequence_no)
        self.assertEqual(1700000000000, first.sent_at_unix_ms)
        self.assertFalse(first.hidden)
        self.assertEqual(2, self.clock.calls)
        self.assertEqual(
            [(ROOM, STUDENT, STUDENT), (ROOM, STUDENT, STUDENT)],
            self.auth.send_calls,
        )

        reopened = ClassroomChatServerSQLiteStore(self.path)
        self.assertEqual(
            (first,),
            reopened.history_after(room_id=ROOM, after_sequence=None, limit=10),
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
