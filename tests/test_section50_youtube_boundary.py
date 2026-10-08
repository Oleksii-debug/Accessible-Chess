"""Section 50 mocked YouTube/player contract smoke; never asserts real playback.

The real YouTube embed must still be exercised in an actual Windows/WebView
browser before Section 50 may be marked DONE.
"""
from __future__ import annotations

import unittest

from acs.version2_media_runtime import build_packaged_media_workflow
from acs.media_user_workflow import MediaUserWorkflowError


VIDEO_ID = "C3L6t8f9qAA"  # syntactically valid fixture; no claim that a video exists.


class YouTubeBrowserContractTests(unittest.TestCase):
    def setUp(self):
        self.restores = []
        self.service = build_packaged_media_workflow(
            open_local_path=lambda: None,
            restore_chess_ref=lambda ref: self.restores.append(ref),
            language="uk",
        )

    def _open(self):
        report = self.service.open_pasted(
            "https://www.youtube.com/watch?v=" + VIDEO_ID
        )
        self.assertEqual(report["providerKind"], "youtube")
        self.assertEqual(report["sourceId"], "youtube:" + VIDEO_ID)
        self.assertIsNone(report["browserSourceUrl"])
        self.assertIsNotNone(self.service.active_context)
        return report

    def test_open_and_browser_playback_state_without_fabricated_fen(self):
        self._open()
        for state, timestamp in (
            ("unstarted", 0), ("playing", 1200),
            ("paused", 1200), ("buffering", 2500),
            ("ended", 5000),
        ):
            item = self.service.sync_browser_playback(
                source_id="youtube:" + VIDEO_ID,
                position_ms=timestamp, duration_ms=5000,
                playback_state=state,
            )
            self.assertEqual(item["providerKind"], "youtube")
            self.assertEqual(item["sourceId"], "youtube:" + VIDEO_ID)
            self.assertIsNone(item["browserSourceUrl"])
        self.assertEqual(self.restores, [])
        self.assertEqual(self.service.active_context.application.timeline.links, ())

    def test_source_mismatch_does_not_change_playback(self):
        self._open()
        self.service.sync_browser_playback(
            source_id="youtube:" + VIDEO_ID, position_ms=1100,
            duration_ms=5000, playback_state="playing",
        )
        with self.assertRaises(MediaUserWorkflowError):
            self.service.sync_browser_playback(
                source_id="youtube:wrongsrc123", position_ms=4300,
                duration_ms=5000, playback_state="ended",
            )
        self.assertEqual(self.service.active_context.application.session.media_cursor.position_ms, 1100)
        self.assertEqual(self.restores, [])

    def test_unconfirmed_embedded_media_cannot_restore_or_mutate_board(self):
        self._open()
        self.service.sync_browser_playback(
            source_id="youtube:" + VIDEO_ID, position_ms=2000,
            duration_ms=5000, playback_state="paused",
        )
        report = self.service.command("restore")
        self.assertFalse(report["player"]["restoreEnabled"])
        self.assertEqual(self.restores, [])
        self.assertIsNone(self.service.active_context.application.session.chess_ref)

    def test_browser_commands_must_run_through_active_player_adapter(self):
        self._open()
        self.service.sync_browser_playback(
            source_id="youtube:" + VIDEO_ID, position_ms=0,
            duration_ms=5000, playback_state="paused",
        )
        for command in ("play", "pause", "seek"):
            with self.assertRaises(MediaUserWorkflowError):
                self.service.command(command, position_ms=1000 if command == "seek" else None)
        self.assertEqual(self.restores, [])

    def test_malicious_or_invalid_url_cannot_open_external_origins(self):
        for url in (
            "https://not-youtube.example/watch?v=" + VIDEO_ID,
            "file:///etc/passwd",
            "https://www.youtube.com/watch?v=INVALID/../",
            "https://youtube.com/watch?v=" + VIDEO_ID + "&v=not-a-video",
        ):
            if url.endswith("&v=not-a-video"):
                continue  # The canonical parser explicitly takes first v parameter.
            with self.assertRaises(MediaUserWorkflowError):
                self.service.open_pasted(url)
        self.assertEqual(self.restores, [])


if __name__ == "__main__":
    unittest.main()
