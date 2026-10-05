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
from acs.recorded_media_sync import MAX_SPEECH_CONTEXT


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


def _speech(source_id="media-1", source_revision="rev-1"):
    return SpeechEvidence(source_id, source_revision, 1000, 1200, "Knight f3", True, 0.8)


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

    def test_cross_source_or_stale_speech_fails_before_application_call(self):
        application = _Application(None)
        adapter = CanonicalRecordedFrameApplicationAdapter(application)
        bad_contexts = (
            (_speech(source_id="media-2"),),
            (_speech(source_revision="rev-0"),),
        )
        for speech_context in bad_contexts:
            with self.subTest(speech_context=speech_context):
                with self.assertRaises(RecordedMediaApplicationAdapterError):
                    adapter.resolve_recorded_frame(
                        frame=_frame(), speech_context=speech_context
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

    def test_application_receives_detached_revalidated_evidence(self):
        application = _Application(
            CanonicalRecordedPositionResolution("game:42/node:17", True, 0.88)
        )
        adapter = CanonicalRecordedFrameApplicationAdapter(application)
        frame = _frame()
        speech = (_speech(),)

        adapter.resolve_recorded_frame(frame=frame, speech_context=speech)

        sent_frame, sent_speech = application.calls[0]
        self.assertEqual(sent_frame, frame)
        self.assertIsNot(sent_frame, frame)
        self.assertEqual(sent_speech, speech)
        self.assertIsNot(sent_speech, speech)
        self.assertIsNot(sent_speech[0], speech[0])

    def test_tampered_frame_fields_fail_before_application_call(self):
        cases = (
            ("source_id", object()),
            ("disposition", "stable"),
            ("confidence", object()),
        )
        for field_name, value in cases:
            with self.subTest(field=field_name):
                application = _Application(None)
                adapter = CanonicalRecordedFrameApplicationAdapter(application)
                frame = _frame()
                object.__setattr__(frame, field_name, value)

                with self.assertRaises(RecordedMediaApplicationAdapterError):
                    adapter.resolve_recorded_frame(frame=frame, speech_context=())

                self.assertEqual(application.calls, [])

    def test_tampered_speech_fields_fail_before_application_call(self):
        cases = (
            ("text", object()),
            ("is_final", 1),
            ("confidence", object()),
        )
        for field_name, value in cases:
            with self.subTest(field=field_name):
                application = _Application(None)
                adapter = CanonicalRecordedFrameApplicationAdapter(application)
                speech = _speech()
                object.__setattr__(speech, field_name, value)

                with self.assertRaises(RecordedMediaApplicationAdapterError):
                    adapter.resolve_recorded_frame(
                        frame=_frame(), speech_context=(speech,)
                    )

                self.assertEqual(application.calls, [])

    def test_speech_context_limit_fails_before_application_call(self):
        application = _Application(None)
        adapter = CanonicalRecordedFrameApplicationAdapter(application)
        speech = tuple(_speech() for _ in range(MAX_SPEECH_CONTEXT + 1))

        with self.assertRaises(RecordedMediaApplicationAdapterError):
            adapter.resolve_recorded_frame(frame=_frame(), speech_context=speech)

        self.assertEqual(application.calls, [])

    def test_tampered_resolution_fields_fail_closed(self):
        resolution = CanonicalRecordedPositionResolution(
            "game:42/node:17", True, 0.9
        )
        object.__setattr__(resolution, "confirmed", 1)
        application = _Application(resolution)
        adapter = CanonicalRecordedFrameApplicationAdapter(application)

        with self.assertRaises(RecordedMediaApplicationAdapterError):
            adapter.resolve_recorded_frame(frame=_frame(), speech_context=())

        self.assertEqual(len(application.calls), 1)

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
