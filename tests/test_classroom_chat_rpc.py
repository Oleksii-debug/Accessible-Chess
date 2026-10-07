from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
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
from acs.classroom_collaboration_chat_server import (
    ClassroomChatServerService,
    ClassroomChatServerSQLiteStore,
)
from acs.classroom_collaboration_storage import (
    ChatMessageMetadata,
    ChatMessageStateUpdate,
)
from acs.classroom_domain import MAX_WIRE_INTEGER


class RealServerAuthorization:
    def __init__(self) -> None:
        self.members = {"teacher-1", "student-1"}

    def authorize_chat_send(
        self,
        *,
        room_id,
        caller_identity,
        sender_id,
    ):
        if (
            room_id != "room-1"
            or caller_identity not in self.members
            or sender_id != caller_identity
        ):
            raise RuntimeError("not authorized")
        return None

    def authorize_chat_history(self, *, room_id, caller_identity):
        if room_id != "room-1" or caller_identity not in self.members:
            raise RuntimeError("not authorized")
        return None

    def authorize_chat_moderation(
        self,
        *,
        room_id,
        caller_identity,
        commands,
    ):
        if (
            room_id != "room-1"
            or caller_identity != "teacher-1"
            or any(command.actor_id != caller_identity for command in commands)
        ):
            raise RuntimeError("not authorized")
        return None


class FakeBackend:
    def __init__(self) -> None:
        self.members = {"teacher-1", "student-1", "student-2"}
        self.by_id = {}
        self.ordered = []
        self.send_callers = []
        self.history_callers = []
        self.moderation_callers = []
        self.moderation_calls = []
        self.state_updates = []
        self.fail = False
        self.auth_fail = False
        self.send_allowed = True
        self.omit_timestamp = False
        self.mutate_delivery = False
        self.history_override = None
        self.state_override = None

    def send_message(self, *, trusted_caller_identity, draft):
        self.send_callers.append(trusted_caller_identity)
        if self.fail:
            raise RuntimeError("backend supersecret token")
        if (
            self.auth_fail
            or not self.send_allowed
            or trusted_caller_identity not in self.members
            or draft.room_id != "room-1"
            or draft.sender_id != trusted_caller_identity
        ):
            raise RuntimeError("server authorization secret detail")
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

    def history_after(
        self,
        *,
        trusted_caller_identity,
        room_id,
        after_sequence,
        limit,
    ):
        self.history_callers.append(trusted_caller_identity)
        if self.fail:
            raise RuntimeError("backend supersecret token")
        if (
            self.auth_fail
            or trusted_caller_identity not in self.members
            or room_id != "room-1"
        ):
            raise RuntimeError("server authorization secret detail")
        if self.history_override is not None:
            return self.history_override
        rows = tuple(
            item
            for item in self.ordered
            if item.room_id == room_id
            and (after_sequence is None or item.sequence_no > after_sequence)
        )
        return rows[:limit]

    def state_updates_after(
        self,
        *,
        trusted_caller_identity,
        room_id,
        after_revision,
        limit,
    ):
        self.history_callers.append(trusted_caller_identity)
        if self.fail:
            raise RuntimeError("backend supersecret token")
        if (
            self.auth_fail
            or trusted_caller_identity not in self.members
            or room_id != "room-1"
        ):
            raise RuntimeError("server authorization secret detail")
        if self.state_override is not None:
            return self.state_override
        rows = tuple(
            item
            for item in self.state_updates
            if item.room_id == room_id
            and (after_revision is None or item.revision > after_revision)
        )
        return rows[:limit]

    def apply_moderation(self, *, trusted_caller_identity, commands) -> None:
        self.moderation_callers.append(trusted_caller_identity)
        if self.fail:
            raise RuntimeError("backend supersecret token")
        if (
            self.auth_fail
            or trusted_caller_identity != "teacher-1"
            or any(command.actor_id != trusted_caller_identity for command in commands)
        ):
            raise RuntimeError("server authorization secret detail")
        self.moderation_calls.append(commands)
        for command in commands:
            if command.action is not ChatModerationAction.HIDE_MESSAGE:
                continue
            self.state_updates.append(
                ChatMessageStateUpdate(
                    room_id=command.room_id,
                    message_id=command.message_id,
                    revision=len(self.state_updates),
                )
            )


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
        self.backend = FakeBackend()
        self.service = ClassroomChatRpcService(
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

    def test_real_trusted_server_round_trip_hide_and_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "chat-server.sqlite3"
            authorization = RealServerAuthorization()
            ticks = iter((1700000000000, 1700000001000))

            server = ClassroomChatServerService(
                store=ClassroomChatServerSQLiteStore(database),
                authorization=authorization,
                clock_unix_ms=lambda: next(ticks),
            )
            endpoint = ClassroomChatRpcService(backend=server)
            student = ClassroomChatRpcClient(
                room_id="room-1",
                participant_id="student-1",
                transport=BoundCall(
                    endpoint,
                    room_id="room-1",
                    participant_id="student-1",
                ),
            )
            teacher = ClassroomChatRpcClient(
                room_id="room-1",
                participant_id="teacher-1",
                transport=BoundCall(
                    endpoint,
                    room_id="room-1",
                    participant_id="teacher-1",
                ),
            )

            sent = student.send_message(
                ChatDraft(
                    "real-rpc-message",
                    "room-1",
                    "student-1",
                    "Durable through RPC",
                )
            )
            self.assertEqual(0, sent.sequence_no)
            self.assertEqual(1700000000000, sent.sent_at_unix_ms)
            self.assertEqual(
                (sent,),
                teacher.history_after(
                    room_id="room-1",
                    after_sequence=None,
                    limit=10,
                ),
            )

            teacher.apply_moderation(
                (
                    ChatModerationCommand(
                        operation_id="real-rpc-hide",
                        room_id="room-1",
                        actor_id="teacher-1",
                        target_id=None,
                        action=ChatModerationAction.HIDE_MESSAGE,
                        message_id=sent.message_id,
                    ),
                )
            )
            updates = student.state_updates_after(
                room_id="room-1",
                after_revision=None,
                limit=10,
            )
            self.assertEqual(1, len(updates))
            self.assertEqual(sent.message_id, updates[0].message_id)
            self.assertTrue(updates[0].hidden)

            recovered_after_hide = student.send_message(
                ChatDraft(
                    "real-rpc-message",
                    "room-1",
                    "student-1",
                    "Durable through RPC",
                )
            )
            self.assertEqual(sent.message_id, recovered_after_hide.message_id)
            self.assertEqual(sent.sequence_no, recovered_after_hide.sequence_no)
            self.assertEqual(
                sent.sent_at_unix_ms,
                recovered_after_hide.sent_at_unix_ms,
            )
            self.assertTrue(recovered_after_hide.hidden)

            restarted_server = ClassroomChatServerService(
                store=ClassroomChatServerSQLiteStore(database),
                authorization=authorization,
                clock_unix_ms=lambda: 1700000001000,
            )
            restarted_endpoint = ClassroomChatRpcService(
                backend=restarted_server,
            )
            reconnected_student = ClassroomChatRpcClient(
                room_id="room-1",
                participant_id="student-1",
                transport=BoundCall(
                    restarted_endpoint,
                    room_id="room-1",
                    participant_id="student-1",
                ),
            )
            history = reconnected_student.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            )
            self.assertEqual(1, len(history))
            self.assertEqual(sent.message_id, history[0].message_id)
            self.assertTrue(history[0].hidden)
            self.assertEqual(
                updates,
                reconnected_student.state_updates_after(
                    room_id="room-1",
                    after_revision=None,
                    limit=10,
                ),
            )

    def test_real_trusted_server_retention_redaction_round_trips_and_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "chat-redaction.sqlite3"
            authorization = RealServerAuthorization()
            server = ClassroomChatServerService(
                store=ClassroomChatServerSQLiteStore(database),
                authorization=authorization,
                clock_unix_ms=lambda: 1700000000000,
            )
            endpoint = ClassroomChatRpcService(backend=server)
            student = ClassroomChatRpcClient(
                room_id="room-1",
                participant_id="student-1",
                transport=BoundCall(
                    endpoint,
                    room_id="room-1",
                    participant_id="student-1",
                ),
            )
            draft = ChatDraft(
                "real-rpc-redacted",
                "room-1",
                "student-1",
                "Private session payload",
            )
            sent = student.send_message(draft)

            authority_updates = server.redact_retention(
                room_id="room-1",
                retentions=("session",),
            )
            self.assertEqual(1, len(authority_updates))
            self.assertTrue(authority_updates[0].redacted)
            self.assertFalse(authority_updates[0].hidden)

            history = student.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            )
            self.assertEqual(1, len(history))
            self.assertEqual(sent.message_id, history[0].message_id)
            self.assertEqual(sent.sequence_no, history[0].sequence_no)
            self.assertEqual(sent.sent_at_unix_ms, history[0].sent_at_unix_ms)
            self.assertEqual("", history[0].body)
            self.assertTrue(history[0].redacted)
            self.assertEqual(
                authority_updates,
                student.state_updates_after(
                    room_id="room-1",
                    after_revision=None,
                    limit=10,
                ),
            )

            restarted = ClassroomChatServerService(
                store=ClassroomChatServerSQLiteStore(database),
                authorization=authorization,
                clock_unix_ms=lambda: 1700000001000,
            )
            reconnected = ClassroomChatRpcClient(
                room_id="room-1",
                participant_id="student-1",
                transport=BoundCall(
                    ClassroomChatRpcService(backend=restarted),
                    room_id="room-1",
                    participant_id="student-1",
                ),
            )
            durable = reconnected.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            )
            self.assertEqual("", durable[0].body)
            self.assertTrue(durable[0].redacted)
            self.assertEqual(authority_updates, reconnected.state_updates_after(
                room_id="room-1",
                after_revision=None,
                limit=10,
            ))

            with self.assertRaisesRegex(
                ClassroomChatRpcError,
                "service unavailable",
            ):
                reconnected.send_message(draft)
            self.assertEqual(
                "",
                reconnected.history_after(
                    room_id="room-1",
                    after_sequence=None,
                    limit=10,
                )[0].body,
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
            ["student-1", "student-1"],
            self.backend.send_callers,
        )
        self.assertNotIn("sent_at_unix_ms", self.student_call.calls[0]["message"])

    def test_message_id_retry_with_different_payload_is_rejected(self):
        self.student.send_message(
            ChatDraft("msg-conflict", "room-1", "student-1", "Original")
        )
        request = {
            "v": 1,
            "op": "send",
            "room_id": "room-1",
            "participant_id": "student-1",
            "message": {
                "message_id": "msg-conflict",
                "body": "Changed",
                "retention": "session",
            },
        }
        with self.assertRaisesRegex(ClassroomChatRpcError, "immutable"):
            self.service.handle(
                request,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )
        self.assertEqual(1, len(self.backend.ordered))
        self.assertEqual("Original", self.backend.ordered[0].body)

    def test_history_round_trip_is_ordered_bounded_and_timestamped(self):
        self.student.send_message(ChatDraft("msg-1", "room-1", "student-1", "One"))
        self.student.send_message(ChatDraft("msg-2", "room-1", "student-1", "Two"))
        rows = self.student.history_after(
            room_id="room-1", after_sequence=0, limit=5
        )
        self.assertEqual(["msg-2"], [item.message_id for item in rows])
        self.assertEqual([1700000001000], [item.sent_at_unix_ms for item in rows])

    def test_redacted_history_round_trip_preserves_sequence_without_body(self):
        self.backend.history_override = (
            ChatMessageMetadata(
                "msg-redacted",
                "room-1",
                "student-2",
                0,
                "",
                "session",
                sent_at_unix_ms=1700000000000,
                redacted=True,
            ),
        )

        rows = self.student.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=10,
        )

        self.assertEqual(1, len(rows))
        self.assertEqual("msg-redacted", rows[0].message_id)
        self.assertEqual(0, rows[0].sequence_no)
        self.assertEqual(1700000000000, rows[0].sent_at_unix_ms)
        self.assertEqual("", rows[0].body)
        self.assertTrue(rows[0].redacted)
        self.assertFalse(rows[0].hidden)

    def test_state_update_stream_round_trip_is_authorized_and_contiguous(self):
        self.backend.state_updates = [
            ChatMessageStateUpdate("room-1", "msg-1", 0),
            ChatMessageStateUpdate(
                "room-1",
                "msg-2",
                1,
                hidden=False,
                redacted=True,
            ),
        ]
        first = self.student.state_updates_after(
            room_id="room-1",
            after_revision=None,
            limit=10,
        )
        self.assertEqual([0, 1], [item.revision for item in first])
        self.assertTrue(first[0].hidden)
        self.assertFalse(first[0].redacted)
        self.assertFalse(first[1].hidden)
        self.assertTrue(first[1].redacted)
        later = self.student.state_updates_after(
            room_id="room-1",
            after_revision=0,
            limit=10,
        )
        self.assertEqual(["msg-2"], [item.message_id for item in later])
        self.assertEqual(
            ["student-1", "student-1"],
            self.backend.history_callers,
        )

    def test_state_update_stream_rejects_room_revision_and_shape_forgery(self):
        cases = (
            (ChatMessageStateUpdate("room-2", "msg-x", 0),),
            (ChatMessageStateUpdate("room-1", "msg-x", 1),),
            (
                ChatMessageStateUpdate("room-1", "msg-x", 0),
                ChatMessageStateUpdate("room-1", "msg-y", 2),
            ),
        )
        for updates in cases:
            with self.subTest(updates=updates):
                self.backend.state_override = updates
                with self.assertRaises(ClassroomChatRpcError):
                    self.student.state_updates_after(
                        room_id="room-1",
                        after_revision=None,
                        limit=10,
                    )

        malformed = ClassroomChatRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=StaticCall({
                "v": 1,
                "ok": True,
                "updates": [{
                    "room_id": "room-1",
                    "message_id": "msg-x",
                    "revision": 0,
                    "hidden": False,
                }],
            }),
        )
        with self.assertRaisesRegex(ClassroomChatRpcError, "state update"):
            malformed.state_updates_after(
                room_id="room-1",
                after_revision=None,
                limit=10,
            )

    def test_state_update_wire_rejects_missing_or_non_boolean_redacted_flag(self):
        for update in (
            {
                "room_id": "room-1",
                "message_id": "msg-x",
                "revision": 0,
                "hidden": True,
            },
            {
                "room_id": "room-1",
                "message_id": "msg-x",
                "revision": 0,
                "hidden": False,
                "redacted": 1,
            },
        ):
            client = ClassroomChatRpcClient(
                room_id="room-1",
                participant_id="student-1",
                transport=StaticCall(
                    {"v": 1, "ok": True, "updates": [update]}
                ),
            )
            with self.subTest(update=update):
                with self.assertRaisesRegex(
                    ClassroomChatRpcError,
                    "state update",
                ):
                    client.state_updates_after(
                        room_id="room-1",
                        after_revision=None,
                        limit=10,
                    )

    def test_state_update_client_refuses_cross_room_and_bool_revision(self):
        with self.assertRaisesRegex(ClassroomChatRpcError, "bound room"):
            self.student.state_updates_after(
                room_id="room-2",
                after_revision=None,
                limit=1,
            )
        with self.assertRaisesRegex(ClassroomChatRpcError, "after_revision"):
            self.student.state_updates_after(
                room_id="room-1",
                after_revision=True,
                limit=1,
            )

    def test_client_and_service_reject_json_unsafe_cursors(self):
        over = MAX_WIRE_INTEGER + 1
        before = len(self.student_call.calls)
        with self.assertRaisesRegex(ClassroomChatRpcError, "after_sequence"):
            self.student.history_after(
                room_id="room-1",
                after_sequence=over,
                limit=1,
            )
        with self.assertRaisesRegex(ClassroomChatRpcError, "after_revision"):
            self.student.state_updates_after(
                room_id="room-1",
                after_revision=over,
                limit=1,
            )
        self.assertEqual(before, len(self.student_call.calls))

        history_request = {
            "v": 1,
            "op": "history",
            "room_id": "room-1",
            "participant_id": "student-1",
            "after_sequence": over,
            "limit": 1,
        }
        state_request = {
            "v": 1,
            "op": "state",
            "room_id": "room-1",
            "participant_id": "student-1",
            "after_revision": over,
            "limit": 1,
        }
        for request in (history_request, state_request):
            with self.subTest(op=request["op"]):
                with self.assertRaises(ClassroomChatRpcError):
                    self.service.handle(
                        request,
                        authenticated_room_id="room-1",
                        authenticated_participant_id="student-1",
                    )

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

    def test_server_enforces_current_send_policy_before_backend_effect(self):
        self.backend.send_allowed = False
        request = {
            "v": 1,
            "op": "send",
            "room_id": "room-1",
            "participant_id": "student-1",
            "message": {
                "message_id": "msg-muted",
                "body": "Bypass attempt",
                "retention": "session",
            },
        }
        with self.assertRaisesRegex(ClassroomChatRpcError, "backend failed"):
            self.service.handle(
                request,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )
        self.assertEqual([], self.backend.ordered)

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
        service = ClassroomChatRpcService(backend=backend)
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

    def test_history_rejects_missing_initial_prefix(self):
        self.backend.history_override = (
            ChatMessageMetadata(
                "m1",
                "room-1",
                "student-2",
                1,
                "Missing sequence zero",
                sent_at_unix_ms=1700000001000,
            ),
        )

        with self.assertRaisesRegex(ClassroomChatRpcError, "sequence gap"):
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
        self.assertEqual("teacher-1", self.backend.moderation_callers[-1])

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
        with self.assertRaisesRegex(ClassroomChatRpcError, "backend failed"):
            self.service.handle(
                direct,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )

    def test_moderation_batch_above_legacy_256_reaches_trusted_server(self):
        self.assertEqual(5000, MAX_MODERATION_COMMANDS)
        teacher = ClassroomChatRpcClient(
            room_id="room-1",
            participant_id="teacher-1",
            transport=BoundCall(
                self.service, room_id="room-1", participant_id="teacher-1"
            ),
        )
        commands = tuple(
            ChatModerationCommand(
                operation_id=f"bulk-{index}",
                room_id="room-1",
                actor_id="teacher-1",
                target_id="student-2",
                action=ChatModerationAction.SET_SEND_PERMISSION,
                allowed=False,
            )
            for index in range(257)
        )

        teacher.apply_moderation(commands)

        self.assertEqual(commands, self.backend.moderation_calls[-1])
        self.assertEqual("teacher-1", self.backend.moderation_callers[-1])

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

    def test_backend_authorization_and_transport_failures_are_sanitized(self):
        self.backend.fail = True
        with self.assertRaises(ClassroomChatRpcError) as caught:
            self.student.send_message(
                ChatDraft("msg-1", "room-1", "student-1", "Hello")
            )
        self.assertNotIn("supersecret", str(caught.exception))

        self.backend.fail = False
        self.backend.auth_fail = True
        with self.assertRaises(ClassroomChatRpcError) as caught:
            self.student.send_message(
                ChatDraft("msg-2", "room-1", "student-1", "Hello")
            )
        self.assertNotIn("authorization secret detail", str(caught.exception))

        self.backend.auth_fail = False
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
                    "redacted": False,
                    "sent_at_unix_ms": 1700000000000,
                },
            }),
        )
        with self.assertRaisesRegex(ClassroomChatRpcError, "immutable"):
            changed.send_message(draft)


if __name__ == "__main__":
    unittest.main()
