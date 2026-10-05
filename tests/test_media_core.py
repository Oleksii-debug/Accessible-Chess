import json
import math
import unittest

from acs.media_core import (
    MEDIA_STATE_SCHEMA,
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
    deserialize_media_state,
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
        for value in (math.nan, math.inf, -0.1, 1.1, True):
            with self.subTest(value=value):
                with self.assertRaises(MediaContractError) as caught:
                    self.link(1_000, "tree:a", confirmed=False, confidence=value)
                self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_CONFIDENCE)

    def test_position_past_known_duration_is_rejected(self):
        session = MediaChessSession(MediaCursor("lesson-1", 0))
        with self.assertRaises(MediaContractError) as caught:
            session.seek_media(120_001, duration_ms=120_000)
        self.assertEqual(caught.exception.code, MediaErrorCode.INVALID_TIMESTAMP)

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

    def test_schema_identifier_is_stable(self):
        self.assertEqual(MEDIA_STATE_SCHEMA, "accessible-chess.media-state")


if __name__ == "__main__":
    unittest.main()
