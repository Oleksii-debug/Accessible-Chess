from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import tempfile
import traceback
import unittest

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


class FakeProviderAdmin:
    def __init__(self):
        self.commands = []
        self.error = None

    async def apply_moderation_command(self, *, room_id, command):
        self.commands.append((room_id, command))
        if self.error is not None:
            raise self.error


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

    def authority(self, path=None, resolver=None):
        return SqliteClassroomMediaPolicyAuthority(
            path or self.path,
            roster_resolver=resolver or self.resolver,
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

    def test_storage_contract_is_file_backed_wal_and_path_redacted(self):
        authority = self.authority()
        self.assertNotIn(str(self.path), repr(authority))
        self.assertIn("redacted", repr(authority))
        with sqlite3.connect(str(self.path)) as connection:
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
                timeout_seconds=True,
            )


if __name__ == "__main__":
    unittest.main()
