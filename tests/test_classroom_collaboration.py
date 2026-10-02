from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.classroom_collaboration import (
    ChatDraft,
    ClassroomCollaborationController,
    CollaborationError,
    FileQuotaPolicy,
    PreparedFile,
)
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    AttachmentStateUpdate,
    ChatMessageMetadata,
    ChatMessageStateUpdate,
    ClassroomCollaborationSQLiteStore,
    content_sha256,
)
from acs.classroom_domain import MAX_WIRE_INTEGER
from acs.classroom_realtime_media import ClassroomRole


class FakeRoster:
    def __init__(self):
        self.roles = {
            "teacher-1": ClassroomRole.TEACHER,
            "co-1": ClassroomRole.CO_TEACHER,
            "student-1": ClassroomRole.STUDENT,
            "student-2": ClassroomRole.STUDENT,
            "observer-1": ClassroomRole.OBSERVER,
        }

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]

    def board_control_allowed(self, participant_id):
        return participant_id != "observer-1"


class FakeChat:
    def __init__(self):
        self.messages = {}
        self.ordered = []
        self.moderation_calls = []
        self.state_updates = []
        self.send_allowed = {}
        self.mutate_delivery = False
        self.omit_timestamp = False

    def send_message(self, draft):
        if not self.send_allowed.get((draft.room_id, draft.sender_id), True):
            raise CollaborationError("server rejected locked chat sender")
        current = self.messages.get(draft.message_id)
        if current is not None:
            return current
        message = ChatMessageMetadata(
            draft.message_id,
            draft.room_id,
            draft.sender_id,
            len(self.ordered),
            draft.body,
            draft.retention,
            sent_at_unix_ms=(
                None
                if self.omit_timestamp
                else 1700000000000 + len(self.ordered) * 1000
            ),
        )
        if self.mutate_delivery:
            message = replace(message, body="transport changed body")
        self.messages[draft.message_id] = message
        self.ordered.append(message)
        return message

    def history_after(self, *, room_id, after_sequence, limit):
        rows = tuple(
            item for item in self.ordered
            if item.room_id == room_id
            and (after_sequence is None or item.sequence_no > after_sequence)
        )
        return rows[:limit]

    def state_updates_after(self, *, room_id, after_revision, limit):
        rows = tuple(
            item for item in self.state_updates
            if item.room_id == room_id
            and (after_revision is None or item.revision > after_revision)
        )
        return rows[:limit]

    def apply_moderation(self, commands):
        self.moderation_calls.append(commands)
        for command in commands:
            if command.action.value == "set_send_permission":
                self.send_allowed[(command.room_id, command.target_id)] = command.allowed
                continue
            if command.action.value != "hide_message":
                continue
            for index, message in enumerate(self.ordered):
                if (
                    message.room_id == command.room_id
                    and message.message_id == command.message_id
                ):
                    hidden = replace(message, hidden=True)
                    self.ordered[index] = hidden
                    self.messages[hidden.message_id] = hidden
                    self.state_updates.append(
                        ChatMessageStateUpdate(
                            room_id=hidden.room_id,
                            message_id=hidden.message_id,
                            revision=len(self.state_updates),
                        )
                    )
                    break


class FakeFiles:
    def __init__(self):
        self.upload_calls = []
        self.retry_calls = []
        self.cancel_calls = []
        self.fail_upload = False
        self.fail_retry = False
        self.scan_state = "pending"
        self.attachments = {}
        self.ordered = []
        self.history_override = None
        self.state_updates = []
        self.state_override = None

    def _next_sequence(self, room_id):
        room_sequences = [
            item.sequence_no
            for item in self.ordered
            if item.room_id == room_id
        ]
        return max(room_sequences, default=-1) + 1

    def _remember(self, attachment):
        current = self.attachments.get(attachment.attachment_id)
        self.attachments[attachment.attachment_id] = attachment
        if current is None:
            self.ordered.append(attachment)
        else:
            self.ordered = [
                attachment if item.attachment_id == attachment.attachment_id else item
                for item in self.ordered
            ]
        self.ordered.sort(key=lambda item: (item.room_id, item.sequence_no))
        return attachment

    def upload(self, prepared):
        self.upload_calls.append(prepared)
        if self.fail_upload:
            raise RuntimeError("provider upload failed")
        current = self.attachments.get(prepared.metadata.attachment_id)
        sequence = (
            current.sequence_no
            if current is not None
            else self._next_sequence(prepared.metadata.room_id)
        )
        return self._remember(
            replace(
                prepared.metadata,
                sequence_no=sequence,
                transfer_state="stored",
                scan_state=self.scan_state,
            )
        )

    def retry(self, prepared):
        self.retry_calls.append(prepared)
        if self.fail_retry:
            raise RuntimeError("provider retry failed")
        current = self.attachments.get(prepared.metadata.attachment_id)
        sequence = (
            current.sequence_no
            if current is not None
            else self._next_sequence(prepared.metadata.room_id)
        )
        return self._remember(
            replace(
                prepared.metadata,
                sequence_no=sequence,
                transfer_state="stored",
                scan_state=self.scan_state,
            )
        )

    def set_authoritative_state(
        self,
        attachment_id,
        *,
        transfer_state=None,
        scan_state=None,
    ):
        current = self.attachments[attachment_id]
        updated = replace(
            current,
            transfer_state=(
                current.transfer_state
                if transfer_state is None
                else transfer_state
            ),
            scan_state=current.scan_state if scan_state is None else scan_state,
        )
        self._remember(updated)
        room_revisions = [
            item.revision
            for item in self.state_updates
            if item.room_id == updated.room_id
        ]
        state = AttachmentStateUpdate(
            room_id=updated.room_id,
            attachment_id=updated.attachment_id,
            revision=max(room_revisions, default=-1) + 1,
            transfer_state=updated.transfer_state,
            scan_state=updated.scan_state,
        )
        self.state_updates.append(state)
        return state

    def cancel(self, *, attachment_id):
        self.cancel_calls.append(attachment_id)
        current = self.attachments.get(attachment_id)
        if current is not None:
            self.set_authoritative_state(
                attachment_id,
                transfer_state="deleted",
            )

    def history_after(self, *, room_id, after_sequence, limit):
        if self.history_override is not None:
            return self.history_override
        rows = tuple(
            item
            for item in self.ordered
            if item.room_id == room_id
            and item.transfer_state in {"stored", "deleted"}
            and (after_sequence is None or item.sequence_no > after_sequence)
        )
        return rows[:limit]

    def state_updates_after(self, *, room_id, after_revision, limit):
        if self.state_override is not None:
            return self.state_override
        rows = tuple(
            item
            for item in self.state_updates
            if item.room_id == room_id
            and (after_revision is None or item.revision > after_revision)
        )
        return rows[:limit]


class FakeFileStore:
    def __init__(self):
        self.read_calls = []
        self.token = "short-lived-read-token"

    def put(self, *, object_key, content, expected_sha256):
        raise AssertionError("controller must not push opaque bytes through download-token path")

    def issue_read_token(self, *, object_key, participant_id, ttl_seconds):
        self.read_calls.append((object_key, participant_id, ttl_seconds))
        return self.token

    def delete(self, *, object_key):
        pass


class ClassroomCollaborationContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ClassroomCollaborationSQLiteStore(str(self.root / "collaboration.sqlite3"))
        self.roster = FakeRoster()
        self.chat = FakeChat()
        self.files = FakeFiles()
        self.file_store = FakeFileStore()

    def tearDown(self):
        self.tmp.cleanup()

    def controller(self, participant="student-1", quota=None):
        return ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id=participant,
            roster=self.roster,
            chat=self.chat,
            files=self.files,
            store=self.store,
            file_store=self.file_store,
            quota=quota or FileQuotaPolicy(),
        )

    def make_file(self, name="payload.unknownext", content=b"abc\x00\xff"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_send_is_server_sequenced_and_idempotent_on_retry(self):
        controller = self.controller()
        first = controller.send_chat(message_id="m1", body="Hello")
        again = controller.send_chat(message_id="m1", body="Hello")
        self.assertEqual(first, again)
        self.assertEqual(first.sequence_no, 0)
        self.assertEqual(first.sent_at_unix_ms, 1700000000000)
        self.assertEqual(self.store.room_messages("room-1"), (first,))
        self.assertEqual(len(self.chat.ordered), 1)

    def test_transport_timestamp_is_required_for_send_receive_and_history(self):
        controller = self.controller()
        self.chat.omit_timestamp = True
        with self.assertRaises(CollaborationError):
            controller.send_chat(message_id="m1", body="No timestamp")
        self.assertEqual(self.store.room_messages("room-1"), ())

        with self.assertRaises(CollaborationError):
            controller.receive_chat(
                ChatMessageMetadata("m2", "room-1", "teacher-1", 0, "Legacy live message")
            )

        self.chat.ordered = [
            ChatMessageMetadata("m3", "room-1", "teacher-1", 0, "Missing timestamp")
        ]
        with self.assertRaises(CollaborationError):
            controller.sync_chat()

    def test_transport_cannot_mutate_message_identity_or_body(self):
        controller = self.controller()
        self.chat.mutate_delivery = True
        with self.assertRaises(CollaborationError):
            controller.send_chat(message_id="m1", body="Original")
        self.assertEqual(self.store.room_messages("room-1"), ())

    def test_chat_body_is_bounded_and_nul_rejected(self):
        controller = self.controller()
        for body in ("", "   ", "bad\x00text", "x" * 4001):
            with self.subTest(body=body[:20]):
                with self.assertRaises(CollaborationError):
                    controller.send_chat(message_id="m1", body=body)

    def test_sync_reconnect_persists_only_new_strictly_ordered_messages(self):
        controller = self.controller()
        one = self.chat.send_message(ChatDraft("m1", "room-1", "teacher-1", "One"))
        two = self.chat.send_message(ChatDraft("m2", "room-1", "student-2", "Two"))
        synced = controller.sync_chat()
        self.assertEqual(synced, (one, two))
        self.assertEqual(controller.sync_chat(), ())
        self.assertEqual(self.store.room_messages("room-1"), (one, two))

    def test_sync_defers_state_for_message_on_next_history_page(self):
        controller = self.controller()
        first = self.chat.send_message(
            ChatDraft("m-page-0", "room-1", "teacher-1", "First")
        )
        second = self.chat.send_message(
            ChatDraft("m-page-1", "room-1", "student-2", "Second")
        )
        third = self.chat.send_message(
            ChatDraft("m-page-2", "room-1", "teacher-1", "Third")
        )
        self.chat.ordered[2] = replace(third, hidden=True)
        self.chat.messages[third.message_id] = self.chat.ordered[2]
        self.chat.state_updates = [
            ChatMessageStateUpdate("room-1", third.message_id, 0),
        ]

        with patch("acs.classroom_collaboration.MAX_SYNC_MESSAGES", 2):
            self.assertEqual(controller.sync_chat(), (first, second))
            self.assertIsNone(self.store.chat_state_revision("room-1"))
            self.assertEqual(controller.sync_chat(), ())

        stored = self.store.room_messages("room-1", include_hidden=True)
        self.assertEqual(tuple(item.message_id for item in stored), (
            first.message_id,
            second.message_id,
            third.message_id,
        ))
        self.assertTrue(stored[-1].hidden)
        self.assertEqual(self.store.chat_state_revision("room-1"), 0)

    def test_send_repairs_missed_server_message_before_committing_later_sequence(self):
        controller = self.controller()
        first = self.chat.send_message(
            ChatDraft("m0", "room-1", "teacher-1", "First")
        )
        missed = self.chat.send_message(
            ChatDraft("m1", "room-1", "student-2", "Missed")
        )
        controller.receive_chat(first)

        sent = controller.send_chat(message_id="m2", body="My later message")

        self.assertEqual(sent.sequence_no, 2)
        self.assertEqual(
            self.store.room_messages("room-1"),
            (first, missed, sent),
        )

    def test_receive_later_message_on_empty_store_recovers_complete_prefix(self):
        controller = self.controller()
        first = self.chat.send_message(
            ChatDraft("m0", "room-1", "teacher-1", "First")
        )
        missed = self.chat.send_message(
            ChatDraft("m1", "room-1", "student-2", "Missed")
        )
        later = self.chat.send_message(
            ChatDraft("m2", "room-1", "teacher-1", "Later")
        )

        received = controller.receive_chat(later)

        self.assertEqual(received, later)
        self.assertEqual(
            self.store.room_messages("room-1"),
            (first, missed, later),
        )

    def test_receive_later_message_fails_closed_when_server_history_omits_prefix(self):
        controller = self.controller()
        later = ChatMessageMetadata(
            "m2",
            "room-1",
            "teacher-1",
            2,
            "Incomplete history",
            sent_at_unix_ms=1700000002000,
        )
        self.chat.ordered = [later]

        with self.assertRaises(CollaborationError):
            controller.receive_chat(later)

        self.assertEqual(self.store.room_messages("room-1"), ())

    def test_sync_rejects_cross_room_or_out_of_order_transport_history(self):
        controller = self.controller()
        self.chat.ordered.append(
            ChatMessageMetadata("m1", "other-room", "teacher-1", 0, "wrong room", sent_at_unix_ms=1700000000000)
        )
        self.assertEqual(controller.sync_chat(), ())

        self.chat.ordered = [
            ChatMessageMetadata("m2", "room-1", "teacher-1", 2, "later", sent_at_unix_ms=1700000002000),
            ChatMessageMetadata("m3", "room-1", "student-1", 1, "earlier", sent_at_unix_ms=1700000001000),
        ]
        with self.assertRaises(CollaborationError):
            controller.sync_chat()

    def test_current_participant_query_tracks_canonical_roster(self):
        controller = self.controller()
        self.assertTrue(controller.is_current_participant("student-2"))

        self.roster.roles.pop("student-2")

        self.assertFalse(controller.is_current_participant("student-2"))
        with self.assertRaises(CollaborationError):
            controller.is_current_participant("bad id")

    def test_departed_sender_history_is_preserved_on_reconnect(self):
        controller = self.controller()
        historical = self.chat.send_message(
            ChatDraft("m1", "room-1", "student-2", "Before leaving")
        )
        self.roster.roles.pop("student-2")

        synced = controller.sync_chat()

        self.assertEqual(synced, (historical,))
        self.assertEqual(
            self.store.room_messages("room-1"),
            (historical,),
        )

    def test_removed_sender_is_rejected_from_received_chat(self):
        controller = self.controller()
        self.roster.roles.pop("student-2")
        with self.assertRaises(CollaborationError):
            controller.receive_chat(
                ChatMessageMetadata("m1", "room-1", "student-2", 0, "orphan", sent_at_unix_ms=1700000000000)
            )

    def test_chat_moderation_capability_projects_canonical_role_hierarchy_without_side_effects(self):
        cases = (
            ("teacher-1", "co-1", True),
            ("teacher-1", "student-1", True),
            ("teacher-1", "observer-1", True),
            ("teacher-1", "teacher-1", False),
            ("co-1", "student-1", True),
            ("co-1", "observer-1", True),
            ("co-1", "teacher-1", False),
            ("co-1", "co-1", False),
            ("student-1", "student-2", False),
            ("observer-1", "student-1", False),
        )
        for actor, target, expected in cases:
            with self.subTest(actor=actor, target=target):
                controller = self.controller(actor)
                calls_before = len(self.chat.moderation_calls)
                self.assertIs(
                    controller.can_moderate_chat_participant(target),
                    expected,
                )
                self.assertEqual(len(self.chat.moderation_calls), calls_before)

        self.roster.roles.pop("student-2")
        teacher = self.controller("teacher-1")
        self.assertFalse(teacher.can_moderate_chat_participant("student-2"))
        self.assertEqual(self.chat.moderation_calls, [])

    def test_teacher_chat_lock_is_server_authoritative_across_controller_recreation(self):
        teacher = self.controller("teacher-1")
        teacher.set_chat_send_permission(
            actor_id="teacher-1",
            target_id="student-1",
            allowed=False,
            operation_id="lock-student-chat",
        )

        student = self.controller("student-1")
        with self.assertRaisesRegex(CollaborationError, "server rejected locked chat sender"):
            student.send_chat(message_id="m1", body="blocked")

        # A fresh controller/reconnect must not reset the server-side permission.
        student = self.controller("student-1")
        with self.assertRaisesRegex(CollaborationError, "server rejected locked chat sender"):
            student.send_chat(message_id="m1b", body="still blocked")

        teacher.set_chat_send_permission(
            actor_id="teacher-1",
            target_id="student-1",
            allowed=True,
            operation_id="unlock-student-chat",
        )
        self.assertEqual(
            student.send_chat(message_id="m2", body="allowed").body,
            "allowed",
        )

    def test_all_students_lock_is_bounded_to_student_roles(self):
        controller = self.controller("teacher-1")
        targets = controller.set_all_students_chat_send_permission(
            actor_id="teacher-1",
            allowed=False,
            operation_id="lock-all-student-chat",
        )
        self.assertEqual(targets, ("student-1", "student-2"))
        commands = self.chat.moderation_calls[-1]
        self.assertEqual({item.target_id for item in commands}, {"student-1", "student-2"})
        self.assertNotIn("co-1", {item.target_id for item in commands})
        self.assertNotIn("observer-1", {item.target_id for item in commands})

    def test_empty_student_batch_still_validates_operation_identity(self):
        self.roster.roles.pop("student-1")
        self.roster.roles.pop("student-2")
        controller = self.controller("teacher-1")
        calls_before = len(self.chat.moderation_calls)

        with self.assertRaises(CollaborationError):
            controller.set_all_students_chat_send_permission(
                actor_id="teacher-1",
                allowed=False,
                operation_id="",
            )

        self.assertEqual(len(self.chat.moderation_calls), calls_before)
        self.assertEqual(
            controller.set_all_students_chat_send_permission(
                actor_id="teacher-1",
                allowed=False,
                operation_id="lock-empty-student-set",
            ),
            (),
        )
        self.assertEqual(len(self.chat.moderation_calls), calls_before)

    def test_all_students_lock_is_enforced_by_server_transport_across_fresh_clients(self):
        teacher = self.controller("teacher-1")
        teacher.set_all_students_chat_send_permission(
            actor_id="teacher-1",
            allowed=False,
            operation_id="lock-all-students",
        )

        for participant in ("student-1", "student-2"):
            with self.subTest(participant=participant):
                student = self.controller(participant)
                with self.assertRaisesRegex(
                    CollaborationError,
                    "server rejected locked chat sender",
                ):
                    student.send_chat(
                        message_id=f"blocked-{participant}",
                        body="blocked",
                    )

        observer = self.controller("observer-1")
        self.assertEqual(
            observer.send_chat(message_id="observer-ok", body="observer").body,
            "observer",
        )

    def test_student_batch_operation_ids_are_stable_across_roster_order(self):
        controller = self.controller("teacher-1")
        self.roster.participant_ids = lambda: (
            "teacher-1",
            "student-2",
            "observer-1",
            "student-1",
            "co-1",
        )
        controller.set_all_students_chat_send_permission(
            actor_id="teacher-1",
            allowed=False,
            operation_id="lock-all",
        )
        first = {
            command.target_id: command.operation_id
            for command in self.chat.moderation_calls[-1]
        }

        self.roster.participant_ids = lambda: (
            "student-1",
            "co-1",
            "teacher-1",
            "observer-1",
            "student-2",
        )
        controller.set_all_students_chat_send_permission(
            actor_id="teacher-1",
            allowed=False,
            operation_id="lock-all",
        )
        second = {
            command.target_id: command.operation_id
            for command in self.chat.moderation_calls[-1]
        }
        self.assertEqual(first, second)
        self.assertNotEqual(first["student-1"], first["student-2"])
        self.assertTrue(all(value.startswith("batch:") for value in first.values()))

        del self.roster.roles["student-1"]
        self.roster.roles["student-3"] = ClassroomRole.STUDENT
        self.roster.participant_ids = lambda: tuple(self.roster.roles)
        controller.set_all_students_chat_send_permission(
            actor_id="teacher-1",
            allowed=False,
            operation_id="lock-all",
        )
        membership_changed = {
            command.target_id: command.operation_id
            for command in self.chat.moderation_calls[-1]
        }
        self.assertEqual(membership_changed["student-2"], first["student-2"])
        self.assertNotIn(membership_changed["student-3"], set(first.values()))

    def test_student_cannot_spoof_teacher_moderation_identity(self):
        controller = self.controller("student-1")

        with self.assertRaises(CollaborationError):
            controller.set_chat_send_permission(
                actor_id="teacher-1",
                target_id="student-2",
                allowed=False,
                operation_id="spoof-single",
            )
        with self.assertRaises(CollaborationError):
            controller.set_all_students_chat_send_permission(
                actor_id="teacher-1",
                allowed=False,
                operation_id="spoof-all",
            )
        with self.assertRaises(CollaborationError):
            controller.hide_message(
                actor_id="teacher-1",
                message_id="m1",
                operation_id="spoof-hide",
            )
        self.assertEqual(self.chat.moderation_calls, [])

    def test_student_and_co_teacher_cannot_moderate_teacher_roles(self):
        controller = self.controller("student-1")
        with self.assertRaises(CollaborationError):
            controller.set_chat_send_permission(
                actor_id="student-1",
                target_id="student-2",
                allowed=False,
                operation_id="student-moderation",
            )
        with self.assertRaises(CollaborationError):
            controller.set_chat_send_permission(
                actor_id="co-1",
                target_id="teacher-1",
                allowed=False,
                operation_id="co-moderates-teacher",
            )

    def test_hide_message_cannot_cross_room_boundary_before_transport(self):
        controller = self.controller("teacher-1")
        foreign = ChatMessageMetadata(
            "foreign-message",
            "room-2",
            "student-2",
            0,
            "foreign room message",
            sent_at_unix_ms=1700000000000,
        )
        self.store.append_message(foreign)

        before_moderation = list(self.chat.moderation_calls)
        with self.assertRaisesRegex(
            CollaborationError,
            "unknown message in current room",
        ):
            controller.hide_message(
                actor_id="teacher-1",
                message_id=foreign.message_id,
                operation_id="hide-foreign-message",
            )

        self.assertEqual(self.chat.moderation_calls, before_moderation)
        self.assertEqual(
            self.store.room_messages("room-2", include_hidden=True),
            (foreign,),
        )
        self.assertFalse(
            self.store.room_messages("room-2", include_hidden=True)[0].hidden
        )

    def test_teacher_can_hide_message_without_deleting_durable_history(self):
        controller = self.controller("teacher-1")
        message = controller.send_chat(message_id="m1", body="moderate me")
        hidden = controller.hide_message(
            actor_id="teacher-1",
            message_id=message.message_id,
            operation_id="hide-message-1",
        )
        self.assertTrue(hidden.hidden)
        self.assertEqual(self.store.room_messages("room-1"), ())
        self.assertEqual(
            self.store.room_messages("room-1", include_hidden=True),
            (hidden,),
        )

    def test_remote_hide_reconciles_without_reannouncing_old_message(self):
        teacher_store = self.store
        teacher = self.controller("teacher-1")
        message = teacher.send_chat(message_id="m1", body="must disappear")

        student_store = ClassroomCollaborationSQLiteStore(
            str(self.root / "student-collaboration.sqlite3")
        )
        student = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-1",
            roster=self.roster,
            chat=self.chat,
            files=self.files,
            store=student_store,
            file_store=self.file_store,
        )
        self.assertEqual(student.sync_chat(), (message,))
        teacher.hide_message(
            actor_id="teacher-1",
            message_id=message.message_id,
            operation_id="hide-message-remote",
        )

        self.assertEqual(student.sync_chat(), ())
        self.assertEqual(student_store.room_messages("room-1"), ())
        hidden = student_store.room_messages("room-1", include_hidden=True)
        self.assertEqual(len(hidden), 1)
        self.assertTrue(hidden[0].hidden)
        self.assertEqual(student_store.chat_state_revision("room-1"), 0)
        self.assertEqual(
            teacher_store.room_messages("room-1"),
            (),
        )

    def test_hidden_history_is_persisted_but_not_returned_for_announcement(self):
        controller = self.controller("student-1")
        message = self.chat.send_message(
            ChatDraft("hidden-before-sync", "room-1", "teacher-1", "hidden")
        )
        self.chat.ordered[0] = replace(message, hidden=True)
        self.chat.messages[message.message_id] = self.chat.ordered[0]
        self.assertEqual(controller.sync_chat(), ())
        stored = self.store.room_messages("room-1", include_hidden=True)
        self.assertEqual(len(stored), 1)
        self.assertTrue(stored[0].hidden)

    def test_moderation_state_stream_must_be_strict_and_reference_known_message(self):
        controller = self.controller("student-1")
        message = self.chat.send_message(
            ChatDraft("m-state", "room-1", "teacher-1", "state")
        )
        self.assertEqual(controller.sync_chat(), (message,))
        self.chat.state_updates = [
            ChatMessageStateUpdate("room-1", "m-state", 1),
            ChatMessageStateUpdate("room-1", "m-state", 0),
        ]
        with self.assertRaises(CollaborationError):
            controller.sync_chat()

        self.chat.state_updates = [
            ChatMessageStateUpdate("room-1", "unknown-message", 0),
        ]
        with self.assertRaises(CollaborationError):
            controller.sync_chat()

    def test_prepare_file_hashes_arbitrary_binary_without_interpreting_extension(self):
        controller = self.controller()
        content = b"\x00\xff\x89opaque\x00data"
        path = self.make_file("lesson.weirdformat", content)
        prepared = controller.prepare_file(
            attachment_id="a1",
            local_path=path,
            sequence_no=0,
            retention="persistent",
        )
        self.assertIsInstance(prepared.local_path, Path)
        self.assertEqual(prepared.local_path, path.resolve())
        self.assertEqual(prepared.metadata.display_name, "lesson.weirdformat")
        self.assertEqual(prepared.metadata.size_bytes, len(content))
        self.assertEqual(prepared.metadata.sha256, content_sha256(content))
        self.assertIsNone(prepared.metadata.mime_type)
        self.assertEqual(prepared.metadata.transfer_state, "pending")
        self.assertEqual(prepared.metadata.scan_state, "pending")

    def test_default_storage_key_supports_canonical_ids_with_colons(self):
        controller = ClassroomCollaborationController(
            room_id="room:42",
            local_participant_id="student-1",
            roster=self.roster,
            chat=self.chat,
            files=self.files,
            store=self.store,
            file_store=self.file_store,
        )
        path = self.make_file("lesson.pgn", b"1. e4 e5")
        first = controller.prepare_file(
            attachment_id="attachment:1",
            local_path=path,
            sequence_no=0,
        )
        again = controller.prepare_file(
            attachment_id="attachment:1",
            local_path=path,
            sequence_no=0,
        )
        self.assertEqual(first.metadata.object_key, again.metadata.object_key)
        self.assertTrue(first.metadata.object_key.startswith("rooms/id-"))
        self.assertNotIn(":", first.metadata.object_key)

    def test_file_quota_and_sequence_use_canonical_json_safe_integer_bound(self):
        FileQuotaPolicy(
            max_file_bytes=1,
            max_room_bytes=MAX_WIRE_INTEGER,
        )
        with self.assertRaises(CollaborationError):
            FileQuotaPolicy(
                max_file_bytes=MAX_WIRE_INTEGER + 1,
                max_room_bytes=MAX_WIRE_INTEGER + 1,
            )

        controller = self.controller()
        with self.assertRaises(CollaborationError):
            controller.prepare_file(
                attachment_id="a-sequence-overflow",
                local_path=self.make_file(content=b"x"),
                sequence_no=MAX_WIRE_INTEGER + 1,
            )
        self.assertEqual(self.store.room_attachments("room-1"), ())
        self.assertEqual(self.files.upload_calls, [])

    def test_prepare_file_enforces_per_file_and_room_quota(self):
        path = self.make_file(content=b"12345")
        controller = self.controller(
            quota=FileQuotaPolicy(max_file_bytes=4, max_room_bytes=10)
        )
        with self.assertRaises(CollaborationError):
            controller.prepare_file(attachment_id="a1", local_path=path, sequence_no=0)

        controller = self.controller(
            quota=FileQuotaPolicy(max_file_bytes=10, max_room_bytes=6)
        )
        first = controller.prepare_file(attachment_id="a1", local_path=path, sequence_no=0)
        self.files.scan_state = "clean"
        controller.upload_file(first)
        second_path = self.make_file("second.bin", b"12")
        with self.assertRaises(CollaborationError):
            controller.prepare_file(attachment_id="a2", local_path=second_path, sequence_no=1)

    def test_upload_rechecks_room_quota_after_multiple_files_were_prepared(self):
        controller = self.controller(
            quota=FileQuotaPolicy(max_file_bytes=6, max_room_bytes=6)
        )
        first = controller.prepare_file(
            attachment_id="a1",
            local_path=self.make_file("one.bin", b"1234"),
            sequence_no=0,
        )
        second = controller.prepare_file(
            attachment_id="a2",
            local_path=self.make_file("two.bin", b"5678"),
            sequence_no=1,
        )

        controller.upload_file(first)
        with self.assertRaises(CollaborationError):
            controller.upload_file(second)

        self.assertEqual(len(self.files.upload_calls), 1)
        self.assertEqual(
            tuple(item.attachment_id for item in self.store.room_attachments("room-1")),
            ("a1",),
        )

    def test_file_content_change_after_prepare_fails_closed_before_transport(self):
        controller = self.controller()
        path = self.make_file(content=b"first")
        prepared = controller.prepare_file(attachment_id="a1", local_path=path, sequence_no=0)
        path.write_bytes(b"changed")
        with self.assertRaises(CollaborationError):
            controller.upload_file(prepared)
        self.assertEqual(self.files.upload_calls, [])

    def test_upload_rejects_forged_prepared_metadata_before_transport(self):
        controller = self.controller()
        path = self.make_file(content=b"opaque prepared payload")
        prepared = controller.prepare_file(
            attachment_id="a-forged",
            local_path=path,
            sequence_no=0,
        )

        forged_metadata = (
            replace(
                prepared.metadata,
                display_name="misleading.txt",
                mime_type="text/plain",
            ),
            replace(prepared.metadata, mime_type="text/plain"),
            replace(
                prepared.metadata,
                object_key="rooms/room-1/not-the-attachment",
            ),
            replace(prepared.metadata, transfer_state="uploading"),
            replace(prepared.metadata, scan_state="clean"),
        )
        for metadata in forged_metadata:
            with self.subTest(metadata=metadata):
                with self.assertRaises(CollaborationError):
                    controller.upload_file(
                        PreparedFile(prepared.local_path, metadata)
                    )

        self.assertEqual(self.files.upload_calls, [])
        self.assertEqual(self.store.room_attachments("room-1"), ())

    def test_upload_adopts_server_authoritative_file_sequence(self):
        controller = self.controller()
        prepared = controller.prepare_file(
            attachment_id="server-sequenced",
            local_path=self.make_file("server-sequenced.bin", b"opaque"),
            sequence_no=73,
            retention="persistent",
        )
        self.files.scan_state = "clean"

        stored = controller.upload_file(prepared)

        self.assertEqual(stored.sequence_no, 0)
        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(self.store.room_attachments("room-1"), (stored,))
        self.assertEqual(self.files.upload_calls[0].metadata.sequence_no, 73)

    def test_second_client_discovers_durable_shared_file_from_server_history(self):
        teacher = self.controller("teacher-1")
        prepared = teacher.prepare_file(
            attachment_id="shared-a1",
            local_path=self.make_file("shared-a1.pgn", b"1. e4 e5"),
            sequence_no=41,
            retention="persistent",
        )
        self.files.scan_state = "clean"
        uploaded = teacher.upload_file(prepared)
        self.assertEqual(uploaded.sequence_no, 0)

        second_store = ClassroomCollaborationSQLiteStore(
            str(self.root / "second-client.sqlite3")
        )
        student = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-2",
            roster=self.roster,
            chat=self.chat,
            files=self.files,
            store=second_store,
            file_store=self.file_store,
        )

        discovered = student.sync_files()

        self.assertEqual(discovered, (uploaded,))
        self.assertEqual(second_store.room_attachments("room-1"), (uploaded,))
        self.assertEqual(student.sync_files(), ())
        self.assertEqual(
            student.issue_download_token(
                attachment_id=uploaded.attachment_id,
                ttl_seconds=60,
            ),
            "short-lived-read-token",
        )

    def test_file_sync_repairs_missing_local_authoritative_prefix(self):
        history = tuple(
            AttachmentMetadata(
                f"remote-prefix-{sequence}",
                "room-1",
                "teacher-1" if sequence != 1 else "student-1",
                sequence,
                f"prefix-{sequence}.bin",
                None,
                1,
                f"{sequence + 1:x}" * 64,
                f"rooms/room-1/remote-prefix-{sequence}",
                "stored",
                "persistent",
                "clean",
            )
            for sequence in range(3)
        )
        self.files.ordered = list(history)
        # Simulate a recoverable local database that retained only a later
        # authoritative row. Reconnect must not use that row as a skip cursor.
        self.store.register_attachment(history[2])
        controller = self.controller("teacher-1")

        repaired = controller.sync_files()

        self.assertEqual(repaired, history)
        self.assertEqual(self.store.room_attachments("room-1"), history)
        self.assertEqual(controller.sync_files(), ())

    def test_file_history_preserves_departed_sender_but_live_receive_requires_membership(self):
        historical = AttachmentMetadata(
            "departed-file",
            "room-1",
            "student-2",
            0,
            "before-leaving.pgn",
            "application/x-chess-pgn",
            8,
            "c" * 64,
            "rooms/room-1/departed-file",
            "stored",
            "persistent",
            "clean",
        )
        self.files.history_override = (historical,)
        self.roster.roles.pop("student-2")
        controller = self.controller("teacher-1")

        self.assertEqual(controller.sync_files(), (historical,))
        self.assertEqual(self.store.room_attachments("room-1"), (historical,))

        live_after_departure = replace(
            historical,
            attachment_id="departed-live",
            sequence_no=1,
            object_key="rooms/room-1/departed-live",
        )
        with self.assertRaises(CollaborationError):
            controller.receive_file(live_after_departure)
        self.assertEqual(self.store.room_attachments("room-1"), (historical,))

    def test_receive_later_file_recovers_complete_authoritative_prefix(self):
        controller = self.controller("teacher-1")
        first = AttachmentMetadata(
            "remote-a0",
            "room-1",
            "student-1",
            0,
            "zero.bin",
            None,
            1,
            "0" * 64,
            "rooms/room-1/remote-a0",
            "stored",
            "persistent",
            "clean",
        )
        missed = AttachmentMetadata(
            "remote-a1",
            "room-1",
            "student-2",
            1,
            "one.bin",
            None,
            1,
            "1" * 64,
            "rooms/room-1/remote-a1",
            "stored",
            "persistent",
            "clean",
        )
        later = AttachmentMetadata(
            "remote-a2",
            "room-1",
            "student-2",
            2,
            "two.bin",
            None,
            1,
            "2" * 64,
            "rooms/room-1/remote-a2",
            "stored",
            "persistent",
            "clean",
        )
        self.files.history_override = (first, missed, later)

        received = controller.receive_file(later)

        self.assertEqual(received, later)
        self.assertEqual(
            self.store.room_attachments("room-1"),
            (first, missed, later),
        )

    def test_receive_later_file_fails_closed_when_server_history_omits_prefix(self):
        controller = self.controller("teacher-1")
        later = AttachmentMetadata(
            "remote-a2",
            "room-1",
            "student-2",
            2,
            "two.bin",
            None,
            1,
            "2" * 64,
            "rooms/room-1/remote-a2",
            "stored",
            "persistent",
            "clean",
        )
        self.files.history_override = (later,)

        with self.assertRaisesRegex(
            CollaborationError,
            "file history has an unresolved sequence gap",
        ):
            controller.receive_file(later)

        self.assertEqual(self.store.room_attachments("room-1"), ())

    def test_file_state_sync_promotes_pending_scan_without_duplicate_discovery(self):
        teacher = self.controller("teacher-1")
        prepared = teacher.prepare_file(
            attachment_id="scan-a1",
            local_path=self.make_file("scan-a1.bin", b"scan me"),
            sequence_no=17,
            retention="persistent",
        )
        uploaded = teacher.upload_file(prepared)
        self.assertEqual(uploaded.scan_state, "pending")

        second_store = ClassroomCollaborationSQLiteStore(
            str(self.root / "state-client.sqlite3")
        )
        student = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-2",
            roster=self.roster,
            chat=self.chat,
            files=self.files,
            store=second_store,
            file_store=self.file_store,
        )
        self.assertEqual(student.sync_files(), (uploaded,))
        with self.assertRaisesRegex(
            CollaborationError,
            "not cleared for download",
        ):
            student.issue_download_token(attachment_id=uploaded.attachment_id)

        state = self.files.set_authoritative_state(
            uploaded.attachment_id,
            scan_state="clean",
        )
        self.assertEqual(state.revision, 0)

        self.assertEqual(student.sync_files(), ())
        current = second_store.room_attachments("room-1")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].scan_state, "clean")
        self.assertEqual(second_store.attachment_state_revision("room-1"), 0)
        self.assertEqual(
            student.issue_download_token(
                attachment_id=uploaded.attachment_id,
                ttl_seconds=60,
            ),
            "short-lived-read-token",
        )

    def test_tombstone_history_preserves_sequence_for_fresh_client(self):
        teacher = self.controller("teacher-1")
        self.files.scan_state = "clean"
        first = teacher.upload_file(
            teacher.prepare_file(
                attachment_id="deleted-a0",
                local_path=self.make_file("deleted-a0.bin", b"old"),
                sequence_no=50,
                retention="persistent",
            )
        )
        second = teacher.upload_file(
            teacher.prepare_file(
                attachment_id="live-a1",
                local_path=self.make_file("live-a1.bin", b"live"),
                sequence_no=51,
                retention="persistent",
            )
        )
        self.assertEqual((first.sequence_no, second.sequence_no), (0, 1))
        self.files.set_authoritative_state(
            first.attachment_id,
            transfer_state="deleted",
        )

        fresh_store = ClassroomCollaborationSQLiteStore(
            str(self.root / "fresh-after-delete.sqlite3")
        )
        fresh = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-2",
            roster=self.roster,
            chat=self.chat,
            files=self.files,
            store=fresh_store,
            file_store=self.file_store,
        )

        discovered = fresh.sync_files()

        self.assertEqual(discovered, (second,))
        persisted = fresh_store.room_attachments("room-1")
        self.assertEqual(
            tuple((item.sequence_no, item.transfer_state) for item in persisted),
            ((0, "deleted"), (1, "stored")),
        )

    def test_attachment_state_revision_gap_fails_before_mutating_local_state(self):
        teacher = self.controller("teacher-1")
        prepared = teacher.prepare_file(
            attachment_id="state-gap-a1",
            local_path=self.make_file("state-gap-a1.bin", b"state"),
            sequence_no=0,
            retention="persistent",
        )
        uploaded = teacher.upload_file(prepared)

        second_store = ClassroomCollaborationSQLiteStore(
            str(self.root / "state-gap.sqlite3")
        )
        student = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-2",
            roster=self.roster,
            chat=self.chat,
            files=self.files,
            store=second_store,
            file_store=self.file_store,
        )
        self.assertEqual(student.sync_files(), (uploaded,))
        self.files.state_override = (
            AttachmentStateUpdate(
                room_id="room-1",
                attachment_id=uploaded.attachment_id,
                revision=1,
                transfer_state="stored",
                scan_state="clean",
            ),
        )

        with self.assertRaisesRegex(
            CollaborationError,
            "attachment state has an unresolved revision gap",
        ):
            student.sync_files()

        current = second_store.room_attachments("room-1")[0]
        self.assertEqual(current.scan_state, "pending")
        self.assertIsNone(second_store.attachment_state_revision("room-1"))

    def test_new_file_history_is_not_exposed_when_state_stream_has_a_gap(self):
        controller = self.controller("teacher-1")
        incoming = AttachmentMetadata(
            "remote-clean-before-gap",
            "room-1",
            "student-1",
            0,
            "clean-before-gap.pgn",
            "application/x-chess-pgn",
            8,
            "d" * 64,
            "rooms/room-1/remote-clean-before-gap",
            "stored",
            "persistent",
            "clean",
        )
        self.files.history_override = (incoming,)
        self.files.state_override = (
            AttachmentStateUpdate(
                room_id="room-1",
                attachment_id=incoming.attachment_id,
                revision=1,
                transfer_state="deleted",
                scan_state="clean",
            ),
        )

        with self.assertRaisesRegex(
            CollaborationError,
            "attachment state has an unresolved revision gap",
        ):
            controller.sync_files()

        self.assertEqual(self.store.room_attachments("room-1"), ())
        self.assertIsNone(self.store.attachment_state_revision("room-1"))

    def test_receive_later_file_rejects_partial_catch_up_that_still_has_a_gap(self):
        controller = self.controller("teacher-1")
        first = AttachmentMetadata(
            "remote-partial-0",
            "room-1",
            "student-1",
            0,
            "zero.bin",
            None,
            1,
            "3" * 64,
            "rooms/room-1/remote-partial-0",
            "stored",
            "persistent",
            "clean",
        )
        later = AttachmentMetadata(
            "remote-partial-2",
            "room-1",
            "student-2",
            2,
            "two.bin",
            None,
            1,
            "4" * 64,
            "rooms/room-1/remote-partial-2",
            "stored",
            "persistent",
            "clean",
        )
        # History can legitimately lag a live delivery. Recover the prefix that
        # is available, but never anchor sequence 2 while sequence 1 is absent.
        self.files.history_override = (first,)

        with self.assertRaisesRegex(
            CollaborationError,
            "live file has an unresolved sequence gap after recovery",
        ):
            controller.receive_file(later)

        self.assertEqual(self.store.room_attachments("room-1"), (first,))

    def test_file_history_rejects_cross_room_and_noncanonical_namespace(self):
        controller = self.controller("teacher-1")
        base = AttachmentMetadata(
            "remote-a1",
            "room-1",
            "student-1",
            0,
            "lesson.pgn",
            "application/x-chess-pgn",
            8,
            "a" * 64,
            "rooms/room-1/remote-a1",
            "stored",
            "persistent",
            "clean",
        )
        invalid = (
            replace(
                base,
                room_id="room-2",
                object_key="rooms/room-2/remote-a1",
            ),
            replace(
                base,
                object_key="rooms/other-room/remote-a1",
            ),
        )
        for remote in invalid:
            with self.subTest(remote=remote):
                self.files.history_override = (remote,)
                with self.assertRaises(CollaborationError):
                    controller.sync_files()
                self.assertEqual(self.store.room_attachments("room-1"), ())
        self.files.history_override = None

    def test_file_history_must_be_contiguous_and_fail_atomically(self):
        controller = self.controller("teacher-1")
        first = AttachmentMetadata(
            "remote-a1",
            "room-1",
            "student-1",
            0,
            "one.bin",
            None,
            1,
            "a" * 64,
            "rooms/room-1/remote-a1",
            "stored",
            "persistent",
            "clean",
        )
        skipped = AttachmentMetadata(
            "remote-a2",
            "room-1",
            "student-2",
            2,
            "two.bin",
            None,
            1,
            "b" * 64,
            "rooms/room-1/remote-a2",
            "stored",
            "persistent",
            "clean",
        )
        self.files.history_override = (first, skipped)

        with self.assertRaisesRegex(
            CollaborationError,
            "file history has an unresolved sequence gap",
        ):
            controller.sync_files()

        self.assertEqual(self.store.room_attachments("room-1"), ())

    def test_upload_failure_is_persisted_failed_and_retry_preserves_identity(self):
        controller = self.controller()
        path = self.make_file(content=b"retry me")
        prepared = controller.prepare_file(attachment_id="a1", local_path=path, sequence_no=0)
        self.files.fail_upload = True
        with self.assertRaises(RuntimeError):
            controller.upload_file(prepared)
        failed = self.store.room_attachments("room-1")[0]
        self.assertEqual(failed.transfer_state, "failed")

        self.files.fail_upload = False
        self.files.scan_state = "clean"
        stored = controller.retry_file(prepared)
        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(stored.scan_state, "clean")
        self.assertEqual(stored.sha256, prepared.metadata.sha256)
        self.assertEqual(len(self.files.retry_calls), 1)

    def test_retry_resets_failed_scan_to_pending_before_clean_rescan(self):
        controller = self.controller()
        path = self.make_file(content=b"retry after scanner outage")
        prepared = controller.prepare_file(
            attachment_id="a-scan-failed",
            local_path=path,
            sequence_no=0,
        )
        self.store.register_attachment(prepared.metadata)
        self.store.update_attachment_state(
            prepared.metadata.attachment_id,
            transfer_state="uploading",
        )
        self.store.update_attachment_state(
            prepared.metadata.attachment_id,
            transfer_state="failed",
            scan_state="failed",
        )

        self.files.scan_state = "clean"
        stored = controller.retry_file(prepared)

        self.assertEqual(len(self.files.retry_calls), 1)
        retry_candidate = self.files.retry_calls[0].metadata
        self.assertEqual(retry_candidate.transfer_state, "uploading")
        self.assertEqual(retry_candidate.scan_state, "pending")
        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(stored.scan_state, "clean")

    def test_retry_never_resends_blocked_attachment(self):
        controller = self.controller()
        path = self.make_file(content=b"blocked payload")
        prepared = controller.prepare_file(
            attachment_id="a-blocked",
            local_path=path,
            sequence_no=0,
        )
        self.store.register_attachment(prepared.metadata)
        self.store.update_attachment_state(
            prepared.metadata.attachment_id,
            transfer_state="uploading",
        )
        self.store.update_attachment_state(
            prepared.metadata.attachment_id,
            transfer_state="failed",
            scan_state="blocked",
        )

        with self.assertRaisesRegex(
            CollaborationError,
            "blocked attachment cannot be retried",
        ):
            controller.retry_file(prepared)

        self.assertEqual(self.files.retry_calls, [])
        current = self.store.room_attachments("room-1")[0]
        self.assertEqual(current.transfer_state, "failed")
        self.assertEqual(current.scan_state, "blocked")

    def test_retry_rejects_changed_source_identity(self):
        controller = self.controller()
        path = self.make_file(content=b"retry me")
        prepared = controller.prepare_file(attachment_id="a1", local_path=path, sequence_no=0)
        self.files.fail_upload = True
        with self.assertRaises(RuntimeError):
            controller.upload_file(prepared)
        path.write_bytes(b"different")
        with self.assertRaises(CollaborationError):
            controller.retry_file(prepared)
        self.assertEqual(self.files.retry_calls, [])

    def test_cancel_is_explicit_and_never_auto_opens_file(self):
        controller = self.controller()
        path = self.make_file(content=b"cancel")
        prepared = controller.prepare_file(attachment_id="a1", local_path=path, sequence_no=0)
        self.store.register_attachment(prepared.metadata)
        cancelled = controller.cancel_file("a1")
        self.assertEqual(cancelled.transfer_state, "deleted")
        self.assertEqual(self.files.cancel_calls, ["a1"])
        self.assertTrue(path.exists())

    def test_cancel_cannot_delete_another_participant_attachment(self):
        controller = self.controller("student-1")
        path = self.make_file(content=b"foreign attachment")
        prepared = controller.prepare_file(
            attachment_id="foreign-a1",
            local_path=path,
            sequence_no=0,
        )
        foreign = replace(prepared.metadata, sender_id="student-2")
        self.store.register_attachment(foreign)

        with self.assertRaisesRegex(
            CollaborationError,
            "cannot cancel another participant",
        ):
            controller.cancel_file(foreign.attachment_id)

        self.assertEqual(self.files.cancel_calls, [])
        self.assertEqual(
            self.store.room_attachments("room-1"),
            (foreign,),
        )

    def test_download_token_requires_durable_stored_and_clean_scan(self):
        controller = self.controller()
        path = self.make_file(content=b"download")
        prepared = controller.prepare_file(
            attachment_id="a1",
            local_path=path,
            sequence_no=0,
            retention="persistent",
        )
        stored = controller.upload_file(prepared)
        self.assertEqual(stored.scan_state, "pending")
        with self.assertRaises(CollaborationError):
            controller.issue_download_token(attachment_id="a1")

        self.store.update_attachment_state("a1", transfer_state="stored", scan_state="clean")
        token = controller.issue_download_token(attachment_id="a1", ttl_seconds=120)
        self.assertEqual(token, "short-lived-read-token")
        self.assertEqual(
            self.file_store.read_calls,
            [("rooms/room-1/a1", "student-1", 120)],
        )

    def test_download_token_rejects_control_whitespace_and_oversize_without_echo(self):
        controller = self.controller()
        prepared = controller.prepare_file(
            attachment_id="token-a1",
            local_path=self.make_file(content=b"token payload"),
            sequence_no=0,
            retention="persistent",
        )
        stored = replace(
            prepared.metadata,
            transfer_state="stored",
            scan_state="clean",
        )
        self.store.register_attachment(stored)

        invalid_tokens = (
            "",
            "token with space",
            "token\nnewline",
            "token\x00nul",
            "token\x1fcontrol",
            "token\x7fdelete",
            "x" * 8193,
        )
        for token in invalid_tokens:
            with self.subTest(token=repr(token)[:40]):
                self.file_store.token = token
                with self.assertRaisesRegex(
                    CollaborationError,
                    "^file store returned invalid short-lived token$",
                ) as caught:
                    controller.issue_download_token(
                        attachment_id=stored.attachment_id,
                    )
                if token:
                    self.assertNotIn(token[:64], str(caught.exception))

    def test_unsafe_object_key_is_rejected_before_transport(self):
        controller = self.controller()
        path = self.make_file(content=b"x")
        with self.assertRaises(ValueError):
            controller.prepare_file(
                attachment_id="a1",
                local_path=path,
                sequence_no=0,
                object_key="../outside/a1",
            )
        self.assertEqual(self.files.upload_calls, [])

    def test_safe_object_key_override_must_match_canonical_room_attachment_namespace(self):
        controller = self.controller()
        path = self.make_file(content=b"namespace-bound")

        canonical = controller.prepare_file(
            attachment_id="a1",
            local_path=path,
            sequence_no=0,
            object_key="rooms/room-1/a1",
        )
        self.assertEqual(canonical.metadata.object_key, "rooms/room-1/a1")

        with self.assertRaisesRegex(
            CollaborationError,
            "canonical attachment namespace",
        ):
            controller.prepare_file(
                attachment_id="a2",
                local_path=path,
                sequence_no=1,
                object_key="rooms/other-room/a2",
            )

        self.assertEqual(self.files.upload_calls, [])
        self.assertEqual(self.store.room_attachments("room-1"), ())

    def test_removed_local_participant_loses_chat_and_file_access(self):
        controller = self.controller("student-1")
        prepared = controller.prepare_file(
            attachment_id="a1",
            local_path=self.make_file("before-removal.bin", b"payload"),
            sequence_no=0,
        )
        stored = replace(
            prepared.metadata,
            transfer_state="stored",
            scan_state="clean",
        )
        self.store.register_attachment(stored)
        self.roster.roles.pop("student-1")

        with self.assertRaises(CollaborationError):
            controller.sync_chat()
        with self.assertRaises(CollaborationError):
            controller.receive_chat(
                ChatMessageMetadata(
                    "m1",
                    "room-1",
                    "teacher-1",
                    0,
                    "After removal",
                    sent_at_unix_ms=1700000000000,
                )
            )
        with self.assertRaises(CollaborationError):
            controller.upload_file(prepared)
        with self.assertRaises(CollaborationError):
            controller.cancel_file("a1")
        with self.assertRaises(CollaborationError):
            controller.issue_download_token(attachment_id="a1")

        self.assertEqual(self.files.upload_calls, [])
        self.assertEqual(self.files.cancel_calls, [])
        self.assertEqual(self.file_store.read_calls, [])

    def test_non_member_cannot_construct_active_room_controller(self):
        self.roster.roles.pop("student-1")
        with self.assertRaises(CollaborationError):
            self.controller("student-1")

    def test_file_transfer_receives_path_and_metadata_not_eager_file_bytes(self):
        controller = self.controller()
        path = self.make_file(content=b"opaque")
        prepared = controller.prepare_file(attachment_id="a1", local_path=path, sequence_no=0)
        controller.upload_file(prepared)
        sent = self.files.upload_calls[0]
        self.assertIsInstance(sent, PreparedFile)
        self.assertIsInstance(sent.local_path, Path)
        self.assertFalse(hasattr(sent, "content"))


if __name__ == "__main__":
    unittest.main()
