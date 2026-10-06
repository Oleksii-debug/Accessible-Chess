from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import traceback
import unittest
from unittest.mock import patch

from acs.classroom_join_credentials import ClassroomJoinGrant
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
    classroom_media_moderation_allowed,
    default_source_policies,
)


class FakeRoster:
    def __init__(self):
        self.roles = {
            "teacher-1": ClassroomRole.TEACHER,
            "co-1": ClassroomRole.CO_TEACHER,
            "student-1": ClassroomRole.STUDENT,
            "student-2": ClassroomRole.STUDENT,
            "observer-1": ClassroomRole.OBSERVER,
        }
        self.board = {participant: False for participant in self.roles}
        self.board["student-1"] = True

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]

    def board_control_allowed(self, participant_id):
        return self.board[participant_id]


class FakeResolver:
    def __init__(self, roster=None):
        self.roster = roster or FakeRoster()
        self.rooms = {"room-1": self.roster}

    def roster_for_room(self, room_id):
        return self.rooms[room_id]


class FakeJoinIdentityResolver:
    def __init__(self):
        self.mapping = {
            "account-17": "student-1",
            "account-student-2": "student-2",
        }
        self.calls = []

    def participant_for_caller(self, *, room_id, trusted_caller_identity):
        self.calls.append((room_id, trusted_caller_identity))
        return self.mapping.get(trusted_caller_identity, trusted_caller_identity)


class FakeProviderAdmin:
    def __init__(self):
        self.commands = []
        self.error = None

    async def apply_moderation_command(self, *, room_id, command):
        self.commands.append((room_id, command))
        if self.error is not None:
            raise self.error


class LostUpdateProviderAdmin:
    """Deliberately stale read/modify/write provider used to prove serialization."""

    def __init__(self):
        self.sources = {MediaSource.MICROPHONE, MediaSource.CAMERA}
        self.commands = []
        self.active = 0
        self.max_active = 0

    async def apply_moderation_command(self, *, room_id, command):
        snapshot = set(self.sources)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.commands.append((room_id, command))
        try:
            # Without cross-instance serialization, two callers both snapshot
            # the original state and the later write loses the earlier revoke.
            await asyncio.sleep(0.05)
            if command.action is ModerationAction.PUBLISH_PERMISSION:
                if command.value:
                    snapshot.add(command.source)
                else:
                    snapshot.discard(command.source)
            self.sources = snapshot
        finally:
            self.active -= 1


def command(
    action,
    *,
    actor="teacher-1",
    target="student-1",
    source=None,
    value=True,
    operation="op-1",
):
    return ModerationCommand(
        operation_id=operation,
        actor_id=actor,
        target_id=target,
        action=action,
        source=source,
        value=value,
    )


class ClassroomMediaPolicyAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "policy.sqlite3"
        self.resolver = FakeResolver()
        self.join_identity = FakeJoinIdentityResolver()

    def authority(self, path=None, resolver=None, join_identity_resolver=None):
        return SqliteClassroomMediaPolicyAuthority(
            path or self.path,
            roster_resolver=resolver or self.resolver,
            join_identity_resolver=(
                self.join_identity
                if join_identity_resolver is None
                else join_identity_resolver
            ),
        )

    def test_distinct_moderation_workflow_binds_live_parent_fail_closed(self):
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "classroom-distinct-moderation-serialization.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$EVENT_BASE_SHA" HEAD', workflow)
        self.assertIn('git fetch --no-tags origin "$EXPECTED_BASE_REF"', workflow)
        self.assertIn(
            'base="$(git rev-parse "refs/remotes/origin/$EXPECTED_BASE_REF")"',
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', workflow)
        self.assertIn('git diff --name-only "$base...HEAD"', workflow)
        self.assertNotIn(
            'git diff --name-only "$EVENT_BASE_SHA...HEAD"',
            workflow,
        )

    def test_shared_default_source_policy_is_exact_for_every_role(self):
        expected = {
            ClassroomRole.TEACHER: (True, True, True),
            ClassroomRole.CO_TEACHER: (True, True, True),
            ClassroomRole.STUDENT: (True, True, False),
            ClassroomRole.OBSERVER: (False, False, False),
        }
        for role, flags in expected.items():
            with self.subTest(role=role):
                policy = default_source_policies(role)
                self.assertEqual(
                    tuple(item.source for item in policy),
                    tuple(MediaSource),
                )
                self.assertEqual(
                    tuple(item.publish_allowed for item in policy),
                    flags,
                )

    def test_shared_moderation_role_matrix_matches_desktop_contract(self):
        expected = {
            (ClassroomRole.TEACHER, ClassroomRole.TEACHER): False,
            (ClassroomRole.TEACHER, ClassroomRole.CO_TEACHER): True,
            (ClassroomRole.TEACHER, ClassroomRole.STUDENT): True,
            (ClassroomRole.TEACHER, ClassroomRole.OBSERVER): True,
            (ClassroomRole.CO_TEACHER, ClassroomRole.TEACHER): False,
            (ClassroomRole.CO_TEACHER, ClassroomRole.CO_TEACHER): False,
            (ClassroomRole.CO_TEACHER, ClassroomRole.STUDENT): True,
            (ClassroomRole.CO_TEACHER, ClassroomRole.OBSERVER): True,
        }
        for actor in ClassroomRole:
            for target in ClassroomRole:
                self.assertEqual(
                    classroom_media_moderation_allowed(actor, target),
                    expected.get((actor, target), False),
                    (actor, target),
                )

    def test_join_uses_current_roster_defaults_without_owning_membership(self):
        authority = self.authority()
        student = authority.authorize_join(
            room_id="room-1",
            trusted_caller_identity="student-1",
            requested_participant_id="student-1",
        )
        observer = authority.authorize_join(
            room_id="room-1",
            trusted_caller_identity="observer-1",
            requested_participant_id="observer-1",
        )
        self.assertIs(type(student), ClassroomJoinGrant)
        self.assertEqual(
            student.publish_sources,
            (MediaSource.MICROPHONE, MediaSource.CAMERA),
        )
        self.assertEqual(observer.publish_sources, ())

    def test_join_maps_authenticated_account_to_room_participant(self):
        authority = self.authority()
        grant = authority.authorize_join(
            room_id="room-1",
            trusted_caller_identity="account-17",
            requested_participant_id="student-1",
        )
        self.assertEqual(grant.participant_id, "student-1")
        self.assertEqual(
            self.join_identity.calls[-1],
            ("room-1", "account-17"),
        )

        with self.assertRaisesRegex(
            ClassroomMediaPolicyError,
            "not authorized for caller",
        ):
            authority.authorize_join(
                room_id="room-1",
                trusted_caller_identity="account-student-2",
                requested_participant_id="student-1",
            )

    def test_join_rejects_impersonation_unknown_room_and_unknown_participant(self):
        authority = self.authority()
        cases = (
            dict(
                room_id="room-1",
                trusted_caller_identity="student-2",
                requested_participant_id="student-1",
            ),
            dict(
                room_id="missing-room",
                trusted_caller_identity="student-1",
                requested_participant_id="student-1",
            ),
            dict(
                room_id="room-1",
                trusted_caller_identity="ghost",
                requested_participant_id="ghost",
            ),
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ClassroomMediaPolicyError):
                    authority.authorize_join(**value)

    def test_join_identity_lookup_failures_are_sanitized_and_fail_closed(self):
        secret = "private-auth-backend-detail"

        class BrokenJoinIdentity:
            def participant_for_caller(self, *, room_id, trusted_caller_identity):
                raise RuntimeError(secret)

        authority = self.authority(join_identity_resolver=BrokenJoinIdentity())
        with self.assertRaisesRegex(
            ClassroomMediaPolicyError,
            "^canonical join identity lookup failed$",
        ) as caught:
            authority.authorize_join(
                room_id="room-1",
                trusted_caller_identity="account-17",
                requested_participant_id="student-1",
            )
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(
            secret,
            "".join(traceback.format_exception(caught.exception)),
        )

        self.join_identity.mapping["account-17"] = "bad participant id"
        with self.assertRaisesRegex(
            ClassroomMediaPolicyError,
            "canonical join participant id is invalid",
        ):
            self.authority().authorize_join(
                room_id="room-1",
                trusted_caller_identity="account-17",
                requested_participant_id="student-1",
            )

    def test_hard_source_revoke_survives_restart_and_fresh_join(self):
        authority = self.authority()
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
            ),
        )
        restarted = self.authority()
        policy = restarted.participant_policy(
            room_id="room-1",
            participant_id="student-1",
        )
        grant = restarted.authorize_join(
            room_id="room-1",
            trusted_caller_identity="student-1",
            requested_participant_id="student-1",
        )
        self.assertFalse(policy.source(MediaSource.MICROPHONE).publish_allowed)
        self.assertTrue(policy.source(MediaSource.CAMERA).publish_allowed)
        self.assertEqual(grant.publish_sources, (MediaSource.CAMERA,))

    def test_hard_restore_is_durable_without_inventing_session_state(self):
        authority = self.authority()
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
                operation="op-revoke",
            ),
        )
        revision = authority.policy_revision(
            room_id="room-1",
            participant_id="student-1",
        )
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=True,
                operation="op-restore",
            ),
        )
        grant = self.authority().authorize_join(
            room_id="room-1",
            trusted_caller_identity="student-1",
            requested_participant_id="student-1",
        )
        self.assertIn(MediaSource.MICROPHONE, grant.publish_sources)
        self.assertEqual(
            self.authority().policy_revision(
                room_id="room-1",
                participant_id="student-1",
            ),
            revision + 1,
        )

    def test_exact_retry_is_idempotent_in_durable_revision(self):
        authority = self.authority()
        value = command(
            ModerationAction.PUBLISH_PERMISSION,
            source=MediaSource.CAMERA,
            value=False,
        )
        authority.record_authorized_command(room_id="room-1", command=value)
        first = authority.policy_revision(
            room_id="room-1",
            participant_id="student-1",
        )
        authority.record_authorized_command(room_id="room-1", command=value)
        second = authority.policy_revision(
            room_id="room-1",
            participant_id="student-1",
        )
        self.assertEqual(first, 1)
        self.assertEqual(second, first)

    def test_role_change_updates_defaults_but_preserves_explicit_lock(self):
        authority = self.authority()
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.CAMERA,
                value=False,
            ),
        )
        self.resolver.roster.roles["student-1"] = ClassroomRole.CO_TEACHER
        policy = self.authority().participant_policy(
            room_id="room-1",
            participant_id="student-1",
        )
        self.assertTrue(policy.source(MediaSource.MICROPHONE).publish_allowed)
        self.assertFalse(policy.source(MediaSource.CAMERA).publish_allowed)
        self.assertTrue(policy.source(MediaSource.SCREEN_SHARE).publish_allowed)

    def test_board_control_remains_external_and_unmodified(self):
        authority = self.authority()
        before = authority.participant_policy(
            room_id="room-1",
            participant_id="student-1",
        )
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.CAMERA,
                value=False,
            ),
        )
        after = authority.participant_policy(
            room_id="room-1",
            participant_id="student-1",
        )
        self.assertTrue(before.board_control_allowed)
        self.assertTrue(after.board_control_allowed)

    def test_block_survives_restart_and_kick_cannot_clear_it(self):
        authority = self.authority()
        authority.record_authorized_command(
            room_id="room-1",
            command=command(ModerationAction.REMOVE, value=True),
        )
        revision = authority.policy_revision(
            room_id="room-1",
            participant_id="student-1",
        )
        restarted = self.authority()
        policy = restarted.participant_policy(
            room_id="room-1",
            participant_id="student-1",
        )
        self.assertTrue(policy.blocked)
        self.assertTrue(policy.removed)
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "blocked"):
            restarted.authorize_join(
                room_id="room-1",
                trusted_caller_identity="student-1",
                requested_participant_id="student-1",
            )
        restarted.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.REMOVE,
                value=False,
                operation="op-kick",
            ),
        )
        self.assertEqual(
            restarted.policy_revision(
                room_id="room-1",
                participant_id="student-1",
            ),
            revision,
        )
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "blocked"):
            restarted.authorize_join(
                room_id="room-1",
                trusted_caller_identity="student-1",
                requested_participant_id="student-1",
            )

    def test_authorization_uses_shared_role_rules_and_trusted_actor(self):
        authority = self.authority()
        allowed = (
            command(
                ModerationAction.SOFT_MUTE,
                actor="co-1",
                target="observer-1",
                source=MediaSource.MICROPHONE,
                value=True,
            ),
        )
        authority.authorize_moderation_batch(
            room_id="room-1",
            caller_identity="co-1",
            commands=allowed,
        )
        denied = (
            command(
                ModerationAction.SOFT_MUTE,
                actor="co-1",
                target="teacher-1",
                source=MediaSource.MICROPHONE,
                value=True,
            ),
        )
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "not allowed"):
            authority.authorize_moderation_batch(
                room_id="room-1",
                caller_identity="co-1",
                commands=denied,
            )
        forged = (
            command(
                ModerationAction.REMOVE,
                actor="teacher-1",
                target="student-1",
                value=False,
            ),
        )
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "trusted caller"):
            authority.authorize_moderation_batch(
                room_id="room-1",
                caller_identity="co-1",
                commands=forged,
            )

    def test_self_unknown_target_and_blocked_actor_fail_closed(self):
        authority = self.authority()
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "own media"):
            authority.authorize_moderation_batch(
                room_id="room-1",
                caller_identity="teacher-1",
                commands=(
                    command(
                        ModerationAction.REMOVE,
                        actor="teacher-1",
                        target="teacher-1",
                        value=False,
                    ),
                ),
            )
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "target"):
            authority.authorize_moderation_batch(
                room_id="room-1",
                caller_identity="teacher-1",
                commands=(
                    command(
                        ModerationAction.REMOVE,
                        target="ghost",
                        value=False,
                    ),
                ),
            )
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.REMOVE,
                target="co-1",
                value=True,
                operation="op-block-co",
            ),
        )
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "blocked"):
            authority.authorize_moderation_batch(
                room_id="room-1",
                caller_identity="co-1",
                commands=(
                    command(
                        ModerationAction.REMOVE,
                        actor="co-1",
                        target="student-1",
                        value=False,
                    ),
                ),
            )

    def test_distinct_cross_instance_revokes_are_serialized_before_provider_rmw(self):
        first_authority = self.authority()
        second_authority = self.authority()
        provider = LostUpdateProviderAdmin()
        first = ClassroomMediaPolicyProviderAdmin(
            authority=first_authority,
            provider_admin=provider,
        )
        second = ClassroomMediaPolicyProviderAdmin(
            authority=second_authority,
            provider_admin=provider,
        )

        async def race():
            await asyncio.gather(
                first.apply_moderation_command(
                    room_id="room-1",
                    command=command(
                        ModerationAction.PUBLISH_PERMISSION,
                        source=MediaSource.CAMERA,
                        value=False,
                        operation="op-lock-camera-distinct",
                    ),
                ),
                second.apply_moderation_command(
                    room_id="room-1",
                    command=command(
                        ModerationAction.PUBLISH_PERMISSION,
                        source=MediaSource.MICROPHONE,
                        value=False,
                        operation="op-lock-microphone-distinct",
                    ),
                ),
            )

        asyncio.run(race())

        self.assertEqual(provider.max_active, 1)
        self.assertEqual(provider.sources, set())
        self.assertEqual(len(provider.commands), 2)
        restarted = self.authority()
        policy = restarted.participant_policy(
            room_id="room-1",
            participant_id="student-1",
        )
        self.assertFalse(policy.source(MediaSource.MICROPHONE).publish_allowed)
        self.assertFalse(policy.source(MediaSource.CAMERA).publish_allowed)

    def test_restore_and_revoke_share_one_total_order_across_instances(self):
        authority = self.authority()
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
                operation="op-initial-mic-lock",
            ),
        )
        provider = LostUpdateProviderAdmin()
        provider.sources.discard(MediaSource.MICROPHONE)
        first = ClassroomMediaPolicyProviderAdmin(
            authority=self.authority(),
            provider_admin=provider,
        )
        second = ClassroomMediaPolicyProviderAdmin(
            authority=self.authority(),
            provider_admin=provider,
        )

        async def race():
            await asyncio.gather(
                first.apply_moderation_command(
                    room_id="room-1",
                    command=command(
                        ModerationAction.PUBLISH_PERMISSION,
                        source=MediaSource.MICROPHONE,
                        value=True,
                        operation="op-restore-mic-distinct",
                    ),
                ),
                second.apply_moderation_command(
                    room_id="room-1",
                    command=command(
                        ModerationAction.PUBLISH_PERMISSION,
                        source=MediaSource.MICROPHONE,
                        value=False,
                        operation="op-revoke-mic-distinct",
                    ),
                ),
            )

        asyncio.run(race())

        grant = self.authority().authorize_join(
            room_id="room-1",
            trusted_caller_identity="student-1",
            requested_participant_id="student-1",
        )
        durable_allows = MediaSource.MICROPHONE in grant.publish_sources
        provider_allows = MediaSource.MICROPHONE in provider.sources
        self.assertEqual(provider.max_active, 1)
        self.assertEqual(provider_allows, durable_allows)

    def test_cancelled_effect_lock_waiter_preserves_cancellation_if_acquire_fails(self):
        authority = self.authority()
        entered = threading.Event()
        finish = threading.Event()

        def failing_acquire(_path, _timeout_seconds):
            entered.set()
            finish.wait(timeout=2.0)
            raise ClassroomMediaPolicyError("private delayed acquisition failure")

        async def exercise():
            scope = authority.provider_effect_scope(
                room_id="room-1",
                participant_id="student-1",
            )
            with patch(
                "acs.classroom_media_policy_authority._acquire_effect_lock",
                side_effect=failing_acquire,
            ):
                waiter = asyncio.create_task(scope.__aenter__())
                while not entered.is_set():
                    await asyncio.sleep(0)
                waiter.cancel()
                finish.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(waiter, timeout=2.0)
            self.assertIsNone(scope._connection)

        asyncio.run(exercise())

    def test_cancelled_effect_lock_waiter_cannot_strand_future_moderation(self):
        first = self.authority()
        second = self.authority()
        third = self.authority()

        async def exercise():
            first_scope = first.provider_effect_scope(
                room_id="room-1",
                participant_id="student-1",
            )
            await first_scope.__aenter__()
            waiter_entered = False

            async def wait_for_same_lock():
                nonlocal waiter_entered
                async with second.provider_effect_scope(
                    room_id="room-1",
                    participant_id="student-1",
                ):
                    waiter_entered = True

            waiter = asyncio.create_task(wait_for_same_lock())
            await asyncio.sleep(0.05)
            waiter.cancel()
            await first_scope.__aexit__(None, None, None)
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(waiter, timeout=2.0)
            self.assertFalse(waiter_entered)

            async with third.provider_effect_scope(
                room_id="room-1",
                participant_id="student-1",
            ):
                return True

        self.assertTrue(asyncio.run(exercise()))

    def test_effect_lock_is_companion_storage_not_policy_or_identity_authority(self):
        authority = self.authority()
        lock_path = self.path.with_name(
            self.path.name + ".provider-effect-lock.sqlite3"
        )
        self.assertTrue(lock_path.exists())
        with closing(sqlite3.connect(str(lock_path))) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(classroom_moderation_effect_lock)"
                )
            }
        self.assertIn("classroom_moderation_effect_lock", tables)
        self.assertEqual(columns, {"singleton", "generation"})
        rendered = repr(
            authority.provider_effect_scope(
                room_id="room-1",
                participant_id="student-1",
            )
        )
        self.assertNotIn(str(self.path), rendered)
        self.assertNotIn("room-1", rendered)
        self.assertNotIn("student-1", rendered)

    def test_provider_wrapper_persists_revoke_before_provider_failure(self):
        authority = self.authority()
        provider = FakeProviderAdmin()
        provider.error = RuntimeError("private provider detail")
        wrapper = ClassroomMediaPolicyProviderAdmin(
            authority=authority,
            provider_admin=provider,
        )
        revoke = command(
            ModerationAction.PUBLISH_PERMISSION,
            source=MediaSource.MICROPHONE,
            value=False,
        )
        with self.assertRaisesRegex(
            ClassroomMediaPolicyError,
            "^media policy provider operation failed$",
        ) as caught:
            asyncio.run(
                wrapper.apply_moderation_command(
                    room_id="room-1",
                    command=revoke,
                )
            )
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(
            "private provider detail",
            "".join(traceback.format_exception(caught.exception)),
        )
        grant = self.authority().authorize_join(
            room_id="room-1",
            trusted_caller_identity="student-1",
            requested_participant_id="student-1",
        )
        self.assertNotIn(MediaSource.MICROPHONE, grant.publish_sources)

    def test_provider_wrapper_failed_restore_does_not_reopen_fresh_join(self):
        authority = self.authority()
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
                operation="op-revoke-before-restore",
            ),
        )
        revision = authority.policy_revision(
            room_id="room-1",
            participant_id="student-1",
        )
        provider = FakeProviderAdmin()
        provider.error = RuntimeError("restore failed privately")
        wrapper = ClassroomMediaPolicyProviderAdmin(
            authority=authority,
            provider_admin=provider,
        )
        restore = command(
            ModerationAction.PUBLISH_PERMISSION,
            source=MediaSource.MICROPHONE,
            value=True,
            operation="op-restore-fails",
        )

        with self.assertRaisesRegex(
            ClassroomMediaPolicyError,
            "^media policy provider operation failed$",
        ):
            asyncio.run(
                wrapper.apply_moderation_command(
                    room_id="room-1",
                    command=restore,
                )
            )

        self.assertEqual(provider.commands, [("room-1", restore)])
        restarted = self.authority()
        self.assertEqual(
            restarted.policy_revision(
                room_id="room-1",
                participant_id="student-1",
            ),
            revision,
        )
        grant = restarted.authorize_join(
            room_id="room-1",
            trusted_caller_identity="student-1",
            requested_participant_id="student-1",
        )
        self.assertNotIn(MediaSource.MICROPHONE, grant.publish_sources)

    def test_provider_wrapper_persists_restore_only_after_provider_success(self):
        authority = self.authority()
        authority.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
                operation="op-revoke-before-successful-restore",
            ),
        )
        revision = authority.policy_revision(
            room_id="room-1",
            participant_id="student-1",
        )

        class InspectingProvider(FakeProviderAdmin):
            def __init__(self):
                super().__init__()
                self.join_allowed_during_provider = None

            async def apply_moderation_command(self, *, room_id, command):
                grant = authority.authorize_join(
                    room_id=room_id,
                    trusted_caller_identity=command.target_id,
                    requested_participant_id=command.target_id,
                )
                self.join_allowed_during_provider = (
                    MediaSource.MICROPHONE in grant.publish_sources
                )
                await super().apply_moderation_command(
                    room_id=room_id,
                    command=command,
                )

        provider = InspectingProvider()
        wrapper = ClassroomMediaPolicyProviderAdmin(
            authority=authority,
            provider_admin=provider,
        )
        restore = command(
            ModerationAction.PUBLISH_PERMISSION,
            source=MediaSource.MICROPHONE,
            value=True,
            operation="op-restore-succeeds",
        )

        asyncio.run(
            wrapper.apply_moderation_command(
                room_id="room-1",
                command=restore,
            )
        )

        self.assertFalse(provider.join_allowed_during_provider)
        restarted = self.authority()
        self.assertEqual(
            restarted.policy_revision(
                room_id="room-1",
                participant_id="student-1",
            ),
            revision + 1,
        )
        grant = restarted.authorize_join(
            room_id="room-1",
            trusted_caller_identity="student-1",
            requested_participant_id="student-1",
        )
        self.assertIn(MediaSource.MICROPHONE, grant.publish_sources)

    def test_provider_wrapper_persists_block_before_remove_failure(self):
        authority = self.authority()
        provider = FakeProviderAdmin()
        provider.error = RuntimeError("remove failed")
        wrapper = ClassroomMediaPolicyProviderAdmin(
            authority=authority,
            provider_admin=provider,
        )
        with self.assertRaises(ClassroomMediaPolicyError):
            asyncio.run(
                wrapper.apply_moderation_command(
                    room_id="room-1",
                    command=command(ModerationAction.REMOVE, value=True),
                )
            )
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "blocked"):
            self.authority().authorize_join(
                room_id="room-1",
                trusted_caller_identity="student-1",
                requested_participant_id="student-1",
            )

    def test_soft_mute_remains_session_only_and_does_not_shrink_join_grant(self):
        authority = self.authority()
        provider = FakeProviderAdmin()
        wrapper = ClassroomMediaPolicyProviderAdmin(
            authority=authority,
            provider_admin=provider,
        )
        muted = command(
            ModerationAction.SOFT_MUTE,
            source=MediaSource.MICROPHONE,
            value=True,
        )
        asyncio.run(
            wrapper.apply_moderation_command(
                room_id="room-1",
                command=muted,
            )
        )
        self.assertEqual(provider.commands, [("room-1", muted)])
        self.assertEqual(
            authority.policy_revision(
                room_id="room-1",
                participant_id="student-1",
            ),
            0,
        )
        grant = authority.authorize_join(
            room_id="room-1",
            trusted_caller_identity="student-1",
            requested_participant_id="student-1",
        )
        self.assertIn(MediaSource.MICROPHONE, grant.publish_sources)

    def test_two_authority_instances_preserve_independent_source_updates(self):
        first = self.authority()
        second = self.authority()
        first.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
                operation="op-mic",
            ),
        )
        second.record_authorized_command(
            room_id="room-1",
            command=command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.CAMERA,
                value=False,
                operation="op-camera",
            ),
        )
        policy = self.authority().participant_policy(
            room_id="room-1",
            participant_id="student-1",
        )
        self.assertFalse(policy.source(MediaSource.MICROPHONE).publish_allowed)
        self.assertFalse(policy.source(MediaSource.CAMERA).publish_allowed)
        self.assertEqual(
            self.authority().policy_revision(
                room_id="room-1",
                participant_id="student-1",
            ),
            2,
        )

    def test_policy_and_effect_lock_paths_share_canonical_spelling(self):
        aliased = self.path.parent / "unused-segment" / ".." / self.path.name
        authority = self.authority(path=aliased)
        canonical = self.path.resolve(strict=False)

        self.assertEqual(authority._path, canonical)
        self.assertEqual(
            authority._effect_lock_path,
            canonical.with_name(canonical.name + ".provider-effect-lock.sqlite3"),
        )
        self.assertTrue(authority._effect_lock_path.exists())

    def test_failed_effect_lock_setup_closes_opened_sqlite_handle(self):
        class FailingPragmaConnection:
            def __init__(self):
                self.closed = False

            def execute(self, statement):
                if statement == "PRAGMA synchronous=FULL":
                    raise sqlite3.OperationalError("private effect-lock pragma failure")
                return self

            def close(self):
                self.closed = True

        authority = self.authority()
        failing = FailingPragmaConnection()
        with patch(
            "acs.classroom_media_policy_authority.sqlite3.connect",
            return_value=failing,
        ):
            with self.assertRaisesRegex(
                ClassroomMediaPolicyError,
                "^moderation effect serialization storage is unavailable$",
            ) as caught:
                authority._connect_effect_lock()

        self.assertTrue(failing.closed)
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("private effect-lock pragma failure", str(caught.exception))

    def test_failed_connection_setup_closes_opened_sqlite_handle(self):
        class FailingPragmaConnection:
            def __init__(self):
                self.closed = False

            def execute(self, statement):
                if statement == "PRAGMA synchronous=FULL":
                    raise sqlite3.OperationalError("private policy pragma failure")
                return self

            def close(self):
                self.closed = True

        authority = self.authority()
        failing = FailingPragmaConnection()
        with patch(
            "acs.classroom_media_policy_authority.sqlite3.connect",
            return_value=failing,
        ):
            with self.assertRaisesRegex(
                ClassroomMediaPolicyError,
                "^media policy storage is unavailable$",
            ) as caught:
                authority._connect()

        self.assertTrue(failing.closed)
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("private policy pragma failure", str(caught.exception))

    def test_storage_contract_is_file_backed_wal_and_path_redacted(self):
        authority = self.authority()
        self.assertNotIn(str(self.path), repr(authority))
        self.assertIn("redacted", repr(authority))
        with closing(sqlite3.connect(str(self.path))) as connection:
            self.assertEqual(
                connection.execute("PRAGMA journal_mode").fetchone()[0].lower(),
                "wal",
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(classroom_media_policy)"
                )
            }
        self.assertEqual(
            columns,
            {
                "room_id",
                "participant_id",
                "microphone_allowed",
                "camera_allowed",
                "screen_share_allowed",
                "blocked",
                "revision",
            },
        )
        with self.assertRaises(ClassroomMediaPolicyError):
            SqliteClassroomMediaPolicyAuthority(
                ":memory:",
                roster_resolver=self.resolver,
                join_identity_resolver=self.join_identity,
            )

    def test_invalid_roster_and_timeout_inputs_fail_closed(self):
        class BadResolver:
            def roster_for_room(self, room_id):
                return object()

        authority = self.authority(
            path=Path(self.temp.name) / "bad-roster.sqlite3",
            resolver=BadResolver(),
        )
        with self.assertRaisesRegex(ClassroomMediaPolicyError, "roster"):
            authority.authorize_join(
                room_id="room-1",
                trusted_caller_identity="student-1",
                requested_participant_id="student-1",
            )
        with self.assertRaises(ClassroomMediaPolicyError):
            SqliteClassroomMediaPolicyAuthority(
                self.path,
                roster_resolver=self.resolver,
                join_identity_resolver=self.join_identity,
                timeout_seconds=True,
            )
        with self.assertRaisesRegex(
            ClassroomMediaPolicyError,
            "join identity resolver",
        ):
            SqliteClassroomMediaPolicyAuthority(
                self.path,
                roster_resolver=self.resolver,
                join_identity_resolver=None,
            )


if __name__ == "__main__":
    unittest.main()