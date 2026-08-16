from __future__ import annotations

import unittest

from acs.board_service import BoardSnapshot
from acs.classroom import (
    BoardControl,
    ClassroomParticipant,
    ClassroomPermissions,
    ClassroomRole,
    ParticipantIdentity,
    UsageStatisticsPolicy,
)
from acs.lesson_plan import ClassroomPairing, LessonPosition
from acs.sound_events import SoundEvent
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundEventPreference, SoundProfile
from acs.sound_runtime import SoundRuntime, SoundRuntimeSettings
from acs.teaching_controls import CoachPointerService
from acs.usage_statistics import UsageStatisticsSnapshot


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class _Playback:
    def __init__(self) -> None:
        self.calls: list[tuple[SoundEvent, int]] = []

    def play(self, event: SoundEvent, *, volume: int) -> None:
        self.calls.append((event, volume))


class TeachingCrossContractTests(unittest.TestCase):
    def test_semantic_pointer_never_mutates_chess_board_state(self) -> None:
        board = BoardSnapshot(tuple([None] * 64), "w")
        before = board
        pointer = CoachPointerService()
        commit = pointer.commit_text("f3")
        self.assertEqual(commit.square, "f3")
        self.assertTrue(commit.clear_input)
        self.assertTrue(commit.keep_focus)
        self.assertEqual(board, before)
        self.assertEqual(board.turn, "w")

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


if __name__ == "__main__":
    unittest.main()
