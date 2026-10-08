from __future__ import annotations

"""Section 47/48 replay, identity, no-privilege, and provider-negative oracles."""
import unittest

from acs.media_core import MediaSession, MediaPlaybackState, MediaSourceKind
from acs.section47_48_browser_media_clock import (
    BrowserMediaClockError,
    BrowserSourceAuthority,
    accept_browser_clock,
)


LOCAL = {
    "providerId": "html5_local_file_v1",
    "sourceId": "local-file:session-1",
    "sourceKind": "local_file",
    "sourceRevision": 1,
    "ok": True,
    "ready": True,
    "playbackState": "playing",
    "positionMs": 7000,
    "durationMs": 26000,
    "playbackRate": 1.5,
    "qualification": "unlinked",
    "chessRef": None,
}
REMOTE = {
    "providerId": "youtube_iframe_v1",
    "sourceId": "youtube:k4BS-4O1iI0",
    "sourceKind": "remote_media",
    "videoId": "k4BS-4O1iI0",
    "ok": True,
    "ready": True,
    "playbackState": "paused",
    "positionMs": 5000,
    "durationMs": 24000,
    "errorCode": None,
    "autoplayBlocked": False,
    "qualification": "unlinked",
    "chessRef": None,
}
A = BrowserSourceAuthority(
    "local-file:session-1", "trusted-sha256-source-revision", "session-unique-47",
    MediaSourceKind.LOCAL_FILE,
)
B = BrowserSourceAuthority(
    "youtube:k4BS-4O1iI0", "trusted-remote-revision", "session-unique-48",
    MediaSourceKind.PROVIDER,
)


class BrowserMediaClockQualificationTest(unittest.TestCase):
    def test_local_actual_rate_and_position_are_in_canonical_media_session(self):
        session = accept_browser_clock(dict(LOCAL), authority=A)
        self.assertIs(type(session), MediaSession)
        self.assertEqual(session.source_kind, MediaSourceKind.LOCAL_FILE)
        self.assertEqual(session.clock.position_ms, 7000)
        self.assertEqual(session.clock.duration_ms, 26000)
        self.assertEqual(session.clock.state, MediaPlaybackState.PLAYING)
        self.assertEqual(session.clock.playback_rate, 1.5)
        self.assertIsNone(session.timeline_identity)
        self.assertIsNone(session.media_chess_ref)
        self.assertIsNone(session.analysis_chess_ref)

    def test_remote_real_source_class_never_grants_chess_authority(self):
        session = accept_browser_clock(dict(REMOTE), authority=B)
        self.assertEqual(session.source_kind, MediaSourceKind.PROVIDER)
        self.assertEqual(session.clock.state, MediaPlaybackState.PAUSED)
        self.assertEqual(session.clock.playback_rate, 1.0)
        self.assertIsNone(session.media_chess_ref)

    def test_seek_backwards_uses_increased_monotonic_revision(self):
        first = accept_browser_clock(dict(LOCAL), authority=A)
        second = accept_browser_clock({**LOCAL, "positionMs": 0,
            "playbackState": "paused"}, authority=A, previous=first)
        self.assertEqual(second.clock.revision, first.clock.revision + 1)
        self.assertEqual(second.revision, first.revision + 1)
        self.assertEqual(second.clock.position_ms, 0)

    def test_malformed_or_forged_browser_snapshots_fail_closed(self):
        cases = [
            {"providerId": "filesystem_superuser"},
            {"sourceId": "local-file:session-999"},
            {"sourceKind": "remote_media"},
            {"sourceRevision": -1},
            {"ok": False},
            {"ready": False},
            {"playbackState": "recorded_superuser"},
            {"positionMs": True},
            {"positionMs": -1},
            {"positionMs": 27000},
            {"durationMs": -1},
            {"playbackRate": 999},
            {"playbackRate": float("nan")},
            {"qualification": "confirmed"},
            {"chessRef": "e4"},
            {"chessRef": "chess:verified"},
        ]
        for changed in cases:
            with self.subTest(changed=changed):
                with self.assertRaises(BrowserMediaClockError):
                    accept_browser_clock({**LOCAL, **changed}, authority=A)
        with self.assertRaises(BrowserMediaClockError):
            accept_browser_clock({**LOCAL, "filename": "/home/private/video.webm"}, authority=A)
        with self.assertRaises(BrowserMediaClockError):
            accept_browser_clock({**LOCAL, "unsafe": "chess-ref"}, authority=A)

    def test_older_sessions_or_foreign_source_identity_rejected(self):
        previous = accept_browser_clock(dict(LOCAL), authority=A)
        foreign = BrowserSourceAuthority(
            "local-file:session-2", "foreign-revision", "session-unique",
            MediaSourceKind.LOCAL_FILE)
        with self.assertRaises(BrowserMediaClockError):
            accept_browser_clock({**LOCAL, "sourceId": foreign.source_id},
                                 authority=foreign, previous=previous)
        with self.assertRaises(BrowserMediaClockError):
            accept_browser_clock(dict(LOCAL), authority=B)

    def test_remote_provider_failure_and_unsupported_keys_rejected(self):
        for changed in [
            {"videoId": "AAAAAAAAAAA"},
            {"sourceId": "youtube:dQw4w9WgXcQ"},
            {"sourceKind": "local_file"},
            {"providerId": "unofficial_youtube_extractor"},
            {"errorCode": "private"},
            {"autoplayBlocked": "blocked"},
            {"ready": False},
            {"ok": False},
            {"qualification": "confirmed"},
            {"chessRef": "unverified-position"},
        ]:
            with self.subTest(changed=changed):
                with self.assertRaises(BrowserMediaClockError):
                    accept_browser_clock({**REMOTE, **changed}, authority=B)

    def test_source_authority_must_be_exact_host_type(self):
        with self.assertRaises(BrowserMediaClockError):
            accept_browser_clock(dict(LOCAL), authority=object())
        with self.assertRaises(BrowserMediaClockError):
            BrowserSourceAuthority("unsafe\x00", "good-revision", "session", MediaSourceKind.LOCAL_FILE)


if __name__ == "__main__":
    unittest.main()
