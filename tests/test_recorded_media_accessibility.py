from __future__ import annotations

import unittest

from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaSource,
    MediaSourceKind,
)
from acs.media_preprocess import (
    PreprocessCheckpoint,
    PreprocessStatus,
)
from acs.recorded_media_sync import (
    AccessibleRecordedSyncEvent,
    RecordedPlaybackResolution,
    RecordedSyncSnapshot,
)
from acs.recorded_media_accessibility import (
    RecordedMediaAccessibilityBridge,
    RecordedMediaAccessibilityError,
    RecordedMediaPlayerCommand,
)


def _source() -> MediaSource:
    return MediaSource(
        source_id="recorded-1",
        title="Blind-user presentation fixture",
        kind=MediaSourceKind.LOCAL_FILE,
        duration_ms=120_000,
    )


def _link(
    timestamp_ms: int,
    chess_ref: str,
    *,
    confirmed: bool = True,
) -> MediaChessLink:
    return MediaChessLink(
        "recorded-1",
        timestamp_ms,
        chess_ref,
        status=MediaLinkStatus.CONFIRMED if confirmed else MediaLinkStatus.CANDIDATE,
        confidence=1.0 if confirmed else 0.6,
        evidence="fixture evidence",
    )


def _clock_kwargs(
    position_ms: int = 20_500,
    *,
    playback_state: str = "paused",
) -> dict[str, object]:
    return {
        "position_ms": position_ms,
        "duration_ms": 120_000,
        "playback_state": playback_state,
        "revision": 7,
    }

def _sync_snapshot(
    links: tuple[MediaChessLink, ...],
    position_ms: int = 20_500,
) -> RecordedSyncSnapshot:
    return RecordedSyncSnapshot(
        source_revision="revision-1",
        cache_fingerprint="cache-fingerprint",
        plan_digest="plan-digest",
        source=_source(),
        timeline=MediaPositionTimeline("recorded-1", links),
        session=MediaChessSession(
            MediaCursor("recorded-1", position_ms),
            "opaque:current-node",
        ),
    )


def _checkpoint(status: PreprocessStatus, completed: int, total: int) -> PreprocessCheckpoint:
    return PreprocessCheckpoint(
        "recorded-1",
        "revision-1",
        "cache-fingerprint",
        "plan-digest",
        completed,
        total,
        completed,
        1,
        status,
    )


class RecordedMediaAccessibilityBridgeTests(unittest.TestCase):
    def test_confirmed_snapshot_is_browser_safe_and_copyable(self) -> None:
        bridge = RecordedMediaAccessibilityBridge(language="en")

        state = bridge.snapshot(
            **_clock_kwargs(),
            sync_snapshot=_sync_snapshot((_link(20_000, "opaque:confirmed-node"),)),
            preprocess=_checkpoint(PreprocessStatus.COMPLETE, 4, 4),
        )

        self.assertTrue(state["ok"])
        self.assertEqual(state["qualification"], "confirmed")
        self.assertTrue(state["restoreEnabled"])
        self.assertEqual(state["playAction"], "play")
        self.assertEqual(state["positionText"], "00:20")
        self.assertEqual(state["preprocessStatus"], "complete")
        self.assertEqual(state["preprocessCompleted"], 4)
        self.assertEqual(state["preprocessTotal"], 4)
        rendered = repr(state)
        self.assertNotIn("opaque:confirmed-node", rendered)
        self.assertNotIn("opaque:current-node", rendered)
        self.assertNotIn("sourceId", state)
        self.assertNotIn("chessRef", state)

    def test_browser_crossing_integers_stay_within_javascript_safe_range(self) -> None:
        bridge = RecordedMediaAccessibilityBridge(language="en")
        unsafe = 9_007_199_254_740_992

        for kwargs in (
            {"position_ms": unsafe},
            {"duration_ms": unsafe},
            {"revision": unsafe},
        ):
            with self.assertRaises(RecordedMediaAccessibilityError):
                bridge.snapshot(**kwargs)

        with self.assertRaises(RecordedMediaAccessibilityError):
            bridge.error_state(position_ms=unsafe)

    def test_seek_command_rejects_integer_outside_javascript_safe_range(self) -> None:
        with self.assertRaises(RecordedMediaAccessibilityError):
            RecordedMediaAccessibilityBridge.command(
                "seek", position_ms=9_007_199_254_740_992
            )

    def test_playing_clock_selects_pause_action(self) -> None:
        bridge = RecordedMediaAccessibilityBridge(language="uk")

        state = bridge.snapshot(
            **_clock_kwargs(playback_state="playing"),
            sync_snapshot=_sync_snapshot((_link(20_000, "node:1"),)),
        )

        self.assertEqual(state["playAction"], "pause")
        self.assertEqual(state["playLabel"], "Призупинити записане медіа")

    def test_candidate_disables_restore_and_uses_visible_status(self) -> None:
        bridge = RecordedMediaAccessibilityBridge(language="en")

        state = bridge.snapshot(
            **_clock_kwargs(),
            sync_snapshot=_sync_snapshot((_link(20_000, "node:candidate", confirmed=False),)),
        )

        self.assertFalse(state["restoreEnabled"])
        self.assertEqual(state["qualification"], "candidate")
        self.assertIn("unconfirmed", state["statusText"].lower())
        self.assertEqual(state["focusTarget"], "recorded-media-seek")

    def test_ambiguous_position_disables_restore(self) -> None:
        bridge = RecordedMediaAccessibilityBridge()

        state = bridge.snapshot(
            **_clock_kwargs(),
            sync_snapshot=_sync_snapshot(
                (_link(20_000, "node:a"), _link(20_000, "node:b"))
            ),
        )

        self.assertFalse(state["restoreEnabled"])
        self.assertEqual(state["qualification"], "ambiguous")
        self.assertIn("ambiguous", state["statusText"].lower())
        self.assertEqual(state["focusTarget"], "recorded-media-seek")

    def test_unlinked_position_is_explicit(self) -> None:
        bridge = RecordedMediaAccessibilityBridge()

        state = bridge.snapshot(
            **_clock_kwargs(position_ms=10_000),
            sync_snapshot=_sync_snapshot((_link(20_000, "node:future"),), position_ms=10_000),
        )

        self.assertFalse(state["restoreEnabled"])
        self.assertEqual(state["qualification"], "unlinked")
        self.assertIn("No confirmed chess position", state["statusText"])

    def test_resolution_event_becomes_visible_and_announcement_text(self) -> None:
        event = AccessibleRecordedSyncEvent(
            "Recorded media evidence was already synchronized.",
            "Recorded media evidence was already synchronized.",
        )
        resolution = RecordedPlaybackResolution(
            session=MediaChessSession(MediaCursor("recorded-1", 20_500), "ignored"),
            resolution=MediaPositionTimeline("recorded-1", (_link(20_000, "node:event"),))
            .resolve_at_or_before(20_500),
            event=event,
        )
        bridge = RecordedMediaAccessibilityBridge()

        state = bridge.snapshot(
            **_clock_kwargs(),
            playback=resolution,
        )

        self.assertEqual(state["announcement"], event.visible_text)
        self.assertEqual(state["focusTarget"], "recorded-media-restore")

    def test_preprocess_running_enables_cancel_and_focuses_cancel(self) -> None:
        bridge = RecordedMediaAccessibilityBridge(language="uk")

        state = bridge.snapshot(
            **_clock_kwargs(),
            preprocess=_checkpoint(PreprocessStatus.RUNNING, 2, 8),
        )

        self.assertTrue(state["cancelEnabled"])
        self.assertEqual(state["focusTarget"], "recorded-media-cancel")
        self.assertIn("2 of 8", state["progressText"])

    def test_error_state_never_exposes_domain_details(self) -> None:
        bridge = RecordedMediaAccessibilityBridge(language="uk")
        state = bridge.error_state(position_ms=12_000)

        self.assertFalse(state["ok"])
        self.assertEqual(state["qualification"], "unavailable")
        self.assertFalse(state["restoreEnabled"])
        self.assertFalse(state["seekEnabled"])
        self.assertFalse(state["cancelEnabled"])
        self.assertEqual(state["focusTarget"], "recorded-media-status")
        self.assertIn("Синхронізація", state["statusText"])

    def test_commands_are_intent_only_and_primitive(self) -> None:
        self.assertEqual(
            RecordedMediaAccessibilityBridge.command("play"),
            {"action": "play"},
        )
        self.assertEqual(
            RecordedMediaAccessibilityBridge.command("seek", position_ms=42_000),
            {"action": "seek", "positionMs": 42_000},
        )
        self.assertEqual(
            RecordedMediaAccessibilityBridge.command("restore"),
            {"action": "restore"},
        )
        self.assertEqual(
            RecordedMediaPlayerCommand("cancel").to_dict(),
            {"action": "cancel"},
        )

    def test_commands_reject_invalid_positions_and_payloads(self) -> None:
        for action, position in (
            ("seek", None),
            ("seek", -1),
            ("seek", True),
            ("play", 1),
            ("restore", 1),
            ("cancel", 1),
        ):
            with self.subTest(action=action, position=position):
                with self.assertRaises(RecordedMediaAccessibilityError):
                    RecordedMediaAccessibilityBridge.command(
                        action, position_ms=position
                    )

    def test_invalid_inputs_fail_closed(self) -> None:
        bridge = RecordedMediaAccessibilityBridge()
        cases = (
            lambda: bridge.set_language("pl"),
            lambda: bridge.snapshot(playback_state=1),
            lambda: bridge.snapshot(preprocess="not-a-checkpoint"),
            lambda: bridge.snapshot(event="not-an-event"),
            lambda: bridge.error_state(position_ms=-1),
        )
        for action in cases:
            with self.subTest(action=action):
                with self.assertRaises(RecordedMediaAccessibilityError):
                    action()

    def test_invalid_clock_values_fail_before_render(self) -> None:
        cases = [
            {"position_ms": -1},
            {"duration_ms": -1},
            {"playback_state": "bogus"},
            {"revision": -1},
            {"position_ms": 120_001, "duration_ms": 120_000},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                kwargs = _clock_kwargs()
                kwargs.update(overrides)
                bridge = RecordedMediaAccessibilityBridge()
                with self.assertRaises(RecordedMediaAccessibilityError):
                    bridge.snapshot(**kwargs)


    def test_cross_source_snapshots_fail_closed(self) -> None:
        bridge = RecordedMediaAccessibilityBridge()
        foreign_source = MediaSource(
            source_id="recorded-2",
            title="Foreign",
            kind=MediaSourceKind.LOCAL_FILE,
            duration_ms=120_000,
        )
        foreign_sync = RecordedSyncSnapshot(
            source_revision="revision-2",
            cache_fingerprint="cache-2",
            plan_digest="plan-2",
            source=foreign_source,
            timeline=MediaPositionTimeline("recorded-2", (_link(20_000, "node:foreign"),)),
            session=MediaChessSession(
                MediaCursor("recorded-2", 20_500),
                "opaque:foreign",
            ),
        )
        with self.assertRaises(RecordedMediaAccessibilityError):
            bridge.snapshot(
                **_clock_kwargs(),
                sync_snapshot=foreign_sync,
                preprocess=_checkpoint(PreprocessStatus.RUNNING, 1, 3),
            )

    def test_tampered_checkpoint_fields_fail_before_render(self) -> None:
        checkpoint = _checkpoint(PreprocessStatus.RUNNING, 2, 8)
        object.__setattr__(checkpoint, "next_index", 9)
        bridge = RecordedMediaAccessibilityBridge()
        with self.assertRaises(RecordedMediaAccessibilityError):
            bridge.snapshot(preprocess=checkpoint)

    def test_no_playback_snapshot_does_not_invent_position(self) -> None:
        bridge = RecordedMediaAccessibilityBridge()

        state = bridge.snapshot()

        self.assertIsNone(state["positionMs"])
        self.assertEqual(state["positionText"], "—")
        self.assertEqual(state["qualification"], "unavailable")
        self.assertFalse(state["seekEnabled"])
        self.assertFalse(state["restoreEnabled"])

    def test_synced_cursor_does_not_cross_browser_boundary(self) -> None:
        bridge = RecordedMediaAccessibilityBridge()
        state = bridge.snapshot(
            **_clock_kwargs(),
            sync_snapshot=_sync_snapshot((_link(20_000, "secret/node:42"),)),
        )
        forbidden_tokens = (
            "secret/node:42",
            "recorded-1",
            "revision-1",
            "cache-fingerprint",
            "plan-digest",
        )
        serialized = repr(state)
        for token in forbidden_tokens:
            self.assertNotIn(token, serialized)


if __name__ == "__main__":
    unittest.main()
