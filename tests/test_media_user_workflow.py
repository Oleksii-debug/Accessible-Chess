from __future__ import annotations

import unittest

from acs.media_application import MediaApplicationService
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaSource,
    MediaSourceKind,
)
from acs.media_user_workflow import (
    MediaPlaybackSnapshot,
    MediaUserWorkflowContext,
    MediaUserWorkflowError,
    MediaUserWorkflowService,
)


class _HostPlayback:
    def __init__(self, source_id: str, *, position_ms: int = 20_500) -> None:
        self.source_id = source_id
        self.position_ms = position_ms
        self.duration_ms = 60_000
        self.playback_state = "playing"
        self.calls: list[tuple[str, int | None]] = []

    def snapshot(self) -> MediaPlaybackSnapshot:
        return MediaPlaybackSnapshot(
            self.source_id,
            self.position_ms,
            self.duration_ms,
            self.playback_state,
        )

    def play(self) -> None:
        self.calls.append(("play", None))
        self.playback_state = "playing"

    def pause(self) -> None:
        self.calls.append(("pause", None))
        self.playback_state = "paused"

    def seek(self, position_ms: int) -> None:
        self.calls.append(("seek", position_ms))
        self.position_ms = position_ms


def _application(
    restored: list[str],
    *,
    source_id: str,
    kind: MediaSourceKind,
) -> MediaApplicationService:
    source = MediaSource(
        source_id=source_id,
        title="Section 20 fixture",
        kind=kind,
        duration_ms=60_000,
    )
    timeline = MediaPositionTimeline(
        source_id,
        (
            MediaChessLink(
                source_id,
                20_000,
                "opaque:canonical-a",
                status=MediaLinkStatus.CONFIRMED,
                confidence=1.0,
            ),
            MediaChessLink(
                source_id,
                40_000,
                "opaque:canonical-b",
                status=MediaLinkStatus.CONFIRMED,
                confidence=1.0,
            ),
        ),
    )
    session = MediaChessSession(
        MediaCursor(source_id, 20_500),
        "opaque:analysis-start",
    )
    return MediaApplicationService(
        source=source,
        timeline=timeline,
        session=session,
        restore_chess_ref=lambda ref: restored.append(ref),
    )


class MediaUserWorkflowTests(unittest.TestCase):
    def test_local_open_pause_explore_seek_and_restore_are_one_workflow(self) -> None:
        restored: list[str] = []
        application = _application(
            restored,
            source_id="local:fixture",
            kind=MediaSourceKind.LOCAL_FILE,
        )
        playback = _HostPlayback("local:fixture")
        context = MediaUserWorkflowContext(
            application=application,
            provider_kind="host",
            playback=playback,
        )
        service = MediaUserWorkflowService(
            open_pasted_source=lambda _source: context,
            open_local_source=lambda: context,
            language="uk",
        )

        opened = service.open_local()
        self.assertEqual("host", opened["providerKind"])
        self.assertEqual("confirmed", opened["player"]["qualification"])
        self.assertTrue(opened["player"]["restoreEnabled"])

        paused = service.command("pause")
        self.assertEqual("paused", paused["player"]["playbackState"])
        self.assertEqual([("pause", None)], playback.calls)

        # Section 20.2: temporary Board/Stockfish/Library exploration remains a
        # separate analysis cursor while the media cursor stays frozen.
        application.select_analysis_chess_ref("opaque:analysis-variation")
        explored = service.snapshot()
        self.assertEqual("opaque:analysis-variation", application.session.chess_ref)
        self.assertEqual(20_500, application.session.media_cursor.position_ms)
        self.assertNotIn("opaque:", repr(explored))

        sought = service.command("seek", position_ms=40_500)
        self.assertEqual(("seek", 40_500), playback.calls[-1])
        self.assertEqual(40_500, application.session.media_cursor.position_ms)
        self.assertEqual("opaque:analysis-variation", application.session.chess_ref)
        self.assertEqual("confirmed", sought["player"]["qualification"])

        restored_state = service.command("restore")
        self.assertEqual(["opaque:canonical-b"], restored)
        self.assertEqual("opaque:canonical-b", application.session.chess_ref)
        self.assertIn("Відновлено", restored_state["player"]["announcement"])
        self.assertNotIn("opaque:", repr(restored_state))

    def test_pasted_youtube_uses_browser_clock_but_never_browser_chess_truth(self) -> None:
        restored: list[str] = []
        source_id = "youtube:dQw4w9WgXcQ"
        application = _application(
            restored,
            source_id=source_id,
            kind=MediaSourceKind.PROVIDER,
        )
        seen: list[str] = []

        def open_pasted(value: str) -> MediaUserWorkflowContext:
            seen.append(value)
            return MediaUserWorkflowContext(
                application=application,
                provider_kind="youtube",
            )

        service = MediaUserWorkflowService(
            open_pasted_source=open_pasted,
            language="en",
        )
        opened = service.open_pasted("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(
            ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
            seen,
        )
        self.assertEqual("youtube", opened["providerKind"])
        self.assertFalse(opened["player"]["ok"])

        synchronized = service.sync_browser_playback(
            source_id=source_id,
            position_ms=20_500,
            duration_ms=60_000,
            playback_state="paused",
        )
        self.assertEqual("confirmed", synchronized["player"]["qualification"])
        self.assertTrue(synchronized["player"]["restoreEnabled"])
        self.assertNotIn("opaque:", repr(synchronized))

        application.select_analysis_chess_ref("opaque:temporary-analysis")
        restored_state = service.command("restore")
        self.assertEqual(["opaque:canonical-a"], restored)
        self.assertNotIn("opaque:", repr(restored_state))

        with self.assertRaisesRegex(MediaUserWorkflowError, "browser playback"):
            service.command("play")
        with self.assertRaisesRegex(MediaUserWorkflowError, "another media source"):
            service.sync_browser_playback(
                source_id="youtube:AAAAAAAAAAA",
                position_ms=20_500,
                duration_ms=60_000,
                playback_state="paused",
            )

    def test_local_picker_cancel_is_accessible_and_does_not_create_state(self) -> None:
        service = MediaUserWorkflowService(
            open_pasted_source=lambda _source: (_ for _ in ()).throw(RuntimeError()),
            open_local_source=lambda: None,
            language="uk",
        )

        state = service.open_local()

        self.assertFalse(state["ok"])
        self.assertIsNone(state["providerKind"])
        self.assertIn("не вибрано", state["player"]["announcement"])
        self.assertIsNone(service.active_context)

    def test_invalid_open_and_provider_facts_fail_closed(self) -> None:
        service = MediaUserWorkflowService(
            open_pasted_source=lambda _source: object(),  # type: ignore[return-value]
            language="en",
        )
        with self.assertRaises(MediaUserWorkflowError):
            service.open_pasted("https://example.invalid/media")
        with self.assertRaises(MediaUserWorkflowError):
            service.open_pasted("   ")

        restored: list[str] = []
        application = _application(
            restored,
            source_id="youtube:dQw4w9WgXcQ",
            kind=MediaSourceKind.PROVIDER,
        )
        safe = MediaUserWorkflowService(
            open_pasted_source=lambda _source: MediaUserWorkflowContext(
                application=application,
                provider_kind="youtube",
            ),
            language="en",
        )
        safe.open_pasted("dQw4w9WgXcQ")
        with self.assertRaises(MediaUserWorkflowError):
            safe.sync_browser_playback(
                source_id="youtube:dQw4w9WgXcQ",
                position_ms=60_001,
                duration_ms=60_000,
                playback_state="paused",
            )
        with self.assertRaises(MediaUserWorkflowError):
            safe.sync_browser_playback(
                source_id="youtube:dQw4w9WgXcQ",
                position_ms=20_500,
                duration_ms=60_000,
                playback_state="bogus",
            )


if __name__ == "__main__":
    unittest.main()
