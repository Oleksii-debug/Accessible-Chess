from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.classroom_join_credentials import ClassroomJoinCredentialService
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
from acs.livekit_moderation_rpc_transport import (
    LIVEKIT_RTC_VERSION,
    MODERATION_RPC_METHOD,
)
from acs.livekit_moderation_service_runtime import LiveKitModerationServiceRuntime
from acs.sqlite_classroom_moderation_ledger import SqliteClassroomModerationLedger
from tests.test_livekit_classroom_moderation_admin import (
    FakeApi,
    FakeRoomService,
    FakeTrackSource,
    participant,
)
from tests.test_livekit_moderation_service_runtime import (
    FakeRoom,
    FakeRtc,
    SERVICE_ID,
    TOKEN,
)


ROOM = "room-1"
TEACHER = "teacher-1"
STUDENT = "student-1"
STUDENT_ACCOUNT = "account-student-1"
NOW = datetime(2026, 10, 2, 22, 0, 0, tzinfo=timezone.utc)


class CanonicalRoster:
    def participant_ids(self):
        return (TEACHER, STUDENT)

    def role_for(self, participant_id):
        if participant_id == TEACHER:
            return ClassroomRole.TEACHER
        if participant_id == STUDENT:
            return ClassroomRole.STUDENT
        raise KeyError(participant_id)

    def board_control_allowed(self, participant_id):
        return participant_id == TEACHER


class CanonicalResolver:
    def __init__(self):
        self.roster = CanonicalRoster()
        self.identity_calls = []

    def roster_for_room(self, room_id):
        if room_id != ROOM:
            raise KeyError(room_id)
        return self.roster

    def participant_for_caller(self, *, room_id, trusted_caller_identity):
        self.identity_calls.append((room_id, trusted_caller_identity))
        if room_id != ROOM:
            raise KeyError(room_id)
        if trusted_caller_identity == STUDENT_ACCOUNT:
            return STUDENT
        if trusted_caller_identity == "account-teacher-1":
            return TEACHER
        raise KeyError(trusted_caller_identity)


class RecordingJoinIssuer:
    def __init__(self):
        self.grants = []

    async def issue_join_token(self, *, grant, issued_at, expires_at):
        self.grants.append((grant, issued_at, expires_at))
        return "header.payload.signature"


def wire(operation_id="op-camera-lock"):
    return json.dumps(
        {
            "version": RPC_VERSION,
            "room_id": ROOM,
            "operations": [
                {
                    "operation_id": operation_id,
                    "actor_id": TEACHER,
                    "target_id": STUDENT,
                    "action": "publish_permission",
                    "source": "camera",
                    "value": False,
                }
            ],
        },
        separators=(",", ":"),
    )


def join_wire():
    return json.dumps(
        {
            "version": 1,
            "room_id": ROOM,
            "participant_id": STUDENT,
        },
        separators=(",", ":"),
    )


class ClassroomRealtimeModerationCompositionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.policy_path = root / "media-policy.sqlite3"
        self.ledger_path = root / "moderation-ledger.sqlite3"
        self.resolver = CanonicalResolver()

        FakeRoom.instances.clear()
        FakeRoom.next_name = ROOM
        FakeRoom.next_identity = SERVICE_ID
        FakeRoom.next_connect_error = None
        FakeRoom.next_disconnect_error = None

    def tearDown(self):
        self.temp.cleanup()

    def authority(self):
        return SqliteClassroomMediaPolicyAuthority(
            self.policy_path,
            roster_resolver=self.resolver,
            join_identity_resolver=self.resolver,
        )

    def service(self, *, authority, provider_room):
        admin = LiveKitClassroomModerationAdmin(
            room_service=provider_room,
            api_module=FakeApi,
            sdk_version=LIVEKIT_API_VERSION,
        )
        policy_provider = ClassroomMediaPolicyProviderAdmin(
            authority=authority,
            provider_admin=admin,
        )
        return ClassroomModerationRpcService(
            authorization=authority,
            provider_admin=policy_provider,
            ledger=SqliteClassroomModerationLedger(self.ledger_path),
        )

    async def test_realtime_rpc_commits_durable_policy_provider_and_next_join_grant(self):
        authority = self.authority()
        provider_room = FakeRoomService(
            participant(
                sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.CAMERA),
                can_publish=True,
                can_publish_data=True,
            )
        )
        moderation_service = self.service(
            authority=authority,
            provider_room=provider_room,
        )
        runtime = LiveKitModerationServiceRuntime(
            provider_url="wss://classroom.example.invalid",
            trusted_room_id=ROOM,
            moderation_participant_identity=SERVICE_ID,
            service=moderation_service,
            rtc_module=FakeRtc,
            sdk_version=LIVEKIT_RTC_VERSION,
        )

        await runtime.connect(service_token=TOKEN)
        self.assertTrue(runtime.ready)
        realtime_room = FakeRoom.instances[-1]
        handler = realtime_room.local_participant.handlers[MODERATION_RPC_METHOD]

        response = await handler(
            SimpleNamespace(
                caller_identity=TEACHER,
                payload=wire(),
            )
        )

        self.assertEqual(
            json.loads(response)["accepted_operation_ids"],
            ["op-camera-lock"],
        )
        self.assertEqual(len(provider_room.updates), 1)
        permission = provider_room.updates[0].permission
        self.assertEqual(
            list(permission.can_publish_sources),
            [FakeTrackSource.MICROPHONE],
        )
        self.assertTrue(permission.can_publish)
        self.assertTrue(permission.can_publish_data)

        ledger_state = SqliteClassroomModerationLedger(
            self.ledger_path
        ).operation_state(
            room_id=ROOM,
            operation_id="op-camera-lock",
        )
        self.assertIsNotNone(ledger_state)
        self.assertTrue(ledger_state.committed)

        reopened = self.authority()
        issuer = RecordingJoinIssuer()
        join_response = await ClassroomJoinCredentialService(
            authorization=reopened,
            token_issuer=issuer,
            ttl_seconds=60,
            now=lambda: NOW,
        ).issue(
            trusted_caller_identity=STUDENT_ACCOUNT,
            payload=join_wire(),
        )
        self.assertEqual(json.loads(join_response)["participant_id"], STUDENT)
        self.assertEqual(
            self.resolver.identity_calls[-1],
            (ROOM, STUDENT_ACCOUNT),
        )
        self.assertEqual(len(issuer.grants), 1)
        self.assertEqual(
            issuer.grants[0][0].publish_sources,
            (MediaSource.MICROPHONE,),
        )

        await runtime.aclose()
        self.assertTrue(runtime.closed)
        self.assertFalse(runtime.ready)
        self.assertNotIn(
            MODERATION_RPC_METHOD,
            realtime_room.local_participant.handlers,
        )
        self.assertFalse(realtime_room.connected)
        self.assertEqual(realtime_room.disconnect_calls, 1)


if __name__ == "__main__":
    unittest.main()
