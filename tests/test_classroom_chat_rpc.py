from __future__ import annotations

from dataclasses import replace
import unittest

from acs.classroom_chat_rpc import (
    MAX_MODERATION_COMMANDS,
    ClassroomChatRpcClient,
    ClassroomChatRpcError,
    ClassroomChatRpcService,
)
from acs.classroom_collaboration import (
    ChatDraft,
    ChatModerationAction,
    ChatModerationCommand,
)
from acs.classroom_collaboration_storage import ChatMessageMetadata


class FakeAuthority:
    def __init__(self) -> None:
        self.members = {"teacher-1", "student-1", "student-2"}
        self.member_calls = []
        self.moderation_calls = []
        self.fail = False

    def authorize_member(self, *, room_id, participant_id) -> None:
        self.member_calls.append((room_id, participant_id))
        if self.fail or room_id != "room-1" or participant_id not in self.members:
            raise RuntimeError("authority secret detail")

    def authorize_moderation(self, *, room_id, actor_id, commands) -> None:
        self.moderation_calls.append((room_id, actor_id, commands))
        if self.fail or room_id != "room-1" or actor_id != "teacher-1":
            raise RuntimeError("authority secret detail")


class FakeBackend:
    def __init__(self) -> None:
        self.by_id = {}
        self.ordered = []
        self.moderation_calls = []
        self.fail = False
        self.omit_timestamp = False
        self.mutate_delivery = False
        self.history_override = None

    def send_message(self, draft):
        if self.fail:
            raise RuntimeError("backend supersecret token")
        existing = self.by_id.get(draft.message_id)
        if existing is not None:
            return existing
        message = ChatMessageMetadata(
            message_id=draft.message_id,
            room_id=draft.room_id,
            sender_id=draft.sender_id,
            sequence_no=len(self.ordered),
            body=draft.body,
            retention=draft.retention,
            sent_at_unix_ms=(
                None
                if self.omit_timestamp
                else 1700000000000 + len(self.ordered) * 1000
            ),
        )
        if self.mutate_delivery:
            message = replace(message, body="mutated")
        self.by_id[draft.message_id] = message
        self.ordered.append(message)
        return message

    def history_after(self, *, room_id, after_sequence, limit):
        if self.fail:
            raise RuntimeError("backend supersecret token")
        if self.history_override is not None:
            return self.history_override
        rows = tuple(
            item
            for item in self.ordered
            if item.room_id == room_id
            and (after_sequence is None or item.sequence_no > after_sequence)
        )
        return rows[:limit]

    def apply_moderation(self, commands) -> None:
        if self.fail:
            raise RuntimeError("backend supersecret token")
        self.moderation_calls.append(commands)


class BoundCall:
    def __init__(self, service, *, room_id, participant_id) -> None:
        self.service = service
        self.room_id = room_id
        self.participant_id = participant_id
        self.calls = []
        self.fail = False

    def call(self, request):
        self.calls.append(dict(request))
        if self.fail:
            raise RuntimeError("transport bearer secret")
        return self.service.handle(
            dict(request),
            authenticated_room_id=self.room_id,
            authenticated_participant_id=self.participant_id,
        )


class StaticCall:
    def __init__(self, response) -> None:
        self.response = response

    def call(self, request):
        return self.response


class ClassroomChatRpcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = FakeAuthority()
        self.backend = FakeBackend()
        self.service = ClassroomChatRpcService(
            authority=self.authority,
            backend=self.backend,
        )
        self.student_call = BoundCall(
            self.service,
            room_id="room-1",
            participant_id="student-1",
        )
        self.student = ClassroomChatRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=self.student_call,
        )

    def test_send_round_trip_is_idempotent_and_preserves_authoritative_timestamp(self):
        draft = ChatDraft("msg-1", "room-1", "student-1", "Hello")
        first = self.student.send_message(draft)
        second = self.student.send_message(draft)
        self.assertEqual(first, second)
        self.assertEqual(0, first.sequence_no)
        self.assertEqual(1700000000000, first.sent_at_unix_ms)
        self.assertEqual(1, len(self.backend.ordered))
        self.assertEqual(
            [("room-1", "student-1"), ("room-1", "student-1")],
            self.authority.member_calls,
        )
        self.assertNotIn("sent_at_unix_ms", self.student_call.calls[0]["message"])

    def test_history_round_trip_is_ordered_bounded_and_timestamped(self):
        self.student.send_message(ChatDraft("msg-1", "room-1", "student-1", "One"))
        self.student.send_message(ChatDraft("msg-2", "room-1", "student-1", "Two"))
        rows = self.student.history_after(
            room_id="room-1", after_sequence=0, limit=5
        )
        self.assertEqual(["msg-2"], [item.message_id for item in rows])
        self.assertEqual([1700000001000], [item.sent_at_unix_ms for item in rows])

    def test_client_refuses_room_or_sender_forgery_before_transport(self):
        with self.assertRaisesRegex(ClassroomChatRpcError, "bound identity"):
            self.student.send_message(
                ChatDraft("msg-1", "room-1", "teacher-1", "No")
            )
        with self.assertRaisesRegex(ClassroomChatRpcError, "bound room"):
            self.student.history_after(
                room_id="room-2", after_sequence=None, limit=1
            )
        self.assertEqual([], self.student_call.calls)

    def test_server_binds_payload_identity_to_authenticated_transport(self):
        request = {
            "v": 1,
            "op": "send",
            "room_id": "room-1",
            "participant_id": "teacher-1",
            "message": {
                "message_id": "msg-1",
                "body": "Forged",
                "retention": "session",
            },
        }
        with self.assertRaisesRegex(ClassroomChatRpcError, "authenticated transport"):
            self.service.handle(
                request,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )
        self.assertEqual([], self.backend.ordered)

    def test_server_rejects_unknown_fields_versions_and_boolean_integer_confusion(self):
        valid = {
            "v": 1,
            "op": "history",
            "room_id": "room-1",
            "participant_id": "student-1",
            "after_sequence": None,
            "limit": 5,
        }
        with self.assertRaisesRegex(ClassroomChatRpcError, "fields"):
            self.service.handle(
                dict(valid, secret="browser-owned"),
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )
        for bad in (
            dict(valid, v=True),
            dict(valid, v=2),
            dict(valid, limit=True),
        ):
            with self.assertRaises(ClassroomChatRpcError):
                self.service.handle(
                    bad,
                    authenticated_room_id="room-1",
                    authenticated_participant_id="student-1",
                )

    def test_live_send_rejects_missing_timestamp_and_mutated_identity(self):
        self.backend.omit_timestamp = True
        with self.assertRaisesRegex(ClassroomChatRpcError, "immutable|timestamp"):
            self.student.send_message(
                ChatDraft("msg-1", "room-1", "student-1", "Hello")
            )

        backend = FakeBackend()
        backend.mutate_delivery = True
        service = ClassroomChatRpcService(authority=self.authority, backend=backend)
        client = ClassroomChatRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=BoundCall(
                service, room_id="room-1", participant_id="student-1"
            ),
        )
        with self.assertRaisesRegex(ClassroomChatRpcError, "immutable"):
            client.send_message(
                ChatDraft("msg-2", "room-1", "student-1", "Hello")
            )

    def test_history_rejects_cross_room_unordered_duplicate_and_missing_timestamp(self):
        cases = (
            (
                ChatMessageMetadata(
                    "x", "room-2", "student-2", 1, "X", sent_at_unix_ms=1
                ),
            ),
            (
                ChatMessageMetadata(
                    "a", "room-1", "student-2", 2, "A", sent_at_unix_ms=2
                ),
                ChatMessageMetadata(
                    "b", "room-1", "student-2", 1, "B", sent_at_unix_ms=3
                ),
            ),
            (
                ChatMessageMetadata(
                    "a", "room-1", "student-2", 1, "A", sent_at_unix_ms=2
                ),
                ChatMessageMetadata(
                    "a", "room-1", "student-2", 2, "B", sent_at_unix_ms=3
                ),
            ),
            (
                ChatMessageMetadata("a", "room-1", "student-2", 1, "A"),
            ),
        )
        for rows in cases:
            with self.subTest(rows=rows):
                self.backend.history_override = rows
                with self.assertRaises(ClassroomChatRpcError):
                    self.student.history_after(
                        room_id="room-1",
                        after_sequence=None,
                        limit=10,
                    )

    def test_history_rejects_gap_after_known_local_baseline(self):
        self.backend.history_override = (
            ChatMessageMetadata(
                "m2",
                "room-1",
                "student-2",
                2,
                "Gap",
                sent_at_unix_ms=1700000002000,
            ),
        )
        with self.assertRaisesRegex(ClassroomChatRpcError, "sequence gap"):
            self.student.history_after(
                room_id="room-1",
                after_sequence=0,
                limit=10,
            )

    def test_moderation_round_trip_preserves_operation_identity_and_requires_authority(self):
        teacher_call = BoundCall(
            self.service,
            room_id="room-1",
            participant_id="teacher-1",
        )
        teacher = ClassroomChatRpcClient(
            room_id="room-1",
            participant_id="teacher-1",
            transport=teacher_call,
        )
        commands = (
            ChatModerationCommand(
                operation_id="op-1",
                room_id="room-1",
                actor_id="teacher-1",
                target_id="student-2",
                action=ChatModerationAction.SET_SEND_PERMISSION,
                allowed=False,
            ),
            ChatModerationCommand(
                operation_id="op-2",
                room_id="room-1",
                actor_id="teacher-1",
                target_id=None,
                action=ChatModerationAction.HIDE_MESSAGE,
                message_id="msg-1",
            ),
        )
        teacher.apply_moderation(commands)
        self.assertEqual(commands, self.backend.moderation_calls[-1])
        self.assertEqual(
            ("room-1", "teacher-1", commands),
            self.authority.moderation_calls[-1],
        )

        student_command = replace(commands[0], actor_id="student-1")
        with self.assertRaisesRegex(ClassroomChatRpcError, "service unavailable"):
            self.student.apply_moderation((student_command,))
        direct = {
            "v": 1,
            "op": "moderate",
            "room_id": "room-1",
            "participant_id": "student-1",
            "commands": [{
                "operation_id": "op-student",
                "action": "set_send_permission",
                "target_id": "student-2",
                "allowed": False,
            }],
        }
        with self.assertRaisesRegex(ClassroomChatRpcError, "authorization"):
            self.service.handle(
                direct,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )

    def test_moderation_batch_is_bounded_and_command_shape_is_closed(self):
        teacher = ClassroomChatRpcClient(
            room_id="room-1",
            participant_id="teacher-1",
            transport=BoundCall(
                self.service, room_id="room-1", participant_id="teacher-1"
            ),
        )
        command = ChatModerationCommand(
            operation_id="op",
            room_id="room-1",
            actor_id="teacher-1",
            target_id="student-2",
            action=ChatModerationAction.SET_SEND_PERMISSION,
            allowed=False,
        )
        with self.assertRaisesRegex(ClassroomChatRpcError, "too large"):
            teacher.apply_moderation(
                tuple(
                    replace(command, operation_id=f"op-{i}")
                    for i in range(MAX_MODERATION_COMMANDS + 1)
                )
            )

        forged = {
            "v": 1,
            "op": "moderate",
            "room_id": "room-1",
            "participant_id": "teacher-1",
            "commands": [{
                "operation_id": "op-1",
                "action": "set_send_permission",
                "target_id": "student-2",
                "allowed": False,
                "role": "teacher",
            }],
        }
        with self.assertRaisesRegex(ClassroomChatRpcError, "invalid"):
            self.service.handle(
                forged,
                authenticated_room_id="room-1",
                authenticated_participant_id="teacher-1",
            )

    def test_backend_authority_and_transport_failures_are_sanitized(self):
        self.backend.fail = True
        with self.assertRaises(ClassroomChatRpcError) as caught:
            self.student.send_message(
                ChatDraft("msg-1", "room-1", "student-1", "Hello")
            )
        self.assertNotIn("supersecret", str(caught.exception))

        self.backend.fail = False
        self.authority.fail = True
        with self.assertRaises(ClassroomChatRpcError) as caught:
            self.student.send_message(
                ChatDraft("msg-2", "room-1", "student-1", "Hello")
            )
        self.assertNotIn("secret detail", str(caught.exception))

        self.authority.fail = False
        self.student_call.fail = True
        with self.assertRaises(ClassroomChatRpcError) as caught:
            self.student.send_message(
                ChatDraft("msg-3", "room-1", "student-1", "Hello")
            )
        self.assertNotIn("bearer secret", str(caught.exception))

    def test_client_rejects_malformed_or_identity_mutating_response(self):
        draft = ChatDraft("msg-1", "room-1", "student-1", "Hello")
        malformed = ClassroomChatRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=StaticCall({"v": 1, "ok": True, "message": {}}),
        )
        with self.assertRaises(ClassroomChatRpcError):
            malformed.send_message(draft)

        changed = ClassroomChatRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=StaticCall({
                "v": 1,
                "ok": True,
                "message": {
                    "message_id": "msg-1",
                    "room_id": "room-1",
                    "sender_id": "student-1",
                    "sequence_no": 0,
                    "body": "Changed",
                    "retention": "session",
                    "hidden": False,
                    "sent_at_unix_ms": 1700000000000,
                },
            }),
        )
        with self.assertRaisesRegex(ClassroomChatRpcError, "immutable"):
            changed.send_message(draft)


if __name__ == "__main__":
    unittest.main()
