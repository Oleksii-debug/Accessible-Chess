from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.classroom import (
    BoardControl,
    ClassroomParticipant,
    ClassroomPermissions,
    ClassroomRole,
    ClassroomRoster,
    ParticipantIdentity,
)
from acs.classroom_collaboration_storage import AttachmentMetadata, ChatMessageMetadata
from acs.classroom_presentation import ClassroomPresentationState
from acs.local_profile import LocalProfileStore
from acs.usage_statistics import UsageStatisticsSnapshot


class ClassroomPresentationTests(unittest.TestCase):
    def test_participant_projection_is_concise_and_exposes_missing_camera_contract_truthfully(self) -> None:
        roster = ClassroomRoster((
            ClassroomParticipant(
                ParticipantIdentity("student-1", "Марко"),
                ClassroomRole.STUDENT,
                ClassroomPermissions(
                    can_publish_microphone=False,
                    board_control=BoardControl.WHITE,
                    can_point=True,
                    can_annotate=False,
                ),
                microphone_muted=True,
                microphone_hard_locked=True,
            ),
        ))
        state = ClassroomPresentationState(roster=roster, room_id="lesson-1")
        view = state.snapshot()
        participant = view["room"]["participants"][0]
        self.assertEqual(participant["displayName"], "Марко")
        self.assertEqual(participant["microphone"], "locked")
        self.assertEqual(participant["boardControl"], "white")
        self.assertFalse(view["room"]["mediaCapability"]["camera"])
        self.assertIn("camera", view["room"]["mediaCapability"]["cameraMissingContract"].lower())

    def test_profile_skip_alias_and_rename_use_existing_local_profile_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProfileStore(Path(tmp) / "profile.json")
            state = ClassroomPresentationState(profile_store=store)
            profile = state.ensure_profile()
            self.assertTrue(profile["generatedAlias"])
            self.assertTrue(profile["needsPrompt"])
            alias = profile["displayName"]
            self.assertTrue(alias.startswith("Учень "))

            renamed = state.set_display_name("Олексій")
            self.assertEqual(renamed["displayName"], "Олексій")
            self.assertFalse(renamed["generatedAlias"])
            reopened = store.load_or_create()
            self.assertEqual(reopened.display_name, "Олексій")

    def test_statistics_projection_is_local_only_and_has_privacy_boundary(self) -> None:
        state = ClassroomPresentationState(
            statistics=UsageStatisticsSnapshot(
                "abcdef0123456789",
                sessions_started=3,
                games_started=2,
                games_completed=1,
                classroom_sessions=4,
            )
        )
        view = state.snapshot()["statistics"]
        self.assertEqual(view["syncState"], "local_only")
        self.assertEqual(view["gamesStarted"], 2)
        self.assertIn("Сирі партії", view["privacyText"])
        self.assertIn("чат", view["privacyText"])
        self.assertIn("файли", view["privacyText"])

    def test_incoming_chat_is_ordered_idempotent_unread_and_non_focus_stealing(self) -> None:
        state = ClassroomPresentationState(room_id="lesson-1")
        second = ChatMessageMetadata("m2", "lesson-1", "student-1", 2, "Другий")
        first = ChatMessageMetadata("m1", "lesson-1", "student-1", 1, "Перший")
        state.append_message(second, sender_display_name="Марко")
        state.append_message(first, sender_display_name="Марко")
        state.append_message(first, sender_display_name="Марко")
        view = state.snapshot()["chat"]
        self.assertEqual([row["id"] for row in view["messages"]], ["m1", "m2"])
        self.assertEqual(view["unreadCount"], 2)
        self.assertEqual(state.last_announcement.text, "Нове повідомлення від Марко.")
        self.assertIsNone(state.last_announcement.focus_target)
        state.mark_chat_read()
        self.assertEqual(state.snapshot()["chat"]["unreadCount"], 0)

    def test_attachment_projection_never_auto_opens_and_requires_safe_stored_item(self) -> None:
        state = ClassroomPresentationState(room_id="lesson-1")
        item = AttachmentMetadata(
            "a1",
            "lesson-1",
            "student-1",
            1,
            "lesson.pdf",
            "application/pdf",
            4096,
            "a" * 64,
            "rooms/lesson-1/a1",
            "stored",
            "session",
            "clean",
        )
        view = state.register_attachment(item, sender_display_name="Марко")
        self.assertEqual(view["name"], "lesson.pdf")
        self.assertTrue(view["canSave"])
        self.assertFalse(view["canOpen"])
        self.assertEqual(view["progressPercent"], 100)

    def test_unsafe_attachment_name_fails_visibly_at_presentation_boundary(self) -> None:
        state = ClassroomPresentationState(room_id="lesson-1")
        item = AttachmentMetadata(
            "a1",
            "lesson-1",
            "student-1",
            1,
            "../evil.exe",
            None,
            10,
            "b" * 64,
            "rooms/lesson-1/a1",
            "stored",
            "session",
            "clean",
        )
        with self.assertRaises(ValueError):
            state.register_attachment(item, sender_display_name="Марко")


if __name__ == "__main__":
    unittest.main()
