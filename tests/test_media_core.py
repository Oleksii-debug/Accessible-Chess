import json
import math
import unittest

from acs.media_core import (
    MEDIA_STATE_SCHEMA,
    MediaClock,
    MediaClockSnapshot,
    MediaPlaybackState,
    MediaSession,
    MediaTimelineBarrier,
    MediaTimelineIdentity,
    CanonicalChessReconciliationPort,
    ChessStateReconciler,
    MediaEvidence,
    MediaEvidenceField,
    MediaEvidenceKind,
    MediaReconciliationResult,
    MediaReconciliationState,
    MAX_MEDIA_LINKS,
    MediaChessLink,
    MediaChessSession,
    MediaContractError,
    MediaCursor,
    MediaErrorCode,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaSource,
    MediaSourceKind,
    deserialize_media_session,
    deserialize_media_state,
    serialize_media_session,
    serialize_media_state,
)


class MediaCoreContractTests(unittest.TestCase):
    def source(self):
        return MediaSource(
            source_id="lesson-1",
            title="Accessible lesson",
            kind=MediaSourceKind.LOCAL_FILE,
            source_ref="opaque-storage-key",
            duration_ms=120_000,
            attribution="User-provided source",
        )

    def link(
        self,
        timestamp_ms,
        chess_ref,
        *,
        confirmed=True,
        confidence=1.0,
        evidence=None,
    ):
        return MediaChessLink(
            source_id="lesson-1",
            timestamp_ms=timestamp_ms,
            chess_ref=chess_ref,
            status=(
                MediaLinkStatus.CONFIRMED
                if confirmed
                else MediaLinkStatus.CANDIDATE
            ),
            confidence=confidence,
            evidence=evidence,
        )

    def test_timeline_sorts_deterministically_without_interpreting_chess(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(20_000, "tree:game-1:path-b", confirmed=False, confidence=0.8),
                self.link(10_000, "tree:game-1:path-a"),
                self.link(20_000, "tree:game-1:path-a", confirmed=False, confidence=0.9),
            ],
        )
        self.assertEqual(timeline.timestamps, (10_000, 20_000))
        self.assertEqual(
            [link.chess_ref for link in timeline.links_at(20_000)],
            ["tree:game-1:path-a", "tree:game-1:path-b"],
        )

    def test_links_at_missing_timestamp_is_empty(self):
        timeline = MediaPositionTimeline("lesson-1", [self.link(1_000, "tree:a")])
        self.assertEqual(timeline.links_at(999), ())
        self.assertEqual(timeline.links_at(1_001), ())

    def test_resolution_uses_latest_confirmed_anchor_at_or_before_media_time(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [self.link(5_000, "tree:a"), self.link(25_000, "tree:b")],
        )
        resolved = timeline.resolve_at_or_before(24_999)
        self.assertTrue(resolved.resolved)
        self.assertEqual(resolved.anchor_timestamp_ms, 5_000)
        self.assertEqual(resolved.chess_ref, "tree:a")

    def test_resolution_before_first_anchor_is_safely_unresolved(self):
        timeline = MediaPositionTimeline("lesson-1", [self.link(5_000, "tree:a")])
        resolved = timeline.resolve_at_or_before(4_999)
        self.assertFalse(resolved.resolved)
        self.assertFalse(resolved.ambiguous)
        self.assertIsNone(resolved.anchor_timestamp_ms)
        self.assertEqual(resolved.links, ())

    def test_new_uncertain_anchor_blocks_stale_confirmed_fallback(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(5_000, "tree:old"),
                self.link(10_000, "candidate:new", confirmed=False, confidence=0.9),
            ],
        )
        resolved = timeline.resolve_at_or_before(12_000)
        self.assertFalse(resolved.resolved)
        self.assertEqual(resolved.anchor_timestamp_ms, 10_000)
        self.assertIsNone(resolved.chess_ref)

    def test_unconfirmed_recognition_never_silently_moves_chess_cursor(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [self.link(5_000, "candidate:a", confirmed=False, confidence=0.99)],
        )
        session = MediaChessSession(MediaCursor("lesson-1", 6_000), "existing:node")
        updated, resolution = session.sync_chess_from_media(timeline)
        self.assertIs(updated, session)
        self.assertFalse(resolution.resolved)
        self.assertFalse(resolution.ambiguous)
        self.assertEqual(updated.chess_ref, "existing:node")

    def test_conflicting_confirmed_links_are_explicitly_ambiguous(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(9_000, "tree:a", confidence=1.0),
                self.link(9_000, "tree:b", confidence=1.0),
            ],
        )
        session = MediaChessSession(MediaCursor("lesson-1", 9_100), "tree:old")
        updated, resolution = session.sync_chess_from_media(timeline)
        self.assertIs(updated, session)
        self.assertTrue(resolution.ambiguous)
        self.assertIsNone(resolution.chess_ref)
        self.assertEqual(updated.chess_ref, "tree:old")

    def test_confirmed_link_wins_over_other_candidates_at_same_anchor(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(9_000, "tree:confirmed"),
                self.link(9_000, "candidate:other", confirmed=False, confidence=0.99),
            ],
        )
        resolved = timeline.resolve_exact(9_000)
        self.assertTrue(resolved.resolved)
        self.assertFalse(resolved.ambiguous)
        self.assertEqual(resolved.chess_ref, "tree:confirmed")

    def test_multiple_unconfirmed_candidates_are_explicitly_ambiguous(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(9_000, "candidate:a", confirmed=False, confidence=0.8),
                self.link(9_000, "candidate:b", confirmed=False, confidence=0.7),
            ],
        )
        session = MediaChessSession(MediaCursor("lesson-1", 9_100), "tree:old")
        updated, resolution = session.sync_chess_from_media(timeline)
        self.assertIs(updated, session)
        self.assertTrue(resolution.ambiguous)
        self.assertFalse(resolution.resolved)
        self.assertEqual(updated.chess_ref, "tree:old")

    def test_explicit_candidate_confirmation_resolves_ambiguity(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(9_000, "candidate:a", confirmed=False, confidence=0.8),
                self.link(9_000, "candidate:b", confirmed=False, confidence=0.7),
            ],
        )
        confirmed = timeline.confirm_candidate(
            9_000, "candidate:b", evidence="user confirmed after review"
        )
        resolved = confirmed.resolve_exact(9_000)
        self.assertTrue(resolved.resolved)
        self.assertEqual(resolved.chess_ref, "candidate:b")
        selected = next(link for link in confirmed.links_at(9_000) if link.chess_ref == "candidate:b")
        self.assertTrue(selected.confirmed)
        self.assertEqual(selected.evidence, "user confirmed after review")
        other = next(link for link in confirmed.links_at(9_000) if link.chess_ref == "candidate:a")
        self.assertFalse(other.confirmed)

    def test_confirmation_cannot_invent_unknown_chess_reference(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [self.link(9_000, "candidate:a", confirmed=False)],
        )
        with self.assertRaises(MediaContractError) as caught:
            timeline.confirm_candidate(9_000, "candidate:missing")
        self.assertEqual(caught.exception.code, MediaErrorCode.LINK_NOT_FOUND)

    def test_confirmation_conflict_requires_explicit_replace(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(9_000, "tree:confirmed"),
                self.link(9_000, "candidate:new", confirmed=False, confidence=0.9),
            ],
        )
        with self.assertRaises(MediaContractError) as caught:
            timeline.confirm_candidate(9_000, "candidate:new")
        self.assertEqual(caught.exception.code, MediaErrorCode.CONFIRMATION_CONFLICT)

        replaced = timeline.confirm_candidate(
            9_000, "candidate:new", replace_confirmed=True
        )
        resolved = replaced.resolve_exact(9_000)
        self.assertTrue(resolved.resolved)
        self.assertEqual(resolved.chess_ref, "candidate:new")
        old = next(link for link in replaced.links_at(9_000) if link.chess_ref == "tree:confirmed")
        self.assertFalse(old.confirmed)

    def test_reconfirm_is_idempotent_when_nothing_changes(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [self.link(9_000, "tree:confirmed")],
        )
        self.assertIs(
            timeline.confirm_candidate(9_000, "tree:confirmed"),
            timeline,
        )

    def test_same_timestamp_and_chess_ref_cannot_exist_with_two_statuses(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaPositionTimeline(
                "lesson-1",
                [
                    self.link(9_000, "tree:a"),
                    self.link(9_000, "tree:a", confirmed=False),
                ],
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.DUPLICATE_LINK)

    def test_media_and_chess_cursors_are_independent_until_explicit_sync(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [self.link(10_000, "tree:a"), self.link(20_000, "tree:b")],
        )
        initial = MediaChessSession(MediaCursor("lesson-1", 0), "tree:manual")
        sought = initial.seek_media(20_500, duration_ms=120_000)
        self.assertEqual(sought.media_cursor.position_ms, 20_500)
        self.assertEqual(sought.chess_ref, "tree:manual")

        synchronized, resolution = sought.sync_chess_from_media(timeline)
        self.assertTrue(resolution.resolved)
        self.assertEqual(synchronized.chess_ref, "tree:b")
        self.assertEqual(synchronized.media_cursor.position_ms, 20_500)

        manually_selected = synchronized.select_chess("tree:a")
        self.assertEqual(manually_selected.media_cursor.position_ms, 20_500)
        self.assertEqual(manually_selected.chess_ref, "tree:a")

    def test_sync_media_to_repeated_chess_position_uses_nearest_then_earlier(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(10_000, "tree:repeat"),
                self.link(30_000, "tree:repeat"),
                self.link(50_000, "tree:other"),
            ],
        )
        session = MediaChessSession(MediaCursor("lesson-1", 20_000), "tree:repeat")
        synced = session.sync_media_from_chess(timeline)
        self.assertEqual(synced.media_cursor.position_ms, 10_000)

    def test_source_mismatch_fails_closed(self):
        timeline = MediaPositionTimeline("different-source", [])
        session = MediaChessSession(MediaCursor("lesson-1", 0))
        with self.assertRaises(MediaContractError) as caught:
            session.sync_chess_from_media(timeline)
        self.assertEqual(caught.exception.code, MediaErrorCode.SOURCE_MISMATCH)

    def test_duplicate_link_is_rejected(self):
        link = self.link(1_000, "tree:a")
        with self.assertRaises(MediaContractError) as caught:
            MediaPositionTimeline("lesson-1", [link, link])
        self.assertEqual(caught.exception.code, MediaErrorCode.DUPLICATE_LINK)

    def test_bool_and_negative_timestamps_are_rejected(self):
        for value in (-1, True):
            with self.subTest(value=value):
                with self.assertRaises(MediaContractError) as caught:
                    MediaCursor("lesson-1", value)
                self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

    def test_non_finite_or_out_of_range_confidence_is_rejected(self):
        for value in (math.nan, math.inf, -0.1, 1.1, True, 10**1000):
            with self.subTest(value=value):
                with self.assertRaises(MediaContractError) as caught:
                    self.link(1_000, "tree:a", confirmed=False, confidence=value)
                self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONFIDENCE)

    def test_position_past_known_duration_is_rejected(self):
        session = MediaChessSession(MediaCursor("lesson-1", 0))
        with self.assertRaises(MediaContractError) as caught:
            session.seek_media(120_001, duration_ms=120_000)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

    def test_oversized_confidence_fails_closed_without_overflow_error(self):
        with self.assertRaises(MediaContractError) as caught:
            self.link(1_000, "tree:a", confirmed=False, confidence=10**1000)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONFIDENCE)

    def test_media_text_rejects_lone_surrogates_at_domain_boundary(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaSource(
                source_id="lesson-1",
                title="broken\ud800",
                kind=MediaSourceKind.LOCAL_FILE,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TEXT)

    def test_serializer_rejects_lone_surrogates_in_state_text(self):
        source = self.source()
        object.__setattr__(source, "attribution", "broken\ud800")
        with self.assertRaises(MediaContractError) as caught:
            serialize_media_state(
                source,
                MediaPositionTimeline("lesson-1", []),
                MediaChessSession(MediaCursor("lesson-1", 0)),
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TEXT)

    def test_loader_rejects_nonfinite_numbers_even_in_unconsumed_fields(self):
        source = self.source()
        timeline = MediaPositionTimeline("lesson-1", [])
        session = MediaChessSession(MediaCursor("lesson-1", 0))
        payload = json.loads(serialize_media_state(source, timeline, session))
        for raw in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(raw=raw):
                text = json.dumps(payload, separators=(",", ":")).replace(
                    '"version":1', f'"version":1,"future_value":{raw}', 1
                )
                with self.assertRaises(MediaContractError) as caught:
                    deserialize_media_state(text)
                self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_SCHEMA)

    def test_loader_rejects_lone_surrogate_before_utf8_size_check(self):
        malformed = '{"schema":"accessible-chess.media-state","version":1,"bad":"\ud800"}'
        with self.assertRaises(MediaContractError) as caught:
            deserialize_media_state(malformed)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TEXT)

    def test_versioned_state_round_trip_preserves_unicode_and_ambiguity(self):
        source = self.source()
        timeline = MediaPositionTimeline(
            "lesson-1",
            [
                self.link(
                    5_000,
                    "tree:білий-хід",
                    confirmed=False,
                    confidence=0.83,
                    evidence="кадр 42",
                ),
                self.link(10_000, "tree:confirmed"),
            ],
        )
        session = MediaChessSession(
            MediaCursor("lesson-1", 10_500), "tree:confirmed"
        )
        text = serialize_media_state(source, timeline, session)
        restored_source, restored_timeline, restored_session = deserialize_media_state(
            text
        )
        self.assertEqual(restored_source, source)
        self.assertEqual(restored_timeline.links, timeline.links)
        self.assertEqual(restored_session, session)
        self.assertIn("tree:білий-хід", text)

    def test_serialized_output_is_deterministic_for_equivalent_input_order(self):
        source = self.source()
        first = self.link(5_000, "tree:a")
        second = self.link(10_000, "tree:b", confirmed=False, confidence=0.7)
        session = MediaChessSession(MediaCursor("lesson-1", 0))
        left = serialize_media_state(
            source, MediaPositionTimeline("lesson-1", [first, second]), session
        )
        right = serialize_media_state(
            source, MediaPositionTimeline("lesson-1", [second, first]), session
        )
        self.assertEqual(left, right)

    def test_loader_rejects_unknown_schema_version(self):
        source = self.source()
        timeline = MediaPositionTimeline("lesson-1", [])
        session = MediaChessSession(MediaCursor("lesson-1", 0))
        payload = json.loads(serialize_media_state(source, timeline, session))
        payload["version"] = 999
        with self.assertRaises(MediaContractError) as caught:
            deserialize_media_state(json.dumps(payload))
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_SCHEMA)

    def test_loader_rejects_non_object_and_broken_json(self):
        for text in ("[]", "{"):
            with self.subTest(text=text):
                with self.assertRaises(MediaContractError) as caught:
                    deserialize_media_state(text)
                self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_SCHEMA)

    def test_loader_rejects_duplicate_json_keys_instead_of_last_write_wins(self):
        duplicate = (
            '{"schema":"accessible-chess.media-state",'
            '"schema":"attacker-controlled",'
            '"version":1,"source":{},"timeline":{},"session":{}}'
        )
        with self.assertRaises(MediaContractError) as caught:
            deserialize_media_state(duplicate)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_SCHEMA)

    def test_loader_rejects_saved_cursor_past_source_duration(self):
        source = self.source()
        timeline = MediaPositionTimeline("lesson-1", [])
        session = MediaChessSession(MediaCursor("lesson-1", 0))
        payload = json.loads(serialize_media_state(source, timeline, session))
        payload["session"]["position_ms"] = 999_999
        with self.assertRaises(MediaContractError) as caught:
            deserialize_media_state(json.dumps(payload))
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

    def test_timeline_link_limit_is_enforced_before_element_validation(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaPositionTimeline("lesson-1", [None] * (MAX_MEDIA_LINKS + 1))
        self.assertEqual(caught.exception.code, MediaErrorCode.LINK_LIMIT)

    def test_timeline_bounds_arbitrary_iterables_before_full_materialization(self):
        seen = []

        def unbounded_links():
            index = 0
            while True:
                seen.append(index)
                yield self.link(index, f"tree:{index}")
                index += 1

        with self.assertRaises(MediaContractError) as caught:
            MediaPositionTimeline("lesson-1", unbounded_links())
        self.assertEqual(caught.exception.code, MediaErrorCode.LINK_LIMIT)
        self.assertEqual(len(seen), MAX_MEDIA_LINKS + 1)

    def test_timeline_rejects_media_link_subclasses_at_dto_boundary(self):
        class DerivedMediaChessLink(MediaChessLink):
            pass

        derived = DerivedMediaChessLink(
            source_id="lesson-1",
            timestamp_ms=1_000,
            chess_ref="tree:derived",
        )
        with self.assertRaises(MediaContractError) as caught:
            MediaPositionTimeline("lesson-1", [derived])
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

    def test_active_enum_like_inputs_fail_closed_without_repr_evaluation(self):
        class ReprBomb:
            def __repr__(self):
                raise AssertionError("repr must not be evaluated")

        with self.assertRaises(MediaContractError) as caught:
            MediaClock(state=ReprBomb())
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)
        self.assertNotIn("ReprBomb", str(caught.exception))

        with self.assertRaises(MediaContractError) as caught:
            MediaSource(
                source_id="lesson-1",
                title="lesson",
                kind=ReprBomb(),
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

        with self.assertRaises(MediaContractError) as caught:
            MediaChessLink(
                source_id="lesson-1",
                timestamp_ms=0,
                chess_ref="tree:a",
                status=ReprBomb(),
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

    def test_serialize_rejects_timeline_subclasses_at_the_authority_boundary(self):
        class DerivedMediaPositionTimeline(MediaPositionTimeline):
            pass

        source = self.source()
        timeline = DerivedMediaPositionTimeline("lesson-1", [])
        session = MediaChessSession(MediaCursor("lesson-1", 0))
        with self.assertRaises(MediaContractError) as caught:
            serialize_media_state(source, timeline, session)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

    def test_session_rejects_cursor_subclasses_at_dto_boundary(self):
        class DerivedMediaCursor(MediaCursor):
            pass

        with self.assertRaises(MediaContractError) as caught:
            MediaChessSession(DerivedMediaCursor("lesson-1", 0))
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)


    def test_media_evidence_is_deeply_immutable_and_deterministic(self):
        evidence = MediaEvidence(
            evidence_id="ev-1",
            source_id="lesson-1",
            kind=MediaEvidenceKind.BOARD_OBSERVATION,
            start_ms=1000,
            end_ms=1200,
            fields=(
                MediaEvidenceField("zeta", "opaque-z"),
                MediaEvidenceField("alpha", "opaque-a"),
            ),
            confidence=0.82,
            producer_revision="boardvision-v1",
        )
        self.assertEqual([field.name for field in evidence.fields], ["alpha", "zeta"])
        with self.assertRaises(AttributeError):
            evidence.fields = ()
        with self.assertRaises(AttributeError):
            evidence.fields[0].value = "mutated"

    def test_media_evidence_rejects_mutable_or_duplicate_fields(self):
        field = MediaEvidenceField("position", "opaque")
        with self.assertRaises(MediaContractError) as caught:
            MediaEvidence(
                evidence_id="ev-1",
                source_id="lesson-1",
                kind=MediaEvidenceKind.BOARD_OBSERVATION,
                start_ms=0,
                end_ms=0,
                fields=[field],
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)
        with self.assertRaises(MediaContractError) as caught:
            MediaEvidence(
                evidence_id="ev-2",
                source_id="lesson-1",
                kind=MediaEvidenceKind.BOARD_OBSERVATION,
                start_ms=0,
                end_ms=1,
                fields=(
                    MediaEvidenceField("position", "one"),
                    MediaEvidenceField("position", "two"),
                ),
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

    def test_media_evidence_rejects_invalid_range_and_active_kind(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaEvidence(
                evidence_id="ev-1",
                source_id="lesson-1",
                kind=MediaEvidenceKind.SPEECH_CONTEXT,
                start_ms=20,
                end_ms=19,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)
        class ReprBomb:
            def __repr__(self):
                raise AssertionError("repr must not be evaluated")
        with self.assertRaises(MediaContractError) as caught:
            MediaEvidence(
                evidence_id="ev-2",
                source_id="lesson-1",
                kind=ReprBomb(),
                start_ms=0,
                end_ms=0,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)


    def test_media_evidence_provenance_is_explicit_but_never_chess_authority(self):
        evidence = MediaEvidence(
            evidence_id="ev-provenance",
            source_id="lesson-1",
            kind=MediaEvidenceKind.STRUCTURED_CHESS,
            start_ms=10,
            end_ms=20,
            confidence=0.99,
            source_authoritative=True,
            source_revision="broadcast-rev-42",
            provider_id="lichess-broadcast",
            producer_revision="adapter-v3",
            provenance="provider structured move feed",
            raw_candidate_ref="provider-ply-17",
        )
        self.assertTrue(evidence.source_authoritative)
        self.assertEqual(evidence.source_revision, "broadcast-rev-42")
        self.assertEqual(evidence.provider_id, "lichess-broadcast")
        self.assertEqual(evidence.producer_revision, "adapter-v3")
        self.assertEqual(evidence.provenance, "provider structured move feed")
        self.assertEqual(evidence.raw_candidate_ref, "provider-ply-17")
        with self.assertRaises(AttributeError):
            _ = evidence.authoritative

    def test_media_evidence_source_authority_is_exact_boolean(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaEvidence(
                evidence_id="ev-bool",
                source_id="lesson-1",
                kind=MediaEvidenceKind.STRUCTURED_CHESS,
                start_ms=0,
                end_ms=0,
                source_authoritative=1,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

    def test_media_evidence_provenance_text_is_bounded_and_utf8_safe(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaEvidence(
                evidence_id="ev-too-long",
                source_id="lesson-1",
                kind=MediaEvidenceKind.SPEECH_CONTEXT,
                start_ms=0,
                end_ms=1,
                provenance="x" * 4097,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TEXT)

        with self.assertRaises(MediaContractError) as caught:
            MediaEvidence(
                evidence_id="ev-bad-utf8",
                source_id="lesson-1",
                kind=MediaEvidenceKind.SPEECH_CONTEXT,
                start_ms=0,
                end_ms=1,
                raw_candidate_ref="bad\ud800",
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TEXT)

    def test_reconciliation_result_enforces_fail_closed_state_semantics(self):
        verified = MediaReconciliationResult(
            source_id="lesson-1",
            state=MediaReconciliationState.VERIFIED,
            evidence_ids=("ev-1",),
            chess_ref="canonical:node:7",
            candidate_refs=("canonical:node:7",),
            confidence=1.0,
            reason="canonical application verified the transition",
        )
        self.assertEqual(verified.chess_ref, "canonical:node:7")
        ambiguous = MediaReconciliationResult(
            source_id="lesson-1",
            state=MediaReconciliationState.AMBIGUOUS,
            evidence_ids=("ev-1",),
            candidate_refs=("canonical:a", "canonical:b"),
            confidence=0.7,
            reason="two canonical candidates remain",
        )
        self.assertIsNone(ambiguous.chess_ref)
        with self.assertRaises(MediaContractError) as caught:
            MediaReconciliationResult(
                source_id="lesson-1",
                state=MediaReconciliationState.AMBIGUOUS,
                evidence_ids=("ev-1",),
                chess_ref="must-not-publish",
                candidate_refs=("canonical:a", "canonical:b"),
                reason="ambiguous",
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.RECONCILIATION_FAILED)
        with self.assertRaises(MediaContractError) as caught:
            MediaReconciliationResult(
                source_id="lesson-1",
                state=MediaReconciliationState.INFERRED,
                evidence_ids=("ev-1",),
                reason="missing canonical ref",
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.RECONCILIATION_FAILED)


    def test_reconciler_batch_preserves_typed_evidence_bundle(self):
        evidence = (
            MediaEvidence(
                evidence_id="board-1",
                source_id="lesson-1",
                kind=MediaEvidenceKind.BOARD_OBSERVATION,
                start_ms=1000,
                end_ms=1000,
                source_revision="source-v1",
                confidence=0.9,
            ),
            MediaEvidence(
                evidence_id="speech-1",
                source_id="lesson-1",
                kind=MediaEvidenceKind.SPEECH_CONTEXT,
                start_ms=900,
                end_ms=1100,
                source_revision="source-v1",
                confidence=0.8,
            ),
        )

        class BatchPort:
            def reconcile_media_evidence_batch(self, *, current_chess_ref, evidence):
                self.seen = (current_chess_ref, evidence)
                return MediaReconciliationResult(
                    source_id="lesson-1",
                    state=MediaReconciliationState.INFERRED,
                    evidence_ids=("speech-1", "board-1"),
                    chess_ref="canonical:node:17",
                    confidence=0.87,
                    reason="canonical application reconciled board and speech",
                )

        port = BatchPort()
        result = ChessStateReconciler(port).reconcile_many(
            evidence,
            current_chess_ref="canonical:node:16",
        )
        self.assertEqual(port.seen, ("canonical:node:16", evidence))
        self.assertEqual(result.chess_ref, "canonical:node:17")
        self.assertEqual(result.state, MediaReconciliationState.INFERRED)

    def test_reconciler_batch_rejects_cross_source_or_revision_evidence(self):
        board = MediaEvidence(
            evidence_id="board-1",
            source_id="lesson-1",
            kind=MediaEvidenceKind.BOARD_OBSERVATION,
            start_ms=1000,
            end_ms=1000,
            source_revision="source-v1",
        )
        cross_source = MediaEvidence(
            evidence_id="speech-1",
            source_id="lesson-2",
            kind=MediaEvidenceKind.SPEECH_CONTEXT,
            start_ms=900,
            end_ms=1100,
            source_revision="source-v1",
        )
        stale = MediaEvidence(
            evidence_id="speech-2",
            source_id="lesson-1",
            kind=MediaEvidenceKind.SPEECH_CONTEXT,
            start_ms=900,
            end_ms=1100,
            source_revision="source-v0",
        )

        class NeverPort:
            def reconcile_media_evidence_batch(self, **_kwargs):
                raise AssertionError("invalid bundle must fail before canonical call")

        reconciler = ChessStateReconciler(NeverPort())
        with self.assertRaises(MediaContractError) as caught:
            reconciler.reconcile_many((board, cross_source))
        self.assertEqual(caught.exception.code, MediaErrorCode.SOURCE_MISMATCH)
        with self.assertRaises(MediaContractError) as caught:
            reconciler.reconcile_many((board, stale))
        self.assertEqual(caught.exception.code, MediaErrorCode.RECONCILIATION_FAILED)

    def test_reconciler_batch_rejects_duplicate_ids_and_partial_result_binding(self):
        first = MediaEvidence(
            evidence_id="ev-1",
            source_id="lesson-1",
            kind=MediaEvidenceKind.BOARD_OBSERVATION,
            start_ms=0,
            end_ms=0,
        )
        duplicate = MediaEvidence(
            evidence_id="ev-1",
            source_id="lesson-1",
            kind=MediaEvidenceKind.SPEECH_CONTEXT,
            start_ms=0,
            end_ms=0,
        )

        class PartialPort:
            def reconcile_media_evidence_batch(self, *, current_chess_ref, evidence):
                return MediaReconciliationResult(
                    source_id="lesson-1",
                    state=MediaReconciliationState.NO_CHANGE,
                    evidence_ids=("ev-1",),
                    confidence=1.0,
                    reason="partial binding",
                )

        reconciler = ChessStateReconciler(PartialPort())
        with self.assertRaises(MediaContractError) as caught:
            reconciler.reconcile_many((first, duplicate))
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

        second = MediaEvidence(
            evidence_id="ev-2",
            source_id="lesson-1",
            kind=MediaEvidenceKind.SPEECH_CONTEXT,
            start_ms=0,
            end_ms=0,
        )
        with self.assertRaises(MediaContractError) as caught:
            reconciler.reconcile_many((first, second))
        self.assertEqual(caught.exception.code, MediaErrorCode.RECONCILIATION_FAILED)

    def test_reconciler_batch_requires_batch_capability(self):
        evidence = (
            MediaEvidence(
                evidence_id="ev-1",
                source_id="lesson-1",
                kind=MediaEvidenceKind.BOARD_OBSERVATION,
                start_ms=0,
                end_ms=0,
            ),
        )

        class SinglePort:
            def reconcile_media_evidence(self, *, current_chess_ref, evidence):
                return MediaReconciliationResult(
                    source_id=evidence.source_id,
                    state=MediaReconciliationState.NO_CHANGE,
                    evidence_ids=(evidence.evidence_id,),
                    reason="single only",
                )

        with self.assertRaises(MediaContractError) as caught:
            ChessStateReconciler(SinglePort()).reconcile_many(evidence)
        self.assertEqual(caught.exception.code, MediaErrorCode.RECONCILIATION_FAILED)

    def test_reconciler_delegates_to_canonical_port_without_chess_semantics(self):
        evidence = MediaEvidence(
            evidence_id="ev-1",
            source_id="lesson-1",
            kind=MediaEvidenceKind.STRUCTURED_CHESS,
            start_ms=1000,
            end_ms=1000,
            fields=(MediaEvidenceField("provider-move", "opaque-provider-token"),),
            confidence=1.0,
            source_authoritative=True,
        )
        class CanonicalPort:
            def reconcile_media_evidence(self, *, current_chess_ref, evidence):
                self.seen = (current_chess_ref, evidence)
                return MediaReconciliationResult(
                    source_id=evidence.source_id,
                    state=MediaReconciliationState.VERIFIED,
                    evidence_ids=(evidence.evidence_id,),
                    chess_ref="canonical:node:next",
                    candidate_refs=("canonical:node:next",),
                    confidence=evidence.confidence,
                    reason="verified by canonical chess application",
                )
        port = CanonicalPort()
        result = ChessStateReconciler(port).reconcile(
            evidence,
            current_chess_ref="canonical:node:current",
        )
        self.assertEqual(port.seen, ("canonical:node:current", evidence))
        self.assertEqual(result.state, MediaReconciliationState.VERIFIED)
        self.assertEqual(result.chess_ref, "canonical:node:next")

    def test_reconciler_preserves_explicit_ambiguity_without_guessing(self):
        evidence = MediaEvidence(
            evidence_id="ev-ambiguous",
            source_id="lesson-1",
            kind=MediaEvidenceKind.BOARD_OBSERVATION,
            start_ms=5000,
            end_ms=5000,
            confidence=0.91,
        )
        class CanonicalPort:
            def reconcile_media_evidence(self, *, current_chess_ref, evidence):
                return MediaReconciliationResult(
                    source_id=evidence.source_id,
                    state=MediaReconciliationState.AMBIGUOUS,
                    evidence_ids=(evidence.evidence_id,),
                    candidate_refs=("canonical:a", "canonical:b"),
                    confidence=evidence.confidence,
                    reason="multiple canonical states remain possible",
                )
        result = ChessStateReconciler(CanonicalPort()).reconcile(evidence)
        self.assertEqual(result.state, MediaReconciliationState.AMBIGUOUS)
        self.assertIsNone(result.chess_ref)
        self.assertEqual(result.candidate_refs, ("canonical:a", "canonical:b"))

    def test_reconciler_sanitizes_port_failure_and_rejects_unbound_results(self):
        evidence = MediaEvidence(
            evidence_id="ev-1",
            source_id="lesson-1",
            kind=MediaEvidenceKind.USER_CORRECTION,
            start_ms=0,
            end_ms=0,
        )
        class BrokenPort:
            def reconcile_media_evidence(self, *, current_chess_ref, evidence):
                raise RuntimeError("private C:/secret/provider/path")
        with self.assertRaises(MediaContractError) as caught:
            ChessStateReconciler(BrokenPort()).reconcile(evidence)
        self.assertEqual(caught.exception.code, MediaErrorCode.RECONCILIATION_FAILED)
        self.assertNotIn("secret", str(caught.exception))
        class UnboundPort:
            def reconcile_media_evidence(self, *, current_chess_ref, evidence):
                return MediaReconciliationResult(
                    source_id="other-source",
                    state=MediaReconciliationState.NO_CHANGE,
                    evidence_ids=("other-evidence",),
                    confidence=1.0,
                    reason="no change",
                )
        with self.assertRaises(MediaContractError) as caught:
            ChessStateReconciler(UnboundPort()).reconcile(evidence)
        self.assertEqual(caught.exception.code, MediaErrorCode.RECONCILIATION_FAILED)






    def test_confirm_candidate_promotes_qualification_and_demotes_replaced_link(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (
                self.link(1000, "tree:old"),
                self.link(1000, "tree:new", confirmed=False, confidence=0.9),
            ),
        )
        updated = timeline.confirm_candidate(
            1000,
            "tree:new",
            replace_confirmed=True,
        )
        links = {link.chess_ref: link for link in updated.links_at(1000)}
        self.assertEqual(links["tree:new"].status, MediaLinkStatus.CONFIRMED)
        self.assertEqual(
            links["tree:new"].qualification,
            MediaReconciliationState.VERIFIED,
        )
        self.assertEqual(links["tree:old"].status, MediaLinkStatus.CANDIDATE)
        self.assertEqual(
            links["tree:old"].qualification,
            MediaReconciliationState.OBSERVED,
        )
        self.assertEqual(updated.resolve_exact(1000).chess_ref, "tree:new")

    def test_timeline_from_dict_rejects_non_list_evidence_ids(self):
        payload = {
            "source_id": "lesson-1",
            "links": [
                {
                    "timestamp_ms": 1000,
                    "chess_ref": "tree:a",
                    "status": "confirmed",
                    "confidence": 1.0,
                    "evidence": None,
                    "evidence_ids": "not-a-list",
                }
            ],
        }
        with self.assertRaises(MediaContractError) as caught:
            MediaPositionTimeline.from_dict(payload)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

    def test_rich_timeline_link_carries_range_segment_position_and_evidence_identity(self):
        link = MediaChessLink(
            source_id="lesson-1",
            timestamp_ms=10_000,
            chess_ref="tree:segment-2:path-17",
            status=MediaLinkStatus.CONFIRMED,
            confidence=0.95,
            evidence="canonical application fixture",
            end_timestamp_ms=14_999,
            segment_id="segment-2",
            position_id="position:canonical-hash-17",
            qualification=MediaReconciliationState.INFERRED,
            evidence_ids=("ev-board-4", "ev-speech-9"),
        )
        timeline = MediaPositionTimeline("lesson-1", (link,))
        resolution = timeline.resolve_exact(10_000)
        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.end_timestamp_ms, 14_999)
        self.assertEqual(resolution.segment_id, "segment-2")
        self.assertEqual(resolution.position_id, "position:canonical-hash-17")
        self.assertEqual(resolution.qualification, MediaReconciliationState.INFERRED)
        self.assertEqual(resolution.evidence_ids, ("ev-board-4", "ev-speech-9"))
        self.assertEqual(timeline.links_covering(12_000), (link,))
        self.assertEqual(timeline.links_covering(15_000), ())

    def test_rich_timeline_link_round_trip_preserves_mapping_metadata(self):
        link = MediaChessLink(
            source_id="lesson-1",
            timestamp_ms=1000,
            chess_ref="tree:a",
            status=MediaLinkStatus.CONFIRMED,
            confidence=1.0,
            end_timestamp_ms=1999,
            segment_id="segment-a",
            position_id="position-a",
            qualification=MediaReconciliationState.VERIFIED,
            evidence_ids=("ev-1",),
        )
        timeline = MediaPositionTimeline("lesson-1", (link,))
        restored = MediaPositionTimeline.from_dict(timeline.to_dict())
        self.assertEqual(restored.links, (link,))
        self.assertEqual(restored.resolve_exact(1000).position_id, "position-a")

    def test_timeline_link_rejects_invalid_range_and_qualification(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaChessLink(
                source_id="lesson-1",
                timestamp_ms=1000,
                chess_ref="tree:a",
                end_timestamp_ms=999,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

        with self.assertRaises(MediaContractError) as caught:
            MediaChessLink(
                source_id="lesson-1",
                timestamp_ms=1000,
                chess_ref="tree:a",
                status=MediaLinkStatus.CONFIRMED,
                qualification=MediaReconciliationState.OBSERVED,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

        with self.assertRaises(MediaContractError) as caught:
            MediaChessLink(
                source_id="lesson-1",
                timestamp_ms=1000,
                chess_ref="candidate:a",
                status=MediaLinkStatus.CANDIDATE,
                qualification=MediaReconciliationState.VERIFIED,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

    def test_next_previous_resolved_skip_candidates_ambiguity_and_resync_barriers(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (
                self.link(1000, "tree:a"),
                self.link(2000, "candidate:only", confirmed=False),
                self.link(3000, "tree:x"),
                self.link(3000, "tree:y"),
                self.link(5000, "tree:b"),
            ),
            barriers=(
                MediaTimelineBarrier(
                    source_id="lesson-1",
                    timestamp_ms=4000,
                    state=MediaReconciliationState.RESYNC_REQUIRED,
                ),
            ),
        )
        next_result = timeline.next_resolved(1000)
        self.assertIsNotNone(next_result)
        self.assertEqual(next_result.anchor_timestamp_ms, 5000)
        self.assertEqual(next_result.chess_ref, "tree:b")

        previous_result = timeline.previous_resolved(5000)
        self.assertIsNotNone(previous_result)
        self.assertEqual(previous_result.anchor_timestamp_ms, 1000)
        self.assertEqual(previous_result.chess_ref, "tree:a")

        self.assertIsNone(timeline.next_resolved(5000))
        self.assertIsNone(timeline.previous_resolved(1000))

    def test_barrier_resolution_exposes_segment_and_evidence_ids(self):
        barrier = MediaTimelineBarrier(
            source_id="lesson-1",
            timestamp_ms=7000,
            state=MediaReconciliationState.RESYNC_REQUIRED,
            segment_id="segment-new",
            evidence_ids=("ev-jump",),
            reason="unrelated position jump",
        )
        timeline = MediaPositionTimeline("lesson-1", (), barriers=(barrier,))
        result = timeline.resolve_exact(7000)
        self.assertEqual(result.segment_id, "segment-new")
        self.assertEqual(result.evidence_ids, ("ev-jump",))
        self.assertEqual(
            result.qualification,
            MediaReconciliationState.RESYNC_REQUIRED,
        )

    def test_resync_barrier_blocks_stale_confirmed_fallback(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (self.link(1000, "canonical:old"),),
            barriers=(
                MediaTimelineBarrier(
                    source_id="lesson-1",
                    timestamp_ms=5000,
                    state=MediaReconciliationState.RESYNC_REQUIRED,
                    reason="provider jumped to an unrelated position",
                ),
            ),
        )
        before = timeline.resolve_at_or_before(4999)
        self.assertEqual(before.chess_ref, "canonical:old")
        blocked = timeline.resolve_at_or_before(5000)
        self.assertFalse(blocked.resolved)
        self.assertIsNone(blocked.chess_ref)
        self.assertEqual(
            blocked.qualification,
            MediaReconciliationState.RESYNC_REQUIRED,
        )
        self.assertIsNotNone(blocked.barrier)

    def test_ambiguous_barrier_is_explicit_and_never_guesses(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (
                self.link(
                    5000,
                    "canonical:a",
                    confirmed=False,
                    confidence=0.9,
                ),
                self.link(
                    5000,
                    "canonical:b",
                    confirmed=False,
                    confidence=0.8,
                ),
            ),
            barriers=(
                MediaTimelineBarrier(
                    source_id="lesson-1",
                    timestamp_ms=5000,
                    state=MediaReconciliationState.AMBIGUOUS,
                    evidence_ids=("ev-a", "ev-b"),
                    reason="two canonical candidates remain",
                ),
            ),
        )
        result = timeline.resolve_exact(5000)
        self.assertTrue(result.ambiguous)
        self.assertIsNone(result.chess_ref)
        self.assertEqual(
            result.qualification,
            MediaReconciliationState.AMBIGUOUS,
        )

    def test_explicit_confirmation_removes_same_timestamp_barrier(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (
                self.link(
                    5000,
                    "canonical:a",
                    confirmed=False,
                    confidence=0.9,
                ),
                self.link(
                    5000,
                    "canonical:b",
                    confirmed=False,
                    confidence=0.8,
                ),
            ),
            barriers=(
                MediaTimelineBarrier(
                    source_id="lesson-1",
                    timestamp_ms=5000,
                    state=MediaReconciliationState.AMBIGUOUS,
                    reason="needs explicit selection",
                ),
            ),
        )
        resolved = timeline.confirm_candidate(5000, "canonical:b")
        self.assertIsNone(resolved.barrier_at(5000))
        self.assertEqual(resolved.resolve_exact(5000).chess_ref, "canonical:b")

    def test_timeline_barrier_round_trip_preserves_fail_closed_anchor(self):
        timeline = MediaPositionTimeline(
            "lesson-1",
            (self.link(1000, "canonical:old"),),
            identity=self.session_identity(),
            barriers=(
                MediaTimelineBarrier(
                    source_id="lesson-1",
                    timestamp_ms=9000,
                    state=MediaReconciliationState.RESYNC_REQUIRED,
                    segment_id="segment-2",
                    evidence_ids=("ev-9",),
                    reason="unrelated-position jump",
                ),
            ),
        )
        encoded = serialize_media_state(
            self.source(),
            timeline,
            MediaChessSession(MediaCursor("lesson-1", 9000), "analysis:node"),
        )
        _source, restored, _session = deserialize_media_state(encoded)
        self.assertEqual(restored.barriers, timeline.barriers)
        result = restored.resolve_at_or_before(9000)
        self.assertFalse(result.resolved)
        self.assertEqual(
            result.qualification,
            MediaReconciliationState.RESYNC_REQUIRED,
        )

    def test_timeline_identity_is_bound_preserved_and_persisted(self):
        identity = MediaTimelineIdentity(
            source_id="lesson-1",
            source_revision="source-v1",
            recognizer_revision="vision-v1",
            reconciliation_revision="reconcile-v1",
            provider_revision="provider-v1",
            cache_version=3,
        )
        timeline = MediaPositionTimeline(
            "lesson-1",
            (self.link(1000, "canonical:a"),),
            identity=identity,
        )
        extended = timeline.with_link(self.link(2000, "canonical:b"))
        self.assertEqual(extended.identity, identity)
        confirmed = extended.confirm_candidate(2000, "canonical:b")
        self.assertEqual(confirmed.identity, identity)

        encoded = serialize_media_state(
            self.source(),
            confirmed,
            MediaChessSession(MediaCursor("lesson-1", 2000), "canonical:analysis"),
        )
        _source, restored, _session = deserialize_media_state(encoded)
        self.assertEqual(restored.identity, identity)
        self.assertEqual(restored.links, confirmed.links)

    def test_timeline_identity_rejects_cross_source_binding(self):
        identity = MediaTimelineIdentity(
            source_id="other-source",
            source_revision="source-v1",
            recognizer_revision="vision-v1",
            reconciliation_revision="reconcile-v1",
        )
        with self.assertRaises(MediaContractError) as caught:
            MediaPositionTimeline("lesson-1", (), identity=identity)
        self.assertEqual(caught.exception.code, MediaErrorCode.SOURCE_MISMATCH)

    def test_legacy_timeline_payload_without_identity_still_loads(self):
        payload = {
            "source_id": "lesson-1",
            "links": [
                {
                    "timestamp_ms": 1000,
                    "chess_ref": "canonical:a",
                    "status": "confirmed",
                    "confidence": 1.0,
                    "evidence": None,
                }
            ],
        }
        timeline = MediaPositionTimeline.from_dict(payload)
        self.assertIsNone(timeline.identity)
        self.assertEqual(timeline.resolve_exact(1000).chess_ref, "canonical:a")

    def session_identity(self, *, provider_revision="provider-v1"):
        return MediaTimelineIdentity(
            source_id="lesson-1",
            source_revision="source-v1",
            recognizer_revision="vision-v1",
            reconciliation_revision="reconcile-v1",
            provider_revision=provider_revision,
            cache_version=1,
        )

    def media_session(self):
        identity = self.session_identity()
        return MediaSession(
            session_id="session-1",
            source_id="lesson-1",
            source_kind=MediaSourceKind.PROVIDER,
            source_revision="source-v1",
            source_ref="opaque-provider-media-id",
            clock=MediaClockSnapshot(
                position_ms=12_500,
                state=MediaPlaybackState.PAUSED,
                playback_rate=1.25,
                duration_ms=120_000,
                revision=7,
            ),
            timeline_identity=identity,
            media_chess_ref="canonical:media-node",
            analysis_chess_ref="canonical:analysis-node",
            revision=11,
        )

    def test_media_session_keeps_media_and_analysis_cursors_independent(self):
        session = self.media_session()
        changed = session.select_analysis_cursor("canonical:variation-node")
        self.assertEqual(changed.media_chess_ref, "canonical:media-node")
        self.assertEqual(changed.analysis_chess_ref, "canonical:variation-node")
        self.assertEqual(changed.clock.position_ms, 12_500)
        self.assertEqual(changed.revision, 12)

    def test_source_revision_change_invalidates_media_timeline_but_preserves_analysis(self):
        session = self.media_session()
        changed = session.with_source_revision("source-v2")
        self.assertEqual(changed.source_revision, "source-v2")
        self.assertIsNone(changed.timeline_identity)
        self.assertIsNone(changed.media_chess_ref)
        self.assertEqual(changed.analysis_chess_ref, "canonical:analysis-node")
        self.assertEqual(changed.clock, session.clock)
        self.assertEqual(changed.timeline_invalidated_reason, "source revision changed")
        self.assertEqual(changed.revision, 12)

    def test_recognizer_or_provider_revision_mismatch_invalidates_fail_closed(self):
        session = self.media_session()
        expected = MediaTimelineIdentity(
            source_id="lesson-1",
            source_revision="source-v1",
            recognizer_revision="vision-v2",
            reconciliation_revision="reconcile-v1",
            provider_revision="provider-v2",
            cache_version=1,
        )
        self.assertFalse(session.timeline_compatible(expected))
        invalidated = session.invalidate_if_timeline_changed(expected)
        self.assertIsNone(invalidated.timeline_identity)
        self.assertIsNone(invalidated.media_chess_ref)
        self.assertEqual(
            invalidated.timeline_invalidated_reason,
            "timeline dependency revision changed",
        )
        self.assertEqual(
            invalidated.analysis_chess_ref,
            "canonical:analysis-node",
        )

    def test_media_cursor_binding_rejects_stale_or_cross_source_timeline(self):
        session = self.media_session().invalidate_timeline("rebuild required")
        stale = MediaTimelineIdentity(
            source_id="lesson-1",
            source_revision="source-v0",
            recognizer_revision="vision-v1",
            reconciliation_revision="reconcile-v1",
        )
        with self.assertRaises(MediaContractError) as caught:
            session.bind_media_cursor(stale, "canonical:new-media-node")
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

        cross_source = MediaTimelineIdentity(
            source_id="other-source",
            source_revision="source-v1",
            recognizer_revision="vision-v1",
            reconciliation_revision="reconcile-v1",
        )
        with self.assertRaises(MediaContractError) as caught:
            session.bind_media_cursor(cross_source, "canonical:new-media-node")
        self.assertEqual(caught.exception.code, MediaErrorCode.SOURCE_MISMATCH)

    def test_media_session_restart_round_trip_preserves_clock_and_timeline_identity(self):
        session = self.media_session()
        encoded = serialize_media_session(session)
        restored = deserialize_media_session(encoded)
        self.assertEqual(restored, session)
        self.assertEqual(restored.clock.position_ms, 12_500)
        self.assertEqual(restored.clock.playback_rate, 1.25)
        self.assertEqual(restored.media_chess_ref, "canonical:media-node")
        self.assertEqual(restored.analysis_chess_ref, "canonical:analysis-node")
        self.assertTrue(restored.timeline_compatible(self.session_identity()))

    def test_media_session_persistence_rejects_unknown_fields_and_duplicate_keys(self):
        session = self.media_session()
        payload = json.loads(serialize_media_session(session))
        payload["unexpected"] = True
        with self.assertRaises(MediaContractError) as caught:
            deserialize_media_session(json.dumps(payload))
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_SCHEMA)

        duplicate = (
            '{"schema":"accessible-chess.media-session",'
            '"schema":"attacker",'
            '"version":1,"session":{}}'
        )
        with self.assertRaises(MediaContractError) as caught:
            deserialize_media_session(duplicate)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_SCHEMA)

    def test_direct_clock_snapshot_construction_is_fail_closed(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaClockSnapshot(
                position_ms=101,
                state=MediaPlaybackState.PAUSED,
                playback_rate=1.0,
                duration_ms=100,
                revision=0,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

        with self.assertRaises(MediaContractError) as caught:
            MediaClockSnapshot(
                position_ms=0,
                state="not-a-state",
                playback_rate=1.0,
                duration_ms=None,
                revision=0,
            )
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

    def test_schema_identifier_is_stable(self):
        self.assertEqual(MEDIA_STATE_SCHEMA, "accessible-chess.media-state")



    def test_clock_restart_from_snapshot_preserves_revision_and_reanchors_host_time(self):
        clock = MediaClock(duration_ms=10_000)
        clock.play(100)
        clock.set_playback_rate(1.5, 1100)
        persisted = clock.snapshot(2100)
        self.assertEqual(persisted.position_ms, 2500)
        self.assertEqual(persisted.revision, 2)

        restored = MediaClock.from_snapshot(persisted, now_ms=50_000)
        immediate = restored.snapshot(50_000)
        self.assertEqual(immediate, persisted)
        self.assertEqual(restored.revision, 2)
        after = restored.snapshot(51_000)
        self.assertEqual(after.position_ms, 4000)
        self.assertEqual(after.revision, 2)

    def test_clock_restart_does_not_replay_process_downtime(self):
        persisted = MediaClockSnapshot(
            position_ms=5000,
            state=MediaPlaybackState.PLAYING,
            playback_rate=1.0,
            duration_ms=20_000,
            revision=9,
        )
        restored = MediaClock.from_snapshot(persisted, now_ms=1_000_000)
        self.assertEqual(restored.snapshot(1_000_000).position_ms, 5000)
        self.assertEqual(restored.snapshot(1_001_000).position_ms, 6000)

    def test_clock_restart_rejects_non_snapshot_and_invalid_host_anchor(self):
        with self.assertRaises(MediaContractError) as caught:
            MediaClock.from_snapshot(object())
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)
        snapshot = MediaClock().snapshot(0)
        with self.assertRaises(MediaContractError) as caught:
            MediaClock.from_snapshot(snapshot, now_ms=-1)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

    def test_media_session_rejects_stale_or_unrevisioned_clock_rollback(self):
        session = self.media_session()
        stale = MediaClockSnapshot(
            position_ms=20_000,
            state=session.clock.state,
            playback_rate=session.clock.playback_rate,
            duration_ms=session.clock.duration_ms,
            revision=session.clock.revision - 1,
        )
        with self.assertRaises(MediaContractError) as caught:
            session.with_clock(stale)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

        same_revision_rewind = MediaClockSnapshot(
            position_ms=session.clock.position_ms - 1,
            state=session.clock.state,
            playback_rate=session.clock.playback_rate,
            duration_ms=session.clock.duration_ms,
            revision=session.clock.revision,
        )
        with self.assertRaises(MediaContractError) as caught:
            session.with_clock(same_revision_rewind)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

    def test_media_session_accepts_same_revision_forward_materialization(self):
        session = self.media_session()
        advanced = MediaClockSnapshot(
            position_ms=session.clock.position_ms + 500,
            state=session.clock.state,
            playback_rate=session.clock.playback_rate,
            duration_ms=session.clock.duration_ms,
            revision=session.clock.revision,
        )
        updated = session.with_clock(advanced)
        self.assertEqual(updated.clock, advanced)
        self.assertEqual(updated.revision, session.revision + 1)

    def test_media_session_requires_revision_for_clock_control_change(self):
        session = self.media_session()
        illegal = MediaClockSnapshot(
            position_ms=session.clock.position_ms,
            state=MediaPlaybackState.PLAYING,
            playback_rate=session.clock.playback_rate,
            duration_ms=session.clock.duration_ms,
            revision=session.clock.revision,
        )
        with self.assertRaises(MediaContractError) as caught:
            session.with_clock(illegal)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONTAINER)

        legal = MediaClockSnapshot(
            position_ms=session.clock.position_ms,
            state=MediaPlaybackState.PLAYING,
            playback_rate=session.clock.playback_rate,
            duration_ms=session.clock.duration_ms,
            revision=session.clock.revision + 1,
        )
        updated = session.with_clock(legal)
        self.assertEqual(updated.clock, legal)

    def test_clock_starts_unstarted_and_snapshot_is_deterministic(self):
        clock = MediaClock()
        first = clock.snapshot(0)
        second = clock.snapshot(1000)
        self.assertIsInstance(first, MediaClockSnapshot)
        self.assertEqual(first.position_ms, 0)
        self.assertEqual(first.state, MediaPlaybackState.UNSTARTED)
        self.assertEqual(first.revision, 0)
        self.assertEqual(second.position_ms, 0)
        self.assertEqual(second.revision, 0)

    def test_clock_play_advances_at_explicit_rate(self):
        clock = MediaClock()
        started = clock.play(100)
        self.assertEqual(started.state, MediaPlaybackState.PLAYING)
        self.assertEqual(started.position_ms, 0)
        advanced = clock.snapshot(1100)
        self.assertEqual(advanced.position_ms, 1000)
        self.assertEqual(advanced.state, MediaPlaybackState.PLAYING)

    def test_clock_pause_freezes_materialized_position(self):
        clock = MediaClock()
        clock.play(0)
        paused = clock.pause(1500)
        self.assertEqual(paused.position_ms, 1500)
        self.assertEqual(paused.state, MediaPlaybackState.PAUSED)
        self.assertEqual(clock.snapshot(3000).position_ms, 1500)

    def test_clock_buffering_freezes_until_resume(self):
        clock = MediaClock()
        clock.play(0)
        buffering = clock.buffer(1200)
        self.assertEqual(buffering.position_ms, 1200)
        self.assertEqual(buffering.state, MediaPlaybackState.BUFFERING)
        self.assertEqual(clock.snapshot(5000).position_ms, 1200)
        resumed = clock.resume(5000)
        self.assertEqual(resumed.state, MediaPlaybackState.PLAYING)
        self.assertEqual(clock.snapshot(5600).position_ms, 1800)

    def test_clock_late_buffer_event_cannot_cancel_explicit_pause(self):
        clock = MediaClock()
        clock.play(0)
        clock.pause(1000)
        buffered = clock.buffer(1100)
        self.assertEqual(buffered.state, MediaPlaybackState.PAUSED)
        self.assertEqual(buffered.position_ms, 1000)
    def test_clock_pause_during_buffering_honors_explicit_user_pause(self):
        clock = MediaClock()
        clock.play(0)
        clock.buffer(1000)
        paused = clock.pause(1200)
        self.assertEqual(paused.state, MediaPlaybackState.PAUSED)
        self.assertEqual(paused.position_ms, 1000)
        self.assertEqual(clock.resume(1200).state, MediaPlaybackState.PLAYING)

    def test_clock_fractional_rate_progress_is_not_lost_between_snapshots(self):
        clock = MediaClock(playback_rate=1.5)
        clock.play(0)
        self.assertEqual(clock.snapshot(1).position_ms, 1)
        self.assertEqual(clock.snapshot(2).position_ms, 3)
        self.assertEqual(clock.snapshot(3).position_ms, 4)

    def test_clock_rate_change_reanchors_without_position_jump(self):
        clock = MediaClock()
        clock.play(0)
        changed = clock.set_playback_rate(2.0, 1000)
        self.assertEqual(changed.position_ms, 1000)
        self.assertEqual(changed.playback_rate, 2.0)
        self.assertEqual(clock.snapshot(1500).position_ms, 2000)

    def test_clock_seek_reanchors_and_allows_rewind_after_end(self):
        clock = MediaClock(duration_ms=2000)
        clock.play(0)
        ended = clock.snapshot(3000)
        self.assertEqual(ended.position_ms, 2000)
        self.assertEqual(ended.state, MediaPlaybackState.ENDED)
        rewound = clock.seek(500, 3000)
        self.assertEqual(rewound.position_ms, 500)
        self.assertEqual(rewound.state, MediaPlaybackState.PAUSED)
        self.assertEqual(clock.snapshot(3500).position_ms, 500)
        clock.resume(3500)
        self.assertEqual(clock.snapshot(4000).position_ms, 1000)

    def test_clock_late_buffer_event_cannot_reopen_ended_media(self):
        clock = MediaClock(duration_ms=1000)
        clock.play(0)
        ended = clock.end(500)
        self.assertEqual(ended.state, MediaPlaybackState.ENDED)
        buffered = clock.buffer(600)
        self.assertEqual(buffered.state, MediaPlaybackState.ENDED)
        self.assertEqual(buffered.position_ms, 1000)
    def test_clock_end_clamps_to_duration_and_stays_ended(self):
        clock = MediaClock(duration_ms=5000)
        clock.play(0)
        ended = clock.end(1200)
        self.assertEqual(ended.position_ms, 5000)
        self.assertEqual(ended.state, MediaPlaybackState.ENDED)
        self.assertEqual(clock.snapshot(9000).position_ms, 5000)

    def test_clock_invalid_seek_does_not_mutate_position(self):
        clock = MediaClock(duration_ms=1000)
        clock.play(0)
        clock.snapshot(500)
        with self.assertRaises(MediaContractError) as caught:
            clock.seek(1001, 500)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)
        self.assertEqual(clock.snapshot(500).position_ms, 500)

    def test_clock_rejects_unrepresentable_elapsed_delta(self):
        clock = MediaClock(playback_rate=16.0)
        clock.play(0)
        before = clock.snapshot(0)
        with self.assertRaises(MediaContractError) as caught:
            clock.snapshot(10**1000)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)
        after = clock.snapshot(0)
        self.assertEqual(after, before)

    def test_clock_rejects_non_monotonic_host_time(self):
        clock = MediaClock()
        clock.play(10)
        with self.assertRaises(MediaContractError) as caught:
            clock.snapshot(9)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

    def test_clock_rejects_invalid_rate_and_duration(self):
        for value in (0, -1, math.nan, math.inf, True, "2.0", 10**1000):
            with self.subTest(value=value):
                with self.assertRaises(MediaContractError) as caught:
                    MediaClock(playback_rate=value)
                self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_PLAYBACK_RATE)
        with self.assertRaises(MediaContractError) as caught:
            MediaClock(position_ms=100, duration_ms=99)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

    def test_clock_revision_changes_on_control_events_not_read_only_advance(self):
        clock = MediaClock()
        self.assertEqual(clock.revision, 0)
        clock.snapshot(100)
        self.assertEqual(clock.revision, 0)
        started = clock.play(100)
        self.assertEqual(started.revision, 1)
        clock.snapshot(200)
        self.assertEqual(clock.revision, 1)
        changed = clock.set_playback_rate(1.5, 200)
        self.assertEqual(changed.revision, 2)
        repeated = clock.set_playback_rate(1.5, 300)
        self.assertEqual(repeated.revision, 2)

if __name__ == "__main__":
    unittest.main()
