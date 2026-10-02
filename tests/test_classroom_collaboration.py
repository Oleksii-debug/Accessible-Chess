from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import (
    ChatDraft,
    ClassroomCollaborationController,
    CollaborationError,
    FileQuotaPolicy,
    PreparedFile,
)
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
    content_sha256,
)
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
        self.mutate_delivery = False

    def send_message(self, draft):
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

    def apply_moderation(self, commands):
        self.moderation_calls.append(commands)


class FakeFiles:
    def __init__(self):
        self.upload_calls = []
        self.retry_calls = []
        self.cancel_calls = []
        self.fail_upload = False
        self.fail_retry = False
        self.scan_state = "pending"

    def upload(self, prepared):
        self.upload_calls.append(prepared)
        if self.fail_upload:
            raise RuntimeError("provider upload failed")
        return replace(
            prepared.metadata,
            transfer_state="stored",
            scan_state=self.scan_state,
        )

    def retry(self, prepared):
        self.retry_calls.append(prepared)
        if self.fail_retry:
            raise RuntimeError("provider retry failed")
        return replace(
            prepared.metadata,
            transfer_state="stored",
            scan_state=self.scan_state,
        )

    def cancel(self, *, attachment_id):
        self.cancel_calls.append(attachment_id)


class FakeFileStore:
    def __init__(self):
        self.read_calls = []

    def put(self, *, object_key, content, expected_sha256):
        raise AssertionError("controller must not push opaque bytes through download-token path")

    def issue_read_token(self, *, object_key, participant_id, ttl_seconds):
        self.read_calls.append((object_key, participant_id, ttl_seconds))
        return "short-lived-read-token"

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
        self.assertEqual(self.store.room_messages("room-1"), (first,))
        self.assertEqual(len(self.chat.ordered), 1)

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

    def test_sync_rejects_cross_room_or_out_of_order_transport_history(self):
        controller = self.controller()
        self.chat.ordered.append(
            ChatMessageMetadata("m1", "other-room", "teacher-1", 0, "wrong room")
        )
        self.assertEqual(controller.sync_chat(), ())

        self.chat.ordered = [
            ChatMessageMetadata("m2", "room-1", "teacher-1", 2, "later"),
            ChatMessageMetadata("m3", "room-1", "student-1", 1, "earlier"),
        ]
        with self.assertRaises(CollaborationError):
            controller.sync_chat()

    def test_removed_sender_is_rejected_from_received_chat(self):
        controller = self.controller()
        self.roster.roles.pop("student-2")
        with self.assertRaises(CollaborationError):
            controller.receive_chat(
                ChatMessageMetadata("m1", "room-1", "student-2", 0, "orphan")
            )

    def test_teacher_chat_lock_prevents_local_send_until_restored(self):
        controller = self.controller("student-1")
        controller.set_chat_send_permission(
            actor_id="teacher-1",
            target_id="student-1",
            allowed=False,
            operation_id="lock-student-chat",
        )
        with self.assertRaises(CollaborationError):
            controller.send_chat(message_id="m1", body="blocked")
        controller.set_chat_send_permission(
            actor_id="teacher-1",
            target_id="student-1",
            allowed=True,
            operation_id="unlock-student-chat",
        )
        self.assertEqual(controller.send_chat(message_id="m2", body="allowed").body, "allowed")

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
        self.assertEqual(prepared.metadata.display_name, "lesson.weirdformat")
        self.assertEqual(prepared.metadata.size_bytes, len(content))
        self.assertEqual(prepared.metadata.sha256, content_sha256(content))
        self.assertIsNone(prepared.metadata.mime_type)
        self.assertEqual(prepared.metadata.transfer_state, "pending")
        self.assertEqual(prepared.metadata.scan_state, "pending")

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

    def test_file_content_change_after_prepare_fails_closed_before_transport(self):
        controller = self.controller()
        path = self.make_file(content=b"first")
        prepared = controller.prepare_file(attachment_id="a1", local_path=path, sequence_no=0)
        path.write_bytes(b"changed")
        with self.assertRaises(CollaborationError):
            controller.upload_file(prepared)
        self.assertEqual(self.files.upload_calls, [])

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

    def test_unsafe_object_key_is_rejected_by_durable_metadata_boundary(self):
        controller = self.controller()
        path = self.make_file(content=b"x")
        prepared = controller.prepare_file(
            attachment_id="a1",
            local_path=path,
            sequence_no=0,
            object_key="../outside/a1",
        )
        with self.assertRaises(ValueError):
            controller.upload_file(prepared)
        self.assertEqual(self.files.upload_calls, [])

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
