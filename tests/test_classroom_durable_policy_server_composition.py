from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from acs.classroom_join_credentials import (
    ClassroomJoinCredentialError,
    ClassroomJoinCredentialService,
)
from acs.classroom_media_policy_authority import (
    ClassroomMediaPolicyProviderAdmin,
    SqliteClassroomMediaPolicyAuthority,
)
from acs.classroom_moderation_rpc import (
    ClassroomModerationRpcError,
    ClassroomModerationRpcService,
    RPC_VERSION,
)
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
TEACHER = "teacher-1"
STUDENT = "student-1"
NOW = datetime(2026, 10, 2, 22, 0, 0, tzinfo=timezone.utc)


class Roster:
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


class Resolver:
    def __init__(self):
        self.roster = Roster()
        self.calls = []

    def roster_for_room(self, room_id):
        self.calls.append(room_id)
        if room_id != ROOM:
            raise KeyError(room_id)
        return self.roster


class RecordingTokenIssuer:
    def __init__(self):
        self.grants = []

    async def issue_join_token(self, *, grant, issued_at, expires_at):
        self.grants.append((grant, issued_at, expires_at))
        return "header.payload.signature"


def moderation_wire(
    operation_id: str,
    *,
    action: str = "publish_permission",
    source: str | None = "camera",
    value: bool = False,
) -> str:
    return json.dumps(
        {
            "version": RPC_VERSION,
            "room_id": ROOM,
            "operations": [
                {
                    "operation_id": operation_id,
                    "actor_id": TEACHER,
                    "target_id": STUDENT,
                    "action": action,
                    "source": source,
                    "value": value,
                }
            ],
        },
        separators=(",", ":"),
    )


def join_wire() -> str:
    return json.dumps(
        {
            "version": 1,
            "room_id": ROOM,
            "participant_id": STUDENT,
        },
        separators=(",", ":"),
    )


class DurablePolicyServerCompositionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.policy_path = root / "media-policy.sqlite3"
        self.ledger_path = root / "moderation-ledger.sqlite3"
        self.resolver = Resolver()

    def tearDown(self):
        self.temp.cleanup()

    def authority(self):
        return SqliteClassroomMediaPolicyAuthority(
            self.policy_path,
            roster_resolver=self.resolver,
        )

    def moderation_service(self, *, authority, room):
        admin = LiveKitClassroomModerationAdmin(
            room_service=room,
            api_module=FakeApi,
            sdk_version=LIVEKIT_API_VERSION,
        )
        provider = ClassroomMediaPolicyProviderAdmin(
            authority=authority,
            provider_admin=admin,
        )
        return ClassroomModerationRpcService(
            authorization=authority,
            provider_admin=provider,
            ledger=SqliteClassroomModerationLedger(self.ledger_path),
        )

    def join_service(self, *, authority, issuer):
        return ClassroomJoinCredentialService(
            authorization=authority,
            token_issuer=issuer,
            ttl_seconds=60,
            now=lambda: NOW,
        )

    async def issue_join(self, *, authority):
        issuer = RecordingTokenIssuer()
        response = await self.join_service(
            authority=authority,
            issuer=issuer,
        ).issue(
            trusted_caller_identity=STUDENT,
            payload=join_wire(),
        )
        self.assertEqual(json.loads(response)["participant_id"], STUDENT)
        self.assertEqual(len(issuer.grants), 1)
        return issuer.grants[0][0]

    async def handle(self, service, wire):
        return await service.handle_rpc(
            trusted_room_id=ROOM,
            trusted_caller_identity=TEACHER,
            payload=wire,
        )

    async def test_hard_revoke_persists_through_restart_and_shapes_next_join_grant(self):
        authority = self.authority()
        initial = await self.issue_join(authority=authority)
        self.assertEqual(
            initial.publish_sources,
            (MediaSource.MICROPHONE, MediaSource.CAMERA),
        )

        room = FakeRoomService(
            participant(
                sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.CAMERA),
                can_publish=True,
            )
        )
        service = self.moderation_service(authority=authority, room=room)
        wire = moderation_wire("op-camera-revoke")

        first = await self.handle(service, wire)
        replay = await self.handle(service, wire)

        self.assertEqual(first, replay)
        self.assertEqual(len(room.updates), 1)
        self.assertEqual(
            list(room.updates[0].permission.can_publish_sources),
            [FakeTrackSource.MICROPHONE],
        )
        state = SqliteClassroomModerationLedger(self.ledger_path).operation_state(
            room_id=ROOM,
            operation_id="op-camera-revoke",
        )
        self.assertIsNotNone(state)
        self.assertTrue(state.committed)

        reopened = self.authority()
        grant = await self.issue_join(authority=reopened)
        self.assertEqual(grant.publish_sources, (MediaSource.MICROPHONE,))
        self.assertEqual(
            reopened.policy_revision(room_id=ROOM, participant_id=STUDENT),
            1,
        )

    async def test_block_survives_remove_failure_and_rejects_join_before_retry(self):
        authority = self.authority()
        room = FakeRoomService(participant())
        room.remove_error = RuntimeError("private provider remove failure")
        service = self.moderation_service(authority=authority, room=room)
        wire = moderation_wire(
            "op-block-student",
            action="remove",
            source=None,
            value=True,
        )

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "^moderation provider operation failed$",
        ):
            await self.handle(service, wire)

        pending = SqliteClassroomModerationLedger(self.ledger_path).operation_state(
            room_id=ROOM,
            operation_id="op-block-student",
        )
        self.assertIsNotNone(pending)
        self.assertFalse(pending.committed)

        reopened = self.authority()
        self.assertTrue(
            reopened.participant_policy(
                room_id=ROOM,
                participant_id=STUDENT,
            ).blocked
        )
        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join request is not authorized$",
        ):
            await self.join_service(
                authority=reopened,
                issuer=RecordingTokenIssuer(),
            ).issue(
                trusted_caller_identity=STUDENT,
                payload=join_wire(),
            )

        room.remove_error = None
        response = await self.handle(
            self.moderation_service(authority=reopened, room=room),
            wire,
        )
        self.assertEqual(json.loads(response)["status"], "ok")
        committed = SqliteClassroomModerationLedger(self.ledger_path).operation_state(
            room_id=ROOM,
            operation_id="op-block-student",
        )
        self.assertTrue(committed.committed)
        self.assertEqual(len(room.removals), 2)

        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join request is not authorized$",
        ):
            await self.join_service(
                authority=self.authority(),
                issuer=RecordingTokenIssuer(),
            ).issue(
                trusted_caller_identity=STUDENT,
                payload=join_wire(),
            )

    async def test_provider_failure_still_closes_reconnect_then_exact_retry_commits(self):
        authority = self.authority()
        room = FakeRoomService(
            participant(
                sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.CAMERA),
                can_publish=True,
            )
        )
        room.update_error = RuntimeError("private provider failure")
        service = self.moderation_service(authority=authority, room=room)
        wire = moderation_wire("op-failclosed-camera")

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "^moderation provider operation failed$",
        ) as caught:
            await self.handle(service, wire)
        self.assertIsNone(caught.exception.__cause__)

        pending = SqliteClassroomModerationLedger(self.ledger_path).operation_state(
            room_id=ROOM,
            operation_id="op-failclosed-camera",
        )
        self.assertIsNotNone(pending)
        self.assertFalse(pending.committed)

        reopened = self.authority()
        grant = await self.issue_join(authority=reopened)
        self.assertEqual(grant.publish_sources, (MediaSource.MICROPHONE,))
        self.assertEqual(
            reopened.policy_revision(room_id=ROOM, participant_id=STUDENT),
            1,
        )

        room.update_error = None
        response = await self.handle(
            self.moderation_service(authority=reopened, room=room),
            wire,
        )
        self.assertEqual(json.loads(response)["status"], "ok")
        committed = SqliteClassroomModerationLedger(self.ledger_path).operation_state(
            room_id=ROOM,
            operation_id="op-failclosed-camera",
        )
        self.assertTrue(committed.committed)
        self.assertEqual(len(room.updates), 2)

        final = await self.issue_join(authority=self.authority())
        self.assertEqual(final.publish_sources, (MediaSource.MICROPHONE,))


if __name__ == "__main__":
    unittest.main()
