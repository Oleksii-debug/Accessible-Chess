from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import threading
import traceback
import unittest
from unittest.mock import patch

import acs.classroom_media_policy_authority as policy_module
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
    def __init__(self, *, fail: bool = False):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = False
        self.fail = fail

    async def apply_moderation_command(self, *, room_id, command):
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("private-provider-failure")
        self.completed = True


class _SynchronousBrokenProvider:
    def apply_moderation_command(self, *, room_id, command):
        raise RuntimeError("private-sync-provider-detail")


def _permission(*, allowed: bool, operation_id: str) -> ModerationCommand:
    return ModerationCommand(
        operation_id=operation_id,
        actor_id="teacher-1",
        target_id="student-1",
        action=ModerationAction.PUBLISH_PERMISSION,
        source=MediaSource.MICROPHONE,
        value=allowed,
    )


def _authority(
    path: Path,
    resolver: _RosterResolver,
    join_identity: _JoinIdentityResolver,
    *,
    timeout_seconds: float,
) -> SqliteClassroomMediaPolicyAuthority:
    return SqliteClassroomMediaPolicyAuthority(
        path,
        roster_resolver=resolver,
        join_identity_resolver=join_identity,
        timeout_seconds=timeout_seconds,
    )


def _microphone_allowed(authority: SqliteClassroomMediaPolicyAuthority) -> bool:
    return MediaSource.MICROPHONE in authority.authorize_join(
        room_id="room-1",
        trusted_caller_identity="student-1",
        requested_participant_id="student-1",
    ).publish_sources


class ClassroomProviderCancellationAtomicityTests(unittest.TestCase):
    def test_synchronous_provider_failure_remains_sanitized_at_async_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            authority = _authority(
                Path(temp) / "policy.sqlite3",
                _RosterResolver(),
                _JoinIdentityResolver(),
                timeout_seconds=0.1,
            )
            wrapper = ClassroomMediaPolicyProviderAdmin(
                authority=authority,
                provider_admin=_SynchronousBrokenProvider(),
            )

            with self.assertRaisesRegex(
                ClassroomMediaPolicyError,
                "^media policy provider operation failed$",
            ) as caught:
                asyncio.run(
                    wrapper.apply_moderation_command(
                        room_id="room-1",
                        command=_permission(
                            allowed=False,
                            operation_id="op-sync-provider-failure",
                        ),
                    )
                )
            rendered = "".join(traceback.format_exception(caught.exception))
            self.assertNotIn("private-sync-provider-detail", rendered)

    def test_repeated_cancel_during_effect_lock_acquire_recovers_and_releases_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "policy.sqlite3"
            authority = _authority(
                path,
                _RosterResolver(),
                _JoinIdentityResolver(),
                timeout_seconds=0.1,
            )
            entered = threading.Event()
            finish = threading.Event()
            completed = threading.Event()
            acquired = object()
            released = []

            def delayed_acquire(_path, _timeout_seconds):
                entered.set()
                finish.wait(timeout=2.0)
                completed.set()
                return acquired

            async def release_result(connection):
                released.append(connection)

            async def exercise() -> None:
                scope = authority.provider_effect_scope(
                    room_id="room-1",
                    participant_id="student-1",
                )
                with patch.object(
                    policy_module,
                    "_acquire_effect_lock",
                    side_effect=delayed_acquire,
                ), patch.object(
                    policy_module,
                    "_release_effect_lock_async",
                    side_effect=release_result,
                ):
                    waiter = asyncio.create_task(scope.__aenter__())
                    while not entered.is_set():
                        await asyncio.sleep(0)
                    waiter.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(waiter.done())
                    waiter.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(waiter.done())
                    finish.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(waiter, timeout=1.0)
                    while not completed.is_set():
                        await asyncio.sleep(0)

                self.assertEqual(released, [acquired])
                self.assertIsNone(scope._connection)

            asyncio.run(exercise())

    def test_cancelled_restore_holds_effect_lock_until_provider_and_durable_restore_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "policy.sqlite3"
            resolver = _RosterResolver()
            join_identity = _JoinIdentityResolver()
            authority = _authority(
                path,
                resolver,
                join_identity,
                timeout_seconds=0.1,
            )
            authority.record_authorized_command(
                room_id="room-1",
                command=_permission(allowed=False, operation_id="op-revoke-first"),
            )
            self.assertFalse(_microphone_allowed(authority))
            contender = _authority(
                path,
                resolver,
                join_identity,
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
                self.assertTrue(_microphone_allowed(authority))

                async with contender.provider_effect_scope(
                    room_id="room-1",
                    participant_id="student-1",
                ):
                    pass

            asyncio.run(exercise())

    def test_cancelled_failed_restore_stays_revoked_until_failure_is_known(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "policy.sqlite3"
            resolver = _RosterResolver()
            join_identity = _JoinIdentityResolver()
            authority = _authority(
                path,
                resolver,
                join_identity,
                timeout_seconds=0.1,
            )
            authority.record_authorized_command(
                room_id="room-1",
                command=_permission(allowed=False, operation_id="op-revoke-before-failure"),
            )
            contender = _authority(
                path,
                resolver,
                join_identity,
                timeout_seconds=0.05,
            )

            async def exercise() -> None:
                provider = _BlockingProvider(fail=True)
                wrapper = ClassroomMediaPolicyProviderAdmin(
                    authority=authority,
                    provider_admin=provider,
                )
                task = asyncio.create_task(
                    wrapper.apply_moderation_command(
                        room_id="room-1",
                        command=_permission(
                            allowed=True,
                            operation_id="op-restore-cancelled-failure",
                        ),
                    )
                )
                await asyncio.wait_for(provider.started.wait(), timeout=1.0)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())

                with self.assertRaisesRegex(
                    ClassroomMediaPolicyError,
                    "serialization acquisition failed",
                ):
                    async with contender.provider_effect_scope(
                        room_id="room-1",
                        participant_id="student-1",
                    ):
                        self.fail("failed provider scope released before terminal failure")

                provider.release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=1.0)

                self.assertFalse(_microphone_allowed(authority))
                async with contender.provider_effect_scope(
                    room_id="room-1",
                    participant_id="student-1",
                ):
                    pass

            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
