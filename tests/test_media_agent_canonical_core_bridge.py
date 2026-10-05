from __future__ import annotations

import inspect
import unittest

from acs.chess_agent_tools import ChessAgentToolsError, MediaAgentBridge
from acs.media_core import MediaChessLink, MediaLinkStatus, MediaPositionTimeline
from acs.media_foundation import MediaClock, MediaSessionState, MediaSourceKind


def _clock(source_id: str = "media-opaque", position_ms: int = 1500) -> MediaClock:
    return MediaClock(
        MediaSessionState(
            session_id="agent-media-session",
            source_id=source_id,
            source_kind=MediaSourceKind.LOCAL_FILE,
            position_ms=position_ms,
            duration_ms=5000,
        )
    )


class MediaAgentCanonicalCoreBridgeTests(unittest.TestCase):
    def test_restore_passes_opaque_reference_without_fen_interpretation(self):
        timeline = MediaPositionTimeline(
            "media-opaque",
            (
                MediaChessLink(
                    "media-opaque",
                    1000,
                    "opaque:not-a-fen",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                    evidence="canonical fixture",
                ),
            ),
        )
        restored = []
        bridge = MediaAgentBridge(
            clock=_clock(),
            timeline=timeline,
            restore_chess_ref=lambda chess_ref: restored.append(chess_ref),
        )
        result = bridge.restore()
        self.assertEqual(restored, ["opaque:not-a-fen"])
        self.assertEqual(result["chessRef"], "opaque:not-a-fen")
        self.assertEqual(result["anchorPositionMs"], 1000)
        self.assertNotIn("fen", result)
        self.assertNotIn("treePath", result)

    def test_candidate_only_reference_fails_before_application_mutation(self):
        timeline = MediaPositionTimeline(
            "media-opaque",
            (
                MediaChessLink(
                    "media-opaque",
                    1000,
                    "tree:candidate",
                    status=MediaLinkStatus.CANDIDATE,
                    confidence=0.99,
                ),
            ),
        )
        restored = []
        bridge = MediaAgentBridge(
            clock=_clock(),
            timeline=timeline,
            restore_chess_ref=lambda chess_ref: restored.append(chess_ref),
        )
        with self.assertRaises(ChessAgentToolsError):
            bridge.restore()
        self.assertEqual(restored, [])
        status = bridge.status()
        self.assertEqual(status["qualification"], "candidate")
        self.assertIsNone(status["synchronizedChessRef"])

    def test_conflicting_confirmed_references_fail_before_application_mutation(self):
        timeline = MediaPositionTimeline(
            "media-opaque",
            (
                MediaChessLink(
                    "media-opaque",
                    1000,
                    "tree:a",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                ),
                MediaChessLink(
                    "media-opaque",
                    1000,
                    "tree:b",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                ),
            ),
        )
        restored = []
        bridge = MediaAgentBridge(
            clock=_clock(),
            timeline=timeline,
            restore_chess_ref=lambda chess_ref: restored.append(chess_ref),
        )
        with self.assertRaises(ChessAgentToolsError):
            bridge.restore()
        self.assertEqual(restored, [])
        status = bridge.status()
        self.assertTrue(status["synchronizationAmbiguous"])
        self.assertEqual(status["qualification"], "ambiguous")

    def test_clock_and_timeline_source_mismatch_is_rejected_at_composition(self):
        timeline = MediaPositionTimeline("different-source", ())
        with self.assertRaises(ChessAgentToolsError):
            MediaAgentBridge(
                clock=_clock(),
                timeline=timeline,
                restore_chess_ref=lambda _chess_ref: None,
            )

    def test_restore_source_has_no_parallel_fen_or_board_mutation_path(self):
        source = inspect.getsource(MediaAgentBridge.restore)
        self.assertNotIn("restore_fen", source)
        self.assertNotIn("set_fen", source)
        self.assertNotIn("Board(", source)
        self.assertIn("restore_chess_ref", source)


if __name__ == "__main__":
    unittest.main()
