from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from acs.classroom_chat_outbox import ChatOutboxError, SecretStoreChatOutbox
from acs.secret_store import WindowsDpapiSecretStore


SCOPE = "https://chat.example.test/v1/classroom/chat"


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def write(self, name: str, value: bytes) -> None:
        self.values[name] = bytes(value)

    def read(self, name: str) -> bytes | None:
        value = self.values.get(name)
        return None if value is None else bytes(value)

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


class ClassroomChatOutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secrets = MemorySecretStore()
        self.outbox = SecretStoreChatOutbox(
            self.secrets,
            SCOPE,
            "room-1",
            "student-1",
        )

    def test_slot_identity_is_stable_hashed_and_repr_is_redacted(self) -> None:
        slot = self.outbox.slot_name
        self.assertTrue(slot.startswith("classroom-chat-outbox-"))
        self.assertNotIn("room-1", slot)
        self.assertNotIn("student-1", slot)
        self.assertEqual(slot, SecretStoreChatOutbox(
            self.secrets,
            SCOPE,
            "room-1",
            "student-1",
        ).slot_name)
        self.assertNotEqual(
            slot,
            SecretStoreChatOutbox(self.secrets, SCOPE, "room-2", "student-1").slot_name,
        )
        self.assertEqual(repr(self.outbox), "SecretStoreChatOutbox(<bound>)")

    def test_transport_scope_is_part_of_slot_and_document_binding(self) -> None:
        self.outbox.reserve(
            message_id="message-one",
            body="Deployment-bound draft",
            retention="session",
        )
        other = SecretStoreChatOutbox(
            self.secrets,
            "https://other-chat.example.test/v1/classroom/chat",
            "room-1",
            "student-1",
        )
        self.assertNotEqual(self.outbox.slot_name, other.slot_name)
        self.secrets.values[other.slot_name] = self.secrets.values[self.outbox.slot_name]
        with self.assertRaisesRegex(ChatOutboxError, "identity binding"):
            other.entries()

    def test_exact_pending_payload_reuses_stable_message_identity(self) -> None:
        reserved = self.outbox.reserve(
            message_id="message-one",
            body="Retry after restart",
            retention="session",
        )
        reopened = SecretStoreChatOutbox(self.secrets, SCOPE, "room-1", "student-1")
        found = reopened.find(body="Retry after restart", retention="session")
        second = reopened.reserve(
            message_id="message-two",
            body="Retry after restart",
            retention="session",
        )

        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.message_id, "message-one")
        self.assertEqual(second.message_id, "message-one")
        self.assertEqual(len(reopened.entries()), 1)
        self.assertNotIn("message-two", repr(reopened))

    def test_same_body_under_different_retention_is_a_distinct_pending_send(self) -> None:
        first = self.outbox.reserve(
            message_id="message-one",
            body="Same text",
            retention="session",
        )
        second = self.outbox.reserve(
            message_id="message-two",
            body="Same text",
            retention="persistent",
        )
        self.assertNotEqual(first.message_id, second.message_id)
        self.assertEqual(len(self.outbox.entries()), 2)

    def test_discard_requires_exact_immutable_payload_and_deletes_empty_slot(self) -> None:
        self.outbox.reserve(
            message_id="message-one",
            body="Immutable body",
            retention="session",
        )
        with self.assertRaisesRegex(ChatOutboxError, "changed unexpectedly"):
            self.outbox.discard(
                message_id="message-one",
                body="Changed body",
                retention="session",
            )
        self.assertTrue(
            self.outbox.discard(
                message_id="message-one",
                body="Immutable body",
                retention="session",
            )
        )
        self.assertFalse(
            self.outbox.discard(
                message_id="message-one",
                body="Immutable body",
                retention="session",
            )
        )
        self.assertNotIn(self.outbox.slot_name, self.secrets.values)

    def test_room_and_participant_binding_fail_closed(self) -> None:
        self.outbox.reserve(
            message_id="message-one",
            body="Bound draft",
            retention="session",
        )
        raw = self.secrets.values[self.outbox.slot_name]
        document = json.loads(raw.decode("utf-8"))
        document["room_id"] = "room-2"
        self.secrets.values[self.outbox.slot_name] = json.dumps(
            document,
            separators=(",", ":"),
        ).encode("utf-8")
        with self.assertRaisesRegex(ChatOutboxError, "identity binding"):
            self.outbox.entries()

    def test_duplicate_json_members_and_unknown_fields_fail_closed(self) -> None:
        self.secrets.values[self.outbox.slot_name] = (
            b'{"v":1,"v":1,"scope_id":"https://chat.example.test/v1/classroom/chat","room_id":"room-1","participant_id":"student-1","entries":[]}'
        )
        with self.assertRaisesRegex(ChatOutboxError, "JSON object") as duplicate:
            self.outbox.entries()
        self.assertIsNone(duplicate.exception.__cause__)

        self.secrets.values[self.outbox.slot_name] = (
            b'{"v":1,"scope_id":"https://chat.example.test/v1/classroom/chat","room_id":"room-1","participant_id":"student-1","entries":[],"extra":1}'
        )
        with self.assertRaisesRegex(ChatOutboxError, "shape"):
            self.outbox.entries()

    def test_duplicate_message_or_payload_identity_fails_closed(self) -> None:
        document = {
            "v": 1,
            "scope_id": SCOPE,
            "room_id": "room-1",
            "participant_id": "student-1",
            "entries": [
                {"message_id": "message-one", "body": "A", "retention": "session"},
                {"message_id": "message-one", "body": "B", "retention": "session"},
            ],
        }
        self.secrets.values[self.outbox.slot_name] = json.dumps(
            document,
            separators=(",", ":"),
        ).encode("utf-8")
        with self.assertRaisesRegex(ChatOutboxError, "duplicate"):
            self.outbox.entries()

        document["entries"] = [
            {"message_id": "message-one", "body": "A", "retention": "session"},
            {"message_id": "message-two", "body": "A", "retention": "session"},
        ]
        self.secrets.values[self.outbox.slot_name] = json.dumps(
            document,
            separators=(",", ":"),
        ).encode("utf-8")
        with self.assertRaisesRegex(ChatOutboxError, "duplicate"):
            self.outbox.entries()

    def test_entry_count_and_document_size_are_bounded(self) -> None:
        for index in range(32):
            self.outbox.reserve(
                message_id=f"message-{index}",
                body=f"pending {index}",
                retention="session",
            )
        with self.assertRaisesRegex(ChatOutboxError, "full"):
            self.outbox.reserve(
                message_id="message-overflow",
                body="overflow",
                retention="session",
            )

        self.secrets.values[self.outbox.slot_name] = b"x" * (60 * 1024 + 1)
        with self.assertRaisesRegex(ChatOutboxError, "invalid"):
            self.outbox.entries()

    def test_secret_store_failure_is_sanitized(self) -> None:
        class FailingSecretStore(MemorySecretStore):
            def read(self, name: str) -> bytes | None:
                raise RuntimeError("SUPER-SECRET backend detail")

        outbox = SecretStoreChatOutbox(
            FailingSecretStore(),
            SCOPE,
            "room-1",
            "student-1",
        )
        with self.assertRaises(ChatOutboxError) as caught:
            outbox.entries()
        self.assertNotIn("SUPER-SECRET", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)


@unittest.skipUnless(sys.platform == "win32", "real encrypted outbox qualification requires Windows")
class WindowsDpapiChatOutboxIntegrationTests(unittest.TestCase):
    def test_pending_chat_round_trip_is_dpapi_encrypted_at_rest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            secret_store = WindowsDpapiSecretStore(Path(td) / "secure")
            outbox = SecretStoreChatOutbox(
                secret_store,
                SCOPE,
                "room-1",
                "student-1",
            )
            body = "Sensitive pending classroom draft"
            reserved = outbox.reserve(
                message_id="message-dpapi-one",
                body=body,
                retention="session",
            )
            ciphertext_path = secret_store._path(outbox.slot_name)
            ciphertext = ciphertext_path.read_bytes()

            self.assertGreater(len(ciphertext), 0)
            self.assertNotIn(body.encode("utf-8"), ciphertext)
            self.assertNotIn(reserved.message_id.encode("utf-8"), ciphertext)

            reopened = SecretStoreChatOutbox(
                WindowsDpapiSecretStore(Path(td) / "secure"),
                SCOPE,
                "room-1",
                "student-1",
            )
            recovered = reopened.find(body=body, retention="session")
            self.assertIsNotNone(recovered)
            assert recovered is not None
            self.assertEqual(recovered.message_id, "message-dpapi-one")
            self.assertTrue(
                reopened.discard(
                    message_id=recovered.message_id,
                    body=recovered.body,
                    retention=recovered.retention,
                )
            )
            self.assertFalse(ciphertext_path.exists())


if __name__ == "__main__":
    unittest.main()
