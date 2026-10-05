from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from acs.media_core import MediaLinkStatus
from acs.media_preprocess import (
    BoardFrameEvidence,
    BoardOrientation,
    FrameDisposition,
    SpeechEvidence,
)
from acs.recorded_media_application import (
    CanonicalRecordedFrameApplicationAdapter,
    CanonicalRecordedPositionResolution,
    RecordedMediaApplicationAdapterError,
)


class _Application:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def reconcile_recorded_observation(self, *, frame, speech_context):
        self.calls.append((frame, speech_context))
        return self.result


def _frame(disposition=FrameDisposition.STABLE):
    return BoardFrameEvidence(
        "media-1",
        "rev-1",
        1200,
        disposition,
        BoardOrientation.WHITE_BOTTOM,
        0.92,
        "vision-observation:17",
    )


def _speech():
    return SpeechEvidence("media-1", "rev-1", 1000, 1200, "Knight f3", True, 0.8)


class RecordedMediaApplicationAdapterTests(unittest.TestCase):
    def test_confirmed_application_resolution_becomes_exact_media_link(self):
        application = _Application(
            CanonicalRecordedPositionResolution("game:42/node:17", True, 0.88)
        )
        adapter = CanonicalRecordedFrameApplicationAdapter(application)
        frame = _frame()
        speech = (_speech(),)

        link = adapter.resolve_recorded_frame(frame=frame, speech_context=speech)

        self.assertEqual(application.calls, [(frame, speech)])
        self.assertEqual(link.source_id, "media-1")
        self.assertEqual(link.timestamp_ms, 1200)
        self.assertEqual(link.chess_ref, "game:42/node:17")
        self.assertIs(link.status, MediaLinkStatus.CONFIRMED)
        self.assertEqual(link.confidence, 0.88)

    def test_candidate_resolution_stays_candidate(self):
        adapter = CanonicalRecordedFrameApplicationAdapter(
            _Application(CanonicalRecordedPositionResolution("game:42/node:18", False, 0.6))
        )
        link = adapter.resolve_recorded_frame(frame=_frame(), speech_context=())
        self.assertIs(link.status, MediaLinkStatus.CANDIDATE)
        self.assertFalse(link.confirmed)

    def test_application_may_decline_observation(self):
        adapter = CanonicalRecordedFrameApplicationAdapter(_Application(None))
        self.assertIsNone(adapter.resolve_recorded_frame(frame=_frame(), speech_context=()))

    def test_ambiguous_evidence_cannot_be_confirmed(self):
        adapter = CanonicalRecordedFrameApplicationAdapter(
            _Application(CanonicalRecordedPositionResolution("game:42/node:17", True, 0.9))
        )
        with self.assertRaises(RecordedMediaApplicationAdapterError):
            adapter.resolve_recorded_frame(
                frame=_frame(FrameDisposition.AMBIGUOUS), speech_context=()
            )

    def test_non_resolvable_frames_fail_before_application_call(self):
        application = _Application(None)
        adapter = CanonicalRecordedFrameApplicationAdapter(application)
        for disposition in (FrameDisposition.TRANSITION, FrameDisposition.OCCLUDED):
            with self.subTest(disposition=disposition):
                with self.assertRaises(RecordedMediaApplicationAdapterError):
                    adapter.resolve_recorded_frame(
                        frame=_frame(disposition), speech_context=()
                    )
        self.assertEqual(application.calls, [])

    def test_wrong_application_result_fails_closed(self):
        adapter = CanonicalRecordedFrameApplicationAdapter(_Application("game:42/node:17"))
        with self.assertRaises(RecordedMediaApplicationAdapterError):
            adapter.resolve_recorded_frame(frame=_frame(), speech_context=())

    def test_invalid_resolution_fields_fail_closed(self):
        bad_values = [
            ("", True, 0.5),
            ("game:1", 1, 0.5),
            ("game:1", True, float("nan")),
            ("game:1", False, 1.1),
        ]
        for args in bad_values:
            with self.subTest(args=args):
                with self.assertRaises(RecordedMediaApplicationAdapterError):
                    CanonicalRecordedPositionResolution(*args)

    def test_adapter_contains_no_chess_parser_or_rules_authority(self):
        source = Path(inspect.getsourcefile(CanonicalRecordedFrameApplicationAdapter)).read_text(
            encoding="utf-8"
        ).lower()
        forbidden = (
            "chesscore",
            "set_fen",
            "parse_san",
            "parse_uci",
            "pseudo_moves",
            "legal_moves",
        )
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
