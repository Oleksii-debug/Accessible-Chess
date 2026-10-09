import unittest

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


if __name__ == "__main__":
    unittest.main()
