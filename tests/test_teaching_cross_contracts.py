from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.board_service import BoardSnapshot
from acs.child_coaching_ui import ChildCoachingPresentationState
from acs.classroom import (
    BoardControl,
    ClassroomParticipant,
    ClassroomPermissions,
    ClassroomRole,
    ParticipantIdentity,
    UsageStatisticsPolicy,
)
from acs.classroom_collaboration_storage import AttachmentMetadata, ChatMessageMetadata
from acs.lesson_plan import (
    ClassroomPairing,
    LessonItem,
    LessonItemKind,
    LessonPlan,
    LessonPosition,
)
from acs.lesson_session_storage import LessonSessionSQLiteStore
from acs.sound_events import SoundEvent
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundEventPreference, SoundProfile
from acs.sound_runtime import SoundRuntime, SoundRuntimeSettings
from acs.teaching_controls import CoachPointerService
from acs.teaching_ui import TeachingUiState
from acs.usage_statistics import UsageStatisticsSnapshot
from acs.visual_preferences import BoardVisualPreferences, CoordinateMode


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class _Playback:
    def __init__(self) -> None:
        self.calls: list[tuple[SoundEvent, int]] = []

    def play(self, event: SoundEvent, *, volume: int) -> None:
        self.calls.append((event, volume))


class TeachingCrossContractTests(unittest.TestCase):
    def test_pointer_coordinates_and_visual_preferences_never_mutate_board(self) -> None:
        board = BoardSnapshot(tuple([None] * 64), "w")
        before = board
        ui = TeachingUiState(
            visual=BoardVisualPreferences(coordinate_mode=CoordinateMode.EVERY_SQUARE)
        )
        result = ui.commit_pointer("f3")
        labels = ui.coordinate_labels_for("f3")
        self.assertEqual(result["square"], "f3")
        self.assertTrue(result["clearInput"])
        self.assertTrue(result["keepFocus"])
        self.assertTrue(labels["showEverySquare"])
        self.assertEqual(board, before)
        self.assertEqual(board.turn, "w")

    def test_semantic_pointer_service_never_mutates_chess_board_state(self) -> None:
        board = BoardSnapshot(tuple([None] * 64), "w")
        before = board
        pointer = CoachPointerService()
        commit = pointer.commit_text("f3")
        self.assertEqual(commit.square, "f3")
        self.assertTrue(commit.clear_input)
        self.assertTrue(commit.keep_focus)
        self.assertEqual(board, before)

    def test_sound_profile_ids_match_production_sound_runtime_events(self) -> None:
        self.assertEqual(set(CORE_SOUND_EVENTS), {event.value for event in SoundEvent})
        profile = SoundProfile(
            master_volume_percent=50,
            events={"move": SoundEventPreference(volume_percent=40)},
        )
        playback = _Playback()
        runtime = SoundRuntime(
            playback,
            settings=SoundRuntimeSettings(volume=profile.effective_volume("move")),
        )
        report = runtime.dispatch((SoundEvent.MOVE,))
        self.assertTrue(report.ok)
        self.assertEqual(playback.calls, [(SoundEvent.MOVE, 20)])
        self.assertEqual(profile.effective_volume("check"), 50)

    def test_lesson_position_preserves_exact_core_fen_payload(self) -> None:
        position = LessonPosition("start", "Start", START_FEN)
        self.assertEqual(position.fen, START_FEN)
        self.assertEqual(len(position.fen.split()), 6)
        self.assertEqual(position.fen.split()[1], "w")

    def test_classroom_permissions_do_not_own_or_share_game_state(self) -> None:
        student = ClassroomParticipant(
            ParticipantIdentity("room-student-1", "Student"),
            ClassroomRole.STUDENT,
            ClassroomPermissions(board_control=BoardControl.WHITE),
        )
        first = ClassroomPairing("pair-1", "student-a", "student-b", 600, 5, START_FEN)
        second = ClassroomPairing("pair-2", "student-c", "student-d", 600, 5, START_FEN)
        self.assertTrue(student.permissions.can_move_side("w"))
        self.assertFalse(student.permissions.can_move_side("b"))
        self.assertNotEqual(first.pairing_id, second.pairing_id)
        self.assertNotEqual(
            {first.white_participant_id, first.black_participant_id},
            {second.white_participant_id, second.black_participant_id},
        )

    def test_pairing_storage_keeps_independent_game_session_ids_and_exact_fen(self) -> None:
        pairing = ClassroomPairing("pair-1", "student-a", "student-b", 600, 5, START_FEN)
        with tempfile.TemporaryDirectory() as tmp:
            store = LessonSessionSQLiteStore(
                Path(tmp) / "lessons.sqlite3",
                fen_validator=lambda fen: None if fen == START_FEN else (_ for _ in ()).throw(ValueError("bad fen")),
            )
            batch = store.record_pairing_batch(
                batch_id="batch-1",
                lesson_id="lesson-1",
                classroom_session_id="classroom-1",
                pairings=(pairing,),
                game_session_ids=("game-session-1",),
            )
            record = batch.records[0]
            self.assertEqual(record.start_fen, START_FEN)
            self.assertEqual(record.game_session_id, "game-session-1")
            self.assertEqual(record.classroom_session_id, "classroom-1")
            self.assertIsNotNone(store.find_by_game_session("game-session-1"))

    def test_identity_and_statistics_privacy_boundaries_remain_separate(self) -> None:
        identity = ParticipantIdentity(
            "room-identity-123",
            "Visible Name",
            installation_id="installation-secret-boundary",
        )
        snapshot = UsageStatisticsSnapshot("installation-secret-boundary")
        payload = snapshot.as_dict()
        policy = UsageStatisticsPolicy()
        self.assertEqual(payload["installation_id"], identity.installation_id)
        self.assertNotIn("room_identity", payload)
        self.assertNotIn("display_name", payload)
        self.assertNotIn("raw_pgn", payload)
        self.assertFalse(policy.upload_raw_games)
        self.assertFalse(policy.upload_book_or_database_content)
        self.assertFalse(policy.record_audio)

    def test_chat_and_file_sender_identity_uses_stable_room_identity_not_display_name(self) -> None:
        identity = ParticipantIdentity("room-student-42", "Student Name")
        message = ChatMessageMetadata(
            message_id="msg-1",
            room_id="room-1",
            sender_id=identity.room_identity,
            sequence_no=1,
            body="hello",
        )
        attachment = AttachmentMetadata(
            attachment_id="file-1",
            room_id="room-1",
            sender_id=identity.room_identity,
            sequence_no=2,
            display_name="notes.bin",
            mime_type="application/octet-stream",
            size_bytes=3,
            sha256="0" * 64,
            object_key="room-1/file-1",
            transfer_state="pending",
        )
        renamed = ParticipantIdentity(identity.room_identity, "Renamed Student")
        self.assertEqual(message.sender_id, renamed.room_identity)
        self.assertEqual(attachment.sender_id, renamed.room_identity)
        self.assertNotEqual(message.sender_id, renamed.display_name)
        self.assertNotEqual(attachment.sender_id, renamed.display_name)

    def test_age_template_deployment_reuses_lesson_position_contract_without_board_ownership(self) -> None:
        position = LessonPosition("start", "Start position", START_FEN)
        lesson = LessonPlan(
            lesson_id="lesson-1",
            title="Beginner lesson",
            age_band="4-6",
            level="beginner",
            items=(LessonItem("item-1", LessonItemKind.POSITION, "Show start", 5, position_id="start"),),
            positions=(position,),
        )
        state = ChildCoachingPresentationState(lesson=lesson, participant_ids=("student-1", "student-2"))
        preset = state.select_template("preschool")
        deployment = state.deploy_selected("participants", participant_ids=("student-1",))
        self.assertEqual(preset["templateId"], "preschool")
        self.assertTrue(deployment["ok"])
        self.assertEqual(deployment["positionId"], position.position_id)
        self.assertEqual(deployment["fen"], START_FEN)
        self.assertEqual(deployment["participantIds"], ["student-1"])
        self.assertFalse(deployment["mutatesGameHere"])


if __name__ == "__main__":
    unittest.main()
