from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from acs.classroom_media_policy_authority import (
    ClassroomMediaPolicyProviderAdmin,
    SqliteClassroomMediaPolicyAuthority,
)
from acs.classroom_moderation_rpc import ClassroomModerationRpcService, RPC_VERSION
from acs.classroom_realtime_media import ClassroomRole, MediaSource
from acs.livekit_classroom_moderation_admin import (
    LIVEKIT_API_VERSION,
    LiveKitClassroomModerationAdmin,
)
from acs.sqlite_classroom_moderation_ledger import SqliteClassroomModerationLedger
from tests.test_livekit_classroom_moderation_admin import (
    FakeApi,
    FakeRoomService,
    FakeTrackSource,
    participant,
)


ROOM = "room-1"
CALLER = "teacher-1"
TARGET = "student-1"


class _Roster:
    def __init__(self) -> None:
        self._roles = {
            CALLER: ClassroomRole.TEACHER,
            TARGET: ClassroomRole.STUDENT,
        }

    def participant_ids(self):
        return tuple(self._roles)

    def role_for(self, participant_id):
        return self._roles[participant_id]

    def board_control_allowed(self, participant_id):
        return False


class _RosterResolver:
    def __init__(self) -> None:
        self._roster = _Roster()

    def roster_for_room(self, room_id):
        if room_id != ROOM:
            raise KeyError(room_id)
        return self._roster


class _JoinIdentityResolver:
    def participant_for_caller(self, *, room_id, trusted_caller_identity):
        if room_id != ROOM:
            raise KeyError(room_id)
        return trusted_caller_identity


class _SlowSharedRoomService(FakeRoomService):
    """Expose the stale read/modify/write race if provider effects overlap."""

    async def update_participant(self, request):
        await asyncio.sleep(0.05)
        return await super().update_participant(request)


def _wire(operation_id: str, source: str) -> str:
    return json.dumps(
        {
            "version": RPC_VERSION,
            "room_id": ROOM,
            "operations": [
                {
                    "operation_id": operation_id,
                    "actor_id": CALLER,
                    "target_id": TARGET,
                    "action": "publish_permission",
                    "source": source,
                    "value": False,
                }
            ],
        },
        separators=(",", ":"),
    )


class ClassroomDistinctModerationCompositionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.policy_path = Path(self.temp.name) / "media-policy.sqlite3"
        self.ledger_path = Path(self.temp.name) / "moderation-ledger.sqlite3"
        self.roster_resolver = _RosterResolver()
        self.join_identity_resolver = _JoinIdentityResolver()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _service(self, room):
        authority = SqliteClassroomMediaPolicyAuthority(
            self.policy_path,
            roster_resolver=self.roster_resolver,
            join_identity_resolver=self.join_identity_resolver,
        )
        livekit = LiveKitClassroomModerationAdmin(
            room_service=room,
            api_module=FakeApi,
            sdk_version=LIVEKIT_API_VERSION,
        )
        provider = ClassroomMediaPolicyProviderAdmin(
            authority=authority,
            provider_admin=livekit,
        )
        ledger = SqliteClassroomModerationLedger(self.ledger_path)
        service = ClassroomModerationRpcService(
            authorization=authority,
            provider_admin=provider,
            ledger=ledger,
        )
        return service, authority, ledger

    async def _handle(self, service, payload):
        return await service.handle_rpc(
            trusted_room_id=ROOM,
            trusted_caller_identity=CALLER,
            payload=payload,
        )

    async def test_distinct_operations_two_services_two_ledgers_preserve_both_revokes(self):
        room = _SlowSharedRoomService(
            participant(
                sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.CAMERA),
                can_publish=True,
                can_publish_data=True,
            )
        )
        first, first_authority, first_ledger = self._service(room)
        second, second_authority, second_ledger = self._service(room)

        camera_payload = _wire("op-lock-camera-distinct", "camera")
        microphone_payload = _wire("op-lock-microphone-distinct", "microphone")

        camera_result, microphone_result = await asyncio.gather(
            self._handle(first, camera_payload),
            self._handle(second, microphone_payload),
        )

        self.assertEqual(
            json.loads(camera_result)["accepted_operation_ids"],
            ["op-lock-camera-distinct"],
        )
        self.assertEqual(
            json.loads(microphone_result)["accepted_operation_ids"],
            ["op-lock-microphone-distinct"],
        )
        self.assertEqual(len(room.lookups), 2)
        self.assertEqual(len(room.updates), 2)
        self.assertEqual(
            set(room.participant.permission.can_publish_sources),
            set(),
        )
        self.assertTrue(room.participant.permission.can_publish)
        self.assertTrue(room.participant.permission.can_publish_data)

        for ledger in (first_ledger, second_ledger):
            camera_state = ledger.operation_state(
                room_id=ROOM,
                operation_id="op-lock-camera-distinct",
            )
            microphone_state = ledger.operation_state(
                room_id=ROOM,
                operation_id="op-lock-microphone-distinct",
            )
            self.assertIsNotNone(camera_state)
            self.assertIsNotNone(microphone_state)
            self.assertTrue(camera_state.committed)
            self.assertTrue(microphone_state.committed)
            self.assertIsNone(camera_state.reservation_owner)
            self.assertIsNone(microphone_state.reservation_owner)

        for authority in (first_authority, second_authority):
            policy = authority.participant_policy(
                room_id=ROOM,
                participant_id=TARGET,
            )
            self.assertFalse(policy.source(MediaSource.CAMERA).publish_allowed)
            self.assertFalse(policy.source(MediaSource.MICROPHONE).publish_allowed)


if __name__ == "__main__":
    unittest.main()
