from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from acs.classroom_realtime_media import (
    ClassroomMediaController,
    ClassroomMediaError,
    ClassroomRole,
    JoinCredential,
    MAX_JOIN_TTL_SECONDS,
    MediaDeviceKind,
    MediaSource,
    ModerationAction,
    ModerationCommand,
)


NOW = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)


class FakeRoster:
    def __init__(self, roles=None, board=None):
        self.roles = roles or {
            "teacher-1": ClassroomRole.TEACHER,
            "co-1": ClassroomRole.CO_TEACHER,
            "student-1": ClassroomRole.STUDENT,
            "student-2": ClassroomRole.STUDENT,
            "observer-1": ClassroomRole.OBSERVER,
        }
        self.board = board or {
            key: key != "observer-1"
            for key in self.roles
        }

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]

    def board_control_allowed(self, participant_id):
        return self.board[participant_id]


class FakeMedia:
    def __init__(self):
        self.connect_calls = []
        self.reconnect_calls = []
        self.disconnect_calls = 0
        self.local_calls = []
        self.moderation_calls = []
        self.device_calls = []
        self.fail_local = False
        self.fail_moderation = False
        self.after_moderation = None

    def connect(self, credential, *, enabled_sources):
        self.connect_calls.append((credential, enabled_sources))

    def reconnect(self, credential, *, enabled_sources):
        self.reconnect_calls.append((credential, enabled_sources))

    def disconnect(self):
        self.disconnect_calls += 1

    def set_local_source(self, source, enabled):
        if self.fail_local:
            raise RuntimeError("provider local-source failure")
        self.local_calls.append((source, enabled))

    def apply_moderation(self, commands):
        if self.fail_moderation:
            raise RuntimeError("provider moderation failure")
        self.moderation_calls.append(commands)
        if self.after_moderation is not None:
            self.after_moderation(commands)

    def recover_device(self, kind, device_id, *, republish_enabled):
        self.device_calls.append((kind, device_id, republish_enabled))


def credential(
    participant="student-1",
    *,
    room="room-1",
    issued=NOW,
    ttl=60,
    token="server-issued-token-value",
):
    return JoinCredential(
        room_id=room,
        participant_id=participant,
        token=token,
        issued_at=issued,
        expires_at=issued + timedelta(seconds=ttl),
    )


class ClassroomRealtimeMediaContractTests(unittest.TestCase):
    def make_controller(self, participant="student-1", roster=None, media=None):
        roster = roster or FakeRoster()
        media = media or FakeMedia()
        return (
            ClassroomMediaController(
                local_participant_id=participant,
                roster=roster,
                media=media,
            ),
            roster,
            media,
        )

    def join(self, controller, participant="student-1"):
        return controller.join(credential(participant), now=NOW + timedelta(seconds=1))

    def test_join_is_silent_by_default_and_token_is_not_diagnostic_repr(self):
        controller, _roster, media = self.make_controller()
        state = self.join(controller)

        self.assertTrue(state.connected)
        self.assertEqual(state.room_id, "room-1")
        self.assertEqual(state.desired_sources, frozenset())
        self.assertEqual(len(media.connect_calls), 1)
        sent_credential, enabled = media.connect_calls[0]
        self.assertEqual(enabled, ())
        self.assertNotIn("server-issued-token-value", repr(sent_credential))

    def test_join_credential_is_short_lived_timezone_aware_and_current(self):
        with self.assertRaises(ClassroomMediaError):
            JoinCredential(
                room_id="room-1",
                participant_id="student-1",
                token="x",
                issued_at=NOW.replace(tzinfo=None),
                expires_at=NOW + timedelta(seconds=30),
            )
        with self.assertRaises(ClassroomMediaError):
            credential(ttl=MAX_JOIN_TTL_SECONDS + 1)
        with self.assertRaises(ClassroomMediaError):
            credential(token="bad token")
        valid = credential()
        with self.assertRaises(ClassroomMediaError):
            valid.assert_usable(NOW - timedelta(seconds=1))
        with self.assertRaises(ClassroomMediaError):
            valid.assert_usable(valid.expires_at)

    def test_join_credential_must_match_local_canonical_roster_identity(self):
        controller, _roster, media = self.make_controller("student-1")
        with self.assertRaises(ClassroomMediaError):
            controller.join(
                credential("student-2"),
                now=NOW + timedelta(seconds=1),
            )
        self.assertEqual(media.connect_calls, [])

        missing = FakeRoster(
            roles={"teacher-1": ClassroomRole.TEACHER},
            board={"teacher-1": True},
        )
        controller, _roster, media = self.make_controller("student-1", roster=missing)
        with self.assertRaises(ClassroomMediaError):
            controller.join(
                credential("student-1"),
                now=NOW + timedelta(seconds=1),
            )
        self.assertEqual(media.connect_calls, [])

    def test_local_camera_and_microphone_require_explicit_actions(self):
        controller, _roster, media = self.make_controller()
        self.join(controller)

        controller.set_local_source(MediaSource.MICROPHONE, True)
        controller.set_local_source(MediaSource.CAMERA, True)
        self.assertEqual(
            controller.state.desired_sources,
            frozenset({MediaSource.MICROPHONE, MediaSource.CAMERA}),
        )
        self.assertEqual(
            media.local_calls,
            [
                (MediaSource.MICROPHONE, True),
                (MediaSource.CAMERA, True),
            ],
        )

    def test_observer_cannot_publish_by_default(self):
        controller, _roster, media = self.make_controller("observer-1")
        self.join(controller, "observer-1")
        for source in MediaSource:
            with self.subTest(source=source):
                with self.assertRaises(ClassroomMediaError):
                    controller.set_local_source(source, True)
        self.assertEqual(media.local_calls, [])

    def test_hard_lock_disables_local_source_and_restore_stays_off(self):
        controller, _roster, media = self.make_controller("student-1")
        self.join(controller)
        controller.set_local_source(MediaSource.CAMERA, True)

        locked = controller.set_publish_permission(
            actor_id="teacher-1",
            target_id="student-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="camera-lock-1",
        )
        self.assertFalse(locked.source(MediaSource.CAMERA).publish_allowed)
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)

        restored = controller.set_publish_permission(
            actor_id="teacher-1",
            target_id="student-1",
            source=MediaSource.CAMERA,
            allowed=True,
            operation_id="camera-restore-1",
        )
        self.assertTrue(restored.source(MediaSource.CAMERA).publish_allowed)
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)
        self.assertEqual(media.local_calls, [(MediaSource.CAMERA, True)])

    def test_soft_mute_is_not_a_hard_publish_lock(self):
        controller, _roster, media = self.make_controller("student-1")
        self.join(controller)
        controller.set_local_source(MediaSource.MICROPHONE, True)

        muted = controller.set_soft_mute(
            actor_id="teacher-1",
            target_id="student-1",
            muted=True,
            operation_id="soft-mute-1",
        )
        self.assertTrue(muted.source(MediaSource.MICROPHONE).publish_allowed)
        self.assertTrue(muted.source(MediaSource.MICROPHONE).soft_muted)
        self.assertNotIn(MediaSource.MICROPHONE, controller.state.desired_sources)

        # Soft mute stops the current publication but does not revoke the source.
        controller.set_local_source(MediaSource.MICROPHONE, True)
        self.assertIn(MediaSource.MICROPHONE, controller.state.desired_sources)
        self.assertFalse(
            controller.participant_policy("student-1")
            .source(MediaSource.MICROPHONE)
            .soft_muted
        )
        self.assertEqual(media.local_calls[-1], (MediaSource.MICROPHONE, True))

        # Hard lock is the operation that prevents self re-enable.
        controller.set_publish_permission(
            actor_id="teacher-1",
            target_id="student-1",
            source=MediaSource.MICROPHONE,
            allowed=False,
            operation_id="hard-mic-lock-after-soft-mute",
        )
        with self.assertRaises(ClassroomMediaError):
            controller.set_local_source(MediaSource.MICROPHONE, True)

    def test_media_moderation_never_changes_board_control_authority(self):
        roster = FakeRoster()
        roster.board["student-1"] = True
        controller, _roster, _media = self.make_controller(roster=roster)

        before = controller.participant_policy("student-1")
        controller.set_publish_permission(
            actor_id="teacher-1",
            target_id="student-1",
            source=MediaSource.MICROPHONE,
            allowed=False,
            operation_id="mic-lock-board-independent",
        )
        after = controller.participant_policy("student-1")
        self.assertTrue(before.board_control_allowed)
        self.assertTrue(after.board_control_allowed)

        roster.board["student-1"] = False
        latest = controller.participant_policy("student-1")
        self.assertFalse(latest.board_control_allowed)
        self.assertFalse(latest.source(MediaSource.MICROPHONE).publish_allowed)

    def test_role_moderation_boundary_is_fail_closed(self):
        controller, _roster, media = self.make_controller()
        with self.assertRaises(ClassroomMediaError):
            controller.set_publish_permission(
                actor_id="student-1",
                target_id="student-2",
                source=MediaSource.CAMERA,
                allowed=False,
                operation_id="student-cannot-lock",
            )
        with self.assertRaises(ClassroomMediaError):
            controller.set_soft_mute(
                actor_id="co-1",
                target_id="teacher-1",
                muted=True,
                operation_id="co-cannot-mute-teacher",
            )
        with self.assertRaises(ClassroomMediaError):
            controller.set_soft_mute(
                actor_id="co-1",
                target_id="co-1",
                muted=True,
                operation_id="self-moderation",
            )

        policy = controller.set_publish_permission(
            actor_id="teacher-1",
            target_id="co-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="teacher-lock-co",
        )
        self.assertFalse(policy.source(MediaSource.CAMERA).publish_allowed)
        self.assertEqual(len(media.moderation_calls), 1)

    def test_hard_lock_all_students_is_one_bounded_provider_batch(self):
        controller, _roster, media = self.make_controller()
        policies = controller.set_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.MICROPHONE,
            allowed=False,
            operation_id="lock-all-students",
        )

        self.assertEqual(
            tuple(item.participant_id for item in policies),
            ("student-1", "student-2"),
        )
        self.assertEqual(len(media.moderation_calls), 1)
        commands = media.moderation_calls[0]
        self.assertEqual(len(commands), 2)
        self.assertTrue(
            all(command.action is ModerationAction.PUBLISH_PERMISSION for command in commands)
        )
        self.assertTrue(
            all(command.source is MediaSource.MICROPHONE for command in commands)
        )
        self.assertEqual(
            {command.target_id for command in commands},
            {"student-1", "student-2"},
        )
        self.assertNotIn("observer-1", {command.target_id for command in commands})
        self.assertNotIn("co-1", {command.target_id for command in commands})

    def test_batch_hard_lock_turns_off_local_student_source(self):
        controller, _roster, _media = self.make_controller("student-1")
        self.join(controller)
        controller.set_local_source(MediaSource.CAMERA, True)

        controller.set_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="camera-lock-all",
        )
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)

    def test_batch_student_lock_never_turns_off_local_teacher_media(self):
        controller, _roster, _media = self.make_controller("teacher-1")
        self.join(controller, "teacher-1")
        controller.set_local_source(MediaSource.CAMERA, True)
        controller.set_local_source(MediaSource.MICROPHONE, True)

        controller.set_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="camera-lock-students-only",
        )
        controller.set_all_students_soft_mute(
            actor_id="teacher-1",
            muted=True,
            operation_id="mute-students-only",
        )
        self.assertEqual(
            controller.state.desired_sources,
            frozenset({MediaSource.CAMERA, MediaSource.MICROPHONE}),
        )

    def test_batch_soft_mute_turns_off_local_student_microphone(self):
        controller, _roster, _media = self.make_controller("student-1")
        self.join(controller)
        controller.set_local_source(MediaSource.MICROPHONE, True)

        controller.set_all_students_soft_mute(
            actor_id="teacher-1",
            muted=True,
            operation_id="mute-all",
        )
        self.assertNotIn(MediaSource.MICROPHONE, controller.state.desired_sources)

    def test_reconnect_reuses_same_room_identity_without_duplicate_publication(self):
        controller, _roster, media = self.make_controller("student-1")
        self.join(controller)
        controller.set_local_source(MediaSource.MICROPHONE, True)
        controller.mark_transport_lost()

        state = controller.reconnect(
            credential(
                "student-1",
                room="room-1",
                issued=NOW + timedelta(minutes=1),
                token="fresh-reconnect-token",
            ),
            now=NOW + timedelta(minutes=1, seconds=1),
        )
        self.assertTrue(state.connected)
        self.assertEqual(
            media.reconnect_calls[-1][1],
            (MediaSource.MICROPHONE,),
        )

        controller.mark_transport_lost()
        with self.assertRaises(ClassroomMediaError):
            controller.reconnect(
                credential(
                    "student-1",
                    room="other-room",
                    issued=NOW + timedelta(minutes=2),
                ),
                now=NOW + timedelta(minutes=2, seconds=1),
            )

    def test_reconnect_respects_permission_revoked_while_transport_is_lost(self):
        controller, _roster, media = self.make_controller("student-1")
        self.join(controller)
        controller.set_local_source(MediaSource.MICROPHONE, True)
        controller.mark_transport_lost()
        controller.set_publish_permission(
            actor_id="teacher-1",
            target_id="student-1",
            source=MediaSource.MICROPHONE,
            allowed=False,
            operation_id="offline-mic-lock",
        )

        controller.reconnect(
            credential(
                "student-1",
                issued=NOW + timedelta(minutes=1),
                token="reconnect-after-lock",
            ),
            now=NOW + timedelta(minutes=1, seconds=1),
        )
        self.assertEqual(media.reconnect_calls[-1][1], ())
        self.assertEqual(controller.state.desired_sources, frozenset())

    def test_device_recovery_republishes_only_currently_enabled_source(self):
        controller, _roster, media = self.make_controller("student-1")
        self.join(controller)
        controller.set_local_source(MediaSource.CAMERA, True)

        controller.recover_device(MediaDeviceKind.CAMERA, "camera-device-1")
        controller.recover_device(MediaDeviceKind.MICROPHONE, "mic-device-2")
        controller.recover_device(MediaDeviceKind.SPEAKER, "speaker-device-3")

        self.assertEqual(
            media.device_calls,
            [
                (MediaDeviceKind.CAMERA, "camera-device-1", True),
                (MediaDeviceKind.MICROPHONE, "mic-device-2", False),
                (MediaDeviceKind.SPEAKER, "speaker-device-3", False),
            ],
        )

    def test_provider_failure_does_not_publish_local_state_change(self):
        controller, _roster, media = self.make_controller("student-1")
        self.join(controller)
        before = controller.state
        media.fail_local = True
        with self.assertRaises(RuntimeError):
            controller.set_local_source(MediaSource.CAMERA, True)
        self.assertEqual(controller.state, before)
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)

    def test_provider_failure_does_not_publish_moderation_policy_change(self):
        controller, _roster, media = self.make_controller()
        before = controller.participant_policy("student-1")
        media.fail_moderation = True
        with self.assertRaises(RuntimeError):
            controller.set_publish_permission(
                actor_id="teacher-1",
                target_id="student-1",
                source=MediaSource.CAMERA,
                allowed=False,
                operation_id="failed-lock",
            )
        self.assertEqual(controller.participant_policy("student-1"), before)

    def test_remove_and_block_are_distinct_provider_commands(self):
        controller, _roster, media = self.make_controller()
        removed = controller.remove_participant(
            actor_id="teacher-1",
            target_id="student-1",
            block=False,
            operation_id="remove-student",
        )
        self.assertTrue(removed.removed)
        self.assertFalse(removed.blocked)

        blocked = controller.remove_participant(
            actor_id="teacher-1",
            target_id="student-2",
            block=True,
            operation_id="block-student",
        )
        self.assertTrue(blocked.removed)
        self.assertTrue(blocked.blocked)
        first, second = media.moderation_calls[-2:]
        self.assertFalse(first[0].value)
        self.assertTrue(second[0].value)

    def test_remove_survives_provider_synchronous_roster_eviction(self):
        roster = FakeRoster()
        media = FakeMedia()
        controller, _roster, _media = self.make_controller(
            "teacher-1",
            roster=roster,
            media=media,
        )

        def evict(_commands):
            roster.roles.pop("student-2")
            roster.board.pop("student-2")

        media.after_moderation = evict
        removed = controller.remove_participant(
            actor_id="teacher-1",
            target_id="student-2",
            block=True,
            operation_id="remove-with-roster-eviction",
        )
        self.assertEqual(removed.participant_id, "student-2")
        self.assertTrue(removed.removed)
        self.assertTrue(removed.blocked)

    def test_local_remove_clears_publication_intent_and_blocks_reconnect(self):
        controller, _roster, media = self.make_controller("student-1")
        self.join(controller)
        controller.set_local_source(MediaSource.CAMERA, True)

        removed = controller.remove_participant(
            actor_id="teacher-1",
            target_id="student-1",
            block=True,
            operation_id="remove-local-student",
        )
        self.assertTrue(removed.removed)
        self.assertTrue(removed.blocked)
        self.assertFalse(controller.state.connected)
        self.assertEqual(controller.state.desired_sources, frozenset())

        controller.mark_transport_lost()
        with self.assertRaises(ClassroomMediaError):
            controller.reconnect(
                credential(
                    "student-1",
                    issued=NOW + timedelta(minutes=1),
                    token="fresh-but-blocked-token",
                ),
                now=NOW + timedelta(minutes=1, seconds=1),
            )
        self.assertEqual(media.reconnect_calls, [])

    def test_screen_share_is_present_in_architecture_without_default_student_publish(self):
        controller, _roster, _media = self.make_controller("student-1")
        student = controller.participant_policy("student-1")
        teacher = controller.participant_policy("teacher-1")
        self.assertFalse(student.source(MediaSource.SCREEN_SHARE).publish_allowed)
        self.assertTrue(teacher.source(MediaSource.SCREEN_SHARE).publish_allowed)

    def test_moderation_command_schema_rejects_ambiguous_shapes(self):
        with self.assertRaises(ClassroomMediaError):
            ModerationCommand(
                operation_id="bad-soft-mute",
                actor_id="teacher-1",
                target_id="student-1",
                action=ModerationAction.SOFT_MUTE,
                source=MediaSource.CAMERA,
                value=True,
            )
        with self.assertRaises(ClassroomMediaError):
            ModerationCommand(
                operation_id="bad-remove",
                actor_id="teacher-1",
                target_id="student-1",
                action=ModerationAction.REMOVE,
                source=MediaSource.MICROPHONE,
                value=False,
            )

    def test_device_id_rejects_control_characters_without_assuming_windows_path_shape(self):
        controller, _roster, _media = self.make_controller("student-1")
        self.join(controller)
        with self.assertRaises(ClassroomMediaError):
            controller.recover_device(MediaDeviceKind.CAMERA, "camera\nsecret")
        # Windows hardware IDs commonly contain backslashes; they remain opaque.
        controller.recover_device(MediaDeviceKind.CAMERA, r"USB\VID_1234&PID_5678")


if __name__ == "__main__":
    unittest.main()
