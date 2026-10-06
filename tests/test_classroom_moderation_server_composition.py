from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from acs.classroom_moderation_rpc import (
    ClassroomModerationRpcError,
    ClassroomModerationRpcService,
    RPC_VERSION,
)
from acs.sqlite_classroom_moderation_ledger import SqliteClassroomModerationLedger
from acs.livekit_classroom_moderation_admin import (
    LIVEKIT_API_VERSION,
    LiveKitClassroomModerationAdmin,
)
from tests.test_livekit_classroom_moderation_admin import (
    FakeApi,
    FakeRoomService,
    FakeServerError,
    FakeServerErrorCode,
    FakeTrackSource,
    participant,
)


ROOM = "room-1"
CALLER = "teacher-1"


def wire(
    operation_id: str,
    *,
    action: str = "publish_permission",
    source: str | None = "camera",
    value: bool = False,
    target_id: str = "student-1",
) -> str:
    return json.dumps(
        {
            "version": RPC_VERSION,
            "room_id": ROOM,
            "operations": [
                {
                    "operation_id": operation_id,
                    "actor_id": CALLER,
                    "target_id": target_id,
                    "action": action,
                    "source": source,
                    "value": value,
                }
            ],
        },
        separators=(",", ":"),
    )


class RecordingAuthorization:
    def __init__(self) -> None:
        self.calls = []
        self.reject = False

    def authorize_moderation_batch(self, *, room_id, caller_identity, commands):
        self.calls.append((room_id, caller_identity, commands))
        if self.reject:
            raise RuntimeError("private classroom authorization detail")


class SlowRoomService(FakeRoomService):
    async def update_participant(self, request):
        await asyncio.sleep(0.05)
        return await super().update_participant(request)


class BlockingRoomService(FakeRoomService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_started = asyncio.Event()
        self.update_continue = asyncio.Event()

    async def update_participant(self, request):
        self.update_started.set()
        await self.update_continue.wait()
        return await super().update_participant(request)


class ClassroomModerationServerCompositionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "moderation.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def service(self, *, room, authorization=None, path=None):
        authorization = authorization or RecordingAuthorization()
        ledger = SqliteClassroomModerationLedger(path or self.path)
        admin = LiveKitClassroomModerationAdmin(
            room_service=room,
            api_module=FakeApi,
            sdk_version=LIVEKIT_API_VERSION,
        )
        service = ClassroomModerationRpcService(
            authorization=authorization,
            provider_admin=admin,
            ledger=ledger,
        )
        return service, authorization, ledger

    async def handle(self, service, payload):
        return await service.handle_rpc(
            trusted_room_id=ROOM,
            trusted_caller_identity=CALLER,
            payload=payload,
        )

    def test_workflow_binds_live_parent_and_current_source_owner_heads(self):
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "classroom-moderation-server-composition.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn(
            "LEDGER_OWNER_SHA: e7366ce87e56f4c2580f5212972f4b42dc4465f9",
            workflow,
        )
        self.assertIn(
            "ADMIN_OWNER_SHA: b0b15666127599aed88d007533e4d622042674bf",
            workflow,
        )
        self.assertIn('git fetch --no-tags origin "$EXPECTED_BASE_REF"', workflow)
        self.assertIn(
            'base="$(git rev-parse "refs/remotes/origin/$EXPECTED_BASE_REF")"',
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', workflow)
        self.assertIn('git diff --name-only "$base...HEAD"', workflow)
        self.assertNotIn('git diff --name-only "$EXPECTED_BASE_SHA" HEAD', workflow)

    async def test_publish_lock_flows_from_rpc_through_durable_commit_and_exact_replay(self):
        room = FakeRoomService(
            participant(
                sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.CAMERA),
                can_publish=True,
                can_publish_data=True,
            )
        )
        service, authorization, ledger = self.service(room=room)
        payload = wire("op-camera-lock", source="camera", value=False)

        first = await self.handle(service, payload)
        second = await self.handle(service, payload)

        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["accepted_operation_ids"], ["op-camera-lock"])
        self.assertEqual(len(authorization.calls), 1)
        self.assertEqual(len(room.updates), 1)
        permission = room.updates[0].permission
        self.assertEqual(
            list(permission.can_publish_sources),
            [FakeTrackSource.MICROPHONE],
        )
        self.assertTrue(permission.can_publish)
        self.assertTrue(permission.can_publish_data)
        state = ledger.operation_state(
            room_id=ROOM,
            operation_id="op-camera-lock",
        )
        self.assertIsNotNone(state)
        self.assertTrue(state.committed)

    async def test_process_restart_replay_is_acked_without_authorization_or_provider_effect(self):
        first_room = FakeRoomService(participant())
        first, first_authorization, ledger = self.service(room=first_room)
        payload = wire("op-durable", source="microphone", value=False)
        await self.handle(first, payload)

        self.assertEqual(len(first_room.updates), 1)
        self.assertTrue(
            ledger.operation_state(room_id=ROOM, operation_id="op-durable").committed
        )

        second_room = FakeRoomService(participant())
        second_authorization = RecordingAuthorization()
        second, _, reopened = self.service(
            room=second_room,
            authorization=second_authorization,
        )
        response = await self.handle(second, payload)

        self.assertEqual(json.loads(response)["status"], "ok")
        self.assertEqual(second_authorization.calls, [])
        self.assertEqual(second_room.updates, [])
        self.assertTrue(
            reopened.operation_state(room_id=ROOM, operation_id="op-durable").committed
        )
        self.assertEqual(len(first_authorization.calls), 1)

    async def test_conflicting_semantics_after_restart_fail_before_authorization_and_provider(self):
        first_room = FakeRoomService(participant())
        first, _, _ = self.service(room=first_room)
        await self.handle(
            first,
            wire("op-conflict", source="camera", value=False),
        )

        second_room = FakeRoomService(participant())
        authorization = RecordingAuthorization()
        second, _, _ = self.service(
            room=second_room,
            authorization=authorization,
        )
        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "reused with different semantics",
        ):
            await self.handle(
                second,
                wire("op-conflict", source="camera", value=True),
            )

        self.assertEqual(authorization.calls, [])
        self.assertEqual(second_room.lookups, [])
        self.assertEqual(second_room.updates, [])

    async def test_provider_failure_leaves_pending_reservation_then_exact_retry_commits(self):
        room = FakeRoomService(participant())
        room.update_error = RuntimeError("private provider failure detail")
        service, authorization, ledger = self.service(room=room)
        payload = wire("op-pending", source="camera", value=False)

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "^moderation provider operation failed$",
        ) as first_error:
            await self.handle(service, payload)

        self.assertIsNone(first_error.exception.__cause__)
        pending = ledger.operation_state(room_id=ROOM, operation_id="op-pending")
        self.assertIsNotNone(pending)
        self.assertFalse(pending.committed)
        self.assertEqual(len(room.updates), 1)

        room.update_error = None
        response = await self.handle(service, payload)

        self.assertEqual(json.loads(response)["status"], "ok")
        self.assertEqual(len(authorization.calls), 2)
        self.assertEqual(len(room.updates), 2)
        committed = ledger.operation_state(room_id=ROOM, operation_id="op-pending")
        self.assertTrue(committed.committed)

    async def test_soft_mute_mutes_only_microphone_then_replay_has_no_second_effect(self):
        room = FakeRoomService(
            participant(
                tracks=(
                    SimpleNamespace(
                        sid="TR_mic",
                        source=FakeTrackSource.MICROPHONE,
                        muted=False,
                    ),
                    SimpleNamespace(
                        sid="TR_camera",
                        source=FakeTrackSource.CAMERA,
                        muted=False,
                    ),
                )
            )
        )
        service, _, ledger = self.service(room=room)
        payload = wire(
            "op-soft-mute",
            action="soft_mute",
            source="microphone",
            value=True,
        )

        await self.handle(service, payload)
        await self.handle(service, payload)

        self.assertEqual(len(room.mutes), 1)
        self.assertEqual(room.mutes[0].track_sid, "TR_mic")
        self.assertTrue(room.mutes[0].muted)
        self.assertTrue(
            ledger.operation_state(room_id=ROOM, operation_id="op-soft-mute").committed
        )

    async def test_remove_not_found_is_idempotent_success_and_is_committed(self):
        room = FakeRoomService(participant())
        room.remove_error = FakeServerError(
            FakeServerErrorCode.NOT_FOUND,
            "provider says participant already gone",
        )
        service, _, ledger = self.service(room=room)
        payload = wire(
            "op-remove",
            action="remove",
            source=None,
            value=True,
        )

        response = await self.handle(service, payload)
        replay = await self.handle(service, payload)

        self.assertEqual(response, replay)
        self.assertEqual(len(room.removals), 1)
        self.assertTrue(
            ledger.operation_state(room_id=ROOM, operation_id="op-remove").committed
        )

    async def test_two_service_instances_exact_duplicate_has_one_reservation_owner(self):
        first_room = BlockingRoomService(participant())
        second_room = FakeRoomService(participant())
        first_auth = RecordingAuthorization()
        second_auth = RecordingAuthorization()
        first, _, first_ledger = self.service(
            room=first_room,
            authorization=first_auth,
        )
        second, _, second_ledger = self.service(
            room=second_room,
            authorization=second_auth,
        )
        payload = wire("op-exact-race", source="camera", value=False)

        first_task = asyncio.create_task(self.handle(first, payload))
        await first_room.update_started.wait()

        pending = first_ledger.operation_state(
            room_id=ROOM,
            operation_id="op-exact-race",
        )
        self.assertIsNotNone(pending)
        self.assertFalse(pending.committed)
        self.assertIsNotNone(pending.reservation_owner)

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "pending in another service participant",
        ):
            await self.handle(second, payload)

        self.assertEqual(second_auth.calls, [])
        self.assertEqual(second_room.lookups, [])
        self.assertEqual(second_room.updates, [])
        self.assertEqual(
            second_ledger.operation_state(
                room_id=ROOM,
                operation_id="op-exact-race",
            ),
            pending,
        )

        first_room.update_continue.set()
        response = await first_task

        self.assertEqual(
            json.loads(response)["accepted_operation_ids"],
            ["op-exact-race"],
        )
        self.assertEqual(len(first_auth.calls), 1)
        self.assertEqual(len(first_room.updates), 1)
        self.assertEqual(second_room.updates, [])
        committed = first_ledger.operation_state(
            room_id=ROOM,
            operation_id="op-exact-race",
        )
        self.assertIsNotNone(committed)
        self.assertTrue(committed.committed)
        self.assertIsNone(committed.reservation_owner)

    async def test_two_service_instances_conflicting_race_has_exactly_one_provider_effect(self):
        slow_room = SlowRoomService(participant())
        other_room = FakeRoomService(participant())
        first_auth = RecordingAuthorization()
        second_auth = RecordingAuthorization()
        first, _, first_ledger = self.service(
            room=slow_room,
            authorization=first_auth,
        )
        second, _, second_ledger = self.service(
            room=other_room,
            authorization=second_auth,
        )

        first_result, second_result = await asyncio.gather(
            self.handle(
                first,
                wire("op-race", source="camera", value=False),
            ),
            self.handle(
                second,
                wire("op-race", source="camera", value=True),
            ),
            return_exceptions=True,
        )

        results = (first_result, second_result)
        self.assertEqual(sum(isinstance(item, str) for item in results), 1)
        errors = [item for item in results if isinstance(item, Exception)]
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ClassroomModerationRpcError)
        self.assertIn("reused with different semantics", str(errors[0]))
        self.assertEqual(len(slow_room.updates) + len(other_room.updates), 1)
        state = first_ledger.operation_state(room_id=ROOM, operation_id="op-race")
        self.assertIsNotNone(state)
        self.assertTrue(state.committed)
        self.assertEqual(
            second_ledger.operation_state(room_id=ROOM, operation_id="op-race"),
            state,
        )

    async def test_authorization_rejection_occurs_before_reservation_and_provider_effect(self):
        room = FakeRoomService(participant())
        authorization = RecordingAuthorization()
        authorization.reject = True
        service, _, ledger = self.service(
            room=room,
            authorization=authorization,
        )

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "^moderation request is not authorized$",
        ) as raised:
            await self.handle(
                service,
                wire("op-denied", source="microphone", value=False),
            )

        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(
            ledger.operation_state(room_id=ROOM, operation_id="op-denied")
        )
        self.assertEqual(room.lookups, [])
        self.assertEqual(room.updates, [])


if __name__ == "__main__":
    unittest.main()
