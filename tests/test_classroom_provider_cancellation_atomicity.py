from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest

from acs.classroom_media_policy_authority import (
    ClassroomMediaPolicyError,
    ClassroomMediaPolicyProviderAdmin,
    SqliteClassroomMediaPolicyAuthority,
)
from acs.classroom_realtime_media import (
    ClassroomRole,
    MediaSource,
    ModerationAction,
    ModerationCommand,
)


class _Roster:
    def participant_ids(self):
        return ("teacher-1", "student-1")

    def role_for(self, participant_id):
        return {
            "teacher-1": ClassroomRole.TEACHER,
            "student-1": ClassroomRole.STUDENT,
        }[participant_id]

    def board_control_allowed(self, participant_id):
        return participant_id == "student-1"


class _RosterResolver:
    def __init__(self):
        self.roster = _Roster()

    def roster_for_room(self, room_id):
        if room_id != "room-1":
            raise KeyError(room_id)
        return self.roster


class _JoinIdentityResolver:
    def participant_for_caller(self, *, room_id, trusted_caller_identity):
        if room_id != "room-1":
            raise KeyError(room_id)
        return trusted_caller_identity


class _BlockingProvider:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = False

    async def apply_moderation_command(self, *, room_id, command):
        self.started.set()
        await self.release.wait()
        self.completed = True


def _permission(*, allowed: bool, operation_id: str) -> ModerationCommand:
    return ModerationCommand(
        operation_id=operation_id,
        actor_id="teacher-1",
        target_id="student-1",
        action=ModerationAction.PUBLISH_PERMISSION,
        source=MediaSource.MICROPHONE,
        value=allowed,
    )


class ClassroomProviderCancellationAtomicityTests(unittest.TestCase):
    def test_cancelled_restore_holds_effect_lock_until_provider_and_durable_restore_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "policy.sqlite3"
            resolver = _RosterResolver()
            join_identity = _JoinIdentityResolver()
            authority = SqliteClassroomMediaPolicyAuthority(
                path,
                roster_resolver=resolver,
                join_identity_resolver=join_identity,
                timeout_seconds=0.1,
            )
            authority.record_authorized_command(
                room_id="room-1",
                command=_permission(allowed=False, operation_id="op-revoke-first"),
            )
            self.assertNotIn(
                MediaSource.MICROPHONE,
                authority.authorize_join(
                    room_id="room-1",
                    trusted_caller_identity="student-1",
                    requested_participant_id="student-1",
                ).publish_sources,
            )

            contender = SqliteClassroomMediaPolicyAuthority(
                path,
                roster_resolver=resolver,
                join_identity_resolver=join_identity,
                timeout_seconds=0.05,
            )

            async def exercise() -> None:
                provider = _BlockingProvider()
                wrapper = ClassroomMediaPolicyProviderAdmin(
                    authority=authority,
                    provider_admin=provider,
                )
                task = asyncio.create_task(
                    wrapper.apply_moderation_command(
                        room_id="room-1",
                        command=_permission(
                            allowed=True,
                            operation_id="op-restore-cancelled",
                        ),
                    )
                )
                await asyncio.wait_for(provider.started.wait(), timeout=1.0)

                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())

                # Cancellation is not allowed to release the cross-process
                # serialization order while the provider effect is unresolved.
                with self.assertRaisesRegex(
                    ClassroomMediaPolicyError,
                    "serialization acquisition failed",
                ):
                    async with contender.provider_effect_scope(
                        room_id="room-1",
                        participant_id="student-1",
                    ):
                        self.fail("cancelled provider scope released too early")

                provider.release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=1.0)
                self.assertTrue(provider.completed)

                # A successful restore is durable before caller cancellation is
                # re-propagated, so provider and reconnect authority cannot diverge.
                self.assertIn(
                    MediaSource.MICROPHONE,
                    authority.authorize_join(
                        room_id="room-1",
                        trusted_caller_identity="student-1",
                        requested_participant_id="student-1",
                    ).publish_sources,
                )

                # The lock is released only after the known terminal outcome.
                async with contender.provider_effect_scope(
                    room_id="room-1",
                    participant_id="student-1",
                ):
                    pass

            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
