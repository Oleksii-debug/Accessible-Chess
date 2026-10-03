from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import (
    AttachmentHistoryPage,
    FileTransferProgress,
    MAX_SYNC_ATTACHMENTS,
    PreparedFile,
    _canonical_object_key,
)
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    AttachmentStateUpdate,
)
from acs.classroom_domain import MAX_WIRE_INTEGER
from acs.classroom_file_rpc import (
    MAX_RPC_UPLOAD_BYTES,
    RPC_VERSION,
    ClassroomFileRpcClient,
    ClassroomFileRpcError,
    ClassroomFileRpcService,
)
from acs.classroom_file_server import (
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)


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
    def scan(self, **kwargs):
        return "clean"


class MemoryObjectStore:
    def __init__(self):
        self.objects = {}
        self.token_calls = []
        self.delete_calls = []

    def stored_sha256(self, *, object_key):
        content = self.objects.get(object_key)
        if content is None:
            return None
        return hashlib.sha256(content).hexdigest()

    def put(self, *, object_key, content, expected_sha256):
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise RuntimeError("hash mismatch")
        existing = self.objects.get(object_key)
        if existing is not None and existing != content:
            raise RuntimeError("object collision")
        self.objects[object_key] = bytes(content)

    def issue_read_token(self, *, object_key, participant_id, ttl_seconds):
        if object_key not in self.objects:
            raise RuntimeError("missing object")
        self.token_calls.append((object_key, participant_id, ttl_seconds))
        return f"read-{participant_id}-{ttl_seconds}"

    def delete(self, *, object_key):
        self.delete_calls.append(object_key)
        self.objects.pop(object_key, None)


class FakeBackend:
    def __init__(self):
        self.upload_calls = []
        self.cancel_calls = []
        self.history_calls = []
        self.state_calls = []
        self.token_calls = []
        self.delete_calls = []
        self.fail = False
        self.upload_override = None
        self.history_override = None
        self.state_override = None
        self.token = "read-student-1-300"
        self._stored = []

    def upload(self, *, trusted_caller_identity, metadata, content):
        self.upload_calls.append(
            (trusted_caller_identity, metadata, bytes(content))
        )
        if self.fail:
            raise RuntimeError("backend bearer supersecret")
        if self.upload_override is not None:
            return self.upload_override
        existing = next(
            (
                item
                for item in self._stored
                if item.attachment_id == metadata.attachment_id
            ),
            None,
        )
        if existing is not None:
            return existing
        result = replace(
            metadata,
            sequence_no=len(self._stored),
            transfer_state="stored",
            scan_state="clean",
        )
        self._stored.append(result)
        return result

    def cancel(
        self,
        *,
        trusted_caller_identity,
        attachment_id,
        expected_room_id=None,
    ):
        self.cancel_calls.append(
            (trusted_caller_identity, attachment_id, expected_room_id)
        )
        if self.fail:
            raise RuntimeError("backend cancellation secret")

    def history_after(
        self,
        *,
        trusted_caller_identity,
        room_id,
        after_sequence,
        limit,
    ):
        self.history_calls.append(
            (trusted_caller_identity, room_id, after_sequence, limit)
        )
        if self.fail:
            raise RuntimeError("backend history secret")
        if self.history_override is not None:
            return self.history_override
        rows = tuple(
            item
            for item in self._stored
            if item.room_id == room_id
            and (after_sequence is None or item.sequence_no > after_sequence)
        )[:limit]
        return AttachmentHistoryPage(rows, None)

    def state_updates_after(
        self,
        *,
        trusted_caller_identity,
        room_id,
        after_revision,
        limit,
    ):
        self.state_calls.append(
            (trusted_caller_identity, room_id, after_revision, limit)
        )
        if self.fail:
            raise RuntimeError("backend state secret")
        if self.state_override is not None:
            return self.state_override
        return ()

    def issue_read_token(
        self,
        *,
        trusted_caller_identity,
        object_key,
        ttl_seconds,
        expected_room_id=None,
    ):
        self.token_calls.append(
            (
                trusted_caller_identity,
                object_key,
                ttl_seconds,
                expected_room_id,
            )
        )
        if self.fail:
            raise RuntimeError("storage signing key secret")
        return self.token

    def delete_object(
        self,
        *,
        trusted_caller_identity,
        object_key,
        expected_room_id=None,
    ):
        self.delete_calls.append(
            (trusted_caller_identity, object_key, expected_room_id)
        )
        if self.fail:
            raise RuntimeError("storage deletion secret")


class BoundCall:
    def __init__(self, service, *, room_id, participant_id):
        self.service = service
        self.room_id = room_id
        self.participant_id = participant_id
        self.calls = []
        self.fail = False
        self.progress_script = None

    def call(self, request, *, on_upload_progress=None):
        self.calls.append(dict(request))
        if self.fail:
            raise RuntimeError("transport bearer supersecret")
        content = request.get("content")
        if type(content) is bytes and on_upload_progress is not None:
            samples = (
                (0, len(content) // 2, len(content))
                if self.progress_script is None
                else tuple(self.progress_script)
            )
            for transferred in samples:
                on_upload_progress(transferred)
        return self.service.handle(
            dict(request),
            authenticated_room_id=self.room_id,
            authenticated_participant_id=self.participant_id,
        )


class StaticCall:
    def __init__(self, response):
        self.response = response

    def call(self, request, *, on_upload_progress=None):
        content = request.get("content")
        if type(content) is bytes and on_upload_progress is not None:
            on_upload_progress(len(content))
        return self.response


class ClassroomFileRpcTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.backend = FakeBackend()
        self.service = ClassroomFileRpcService(backend=self.backend)
        self.call = BoundCall(
            self.service,
            room_id="room-1",
            participant_id="student-1",
        )
        self.client = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=self.call,
        )

    def tearDown(self):
        self.temp.cleanup()

    def prepared(
        self,
        *,
        attachment_id="att-1",
        room_id="room-1",
        sender_id="student-1",
        content=b"opaque\x00bytes\xff",
        sequence_no=0,
        transfer_state="pending",
        scan_state="pending",
        filename="sample.bin",
    ):
        path = self.root / filename
        path.write_bytes(content)
        return PreparedFile(
            path,
            AttachmentMetadata(
                attachment_id=attachment_id,
                room_id=room_id,
                sender_id=sender_id,
                sequence_no=sequence_no,
                display_name=filename,
                mime_type="application/octet-stream",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                object_key=_canonical_object_key(room_id, attachment_id),
                transfer_state=transfer_state,
                retention="session",
                scan_state=scan_state,
            ),
        )

    @staticmethod
    def wire(metadata):
        return {
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
        }

    @staticmethod
    def state_wire(update):
        return {
            "room_id": update.room_id,
            "attachment_id": update.attachment_id,
            "revision": update.revision,
            "transfer_state": update.transfer_state,
            "scan_state": update.scan_state,
        }

    def test_real_server_round_trip_restart_token_and_tombstone(self):
        database = self.root / "file-server.sqlite3"
        auth = AllowMembers({("student-1", "room-1")})
        objects = MemoryObjectStore()
        server = ClassroomFileServerService(
            store=ClassroomFileServerSQLiteStore(str(database)),
            authorization=auth,
            scanner=CleanScanner(),
            object_store=objects,
        )
        endpoint = ClassroomFileRpcService(backend=server)
        client = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=BoundCall(
                endpoint,
                room_id="room-1",
                participant_id="student-1",
            ),
        )
        prepared = self.prepared(content=b"\x00\xffarbitrary\nbytes")
        stored = client.upload(prepared)
        self.assertEqual(stored.sequence_no, 0)
        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(stored.scan_state, "clean")
        self.assertEqual(
            objects.objects[stored.object_key],
            b"\x00\xffarbitrary\nbytes",
        )
        self.assertEqual(
            client.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            ).attachments,
            (stored,),
        )
        self.assertEqual(
            client.issue_read_token(
                object_key=stored.object_key,
                participant_id="student-1",
                ttl_seconds=300,
            ),
            "read-student-1-300",
        )

        restarted_server = ClassroomFileServerService(
            store=ClassroomFileServerSQLiteStore(str(database)),
            authorization=auth,
            scanner=CleanScanner(),
            object_store=objects,
        )
        restarted = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=BoundCall(
                ClassroomFileRpcService(backend=restarted_server),
                room_id="room-1",
                participant_id="student-1",
            ),
        )
        self.assertEqual(
            restarted.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            ).attachments,
            (stored,),
        )
        restarted.cancel(attachment_id=stored.attachment_id)
        self.assertNotIn(stored.object_key, objects.objects)
        tombstone_page = restarted.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=10,
        )
        self.assertEqual(tombstone_page.snapshot_state_revision, 0)
        tombstone = tombstone_page.attachments[0]
        self.assertEqual(tombstone.transfer_state, "deleted")
        updates = restarted.state_updates_after(
            room_id="room-1",
            after_revision=None,
            limit=10,
        )
        self.assertEqual(
            updates,
            (
                AttachmentStateUpdate(
                    room_id="room-1",
                    attachment_id=stored.attachment_id,
                    revision=0,
                    transfer_state="deleted",
                    scan_state="clean",
                ),
            ),
        )
        restarted.delete(object_key=stored.object_key)

    def test_authenticated_room_blocks_cross_room_cancel_for_shared_member(self):
        database = self.root / "rooms.sqlite3"
        auth = AllowMembers(
            {
                ("student-1", "room-1"),
                ("student-1", "room-2"),
            }
        )
        objects = MemoryObjectStore()
        server = ClassroomFileServerService(
            store=ClassroomFileServerSQLiteStore(str(database)),
            authorization=auth,
            scanner=CleanScanner(),
            object_store=objects,
        )
        endpoint = ClassroomFileRpcService(backend=server)
        room2 = ClassroomFileRpcClient(
            room_id="room-2",
            participant_id="student-1",
            transport=BoundCall(
                endpoint,
                room_id="room-2",
                participant_id="student-1",
            ),
        )
        stored = room2.upload(
            self.prepared(
                attachment_id="att-room2",
                room_id="room-2",
                content=b"room two",
            )
        )
        room1 = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=BoundCall(
                endpoint,
                room_id="room-1",
                participant_id="student-1",
            ),
        )
        with self.assertRaises(ClassroomFileRpcError):
            room1.cancel(attachment_id=stored.attachment_id)
        self.assertIn(stored.object_key, objects.objects)
        self.assertEqual(
            server.history_after(
                trusted_caller_identity="student-1",
                room_id="room-2",
                after_sequence=None,
                limit=10,
            ).attachments[0].transfer_state,
            "stored",
        )

    def test_upload_is_binary_exact_idempotent_and_reports_transport_progress(self):
        prepared = self.prepared(content=b"\x00\x01\xfe\xffbinary")
        total = prepared.metadata.size_bytes
        midpoint = total // 2
        self.call.progress_script = (0, midpoint, midpoint, total)
        samples = []

        first = self.client.upload(prepared, on_progress=samples.append)
        second = self.client.retry(prepared, on_progress=samples.append)

        self.assertEqual(first, second)
        expected = [
            FileTransferProgress("att-1", 0, total),
            FileTransferProgress("att-1", midpoint, total),
            FileTransferProgress("att-1", total, total),
        ]
        self.assertEqual(samples, expected + expected)
        self.assertTrue(all(not sample.complete for sample in samples))
        self.assertEqual(len(self.backend.upload_calls), 2)
        self.assertEqual(
            self.backend.upload_calls[0][2],
            prepared.local_path.read_bytes(),
        )
        request = self.call.calls[0]
        self.assertIs(type(request["content"]), bytes)
        self.assertNotIn("local_path", request)
        self.assertNotIn(str(prepared.local_path), repr(request["metadata"]))

    def test_transport_progress_rejects_invalid_or_backward_samples_before_backend(self):
        cases = (
            ("negative", (-1,)),
            ("boolean", (True,)),
            ("overflow", (999,)),
            ("backward", (0, 5, 4)),
        )
        for index, (label, script) in enumerate(cases):
            with self.subTest(label=label):
                self.call.progress_script = script
                before = len(self.backend.upload_calls)
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.upload(
                        self.prepared(
                            attachment_id=f"bad-progress-{index}",
                            content=b"12345678",
                        )
                    )
                self.assertEqual(len(self.backend.upload_calls), before)

    def test_missing_final_transport_progress_is_ambiguous_and_exact_retry_converges(self):
        prepared = self.prepared(
            attachment_id="ambiguous-progress",
            content=b"exactly-once-progress",
        )
        self.call.progress_script = (0, 2)

        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "omitted final upload progress",
        ):
            self.client.upload(prepared)

        self.assertEqual(len(self.backend.upload_calls), 1)
        self.assertEqual(len(self.backend._stored), 1)

        self.call.progress_script = (0, prepared.metadata.size_bytes)
        replayed = self.client.retry(prepared)
        self.assertEqual(replayed, self.backend._stored[0])
        self.assertEqual(len(self.backend._stored), 1)

    def test_progress_consumer_failure_is_presentation_only(self):
        prepared = self.prepared(
            attachment_id="broken-progress-consumer",
            content=b"observer-only",
        )

        def broken(_sample):
            raise RuntimeError("presentation callback failed")

        stored = self.client.upload(prepared, on_progress=broken)

        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(len(self.backend.upload_calls), 1)

    def test_client_revalidates_changed_file_before_transport(self):
        prepared = self.prepared(content=b"before")
        prepared.local_path.write_bytes(b"after!")
        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "changed before RPC upload",
        ):
            self.client.upload(prepared)
        self.assertEqual(self.call.calls, [])

    def test_client_rejects_cross_room_sender_and_namespace_before_transport(self):
        for prepared in (
            self.prepared(attachment_id="room-x", room_id="room-2"),
            self.prepared(attachment_id="sender-x", sender_id="student-2"),
        ):
            with self.subTest(attachment=prepared.metadata.attachment_id):
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.upload(prepared)
        valid = self.prepared(attachment_id="key-x")
        forged = PreparedFile(
            valid.local_path,
            replace(
                valid.metadata,
                object_key=_canonical_object_key("room-2", "key-x"),
            ),
        )
        with self.assertRaises(ClassroomFileRpcError):
            self.client.upload(forged)
        self.assertEqual(self.call.calls, [])

    def test_client_upload_limit_fails_before_transport(self):
        tiny = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=self.call,
            max_upload_bytes=3,
        )
        with self.assertRaisesRegex(ClassroomFileRpcError, "upload limit"):
            tiny.upload(self.prepared(content=b"four"))
        self.assertEqual(self.call.calls, [])

    def test_service_rejects_nonbytes_size_hash_and_oversize_before_backend(self):
        prepared = self.prepared(content=b"abcdef")
        base = {
            "v": RPC_VERSION,
            "op": "upload",
            "room_id": "room-1",
            "participant_id": "student-1",
            "metadata": self.wire(prepared.metadata),
            "content": b"abcdef",
        }
        cases = []
        bad_type = dict(base)
        bad_type["content"] = bytearray(b"abcdef")
        cases.append(bad_type)
        bad_size = dict(base)
        bad_size["content"] = b"abcde"
        cases.append(bad_size)
        bad_hash = dict(base)
        bad_hash["content"] = b"ABCDEF"
        cases.append(bad_hash)
        for request in cases:
            with self.subTest(content=request["content"]):
                with self.assertRaises(ClassroomFileRpcError):
                    self.service.handle(
                        request,
                        authenticated_room_id="room-1",
                        authenticated_participant_id="student-1",
                    )
        oversized = dict(base)
        oversized_metadata = dict(base["metadata"])
        oversized_metadata["size_bytes"] = MAX_RPC_UPLOAD_BYTES + 1
        oversized_metadata["sha256"] = hashlib.sha256(b"").hexdigest()
        oversized["metadata"] = oversized_metadata
        oversized["content"] = b""
        with self.assertRaisesRegex(ClassroomFileRpcError, "upload limit"):
            self.service.handle(
                oversized,
                authenticated_room_id="room-1",
                authenticated_participant_id="student-1",
            )
        self.assertEqual(self.backend.upload_calls, [])

    def test_service_binds_payload_identity_to_authenticated_transport(self):
        prepared = self.prepared()
        request = {
            "v": RPC_VERSION,
            "op": "upload",
            "room_id": "room-1",
            "participant_id": "student-1",
            "metadata": self.wire(prepared.metadata),
            "content": prepared.local_path.read_bytes(),
        }
        for authenticated_room, authenticated_participant in (
            ("room-2", "student-1"),
            ("room-1", "student-2"),
        ):
            with self.subTest(
                room=authenticated_room,
                participant=authenticated_participant,
            ):
                with self.assertRaises(ClassroomFileRpcError):
                    self.service.handle(
                        request,
                        authenticated_room_id=authenticated_room,
                        authenticated_participant_id=authenticated_participant,
                    )
        self.assertEqual(self.backend.upload_calls, [])

    def test_upload_rejects_mutated_identity_nonterminal_and_unclean_stored(self):
        prepared = self.prepared()
        mutations = (
            replace(
                prepared.metadata,
                room_id="room-2",
                transfer_state="stored",
                scan_state="clean",
            ),
            replace(
                prepared.metadata,
                transfer_state="uploading",
            ),
            replace(
                prepared.metadata,
                transfer_state="stored",
                scan_state="pending",
            ),
        )
        for result in mutations:
            with self.subTest(result=result):
                self.backend.upload_override = result
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.upload(prepared)

    def test_failed_upload_result_must_keep_provisional_sequence(self):
        prepared = self.prepared(sequence_no=7)
        self.backend.upload_override = replace(
            prepared.metadata,
            sequence_no=8,
            transfer_state="failed",
            scan_state="failed",
        )
        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "provisional sequence",
        ):
            self.client.upload(prepared)

    def test_history_round_trip_is_ordered_bounded_and_room_scoped(self):
        first = self.client.upload(self.prepared(attachment_id="att-1"))
        second = self.client.upload(self.prepared(attachment_id="att-2"))
        self.assertEqual(
            self.client.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=1,
            ).attachments,
            (first,),
        )
        self.assertEqual(
            self.client.history_after(
                room_id="room-1",
                after_sequence=0,
                limit=10,
            ).attachments,
            (second,),
        )
        with self.assertRaises(ClassroomFileRpcError):
            self.client.history_after(
                room_id="room-2",
                after_sequence=None,
                limit=10,
            )

    def test_history_rejects_gap_duplicate_cross_room_and_nonterminal(self):
        base = replace(
            self.prepared().metadata,
            transfer_state="stored",
            scan_state="clean",
        )
        cases = (
            (replace(base, sequence_no=1),),
            (
                replace(base, sequence_no=0),
                replace(base, sequence_no=1),
            ),
            (
                replace(
                    base,
                    attachment_id="other",
                    room_id="room-2",
                    object_key=_canonical_object_key("room-2", "other"),
                    sequence_no=0,
                ),
            ),
            (replace(base, sequence_no=0, transfer_state="failed"),),
        )
        for history in cases:
            with self.subTest(history=history):
                self.backend.history_override = AttachmentHistoryPage(history, None)
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.history_after(
                        room_id="room-1",
                        after_sequence=None,
                        limit=10,
                    )

    def test_history_preserves_and_validates_snapshot_state_watermark(self):
        stored = self.client.upload(self.prepared())
        self.backend.history_override = AttachmentHistoryPage((stored,), 7)
        page = self.client.history_after(
            room_id="room-1",
            after_sequence=None,
            limit=10,
        )
        self.assertEqual(page.attachments, (stored,))
        self.assertEqual(page.snapshot_state_revision, 7)

        response = {
            "v": RPC_VERSION,
            "ok": True,
            "attachments": [self.wire(stored)],
            "snapshot_state_revision": True,
        }
        malformed = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=StaticCall(response),
        )
        with self.assertRaises(ClassroomFileRpcError):
            malformed.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=10,
            )

    def test_state_round_trip_and_revision_validation(self):
        update = AttachmentStateUpdate(
            room_id="room-1",
            attachment_id="att-1",
            revision=0,
            transfer_state="deleted",
            scan_state="clean",
        )
        self.backend.state_override = (update,)
        self.assertEqual(
            self.client.state_updates_after(
                room_id="room-1",
                after_revision=None,
                limit=10,
            ),
            (update,),
        )
        for bad in (
            replace(update, revision=1),
            replace(update, room_id="room-2"),
        ):
            self.backend.state_override = (bad,)
            with self.assertRaises(ClassroomFileRpcError):
                self.client.state_updates_after(
                    room_id="room-1",
                    after_revision=None,
                    limit=10,
                )

    def test_cursor_and_limit_types_are_json_safe_and_bool_is_not_integer(self):
        for cursor in (True, -1, MAX_WIRE_INTEGER + 1):
            with self.subTest(cursor=cursor):
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.history_after(
                        room_id="room-1",
                        after_sequence=cursor,
                        limit=1,
                    )
        for limit in (True, 0, MAX_SYNC_ATTACHMENTS + 1):
            with self.subTest(limit=limit):
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.history_after(
                        room_id="room-1",
                        after_sequence=None,
                        limit=limit,
                    )

    def test_cancel_token_and_delete_forward_authenticated_room(self):
        key = _canonical_object_key("room-1", "att-1")
        self.client.cancel(attachment_id="att-1")
        token = self.client.issue_read_token(
            object_key=key,
            participant_id="student-1",
            ttl_seconds=300,
        )
        self.client.delete(object_key=key)
        self.assertEqual(
            self.backend.cancel_calls[-1],
            ("student-1", "att-1", "room-1"),
        )
        self.assertEqual(
            self.backend.token_calls[-1],
            ("student-1", key, 300, "room-1"),
        )
        self.assertEqual(
            self.backend.delete_calls[-1],
            ("student-1", key, "room-1"),
        )
        self.assertEqual(token, "read-student-1-300")

    def test_client_refuses_spoofed_download_identity_and_cross_room_key(self):
        own = _canonical_object_key("room-1", "att-1")
        other = _canonical_object_key("room-2", "att-1")
        with self.assertRaises(ClassroomFileRpcError):
            self.client.issue_read_token(
                object_key=own,
                participant_id="student-2",
                ttl_seconds=300,
            )
        for key in (other, "../room-1/att-1", "/absolute"):
            with self.subTest(key=key):
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.delete(object_key=key)
        self.assertEqual(self.call.calls, [])

    def test_read_token_ttl_and_token_shape_are_bounded(self):
        key = _canonical_object_key("room-1", "att-1")
        for ttl in (True, 0, 3601):
            with self.subTest(ttl=ttl):
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.issue_read_token(
                        object_key=key,
                        participant_id="student-1",
                        ttl_seconds=ttl,
                    )
        for token in ("", "has space", "line\nbreak"):
            self.backend.token = token
            with self.subTest(token=token):
                with self.assertRaises(ClassroomFileRpcError):
                    self.client.issue_read_token(
                        object_key=key,
                        participant_id="student-1",
                        ttl_seconds=300,
                    )

    def test_request_shapes_versions_and_unknown_operations_fail_closed(self):
        prepared = self.prepared()
        valid = {
            "v": RPC_VERSION,
            "op": "upload",
            "room_id": "room-1",
            "participant_id": "student-1",
            "metadata": self.wire(prepared.metadata),
            "content": prepared.local_path.read_bytes(),
        }
        cases = []
        extra = dict(valid)
        extra["secret"] = "unexpected"
        cases.append(extra)
        bad_version = dict(valid)
        bad_version["v"] = True
        cases.append(bad_version)
        unknown = {
            "v": RPC_VERSION,
            "op": "execute",
            "room_id": "room-1",
            "participant_id": "student-1",
        }
        cases.append(unknown)
        for request in cases:
            with self.subTest(request=request):
                with self.assertRaises(ClassroomFileRpcError):
                    self.service.handle(
                        request,
                        authenticated_room_id="room-1",
                        authenticated_participant_id="student-1",
                    )
        self.assertEqual(self.backend.upload_calls, [])

    def test_backend_and_transport_secret_failures_are_sanitized(self):
        prepared = self.prepared()
        self.backend.fail = True
        with self.assertRaises(ClassroomFileRpcError) as caught:
            self.client.upload(prepared)
        self.assertNotIn("supersecret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

        self.backend.fail = False
        self.call.fail = True
        with self.assertRaises(ClassroomFileRpcError) as caught:
            self.client.upload(prepared)
        self.assertEqual(
            str(caught.exception),
            "classroom file service unavailable",
        )
        self.assertIsNone(caught.exception.__cause__)

    def test_client_rejects_malformed_closed_or_identity_mutating_response(self):
        prepared = self.prepared()
        good = replace(
            prepared.metadata,
            transfer_state="stored",
            scan_state="clean",
        )
        cases = (
            None,
            {"v": RPC_VERSION, "ok": True, "attachment": self.wire(good), "x": 1},
            {"v": True, "ok": True, "attachment": self.wire(good)},
            {
                "v": RPC_VERSION,
                "ok": True,
                "attachment": self.wire(
                    replace(good, display_name="mutated.bin")
                ),
            },
        )
        for response in cases:
            client = ClassroomFileRpcClient(
                room_id="room-1",
                participant_id="student-1",
                transport=StaticCall(response),
            )
            with self.subTest(response=response):
                with self.assertRaises(ClassroomFileRpcError):
                    client.upload(prepared)

    def test_response_pages_cannot_exceed_requested_bound(self):
        stored = replace(
            self.prepared().metadata,
            transfer_state="stored",
            scan_state="clean",
        )
        history = {
            "v": RPC_VERSION,
            "ok": True,
            "attachments": [
                self.wire(stored),
                self.wire(
                    replace(
                        stored,
                        attachment_id="att-2",
                        sequence_no=1,
                        object_key=_canonical_object_key("room-1", "att-2"),
                    )
                ),
            ],
            "snapshot_state_revision": None,
        }
        client = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=StaticCall(history),
        )
        with self.assertRaises(ClassroomFileRpcError):
            client.history_after(
                room_id="room-1",
                after_sequence=None,
                limit=1,
            )

    def test_constructor_limits_require_positive_exact_integers(self):
        for value in (True, 0, -1, MAX_WIRE_INTEGER + 1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ClassroomFileRpcClient(
                        room_id="room-1",
                        participant_id="student-1",
                        transport=self.call,
                        max_upload_bytes=value,
                    )
                with self.assertRaises(ValueError):
                    ClassroomFileRpcService(
                        backend=self.backend,
                        max_upload_bytes=value,
                    )


if __name__ == "__main__":
    unittest.main()
