from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.classroom_collaboration import ChatDraft, ClassroomCollaborationController
from acs.classroom_collaboration_outbox import (
    DurableChatDraftOutbox,
    DurableChatOutboxError,
    DurableOutboxClassroomCollaborationController,
)
from acs.classroom_collaboration_runtime import (
    build_classroom_collaboration_http_runtime,
)
from acs.classroom_collaboration_storage import (
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
)


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.fail_delete = False

    def write(self, name: str, value: bytes) -> None:
        self.values[name] = bytes(value)

    def read(self, name: str) -> bytes | None:
        value = self.values.get(name)
        return None if value is None else bytes(value)

    def delete(self, name: str) -> bool:
        if self.fail_delete:
            raise RuntimeError("simulated secret cleanup failure")
        return self.values.pop(name, None) is not None


class Roster:
    def participant_ids(self) -> tuple[str, ...]:
        return ("student-1",)

    def role_for(self, participant_id: str) -> str:
        if participant_id != "student-1":
            raise KeyError(participant_id)
        return "student"

    def board_control_allowed(self, participant_id: str) -> bool:
        if participant_id != "student-1":
            raise KeyError(participant_id)
        return True


class NeverUsedFiles:
    pass


class AmbiguousCommitChat:
    def __init__(self) -> None:
        self.message_ids: list[str] = []

    def send_message(self, draft: ChatDraft) -> ChatMessageMetadata:
        self.message_ids.append(draft.message_id)
        raise OSError("server commit acknowledgement lost")

    def history_after(self, *, room_id: str, after_sequence: int | None, limit: int):
        raise OSError("history temporarily unavailable")

    def state_updates_after(self, *, room_id: str, after_revision: int | None, limit: int):
        return ()

    def apply_moderation(self, commands):
        raise AssertionError("moderation is not part of this test")


class SuccessfulChat:
    def __init__(self) -> None:
        self.message_ids: list[str] = []

    def send_message(self, draft: ChatDraft) -> ChatMessageMetadata:
        self.message_ids.append(draft.message_id)
        return ChatMessageMetadata(
            message_id=draft.message_id,
            room_id=draft.room_id,
            sender_id=draft.sender_id,
            sequence_no=0,
            body=draft.body,
            retention=draft.retention,
            sent_at_unix_ms=1700000000000,
        )

    def history_after(self, *, room_id: str, after_sequence: int | None, limit: int):
        return ()

    def state_updates_after(self, *, room_id: str, after_revision: int | None, limit: int):
        return ()

    def apply_moderation(self, commands):
        raise AssertionError("moderation is not part of this test")


class ExplodingChat(SuccessfulChat):
    def send_message(self, draft: ChatDraft) -> ChatMessageMetadata:
        self.message_ids.append(draft.message_id)
        raise AssertionError("network must not be reached")


class DurableChatOutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "collaboration.sqlite3"
        self.store = ClassroomCollaborationSQLiteStore(str(self.path))
        self.secrets = MemorySecretStore()

    def lookup(self, message_id: str) -> ChatMessageMetadata | None:
        for item in self.store.room_messages("room-1", include_hidden=True):
            if item.message_id == message_id:
                return item
        return None

    def outbox(self) -> DurableChatDraftOutbox:
        return DurableChatDraftOutbox(
            secret_store=self.secrets,
            room_id="room-1",
            participant_id="student-1",
            storage_scope=str(self.path.resolve()),
            message_lookup=self.lookup,
        )

    def controller(self, chat, outbox: DurableChatDraftOutbox):
        return DurableOutboxClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-1",
            roster=Roster(),
            chat=chat,
            files=NeverUsedFiles(),
            store=self.store,
            chat_outbox=outbox,
        )

    def test_ambiguous_send_reuses_exact_message_identity_after_process_restart(self) -> None:
        first_chat = AmbiguousCommitChat()
        first = self.controller(first_chat, self.outbox())

        with self.assertRaises(OSError):
            first.send_chat(
                message_id="message-first-process",
                body="Restart-safe hello",
                retention="session",
            )

        self.assertEqual(
            first_chat.message_ids,
            ["message-first-process", "message-first-process"],
        )
        self.assertEqual(self.store.room_messages("room-1"), ())
        self.assertEqual(len(self.secrets.values), 1)
        self.assertTrue(
            all("Restart-safe hello" not in key for key in self.secrets.values)
        )

        second_chat = SuccessfulChat()
        second = self.controller(second_chat, self.outbox())
        delivered = second.send_chat(
            message_id="message-new-process-would-have-used",
            body="Restart-safe hello",
            retention="session",
        )

        self.assertEqual(delivered.message_id, "message-first-process")
        self.assertEqual(second_chat.message_ids, ["message-first-process"])
        persisted = self.store.room_messages("room-1")
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].message_id, "message-first-process")
        self.assertEqual(self.secrets.values, {})

    def test_restart_retry_preserves_original_retention_for_same_body(self) -> None:
        first_chat = AmbiguousCommitChat()
        first = self.controller(first_chat, self.outbox())
        with self.assertRaises(OSError):
            first.send_chat(
                message_id="message-original-retention",
                body="Same logical draft",
                retention="session",
            )

        second_chat = SuccessfulChat()
        second = self.controller(second_chat, self.outbox())
        delivered = second.send_chat(
            message_id="message-new-process",
            body="Same logical draft",
            retention="persistent",
        )

        self.assertEqual(delivered.message_id, "message-original-retention")
        self.assertEqual(delivered.retention, "session")
        self.assertEqual(second_chat.message_ids, ["message-original-retention"])

    def test_persisted_message_with_failed_outbox_cleanup_never_resends(self) -> None:
        self.secrets.fail_delete = True
        first_chat = SuccessfulChat()
        first = self.controller(first_chat, self.outbox())

        delivered = first.send_chat(
            message_id="message-before-crash",
            body="Already durable",
        )
        self.assertEqual(delivered.message_id, "message-before-crash")
        self.assertEqual(first_chat.message_ids, ["message-before-crash"])
        self.assertEqual(len(self.secrets.values), 1)

        after_restart_chat = ExplodingChat()
        second = self.controller(after_restart_chat, self.outbox())
        recovered = second.send_chat(
            message_id="message-after-restart",
            body="Already durable",
        )

        self.assertEqual(recovered.message_id, "message-before-crash")
        self.assertEqual(after_restart_chat.message_ids, [])
        self.assertEqual(len(self.store.room_messages("room-1")), 1)

    def test_unrelated_new_send_fails_closed_if_stale_durable_slot_cannot_retire(self) -> None:
        self.secrets.fail_delete = True
        first = self.controller(SuccessfulChat(), self.outbox())
        first.send_chat(message_id="old-message", body="Old durable body")

        network = ExplodingChat()
        second = self.controller(network, self.outbox())
        with self.assertRaisesRegex(
            DurableChatOutboxError,
            "cannot be deleted",
        ):
            second.send_chat(
                message_id="new-message",
                body="Different new body",
            )
        self.assertEqual(network.message_ids, [])

    def test_corrupt_or_cross_identity_secret_fails_before_network(self) -> None:
        outbox = self.outbox()
        draft = ChatDraft(
            message_id="message-corrupt",
            room_id="room-1",
            sender_id="student-1",
            body="Original",
        )
        resolution = outbox.prepare(draft)
        self.assertEqual(resolution.draft, draft)
        self.assertEqual(len(self.secrets.values), 1)

        slot = next(iter(self.secrets.values))
        self.secrets.values[slot] = (
            b'{"body":"Original","message_id":"message-corrupt",'
            b'"retention":"session","room_id":"other-room",'
            b'"sender_id":"student-1","v":1}'
        )
        network = ExplodingChat()
        controller = self.controller(network, self.outbox())
        with self.assertRaisesRegex(
            DurableChatOutboxError,
            "identity boundary",
        ):
            controller.send_chat(
                message_id="new-message",
                body="Original",
            )
        self.assertEqual(network.message_ids, [])

    def test_duplicate_json_members_fail_closed(self) -> None:
        outbox = self.outbox()
        slot_name = outbox._slot(0)
        self.secrets.values[slot_name] = (
            b'{"v":1,"v":1,"message_id":"m1","room_id":"room-1",'
            b'"sender_id":"student-1","body":"x","retention":"session"}'
        )
        with self.assertRaisesRegex(
            DurableChatOutboxError,
            "duplicate JSON members",
        ):
            outbox.prepare(
                ChatDraft(
                    message_id="m2",
                    room_id="room-1",
                    sender_id="student-1",
                    body="x",
                )
            )

    def test_storage_scope_isolates_same_room_participant_slots(self) -> None:
        first = DurableChatDraftOutbox(
            secret_store=self.secrets,
            room_id="room-1",
            participant_id="student-1",
            storage_scope="profile-a",
            message_lookup=self.lookup,
        )
        second = DurableChatDraftOutbox(
            secret_store=self.secrets,
            room_id="room-1",
            participant_id="student-1",
            storage_scope="profile-b",
            message_lookup=self.lookup,
        )
        self.assertNotEqual(first._slot(0), second._slot(0))
        self.assertNotIn("profile-a", first._slot(0))
        self.assertNotIn("profile-b", second._slot(0))

    def test_fixed_slot_names_do_not_encode_body_or_message_identity(self) -> None:
        outbox = self.outbox()
        draft = ChatDraft(
            message_id="very-distinct-message-id",
            room_id="room-1",
            sender_id="student-1",
            body="very distinct secret classroom sentence",
        )
        outbox.prepare(draft)
        self.assertEqual(len(self.secrets.values), 1)
        slot_name = next(iter(self.secrets.values))
        self.assertNotIn("distinct", slot_name)
        self.assertNotIn("message", slot_name)
        self.assertTrue(slot_name.endswith("-00"))

    def test_non_windows_runtime_preserves_exact_canonical_controller(self) -> None:
        target = Path(self.temp.name) / "plain-runtime.sqlite3"
        with mock.patch("acs.classroom_collaboration_runtime.sys.platform", "linux"):
            runtime = build_classroom_collaboration_http_runtime(
                room_id="room-1",
                participant_id="student-1",
                roster=Roster(),
                store_path=target,
                chat_endpoint_url="https://chat.example.test/v1/classroom/chat",
                file_endpoint_url="https://files.example.test/v1/classroom/files",
                chat_bearer_token_provider=lambda: "chat-token",
                file_bearer_token_provider=lambda: "file-token",
                participant_label=lambda participant_id: participant_id,
            )

        self.assertIsNone(runtime.chat_outbox)
        self.assertIs(type(runtime.controller), ClassroomCollaborationController)

    def test_windows_runtime_selects_dpapi_secret_store_without_browser_changes(self) -> None:
        secret_store = MemorySecretStore()
        target = Path(self.temp.name) / "runtime.sqlite3"
        with (
            mock.patch("acs.classroom_collaboration_runtime.sys.platform", "win32"),
            mock.patch(
                "acs.classroom_collaboration_runtime.WindowsDpapiSecretStore.for_current_user",
                return_value=secret_store,
            ) as current_user_store,
        ):
            runtime = build_classroom_collaboration_http_runtime(
                room_id="room-1",
                participant_id="student-1",
                roster=Roster(),
                store_path=target,
                chat_endpoint_url="https://chat.example.test/v1/classroom/chat",
                file_endpoint_url="https://files.example.test/v1/classroom/files",
                chat_bearer_token_provider=lambda: "chat-token",
                file_bearer_token_provider=lambda: "file-token",
                participant_label=lambda participant_id: participant_id,
            )

        current_user_store.assert_called_once_with()
        self.assertIsNotNone(runtime.chat_outbox)
        self.assertIsInstance(
            runtime.controller,
            DurableOutboxClassroomCollaborationController,
        )
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
