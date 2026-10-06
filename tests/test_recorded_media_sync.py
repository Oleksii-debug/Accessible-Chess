from __future__ import annotations

import ast
import inspect
import json
import unittest

import acs.recorded_media_sync as sync_module
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaReconciliationState,
)
from acs.media_preprocess import (
    AdaptiveSamplingPolicy,
    BoardFrameEvidence,
    FrameDisposition,
    RecordedMediaPreprocessPlan,
    RecordedMediaSourceRevision,
    SpeechEvidence,
)
from acs.recorded_media_sync import (
    CanonicalRecordedFramePort,
    RecordedMediaTimelineBuilder,
    RecordedSyncContractError,
    RecordedSyncErrorCode,
    RecordedSyncStepKind,
    deserialize_recorded_sync_state,
    seek_recorded_media,
    serialize_recorded_sync_state,
)


class Canonical:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def resolve_recorded_frame(self, *, frame, speech_context):
        self.calls.append((frame, speech_context))
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class RecordedMediaSyncTests(unittest.TestCase):
    def source(self, *, revision="source-v1", duration=3000):
        return RecordedMediaSourceRevision(
            "video-1",
            revision,
            "opaque-local-media-ref",
            duration,
        )

    def plan(self, *, revision="source-v1", duration=3000, board_revision="vision-v1"):
        return RecordedMediaPreprocessPlan.build(
            self.source(revision=revision, duration=duration),
            board_revision=board_revision,
            speech_revision="speech-v1",
            policy=AdaptiveSamplingPolicy(1000, 200, 0, revision="sampling-v1"),
        )

    def frame(
        self,
        timestamp=0,
        *,
        revision="source-v1",
        disposition=FrameDisposition.STABLE,
        confidence=.9,
    ):
        return BoardFrameEvidence(
            "video-1",
            revision,
            timestamp,
            disposition,
            confidence=confidence,
            observation_ref=(
                f"fixture:{timestamp}"
                if disposition in (FrameDisposition.STABLE, FrameDisposition.AMBIGUOUS)
                else None
            ),
        )

    def speech(self, *, revision="source-v1", start=0, end=200):
        return SpeechEvidence(
            "video-1",
            revision,
            start,
            end,
            "commentary context",
            True,
            .8,
        )

    def link(
        self,
        timestamp=0,
        ref="tree:game-1:node-0",
        *,
        status=MediaLinkStatus.CONFIRMED,
        confidence=.95,
        evidence="canonical-fixture",
    ):
        return MediaChessLink(
            "video-1",
            timestamp,
            ref,
            status,
            confidence,
            evidence,
        )

    def test_stable_frame_uses_canonical_port_and_replay_is_idempotent(self):
        link = self.link()
        canonical = Canonical(link, link)
        self.assertIsInstance(canonical, CanonicalRecordedFramePort)
        builder = RecordedMediaTimelineBuilder(self.plan(), canonical)

        first = builder.accept(self.frame(), speech_context=(self.speech(),))
        replay = builder.accept(self.frame(), speech_context=(self.speech(),))

        self.assertEqual(first.kind, RecordedSyncStepKind.LINKED)
        self.assertEqual(replay.kind, RecordedSyncStepKind.NO_CHANGE)
        self.assertEqual(builder.timeline.links, (link,))
        self.assertEqual(len(canonical.calls), 2)
        self.assertEqual(
            first.event.visible_text,
            first.event.announcement_text,
        )
        self.assertNotIn(link.chess_ref, first.event.visible_text)

    def test_ambiguous_frame_cannot_publish_confirmed_chess_truth(self):
        canonical = Canonical(self.link())
        builder = RecordedMediaTimelineBuilder(self.plan(), canonical)

        with self.assertRaises(RecordedSyncContractError) as caught:
            builder.accept(
                self.frame(disposition=FrameDisposition.AMBIGUOUS)
            )
        self.assertEqual(
            caught.exception.code,
            RecordedSyncErrorCode.UNSAFE_CONFIRMATION,
        )
        self.assertEqual(builder.timeline.links, ())

    def test_ambiguous_candidate_is_retained_as_unconfirmed_evidence(self):
        candidate = self.link(
            status=MediaLinkStatus.CANDIDATE,
            confidence=.55,
        )
        builder = RecordedMediaTimelineBuilder(self.plan(), Canonical(candidate))
        step = builder.accept(
            self.frame(disposition=FrameDisposition.AMBIGUOUS)
        )
        self.assertEqual(step.kind, RecordedSyncStepKind.LINKED)
        self.assertFalse(step.link.confirmed)
        self.assertIn("confirmation is required", step.event.visible_text)

    def test_transition_and_occlusion_skip_without_canonical_provider_use(self):
        class ExplodingCanonical:
            called = False

            def resolve_recorded_frame(self, *, frame, speech_context):
                self.called = True
                raise AssertionError("canonical port must not be called")

        canonical = ExplodingCanonical()
        builder = RecordedMediaTimelineBuilder(self.plan(), canonical)
        for disposition in (FrameDisposition.TRANSITION, FrameDisposition.OCCLUDED):
            with self.subTest(disposition=disposition):
                step = builder.accept(self.frame(disposition=disposition))
                self.assertEqual(step.kind, RecordedSyncStepKind.SKIPPED)
        self.assertFalse(canonical.called)
        self.assertEqual(builder.timeline.links, ())
        self.assertEqual(len(builder.timeline.barriers), 2)
        self.assertTrue(
            all(
                barrier.state is MediaReconciliationState.RESYNC_REQUIRED
                for barrier in builder.timeline.barriers
            )
        )


    def test_no_link_and_ambiguous_frame_block_stale_confirmed_fallback(self):
        timeline = MediaPositionTimeline(
            "video-1",
            (self.link(0, "tree:old"),),
        )
        builder = RecordedMediaTimelineBuilder(
            self.plan(),
            Canonical(None, None),
            timeline=timeline,
        )

        stable_none = builder.accept(self.frame(timestamp=1000))
        self.assertEqual(stable_none.kind, RecordedSyncStepKind.NO_LINK)
        observed = builder.timeline.resolve_at_or_before(1500)
        self.assertFalse(observed.resolved)
        self.assertEqual(
            observed.qualification,
            MediaReconciliationState.OBSERVED,
        )
        self.assertIsNone(observed.chess_ref)

        ambiguous_none = builder.accept(
            self.frame(
                timestamp=2000,
                disposition=FrameDisposition.AMBIGUOUS,
            )
        )
        self.assertEqual(ambiguous_none.kind, RecordedSyncStepKind.NO_LINK)
        ambiguous = builder.timeline.resolve_at_or_before(2500)
        self.assertTrue(ambiguous.ambiguous)
        self.assertEqual(
            ambiguous.qualification,
            MediaReconciliationState.AMBIGUOUS,
        )
        self.assertIsNone(ambiguous.chess_ref)

    def test_successful_reprocess_replaces_same_timestamp_barrier(self):
        link = self.link(1000, "tree:new")
        builder = RecordedMediaTimelineBuilder(
            self.plan(),
            Canonical(None, link),
            timeline=MediaPositionTimeline(
                "video-1",
                (self.link(0, "tree:old"),),
            ),
        )

        builder.accept(self.frame(timestamp=1000))
        self.assertIsNotNone(builder.timeline.barrier_at(1000))
        linked = builder.accept(self.frame(timestamp=1000))
        self.assertEqual(linked.kind, RecordedSyncStepKind.LINKED)
        self.assertIsNone(builder.timeline.barrier_at(1000))
        self.assertEqual(
            builder.timeline.resolve_at_or_before(1500).chess_ref,
            "tree:new",
        )

    def test_stale_frame_or_speech_revision_fails_before_canonical_use(self):
        class ExplodingCanonical:
            called = False

            def resolve_recorded_frame(self, *, frame, speech_context):
                self.called = True
                raise AssertionError("canonical port must not be called")

        canonical = ExplodingCanonical()
        builder = RecordedMediaTimelineBuilder(self.plan(), canonical)

        with self.assertRaises(RecordedSyncContractError) as frame_error:
            builder.accept(self.frame(revision="stale"))
        self.assertEqual(
            frame_error.exception.code,
            RecordedSyncErrorCode.REVISION_MISMATCH,
        )

        with self.assertRaises(RecordedSyncContractError) as speech_error:
            builder.accept(
                self.frame(),
                speech_context=(self.speech(revision="stale"),),
            )
        self.assertEqual(
            speech_error.exception.code,
            RecordedSyncErrorCode.REVISION_MISMATCH,
        )
        self.assertFalse(canonical.called)

    def test_canonical_failure_and_invalid_result_never_publish_progress(self):
        for response, code in (
            (
                RuntimeError("private canonical failure"),
                RecordedSyncErrorCode.CANONICAL_REJECTED,
            ),
            (
                object(),
                RecordedSyncErrorCode.INVALID_CANONICAL_RESULT,
            ),
            (
                MediaChessLink(
                    "other-source",
                    0,
                    "tree:x",
                    MediaLinkStatus.CONFIRMED,
                    1.0,
                    "fixture",
                ),
                RecordedSyncErrorCode.SOURCE_MISMATCH,
            ),
            (
                self.link(timestamp=1000),
                RecordedSyncErrorCode.INVALID_CANONICAL_RESULT,
            ),
        ):
            with self.subTest(code=code):
                builder = RecordedMediaTimelineBuilder(
                    self.plan(),
                    Canonical(response),
                )
                with self.assertRaises(RecordedSyncContractError) as caught:
                    builder.accept(self.frame())
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(builder.timeline.links, ())

    def test_conflicting_replay_fails_closed_instead_of_rewriting_link(self):
        candidate = self.link(status=MediaLinkStatus.CANDIDATE, confidence=.6)
        confirmed = self.link(status=MediaLinkStatus.CONFIRMED, confidence=.9)
        builder = RecordedMediaTimelineBuilder(
            self.plan(),
            Canonical(candidate, confirmed),
        )
        builder.accept(self.frame())

        with self.assertRaises(RecordedSyncContractError) as caught:
            builder.accept(self.frame())
        self.assertEqual(
            caught.exception.code,
            RecordedSyncErrorCode.REPLAY_CONFLICT,
        )
        self.assertEqual(builder.timeline.links, (candidate,))

    def test_seek_resolves_confirmed_state_without_mutating_unresolved_chess_cursor(self):
        timeline = MediaPositionTimeline(
            "video-1",
            (
                self.link(1000, "tree:confirmed"),
                self.link(
                    2000,
                    "tree:candidate-a",
                    status=MediaLinkStatus.CANDIDATE,
                ),
                self.link(
                    2000,
                    "tree:candidate-b",
                    status=MediaLinkStatus.CANDIDATE,
                ),
            ),
        )
        session = MediaChessSession(
            MediaCursor("video-1", 0),
            "tree:user-analysis",
        )

        resolved = seek_recorded_media(
            session,
            timeline,
            1500,
            duration_ms=3000,
        )
        self.assertTrue(resolved.resolution.resolved)
        self.assertEqual(resolved.session.chess_ref, "tree:confirmed")

        ambiguous = seek_recorded_media(
            session,
            timeline,
            2500,
            duration_ms=3000,
        )
        self.assertTrue(ambiguous.resolution.ambiguous)
        self.assertEqual(
            ambiguous.session.chess_ref,
            "tree:user-analysis",
        )
        self.assertIn("not changed", ambiguous.event.visible_text)
        self.assertEqual(
            ambiguous.event.visible_text,
            ambiguous.event.announcement_text,
        )

    def test_rewind_and_repeated_position_choose_nearest_confirmed_timestamp(self):
        timeline = MediaPositionTimeline(
            "video-1",
            (
                self.link(0, "tree:A"),
                self.link(1000, "tree:B"),
                self.link(2000, "tree:A"),
            ),
        )
        session = MediaChessSession(MediaCursor("video-1", 1900), "tree:A")
        rewound = session.sync_media_from_chess(timeline)
        self.assertEqual(rewound.media_cursor.position_ms, 2000)

        playback = seek_recorded_media(
            session,
            timeline,
            1100,
            duration_ms=3000,
        )
        self.assertEqual(playback.session.chess_ref, "tree:B")
        self.assertEqual(playback.resolution.anchor_timestamp_ms, 1000)

    def test_recorded_state_roundtrip_reuses_media_core_and_binds_revision(self):
        plan = self.plan()
        timeline = MediaPositionTimeline(
            "video-1",
            (self.link(1000, "tree:confirmed"),),
        )
        session = MediaChessSession(
            MediaCursor("video-1", 1500),
            "tree:user-analysis",
        )

        text = serialize_recorded_sync_state(
            plan,
            title="Київська партія",
            timeline=timeline,
            session=session,
        )
        restored = deserialize_recorded_sync_state(
            text,
            expected_plan=plan,
        )
        self.assertEqual(restored.timeline.links, timeline.links)
        self.assertEqual(
            restored.session.media_cursor.position_ms,
            1500,
        )
        self.assertEqual(restored.source.title, "Київська партія")
        self.assertEqual(
            restored.cache_fingerprint,
            plan.cache_key.fingerprint(),
        )

        stale_plan = self.plan(revision="source-v2")
        with self.assertRaises(RecordedSyncContractError) as stale:
            deserialize_recorded_sync_state(
                text,
                expected_plan=stale_plan,
            )
        self.assertEqual(
            stale.exception.code,
            RecordedSyncErrorCode.STATE_MISMATCH,
        )

    def test_saved_state_rejects_duplicate_outer_keys_and_media_state_tamper(self):
        plan = self.plan()
        timeline = MediaPositionTimeline("video-1")
        session = MediaChessSession(MediaCursor("video-1", 0))
        text = serialize_recorded_sync_state(
            plan,
            title="Fixture",
            timeline=timeline,
            session=session,
        )

        duplicate = text[:-1] + ',"schema":"other"}'
        with self.assertRaises(RecordedSyncContractError) as caught:
            deserialize_recorded_sync_state(duplicate)
        self.assertEqual(
            caught.exception.code,
            RecordedSyncErrorCode.INVALID_SCHEMA,
        )

        payload = json.loads(text)
        payload["media_state"] = "{not-json"
        malformed = json.dumps(payload)
        with self.assertRaises(RecordedSyncContractError) as nested:
            deserialize_recorded_sync_state(malformed)
        self.assertEqual(
            nested.exception.code,
            RecordedSyncErrorCode.INVALID_SCHEMA,
        )

    def test_module_has_no_chess_rules_parser_or_provider_network_authority(self):
        tree = ast.parse(inspect.getsource(sync_module))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = (
            "chesscore",
            "board_service",
            "gametree",
            "pgn",
            "notation",
            "requests",
            "urllib",
            "httpx",
            "aiohttp",
            "socket",
            "subprocess",
        )
        for module in imported:
            self.assertFalse(
                any(fragment in module for fragment in forbidden),
                module,
            )


if __name__ == "__main__":
    unittest.main()
