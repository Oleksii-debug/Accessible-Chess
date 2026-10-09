import unittest
from pathlib import Path
import tempfile

from acs.settings import Settings
from acs.webapp import AccessibleChessAPI


class VideoBoardSyncBridgeTests(unittest.TestCase):
    def test_sync_commits_only_canonical_legal_moves(self):
        api = AccessibleChessAPI("uk")
        started = api.video_sync_start()
        self.assertTrue(started["ok"])
        e4 = next(item for item in started["candidates"] if item["uci"] == "e2e4")
        self.assertEqual(e4["changedSquares"], [12, 28])
        committed = api.video_sync_commit_move("e2e4", 105.5, 0.91)
        self.assertTrue(committed["ok"])
        self.assertIn("e 4", committed["moves"])
        self.assertEqual(committed["videoSync"]["timecode"], 105.5)
        self.assertAlmostEqual(committed["videoSync"]["confidence"], 0.91)

    def test_illegal_or_unbounded_video_events_do_not_mutate_board(self):
        api = AccessibleChessAPI("en")
        api.video_sync_start()
        before = api.get_state()["fen"]
        self.assertFalse(api.video_sync_commit_move("e2e5", 10, 0.9)["ok"])
        self.assertFalse(api.video_sync_commit_move("e2e4", -1, 0.9)["ok"])
        self.assertFalse(api.video_sync_commit_move("e2e4", 10, 1.1)["ok"])
        self.assertEqual(api.get_state()["fen"], before)

    def test_castling_candidate_includes_rook_squares(self):
        api = AccessibleChessAPI("en")
        api.set_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        api.video_sync_active = True
        candidates = api.video_sync_candidates()["candidates"]
        king_side = next(item for item in candidates if item["uci"] == "e1g1")
        self.assertEqual(king_side["changedSquares"], [4, 5, 6, 7])

    def test_background_preparation_builds_timed_history_without_live_mutation(self):
        api = AccessibleChessAPI("en")
        original = api.get_state()["fen"]
        started = api.video_prepare_start()
        self.assertTrue(started["ok"])
        self.assertTrue(api.video_prepare_commit_move("e2e4", 75.0, 0.8)["ok"])
        self.assertTrue(api.video_prepare_commit_move("e7e5", 77.0, 0.9)["ok"])
        self.assertEqual(api.get_state()["fen"], original)

        finished = api.video_prepare_finish()
        self.assertTrue(finished["ok"])
        self.assertEqual(len(finished["timeline"]), 2)
        self.assertEqual(finished["reviewCursor"], 0)
        self.assertIn("No moves", finished["moves"])

        at_first_move = api.video_sync_seek_time(75.5)
        self.assertEqual(at_first_move["reviewCursor"], 1)
        self.assertIn("e 4", at_first_move["moves"])
        at_second_move = api.video_sync_seek_time(80.0)
        self.assertEqual(at_second_move["reviewCursor"], 2)
        self.assertIn("e 5", at_second_move["moves"])

    def test_prepared_timeline_can_be_switched_and_is_revalidated(self):
        api = AccessibleChessAPI("en")
        timeline = [
            {"uci": "d2d4", "timecode": 12.0, "confidence": 0.7},
            {"uci": "d7d5", "timecode": 15.0, "confidence": 0.8},
        ]
        loaded = api.video_sync_load_timeline(timeline)
        self.assertTrue(loaded["ok"])
        self.assertEqual([item["san"] for item in loaded["timeline"]], ["d4", "d5"])
        rejected = api.video_sync_load_timeline([
            {"uci": "e2e5", "timecode": 1.0, "confidence": 1.0},
        ])
        self.assertFalse(rejected["ok"])
        self.assertEqual(api.video_sync_timeline()["timeline"], [])

    def test_prepared_session_survives_settings_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            first = AccessibleChessAPI("en")
            first._settings = Settings(path)
            timeline = [
                {"uci": "e2e4", "timecode": 10.0, "confidence": 0.75},
                {"uci": "e7e5", "timecode": 12.0, "confidence": 0.8},
            ]
            saved = first.video_session_save("video-1", "lesson.mp4", 120.0, timeline)
            self.assertTrue(saved["ok"])

            restarted = AccessibleChessAPI("en")
            restarted._settings = Settings(path)
            loaded = restarted.video_session_get("video-1")
            self.assertTrue(loaded["ok"])
            self.assertEqual([item["san"] for item in loaded["timeline"]], ["e4", "e5"])


if __name__ == "__main__":
    unittest.main()
