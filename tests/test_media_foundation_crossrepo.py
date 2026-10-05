from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.media_foundation import (
    ChessStateReconciler,
    MediaClock,
    MediaContractError,
    MediaPositionBinding,
    MediaPositionTimeline,
    MediaSessionState,
    MediaSourceKind,
    PlaybackState,
    ReconciliationState,
)


AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E4_PLACEMENT = AFTER_E4.split()[0]


class MediaFoundationCrossRepoTests(unittest.TestCase):
    def test_structured_move_is_verified_only_after_canonical_legality(self):
        result = ChessStateReconciler().reconcile_structured_move(
            Board.START,
            "e4",
            authoritative=True,
        )
        self.assertEqual(result.state, ReconciliationState.VERIFIED)
        self.assertEqual(result.move_san, "e4")
        self.assertEqual(result.resulting_fen, AFTER_E4)

    def test_illegal_structured_move_fails_closed(self):
        result = ChessStateReconciler().reconcile_structured_move(
            Board.START,
            "e5",
            authoritative=True,
        )
        self.assertEqual(result.state, ReconciliationState.RESYNC_REQUIRED)
        self.assertIsNone(result.resulting_fen)

    def test_vision_candidate_can_only_infer_unique_legal_transition(self):
        result = ChessStateReconciler().reconcile_board_placement(
            Board.START,
            AFTER_E4_PLACEMENT,
            confidence=0.99,
        )
        self.assertEqual(result.state, ReconciliationState.INFERRED)
        self.assertEqual(result.move_san, "e4")
        self.assertEqual(result.resulting_fen, AFTER_E4)

    def test_low_confidence_vision_never_changes_canonical_state(self):
        result = ChessStateReconciler().reconcile_board_placement(
            Board.START,
            AFTER_E4_PLACEMENT,
            confidence=0.2,
        )
        self.assertEqual(result.state, ReconciliationState.OBSERVED)
        self.assertIsNone(result.resulting_fen)
        self.assertEqual(result.candidate_san, ("e4",))

    def test_unreachable_high_confidence_position_requires_resync(self):
        impossible_transition = "rnbqkbnr/pppppppp/8/8/4P3/3P4/PPP2PPP/RNBQKBNR"
        result = ChessStateReconciler().reconcile_board_placement(
            Board.START,
            impossible_transition,
            confidence=0.99,
        )
        self.assertEqual(result.state, ReconciliationState.RESYNC_REQUIRED)
        self.assertIsNone(result.resulting_fen)

    def test_timeline_restore_tracks_media_timestamp_not_user_analysis(self):
        timeline = MediaPositionTimeline(
            (
                MediaPositionBinding(
                    0,
                    1000,
                    Board.START,
                    tree_path=(),
                ),
                MediaPositionBinding(
                    1000,
                    3000,
                    AFTER_E4,
                    tree_path=(0,),
                ),
            )
        )
        self.assertEqual(timeline.restore_fen(0), Board().fen())
        self.assertEqual(timeline.restore_fen(1500), AFTER_E4)
        with self.assertRaises(MediaContractError):
            timeline.restore_fen(5000)

    def test_clock_seek_pause_and_rate_publish_revisioned_state(self):
        clock = MediaClock(
            MediaSessionState(
                session_id="session-1",
                source_id="video-1",
                source_kind=MediaSourceKind.LOCAL_FILE,
                duration_ms=10_000,
            )
        )
        self.assertEqual(clock.state.revision, 0)
        clock.set_state(PlaybackState.PLAYING)
        clock.seek(2500)
        clock.set_rate(1.5)
        clock.set_state(PlaybackState.PAUSED)
        self.assertEqual(clock.state.position_ms, 2500)
        self.assertEqual(clock.state.playback_rate, 1.5)
        self.assertEqual(clock.state.playback_state, PlaybackState.PAUSED)
        self.assertEqual(clock.state.revision, 4)


if __name__ == "__main__":
    unittest.main()
