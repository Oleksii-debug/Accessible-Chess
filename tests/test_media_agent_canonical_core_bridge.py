from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from acs.chess_agent_tools import ChessAgentToolsError, MediaAgentBridge
from acs.media_application import MediaApplicationError, MediaApplicationService
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaSource,
    MediaSourceKind as CoreMediaSourceKind,
)
from acs.media_foundation import (
    MediaClock,
    MediaSessionState,
    MediaSourceKind as RuntimeMediaSourceKind,
)


def _clock(source_id: str = "media-opaque", position_ms: int = 1500) -> MediaClock:
    return MediaClock(
        MediaSessionState(
            session_id="agent-media-session",
            source_id=source_id,
            source_kind=RuntimeMediaSourceKind.LOCAL_FILE,
            position_ms=position_ms,
            duration_ms=5000,
        )
    )


def _source(source_id: str = "media-opaque") -> MediaSource:
    return MediaSource(
        source_id=source_id,
        title="Agent bridge fixture",
        kind=CoreMediaSourceKind.LOCAL_FILE,
        duration_ms=5000,
    )


def _application(
    timeline: MediaPositionTimeline,
    restored: list[str],
    *,
    source_id: str = "media-opaque",
) -> MediaApplicationService:
    return MediaApplicationService(
        source=_source(source_id),
        timeline=timeline,
        session=MediaChessSession(MediaCursor(source_id, 0)),
        restore_chess_ref=lambda chess_ref: restored.append(chess_ref),
    )


class MediaAgentCanonicalCoreBridgeTests(unittest.TestCase):
    def test_status_projects_provider_time_without_mutating_application_cursor(self):
        timeline = MediaPositionTimeline(
            "media-opaque",
            (
                MediaChessLink(
                    "media-opaque",
                    1000,
                    "tree:provider-view",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                ),
            ),
        )
        restored = []
        application = _application(timeline, restored)
        bridge = MediaAgentBridge(clock=_clock(), application=application)

        status = bridge.status()

        self.assertEqual(status["positionMs"], 1500)
        self.assertEqual(status["synchronizedChessRef"], "tree:provider-view")
        self.assertEqual(status["qualification"], "confirmed")
        self.assertTrue(status["canRestore"])
        self.assertIn("confirmed chess position", status["statusText"].lower())
        self.assertEqual(application.session.media_cursor.position_ms, 0)
        self.assertEqual(application.revision, 0)
        self.assertEqual(restored, [])

    def test_restore_passes_opaque_reference_through_application_boundary(self):
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
        application = _application(timeline, restored)
        bridge = MediaAgentBridge(clock=_clock(), application=application)

        result = bridge.restore()

        self.assertEqual(restored, ["opaque:not-a-fen"])
        self.assertEqual(result["chessRef"], "opaque:not-a-fen")
        self.assertEqual(result["anchorPositionMs"], 1000)
        self.assertEqual(result["positionMs"], 1500)
        self.assertEqual(result["applicationRevision"], 1)
        self.assertIn("Restored the chess position", result["accessibleText"])
        self.assertEqual(application.session.media_cursor.position_ms, 1500)
        self.assertEqual(application.session.chess_ref, "opaque:not-a-fen")
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
        application = _application(timeline, restored)
        bridge = MediaAgentBridge(clock=_clock(), application=application)

        with self.assertRaises(MediaApplicationError):
            bridge.restore()

        self.assertEqual(restored, [])
        self.assertEqual(application.session.media_cursor.position_ms, 0)
        self.assertEqual(application.revision, 0)

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
        application = _application(timeline, restored)
        bridge = MediaAgentBridge(clock=_clock(), application=application)

        with self.assertRaises(MediaApplicationError):
            bridge.restore()

        self.assertEqual(restored, [])
        self.assertEqual(application.revision, 0)
        status = bridge.status()
        self.assertTrue(status["synchronizationAmbiguous"])
        self.assertEqual(status["qualification"], "ambiguous")

    def test_clock_and_application_source_mismatch_is_rejected_at_composition(self):
        application = _application(
            MediaPositionTimeline("different-source", ()),
            [],
            source_id="different-source",
        )
        with self.assertRaises(ChessAgentToolsError):
            MediaAgentBridge(
                clock=_clock(),
                application=application,
            )

    def test_qualification_gate_covers_full_eight_path_bridge_scope(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "media-agent-canonical-core-bridge.yml"
        ).read_text(encoding="utf-8")
        for path in (
            "acs/media_application.py",
            "tests/test_media_application.py",
        ):
            with self.subTest(path=path):
                self.assertIn(f"'{path}'", workflow)

    def test_agent_bridge_contains_no_timeline_or_chess_mutation_authority(self):
        restore_source = inspect.getsource(MediaAgentBridge.restore)
        status_source = inspect.getsource(MediaAgentBridge.status)
        self.assertIn("application.restore_media_position", restore_source)
        self.assertIn("application.snapshot_at", status_source)
        for forbidden in (
            "timeline",
            "restore_chess_ref",
            "restore_fen",
            "set_fen",
            "Board(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, restore_source + status_source)


if __name__ == "__main__":
    unittest.main()
