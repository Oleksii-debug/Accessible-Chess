from __future__ import annotations

import unittest

from acs.classroom import (
    BoardControl,
    ClassroomParticipant,
    ClassroomPermissions,
    ClassroomRole,
    ClassroomRoster,
    ParticipantIdentity,
    StatisticsScope,
    UsageStatisticsPolicy,
    generated_alias,
)


class ClassroomTests(unittest.TestCase):
    def student(self, identity: str = "p1", name: str = "Марія") -> ClassroomParticipant:
        return ClassroomParticipant(
            ParticipantIdentity(identity, name),
            ClassroomRole.STUDENT,
            ClassroomPermissions(),
        )

    def test_generated_alias_is_available_when_name_is_skipped(self) -> None:
        self.assertEqual(generated_alias(7), "Учень 0007")
        self.assertEqual(generated_alias(7, lang="en"), "Player 0007")

    def test_display_name_is_separate_from_unique_room_identity(self) -> None:
        first = self.student("p1", "Оля")
        second = self.student("p2", "Оля")
        roster = ClassroomRoster((first, second))
        self.assertEqual(len(roster.snapshot()), 2)
        self.assertEqual(roster.get("p1").identity.display_name, roster.get("p2").identity.display_name)

    def test_teacher_can_hard_lock_student_microphone_policy(self) -> None:
        roster = ClassroomRoster((self.student(),))
        updated = roster.set_microphone_lock("p1", True)
        self.assertTrue(updated.microphone_hard_locked)
        self.assertTrue(updated.microphone_muted)
        self.assertFalse(updated.permissions.can_publish_microphone)

        restored = roster.set_microphone_lock("p1", False)
        self.assertFalse(restored.microphone_hard_locked)
        self.assertTrue(restored.permissions.can_publish_microphone)

    def test_mute_all_students_does_not_mute_teacher(self) -> None:
        teacher = ClassroomParticipant(
            ParticipantIdentity("teacher", "Coach"),
            ClassroomRole.TEACHER,
            ClassroomPermissions(can_moderate=True, can_deploy_positions=True),
            microphone_muted=False,
        )
        roster = ClassroomRoster((teacher, self.student("p1"), self.student("p2", "Іван")))
        changed = roster.mute_all_students(hard_lock=True)
        self.assertEqual(len(changed), 2)
        self.assertFalse(roster.get("teacher").microphone_muted)
        self.assertFalse(roster.get("p1").permissions.can_publish_microphone)
        self.assertFalse(roster.get("p2").permissions.can_publish_microphone)

    def test_board_control_is_side_specific(self) -> None:
        permissions = ClassroomPermissions(board_control=BoardControl.WHITE)
        self.assertTrue(permissions.can_move_side("w"))
        self.assertFalse(permissions.can_move_side("b"))

    def test_rename_preserves_network_identity(self) -> None:
        roster = ClassroomRoster((self.student(),))
        updated = roster.rename("p1", "Марійка")
        self.assertEqual(updated.identity.room_identity, "p1")
        self.assertEqual(updated.identity.display_name, "Марійка")

    def test_statistics_default_excludes_raw_content_and_audio(self) -> None:
        policy = UsageStatisticsPolicy(scope=StatisticsScope.CLASSROOM)
        self.assertFalse(policy.upload_raw_games)
        self.assertFalse(policy.upload_book_or_database_content)
        self.assertFalse(policy.record_audio)

    def test_aggregate_statistics_contract_rejects_raw_content_collection(self) -> None:
        with self.assertRaises(ValueError):
            UsageStatisticsPolicy(upload_raw_games=True)
        with self.assertRaises(ValueError):
            UsageStatisticsPolicy(record_audio=True)


if __name__ == "__main__":
    unittest.main()
