from __future__ import annotations

from dataclasses import replace
import hashlib
import tempfile
import unittest
from pathlib import Path

from acs.classroom_collaboration import (
    AttachmentHistoryPage,
    ClassroomCollaborationController,
    FileQuotaPolicy,
    PreparedFile,
    _canonical_object_key,
)
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    ClassroomCollaborationSQLiteStore,
)
from acs.classroom_file_rpc import (
    RPC_VERSION,
    ClassroomFileRpcClient,
    ClassroomFileRpcError,
    ClassroomFileRpcService,
)
from acs.classroom_file_server import (
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)
from acs.classroom_realtime_media import ClassroomRole


class AllowMembers:
    def __init__(self, members):
        self.members = set(members)

    def authorize_file_action(
        self,
        *,
        trusted_caller_identity,
        room_id,
        action,
        attachment_id,
        retention,
    ):
        return (trusted_caller_identity, room_id) in self.members


class CleanScanner:
    def __init__(self):
        self.calls = []

    def scan(self, **kwargs):
        self.calls.append(kwargs)
        return "clean"


class MemoryObjectStore:
    def __init__(self):
        self.objects = {}
        self.put_calls = []
        self.delete_calls = []
        self.token_calls = []
        self.fail_status_with = None

    def stored_sha256(self, *, object_key):
        if self.fail_status_with is not None:
            raise RuntimeError(self.fail_status_with)
        content = self.objects.get(object_key)
        return None if content is None else hashlib.sha256(content).hexdigest()

    def put(self, *, object_key, content, expected_sha256):
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise RuntimeError("object hash mismatch")
        existing = self.objects.get(object_key)
        if existing is not None and existing != content:
            raise RuntimeError("object identity conflict")
        self.objects[object_key] = bytes(content)
        self.put_calls.append((object_key, bytes(content), expected_sha256))

    def issue_read_token(self, *, object_key, participant_id, ttl_seconds):
        if object_key not in self.objects:
            raise RuntimeError("object is missing")
        self.token_calls.append((object_key, participant_id, ttl_seconds))
        return f"token-{participant_id}-{ttl_seconds}"

    def delete(self, *, object_key):
        self.delete_calls.append(object_key)
        self.objects.pop(object_key, None)


class BoundRpcTransport:
    """In-process stand-in for one authenticated binary-capable transport."""

    def __init__(self, service, *, room_id, participant_id):
        self.service = service
        self.room_id = room_id
        self.participant_id = participant_id
        self.requests = []
        self.binary_payloads = []
        self.progress_script = None
        self.response_mutator = None

    def call(
        self,
        request,
        *,
        binary_content=None,
        on_upload_progress=None,
    ):
        self.requests.append(dict(request))
        self.binary_payloads.append(binary_content)
        if binary_content is not None and on_upload_progress is not None:
            if self.progress_script is None:
                total = len(binary_content)
                samples = (0, total // 2, total)
            else:
                samples = tuple(self.progress_script)
            for transferred in samples:
                on_upload_progress(transferred)
        response = self.service.handle(
            dict(request),
            authenticated_room_id=self.room_id,
            authenticated_participant_id=self.participant_id,
            binary_content=binary_content,
        )
        if self.response_mutator is not None:
            response = self.response_mutator(dict(response))
        return response


class RoomRoster:
    def participant_ids(self):
        return ("student-1", "student-2")

    def role_for(self, participant_id):
        if participant_id not in self.participant_ids():
            raise KeyError(participant_id)
        return ClassroomRole.STUDENT

    def board_control_allowed(self, participant_id):
        return participant_id in self.participant_ids()


class UnusedChat:
    def send_message(self, _draft):
        raise AssertionError("chat must not be used by file RPC tests")

    def history_after(self, **_kwargs):
        raise AssertionError("chat must not be used by file RPC tests")

    def state_updates_after(self, **_kwargs):
        raise AssertionError("chat must not be used by file RPC tests")

    def apply_moderation(self, _commands):
        raise AssertionError("chat must not be used by file RPC tests")


class ClassroomFileRpcTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server_db = self.root / "file-server.sqlite3"
        self.authorization = AllowMembers(
            {
                ("student-1", "room-1"),
                ("student-2", "room-1"),
                ("student-1", "room-2"),
            }
        )
        self.scanner = CleanScanner()
        self.objects = MemoryObjectStore()
        self.quota = FileQuotaPolicy(
            max_file_bytes=4 * 1024 * 1024,
            max_room_bytes=8 * 1024 * 1024,
        )
        self.server_store = ClassroomFileServerSQLiteStore(str(self.server_db))
        self.server = ClassroomFileServerService(
            store=self.server_store,
            authorization=self.authorization,
            scanner=self.scanner,
            object_store=self.objects,
            quota=self.quota,
        )
        self.rpc = ClassroomFileRpcService(
            backend=self.server,
            max_upload_bytes=self.quota.max_file_bytes,
        )
        self.transport1 = BoundRpcTransport(
            self.rpc,
            room_id="room-1",
            participant_id="student-1",
        )
        self.transport2 = BoundRpcTransport(
            self.rpc,
            room_id="room-1",
            participant_id="student-2",
        )
        self.client1 = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=self.transport1,
            max_upload_bytes=self.quota.max_file_bytes,
        )
        self.client2 = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-2",
            transport=self.transport2,
            max_upload_bytes=self.quota.max_file_bytes,
        )

    def tearDown(self):
        self.temp.cleanup()

    def prepared(
        self,
        *,
        attachment_id,
        participant_id="student-1",
        room_id="room-1",
        content=b"opaque\x00payload",
        sequence_no=700,
    ):
        path = self.root / f"{room_id}-{attachment_id}.bin"
        path.write_bytes(content)
        metadata = AttachmentMetadata(
            attachment_id,
            room_id,
            participant_id,
            sequence_no,
            path.name,
            "application/octet-stream",
            len(content),
            hashlib.sha256(content).hexdigest(),
            _canonical_object_key(room_id, attachment_id),
            "uploading",
            "persistent",
            "pending",
        )
        return PreparedFile(path, metadata)

    def controller(self, participant_id, client, filename):
        return ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id=participant_id,
            roster=RoomRoster(),
            chat=UnusedChat(),
            files=client,
            store=ClassroomCollaborationSQLiteStore(str(self.root / filename)),
            file_store=client,
            quota=self.quota,
        )

    def test_upload_uses_separate_binary_channel_and_preserves_arbitrary_bytes(self):
        payload = b"\x00\xff\x10binary\x00\x7f"
        prepared = self.prepared(
            attachment_id="binary-a0",
            content=payload,
        )

        stored = self.client1.upload(prepared)

        request = self.transport1.requests[-1]
        self.assertEqual(
            set(request),
            {"v", "op", "room_id", "participant_id", "metadata"},
        )
        self.assertNotIn("content", request)
        self.assertEqual(self.transport1.binary_payloads[-1], payload)
        self.assertEqual(self.objects.objects[stored.object_key], payload)
        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(stored.scan_state, "clean")

    def test_transport_progress_is_monotonic_nonterminal_and_deduplicated(self):
        payload = b"abcdefgh"
        prepared = self.prepared(
            attachment_id="progress-a0",
            content=payload,
        )
        self.transport1.progress_script = (0, 4, 4, len(payload))
        observed = []

        stored = self.client1.upload(
            prepared,
            on_progress=observed.append,
        )

        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(
            [
                (item.transferred_bytes, item.total_bytes, item.complete)
                for item in observed
            ],
            [
                (0, len(payload), False),
                (4, len(payload), False),
                (len(payload), len(payload), False),
            ],
        )

    def test_transport_progress_rejects_malformed_or_backward_samples_before_backend(self):
        cases = (
            ("negative", (-1,)),
            ("boolean", (True,)),
            ("overflow", (9,)),
            ("backward", (0, 5, 4)),
        )
        for index, (label, script) in enumerate(cases):
            with self.subTest(label=label):
                prepared = self.prepared(
                    attachment_id=f"bad-progress-{index}",
                    content=b"12345678",
                )
                self.transport1.progress_script = script
                put_count = len(self.objects.put_calls)
                with self.assertRaises(ClassroomFileRpcError):
                    self.client1.upload(prepared)
                self.assertEqual(len(self.objects.put_calls), put_count)

    def test_success_without_terminal_transport_progress_is_ambiguous_but_retry_converges(self):
        payload = b"exactly-once"
        prepared = self.prepared(
            attachment_id="missing-progress-a0",
            content=payload,
        )
        self.transport1.progress_script = (0, 2)

        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "omitted final upload progress",
        ):
            self.client1.upload(prepared)

        self.assertEqual(
            self.objects.objects[prepared.metadata.object_key],
            payload,
        )
        self.assertEqual(len(self.objects.put_calls), 1)

        self.transport1.progress_script = (0, len(payload))
        replayed = self.client1.retry(prepared)

        self.assertEqual(replayed.transfer_state, "stored")
        self.assertEqual(replayed.sequence_no, 0)
        self.assertEqual(len(self.objects.put_calls), 1)

    def test_progress_consumer_failure_does_not_corrupt_accepted_upload(self):
        prepared = self.prepared(
            attachment_id="consumer-failure-a0",
            content=b"observer failure is presentation-only",
        )

        def broken_consumer(_sample):
            raise RuntimeError("presentation exploded")

        stored = self.client1.upload(
            prepared,
            on_progress=broken_consumer,
        )

        self.assertEqual(stored.transfer_state, "stored")
        self.assertIn(stored.object_key, self.objects.objects)

    def test_source_mutation_fails_before_authenticated_transport(self):
        mutations = (
            b"x",
            b"opaque\x00payload-extra",
            b"same-length-no",
        )
        for index, replacement in enumerate(mutations):
            with self.subTest(index=index):
                prepared = self.prepared(
                    attachment_id=f"source-change-{index}",
                    content=b"same-length-ok",
                )
                prepared.local_path.write_bytes(replacement)
                before = len(self.transport1.requests)
                with self.assertRaisesRegex(
                    ClassroomFileRpcError,
                    "changed before RPC upload",
                ):
                    self.client1.upload(prepared)
                self.assertEqual(len(self.transport1.requests), before)

    def test_service_requires_binary_body_only_for_upload(self):
        prepared = self.prepared(attachment_id="wire-body-a0")
        metadata = prepared.metadata
        upload_request = {
            "v": RPC_VERSION,
            "op": "upload",
            "room_id": "room-1",
            "participant_id": "student-1",
            "metadata": {
                "attachment_id": metadata.attachment_id,
                "room_id": metadata.room_id,
                "sender_id": metadata.sender_id,
                "sequence_no": metadata.sequence_no,
                "display_name": metadata.display_name,
                "mime_type": metadata.mime_type,
                "size_bytes": metadata.size_bytes,
                "sha256": metadata.sha256,
                "object_key": metadata.object_key,
                "transfer_state": metadata.transfer_state,
                "retention": metadata.retention,
                "scan_state": metadata.scan_state,
            },
        }
        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "content must be opaque bytes",
        ):
            self.rpc.handle(
                upload_request,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )

        history_request = {
            "v": RPC_VERSION,
            "op": "history",
            "room_id": "room-1",
            "participant_id": "student-1",
            "after_sequence": None,
            "limit": 10,
        }
        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "only valid for upload",
        ):
            self.rpc.handle(
                history_request,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
                binary_content=b"unexpected",
            )

    def test_authenticated_transport_identity_cannot_be_forged_in_request(self):
        request = {
            "v": RPC_VERSION,
            "op": "history",
            "room_id": "room-2",
            "participant_id": "student-1",
            "after_sequence": None,
            "limit": 10,
        }

        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "does not match authenticated transport",
        ):
            self.rpc.handle(
                request,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )

    def test_cancel_cannot_cross_authenticated_room_by_attachment_id(self):
        room2 = self.prepared(
            attachment_id="room2-a0",
            room_id="room-2",
            participant_id="student-1",
            content=b"room two",
        )
        stored = self.server.upload(
            trusted_caller_identity="student-1",
            metadata=room2.metadata,
            content=room2.local_path.read_bytes(),
        )
        self.assertEqual(stored.room_id, "room-2")

        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "backend failed",
        ):
            self.client1.cancel(attachment_id=stored.attachment_id)

        page = self.server.history_after(
            trusted_caller_identity="student-1",
            room_id="room-2",
            after_sequence=None,
            limit=10,
        )
        self.assertEqual(page.attachments, (stored,))

    def test_history_wire_preserves_snapshot_state_watermark(self):
        prepared = self.prepared(attachment_id="watermark-a0")
        stored = self.client1.upload(prepared)
        self.client1.cancel(attachment_id=stored.attachment_id)

        page = self.client2.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=10,
        )

        self.assertIsInstance(page, AttachmentHistoryPage)
        self.assertEqual(len(page.attachments), 1)
        self.assertEqual(page.attachments[0].transfer_state, "deleted")
        self.assertEqual(page.snapshot_state_revision, 0)

    def test_history_client_rejects_invalid_or_extra_watermark_fields(self):
        prepared = self.prepared(attachment_id="bad-watermark-a0")
        self.client1.upload(prepared)

        def invalid_watermark(response):
            if "snapshot_state_revision" in response:
                response["snapshot_state_revision"] = True
            return response

        self.transport2.response_mutator = invalid_watermark
        with self.assertRaises(ClassroomFileRpcError):
            self.client2.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            )

        def extra_field(response):
            if "snapshot_state_revision" in response:
                response["unexpected"] = "drift"
            return response

        self.transport2.response_mutator = extra_field
        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "history response fields are invalid",
        ):
            self.client2.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            )

    def test_two_clients_rejoin_after_server_restart_with_same_durable_authority(self):
        payload = b"restart-safe"
        prepared = self.prepared(
            attachment_id="restart-a0",
            content=payload,
        )
        stored = self.client1.upload(prepared)

        reopened_server = ClassroomFileServerService(
            store=ClassroomFileServerSQLiteStore(str(self.server_db)),
            authorization=self.authorization,
            scanner=self.scanner,
            object_store=self.objects,
            quota=self.quota,
        )
        reopened_rpc = ClassroomFileRpcService(
            backend=reopened_server,
            max_upload_bytes=self.quota.max_file_bytes,
        )
        rejoined1 = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=BoundRpcTransport(
                reopened_rpc,
                room_id="room-1",
                participant_id="student-1",
            ),
            max_upload_bytes=self.quota.max_file_bytes,
        )
        rejoined2 = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-2",
            transport=BoundRpcTransport(
                reopened_rpc,
                room_id="room-1",
                participant_id="student-2",
            ),
            max_upload_bytes=self.quota.max_file_bytes,
        )

        page = rejoined2.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=10,
        )
        self.assertEqual(page.attachments, (stored,))
        self.assertIsNone(page.snapshot_state_revision)
        token = rejoined2.issue_read_token(
            object_key=stored.object_key,
            participant_id="student-2",
            ttl_seconds=60,
        )
        self.assertEqual(token, "token-student-2-60")

        rejoined1.cancel(attachment_id=stored.attachment_id)
        tombstone = rejoined2.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=10,
        )
        self.assertEqual(tombstone.attachments[0].transfer_state, "deleted")
        self.assertEqual(tombstone.snapshot_state_revision, 0)

    def test_controller_sync_applies_state_for_old_attachment_when_incremental_history_is_empty(self):
        prepared = self.prepared(
            attachment_id="incremental-cancel-a0",
            content=b"state after initial history",
        )
        stored = self.client1.upload(prepared)
        controller2 = self.controller(
            "student-2",
            self.client2,
            "student2-collaboration.sqlite3",
        )

        self.assertEqual(controller2.sync_files(), (stored,))
        local_store = controller2._store
        self.assertEqual(
            local_store.room_attachments("room-1")[0].transfer_state,
            "stored",
        )

        self.client1.cancel(attachment_id=stored.attachment_id)
        # after_sequence is now 0, so server history contributes no new
        # attachment snapshot. Revision 0 must still flow through state sync.
        self.assertEqual(controller2.sync_files(), ())
        current = local_store.room_attachments("room-1")[0]
        self.assertEqual(current.transfer_state, "deleted")
        self.assertEqual(
            local_store.attachment_state_revision("room-1"),
            0,
        )

    def test_controller_over_rpc_emits_terminal_completion_only_after_stored_result(self):
        controller1 = self.controller(
            "student-1",
            self.client1,
            "student1-collaboration.sqlite3",
        )
        payload = b"controller-rpc-progress"
        path = self.root / "controller-rpc-progress.bin"
        path.write_bytes(payload)
        prepared = controller1.prepare_file(
            attachment_id="controller-rpc-a0",
            local_path=path,
            sequence_no=500,
            retention="persistent",
        )
        self.transport1.progress_script = (0, 5, len(payload))
        observed = []

        stored = controller1.upload_file(
            prepared,
            on_progress=observed.append,
        )

        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(observed[-1].transferred_bytes, len(payload))
        self.assertTrue(observed[-1].complete)
        self.assertTrue(all(not item.complete for item in observed[:-1]))

    def test_backend_failure_is_sanitized_without_sensitive_cause(self):
        prepared = self.prepared(
            attachment_id="sanitized-a0",
            content=b"no secret leakage",
        )
        self.objects.fail_status_with = "secret C:/provider/credentials.json"

        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "classroom file backend failed",
        ) as raised:
            self.client1.upload(prepared)

        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("credentials", str(raised.exception).lower())
        self.assertNotIn("provider", str(raised.exception).lower())


if __name__ == "__main__":
    unittest.main()
