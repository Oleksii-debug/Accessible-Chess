from __future__ import annotations

import inspect
import unittest

from acs.media_application import (
    MediaApplicationCode,
    MediaApplicationError,
    MediaApplicationService,
)
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaReconciliationState,
    MediaTimelineBarrier,
    MediaSource,
    MediaSourceKind,
    deserialize_media_state,
    serialize_media_state,
)


def source(source_id="lesson-1", duration_ms=120_000):
    return MediaSource(
        source_id=source_id,
        title="Application fixture",
        kind=MediaSourceKind.LOCAL_FILE,
        duration_ms=duration_ms,
    )


def link(timestamp_ms, chess_ref, *, confirmed=True):
    return MediaChessLink(
        "lesson-1",
        timestamp_ms,
        chess_ref,
        status=(
            MediaLinkStatus.CONFIRMED
            if confirmed
            else MediaLinkStatus.CANDIDATE
        ),
        confidence=1.0 if confirmed else 0.8,
        evidence="application fixture",
    )


class MediaApplicationTests(unittest.TestCase):
    def service(self, timeline, session=None, restored=None):
        if session is None:
            session = MediaChessSession(MediaCursor("lesson-1", 20_500), "tree:manual")
        if restored is None:
            restored = []
        return MediaApplicationService(
            source=source(),
            timeline=timeline,
            session=session,
            restore_chess_ref=lambda chess_ref: restored.append(chess_ref),
        )

    def test_seek_keeps_analysis_cursor_independent_until_explicit_restore(self):
        timeline = MediaPositionTimeline(
            "lesson-1", (link(10_000, "tree:a"), link(20_000, "tree:b"))
        )
        service = self.service(
            timeline,
            MediaChessSession(MediaCursor("lesson-1", 0), "tree:analysis"),
        )

        snapshot = service.seek_media(20_500)

        self.assertEqual(snapshot.position_ms, 20_500)
        self.assertEqual(snapshot.analysis_chess_ref, "tree:analysis")
        self.assertEqual(snapshot.synchronized_chess_ref, "tree:b")
        self.assertTrue(snapshot.can_restore)
        self.assertEqual(snapshot.qualification, "confirmed")
        self.assertIn("confirmed chess position", snapshot.status_text.lower())

    def test_restore_delegates_opaque_reference_then_commits_analysis_cursor(self):
        timeline = MediaPositionTimeline(
            "lesson-1", (link(20_000, "opaque:not-a-fen"),)
        )
        restored = []
        service = self.service(timeline, restored=restored)

        result = service.restore_media_position()

        self.assertEqual(restored, ["opaque:not-a-fen"])
        self.assertEqual(result.chess_ref, "opaque:not-a-fen")
        self.assertEqual(result.previous_chess_ref, "tree:manual")
        self.assertTrue(result.changed)
        self.assertEqual(result.anchor_timestamp_ms, 20_000)
        self.assertEqual(result.revision, 1)
        self.assertEqual(service.session.chess_ref, "opaque:not-a-fen")
        self.assertIn("Restored the chess position", result.accessible_text)

    def test_snapshot_at_provider_time_is_side_effect_free(self):
        timeline = MediaPositionTimeline(
            "lesson-1", (link(20_000, "tree:provider-view"),)
        )
        service = self.service(
            timeline,
            MediaChessSession(MediaCursor("lesson-1", 0), "tree:analysis"),
        )

        snapshot = service.snapshot_at(20_500)

        self.assertEqual(snapshot.position_ms, 20_500)
        self.assertEqual(snapshot.synchronized_chess_ref, "tree:provider-view")
        self.assertEqual(snapshot.analysis_chess_ref, "tree:analysis")
        self.assertEqual(service.session.media_cursor.position_ms, 0)
        self.assertEqual(service.session.chess_ref, "tree:analysis")
        self.assertEqual(service.revision, 0)

    def test_restore_can_use_explicit_provider_timestamp_atomically(self):
        timeline = MediaPositionTimeline(
            "lesson-1", (link(20_000, "tree:provider-time"),)
        )
        calls = []
        service = self.service(
            timeline,
            MediaChessSession(MediaCursor("lesson-1", 0), "tree:analysis"),
            calls,
        )

        result = service.restore_media_position(20_500)

        self.assertEqual(calls, ["tree:provider-time"])
        self.assertEqual(result.position_ms, 20_500)
        self.assertEqual(service.session.media_cursor.position_ms, 20_500)
        self.assertEqual(service.session.chess_ref, "tree:provider-time")
        self.assertEqual(service.revision, 1)

    def test_restore_failure_does_not_commit_application_cursor_or_revision(self):
        timeline = MediaPositionTimeline("lesson-1", (link(20_000, "tree:b"),))

        def reject(_chess_ref):
            raise RuntimeError("canonical application rejected reference")

        service = MediaApplicationService(
            source=source(),
            timeline=timeline,
            session=MediaChessSession(
                MediaCursor("lesson-1", 20_500), "tree:analysis"
            ),
            restore_chess_ref=reject,
        )

        with self.assertRaises(RuntimeError):
            service.restore_media_position(21_000)

        self.assertEqual(service.session.chess_ref, "tree:analysis")
        self.assertEqual(service.session.media_cursor.position_ms, 20_500)
        self.assertEqual(service.revision, 0)

    def test_restore_blocks_reentrant_media_mutation_and_releases_guard(self):
        timeline = MediaPositionTimeline(
            "lesson-1", (link(20_000, "tree:restore"),)
        )
        holder = {}

        def reenter(_chess_ref):
            holder["service"].seek_media(30_000)

        service = MediaApplicationService(
            source=source(),
            timeline=timeline,
            session=MediaChessSession(
                MediaCursor("lesson-1", 20_500), "tree:analysis"
            ),
            restore_chess_ref=reenter,
        )
        holder["service"] = service

        with self.assertRaises(MediaApplicationError) as caught:
            service.restore_media_position(21_000)

        self.assertEqual(caught.exception.code, MediaApplicationCode.INVALID_STATE)
        self.assertEqual(service.session.media_cursor.position_ms, 20_500)
        self.assertEqual(service.session.chess_ref, "tree:analysis")
        self.assertEqual(service.revision, 0)

        snapshot = service.seek_media(30_000)
        self.assertEqual(snapshot.position_ms, 30_000)
        self.assertEqual(service.revision, 1)

    def test_restore_rejects_reentrant_analysis_selection_without_clobbering_outer_commit(self):
        timeline = MediaPositionTimeline(
            "lesson-1", (link(20_000, "tree:restore"),)
        )
        holder = {}
        blocked = []

        def restore(_chess_ref):
            try:
                holder["service"].select_analysis_chess_ref("tree:reentrant")
            except MediaApplicationError as exc:
                blocked.append(exc.code)

        service = MediaApplicationService(
            source=source(),
            timeline=timeline,
            session=MediaChessSession(
                MediaCursor("lesson-1", 20_500), "tree:analysis"
            ),
            restore_chess_ref=restore,
        )
        holder["service"] = service

        result = service.restore_media_position(21_000)

        self.assertEqual(blocked, [MediaApplicationCode.INVALID_STATE])
        self.assertEqual(result.chess_ref, "tree:restore")
        self.assertEqual(service.session.media_cursor.position_ms, 21_000)
        self.assertEqual(service.session.chess_ref, "tree:restore")
        self.assertEqual(service.revision, 1)


    def test_resync_required_is_exposed_distinctly_and_blocks_restore(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (link(10_000, "tree:old"),),
            barriers=(
                MediaTimelineBarrier(
                    source_id="lesson-1",
                    timestamp_ms=20_000,
                    state=MediaReconciliationState.RESYNC_REQUIRED,
                    reason="provider jumped to an unrelated position",
                ),
            ),
        )
        restored = []
        service = self.service(
            timeline,
            MediaChessSession(MediaCursor("lesson-1", 20_500), "tree:analysis"),
            restored,
        )

        snapshot = service.snapshot()
        self.assertEqual(snapshot.qualification, "resync_required")
        self.assertFalse(snapshot.can_restore)
        self.assertIn("synchronization", snapshot.status_text.lower())
        self.assertEqual(snapshot.synchronized_chess_ref, None)

        with self.assertRaises(MediaApplicationError) as caught:
            service.restore_media_position()
        self.assertEqual(caught.exception.code, MediaApplicationCode.RESYNC_REQUIRED)
        self.assertEqual(restored, [])
        self.assertEqual(service.session.chess_ref, "tree:analysis")
        self.assertEqual(service.revision, 0)

    def test_candidate_only_state_fails_before_restore_effect(self):
        timeline = MediaPositionTimeline(
            "lesson-1", (link(20_000, "tree:candidate", confirmed=False),)
        )
        restored = []
        service = self.service(timeline, restored=restored)

        with self.assertRaises(MediaApplicationError) as caught:
            service.restore_media_position()

        self.assertEqual(
            caught.exception.code, MediaApplicationCode.NO_CONFIRMED_POSITION
        )
        self.assertEqual(restored, [])
        self.assertEqual(service.session.chess_ref, "tree:manual")
        self.assertEqual(service.revision, 0)
        self.assertEqual(service.snapshot().qualification, "candidate")

    def test_ambiguous_state_fails_before_restore_effect(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (link(20_000, "tree:a"), link(20_000, "tree:b")),
        )
        restored = []
        service = self.service(timeline, restored=restored)

        with self.assertRaises(MediaApplicationError) as caught:
            service.restore_media_position()

        self.assertEqual(caught.exception.code, MediaApplicationCode.AMBIGUOUS_POSITION)
        self.assertEqual(restored, [])
        self.assertEqual(service.session.chess_ref, "tree:manual")
        self.assertFalse(service.snapshot().can_restore)

    def test_source_identity_is_bound_at_composition(self):
        with self.assertRaises(MediaApplicationError) as caught:
            MediaApplicationService(
                source=source(),
                timeline=MediaPositionTimeline("other-source", ()),
                session=MediaChessSession(MediaCursor("lesson-1", 0)),
                restore_chess_ref=lambda _ref: None,
            )
        self.assertEqual(caught.exception.code, MediaApplicationCode.SOURCE_MISMATCH)

    def test_cursor_past_source_duration_is_rejected_at_composition(self):
        with self.assertRaises(MediaApplicationError) as caught:
            MediaApplicationService(
                source=source(duration_ms=10_000),
                timeline=MediaPositionTimeline("lesson-1", ()),
                session=MediaChessSession(MediaCursor("lesson-1", 10_001)),
                restore_chess_ref=lambda _ref: None,
            )
        self.assertEqual(caught.exception.code, MediaApplicationCode.INVALID_STATE)

    def test_align_media_to_analysis_uses_canonical_timeline_nearest_rule(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (
                link(10_000, "tree:repeat"),
                link(30_000, "tree:repeat"),
                link(50_000, "tree:other"),
            ),
        )
        service = self.service(
            timeline,
            MediaChessSession(MediaCursor("lesson-1", 20_000), "tree:repeat"),
        )

        snapshot = service.align_media_to_analysis()

        self.assertEqual(snapshot.position_ms, 10_000)
        self.assertEqual(snapshot.analysis_chess_ref, "tree:repeat")
        self.assertEqual(service.revision, 1)

    def test_restart_from_canonical_serialized_state_preserves_restore_target(self):
        original_source = source()
        timeline = MediaPositionTimeline(
            "lesson-1", (link(20_000, "tree:resume"),)
        )
        session = MediaChessSession(MediaCursor("lesson-1", 20_500), "tree:analysis")
        encoded = serialize_media_state(original_source, timeline, session)
        restored_source, restored_timeline, restored_session = deserialize_media_state(
            encoded
        )
        calls = []
        service = MediaApplicationService(
            source=restored_source,
            timeline=restored_timeline,
            session=restored_session,
            restore_chess_ref=lambda chess_ref: calls.append(chess_ref),
        )

        result = service.restore_media_position()

        self.assertEqual(calls, ["tree:resume"])
        self.assertEqual(result.chess_ref, "tree:resume")
        self.assertEqual(service.session.media_cursor.position_ms, 20_500)

    def test_module_has_no_chess_rules_or_format_authority_import(self):
        import acs.media_application as module

        text = inspect.getsource(module)
        for forbidden in (
            "chesscore",
            "gametree",
            "pgn_",
            "parse_move",
            "set_fen",
            "Board(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
