from __future__ import annotations

import asyncio
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import tempfile
import unittest

from acs.classroom_media_policy_authority import (
    ClassroomMediaPolicyError,
    SqliteClassroomMediaPolicyAuthority,
)
from acs.classroom_realtime_media import ClassroomRole


class _Roster:
    def participant_ids(self):
        return ("teacher-1", "student-1")

    def role_for(self, participant_id):
        return {
            "teacher-1": ClassroomRole.TEACHER,
            "student-1": ClassroomRole.STUDENT,
        }[participant_id]

    def board_control_allowed(self, participant_id):
        return False


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


async def _attempt_effect_scope(
    authority: SqliteClassroomMediaPolicyAuthority,
) -> None:
    async with authority.provider_effect_scope(
        room_id="room-1",
        participant_id="student-1",
    ):
        return None


def _effect_lock_worker(path: str, connection: Connection) -> None:
    """Long-lived independent process used to prove OS-level SQLite locking."""

    try:
        authority = SqliteClassroomMediaPolicyAuthority(
            Path(path),
            roster_resolver=_RosterResolver(),
            join_identity_resolver=_JoinIdentityResolver(),
            timeout_seconds=0.5,
        )
        connection.send(("ready", None))
        while True:
            request = connection.recv()
            if request == "stop":
                return
            if request != "attempt":
                connection.send(("error", "invalid-request"))
                continue
            try:
                asyncio.run(_attempt_effect_scope(authority))
            except ClassroomMediaPolicyError:
                connection.send(("blocked", None))
            except BaseException as exc:
                connection.send(("error", type(exc).__name__))
            else:
                connection.send(("acquired", None))
    except BaseException as exc:
        try:
            connection.send(("error", type(exc).__name__))
        except BaseException:
            pass
        raise
    finally:
        connection.close()


def _crashing_effect_lock_owner(path: str, connection: Connection) -> None:
    """Acquire the production mutex, then die without running async cleanup."""

    authority = SqliteClassroomMediaPolicyAuthority(
        Path(path),
        roster_resolver=_RosterResolver(),
        join_identity_resolver=_JoinIdentityResolver(),
        timeout_seconds=5.0,
    )

    async def crash_while_locked() -> None:
        scope = authority.provider_effect_scope(
            room_id="room-1",
            participant_id="student-1",
        )
        await scope.__aenter__()
        connection.send(("locked", None))
        # Deliberately bypass __aexit__, finally blocks and Python-level close.
        # The next process must rely on OS/SQLite crash cleanup only.
        os._exit(23)

    asyncio.run(crash_while_locked())


def _receive(connection: Connection, timeout: float = 8.0):
    if not connection.poll(timeout):
        raise AssertionError("spawned moderation-lock worker did not respond")
    return connection.recv()


class ClassroomEffectLockCrossProcessTests(unittest.TestCase):
    def test_spawned_process_observes_same_effect_mutex(self):
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.sqlite3"
            parent_authority = SqliteClassroomMediaPolicyAuthority(
                policy_path,
                roster_resolver=_RosterResolver(),
                join_identity_resolver=_JoinIdentityResolver(),
                timeout_seconds=5.0,
            )

            context = multiprocessing.get_context("spawn")
            parent_connection, child_connection = context.Pipe(duplex=True)
            process = context.Process(
                target=_effect_lock_worker,
                args=(str(policy_path), child_connection),
                name="classroom-effect-lock-proof",
            )
            process.start()
            child_connection.close()

            try:
                self.assertEqual(_receive(parent_connection), ("ready", None))

                async def hold_parent_scope_and_probe_child():
                    async with parent_authority.provider_effect_scope(
                        room_id="room-1",
                        participant_id="student-1",
                    ):
                        parent_connection.send("attempt")
                        return await asyncio.to_thread(
                            _receive,
                            parent_connection,
                        )

                # While this process owns BEGIN IMMEDIATE, the independently
                # spawned process must time out instead of entering a second
                # provider-effect critical section.
                blocked = asyncio.run(hold_parent_scope_and_probe_child())
                self.assertEqual(blocked, ("blocked", None))

                # Once the first process releases the transaction, the exact
                # same already-initialized child must acquire the mutex. This
                # distinguishes real cross-process serialization from a
                # process-local asyncio.Lock or a constructor-only artifact.
                parent_connection.send("attempt")
                self.assertEqual(
                    _receive(parent_connection),
                    ("acquired", None),
                )
                parent_connection.send("stop")
                process.join(timeout=8.0)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 0)
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5.0)
                parent_connection.close()

    def test_crashed_lock_owner_releases_effect_mutex_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.sqlite3"
            retry_authority = SqliteClassroomMediaPolicyAuthority(
                policy_path,
                roster_resolver=_RosterResolver(),
                join_identity_resolver=_JoinIdentityResolver(),
                timeout_seconds=5.0,
            )
            context = multiprocessing.get_context("spawn")
            parent_connection, child_connection = context.Pipe(duplex=True)
            process = context.Process(
                target=_crashing_effect_lock_owner,
                args=(str(policy_path), child_connection),
                name="classroom-effect-lock-crash-proof",
            )
            process.start()
            child_connection.close()

            try:
                self.assertEqual(_receive(parent_connection), ("locked", None))
                process.join(timeout=8.0)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 23)

                # The crashed process never executed __aexit__. The OS must
                # release its SQLite writer lock so a later service participant
                # can retry through the same production scope.
                asyncio.run(_attempt_effect_scope(retry_authority))
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5.0)
                parent_connection.close()


if __name__ == "__main__":
    unittest.main()
