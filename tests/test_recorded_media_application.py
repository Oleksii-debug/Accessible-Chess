from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from acs.media_core import (
    MAX_MEDIA_RECONCILIATION_REFS,
    MediaEvidence,
    MediaEvidenceKind,
    MediaReconciliationResult,
    MediaReconciliationState,
)
from acs.media_preprocess import (
    BoardFrameEvidence,
    BoardOrientation,
    FrameDisposition,
    SpeechEvidence,
)
from acs.recorded_media_application import (
    CanonicalRecordedFrameApplicationAdapter,
    RecordedMediaApplicationAdapterError,
)


class _Application:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def reconcile_media_evidence_batch(self, *, current_chess_ref, evidence):
        self.calls.append((current_chess_ref, evidence))
        if isinstance(self.result, BaseException):
            raise self.result
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


def _speech(
    source_id="media-1",
    source_revision="rev-1",
    *,
    text="Хід кінь f3",
    language="uk",
):
    return SpeechEvidence(
        source_id,
        source_revision,
        1000,
        1200,
        text,
        True,
        0.8,
        language=language,
    )


def _result(
    evidence,
    *,
    state=MediaReconciliationState.VERIFIED,
    chess_ref="game:42/node:17",
    candidate_refs=(),
    confidence=.88,
):
    return MediaReconciliationResult(
        source_id="media-1",
        state=state,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        chess_ref=chess_ref,
        candidate_refs=candidate_refs,
        confidence=confidence,
        reason="canonical application fixture",
    )


class DynamicApplication:
    def __init__(
        self,
        *,
        state=MediaReconciliationState.VERIFIED,
        chess_ref="game:42/node:17",
        candidate_refs=(),
        confidence=.88,
    ):
        self.state=state
        self.chess_ref=chess_ref
        self.candidate_refs=candidate_refs
        self.confidence=confidence
        self.calls=[]

    def reconcile_media_evidence_batch(self, *, current_chess_ref, evidence):
        self.calls.append((current_chess_ref,evidence))
        return _result(
            evidence,
            state=self.state,
            chess_ref=self.chess_ref,
            candidate_refs=self.candidate_refs,
            confidence=self.confidence,
        )


class RecordedMediaApplicationAdapterTests(unittest.TestCase):
    def test_board_and_speech_become_typed_media_evidence_before_application(self):
        application = DynamicApplication()
        adapter = CanonicalRecordedFrameApplicationAdapter(application)
        frame = _frame()
        speech = (_speech(),)

        result = adapter.resolve_recorded_frame(frame=frame, speech_context=speech)

        self.assertEqual(result.state, MediaReconciliationState.VERIFIED)
        self.assertEqual(len(application.calls), 1)
        current_ref, evidence = application.calls[0]
        self.assertIsNone(current_ref)
        self.assertEqual(len(evidence), 2)
        self.assertTrue(all(type(item) is MediaEvidence for item in evidence))
        self.assertEqual(evidence[0].kind, MediaEvidenceKind.BOARD_OBSERVATION)
        self.assertEqual(evidence[1].kind, MediaEvidenceKind.SPEECH_CONTEXT)
        self.assertEqual(evidence[0].source_revision, "rev-1")
        self.assertEqual(evidence[1].source_revision, "rev-1")
        speech_fields = {field.name: field.value for field in evidence[1].fields}
        self.assertEqual(speech_fields["language"], "uk")
        self.assertEqual(speech_fields["text"], "Хід кінь f3")
        self.assertFalse(evidence[0].source_authoritative)
        self.assertFalse(evidence[1].source_authoritative)
        self.assertEqual(evidence[0].raw_candidate_ref, "vision-observation:17")
        self.assertEqual(
            set(result.evidence_ids),
            {item.evidence_id for item in evidence},
        )

    def test_typed_evidence_ids_are_deterministic_for_same_inputs(self):
        app1=DynamicApplication()
        app2=DynamicApplication()
        CanonicalRecordedFrameApplicationAdapter(app1).resolve_recorded_frame(
            frame=_frame(), speech_context=(_speech(),)
        )
        CanonicalRecordedFrameApplicationAdapter(app2).resolve_recorded_frame(
            frame=_frame(), speech_context=(_speech(),)
        )
        ids1=tuple(item.evidence_id for item in app1.calls[0][1])
        ids2=tuple(item.evidence_id for item in app2.calls[0][1])
        self.assertEqual(ids1,ids2)

        app3 = DynamicApplication()
        CanonicalRecordedFrameApplicationAdapter(app3).resolve_recorded_frame(
            frame=_frame(), speech_context=(_speech(language="en"),)
        )
        ids3 = tuple(item.evidence_id for item in app3.calls[0][1])
        self.assertNotEqual(ids1[1], ids3[1])

    def test_canonical_states_remain_standard_media_reconciliation_results(self):
        for state,chess_ref,candidates in (
            (MediaReconciliationState.VERIFIED,"game:42/node:17",()),
            (MediaReconciliationState.INFERRED,"game:42/node:18",()),
            (MediaReconciliationState.OBSERVED,None,("game:42/candidate",)),
            (MediaReconciliationState.AMBIGUOUS,None,("game:a","game:b")),
            (MediaReconciliationState.RESYNC_REQUIRED,None,()),
            (MediaReconciliationState.NO_CHANGE,None,()),
        ):
            with self.subTest(state=state):
                app=DynamicApplication(
                    state=state,chess_ref=chess_ref,candidate_refs=candidates
                )
                result=CanonicalRecordedFrameApplicationAdapter(app).resolve_recorded_frame(
                    frame=_frame(),speech_context=()
                )
                self.assertEqual(result.state,state)

    def test_ambiguous_visual_evidence_cannot_publish_verified_or_inferred_truth(self):
        for state in (
            MediaReconciliationState.VERIFIED,
            MediaReconciliationState.INFERRED,
        ):
            with self.subTest(state=state):
                adapter=CanonicalRecordedFrameApplicationAdapter(
                    DynamicApplication(state=state)
                )
                with self.assertRaises(RecordedMediaApplicationAdapterError):
                    adapter.resolve_recorded_frame(
                        frame=_frame(FrameDisposition.AMBIGUOUS),
                        speech_context=(),
                    )

    def test_non_resolvable_frames_fail_before_application_call(self):
        application=DynamicApplication()
        adapter=CanonicalRecordedFrameApplicationAdapter(application)
        for disposition in (FrameDisposition.TRANSITION,FrameDisposition.OCCLUDED):
            with self.subTest(disposition=disposition):
                with self.assertRaises(RecordedMediaApplicationAdapterError):
                    adapter.resolve_recorded_frame(
                        frame=_frame(disposition),speech_context=()
                    )
        self.assertEqual(application.calls,[])

    def test_cross_source_or_stale_speech_fails_before_application_call(self):
        application=DynamicApplication()
        adapter=CanonicalRecordedFrameApplicationAdapter(application)
        for context in (
            (_speech(source_id="media-2"),),
            (_speech(source_revision="rev-0"),),
        ):
            with self.subTest(context=context):
                with self.assertRaises(RecordedMediaApplicationAdapterError):
                    adapter.resolve_recorded_frame(frame=_frame(),speech_context=context)
        self.assertEqual(application.calls,[])

    def test_bundle_limit_fails_before_application_call(self):
        application=DynamicApplication()
        adapter=CanonicalRecordedFrameApplicationAdapter(application)
        speech=tuple(
            _speech(text=f"commentary {index}")
            for index in range(MAX_MEDIA_RECONCILIATION_REFS)
        )
        with self.assertRaises(RecordedMediaApplicationAdapterError):
            adapter.resolve_recorded_frame(frame=_frame(),speech_context=speech)
        self.assertEqual(application.calls,[])

    def test_wrong_or_partial_application_result_fails_closed(self):
        class WrongApplication:
            def reconcile_media_evidence_batch(self, *, current_chess_ref, evidence):
                return "not-a-result"
        with self.assertRaises(RecordedMediaApplicationAdapterError):
            CanonicalRecordedFrameApplicationAdapter(
                WrongApplication()
            ).resolve_recorded_frame(frame=_frame(),speech_context=())

        class PartialApplication:
            def reconcile_media_evidence_batch(self, *, current_chess_ref, evidence):
                return MediaReconciliationResult(
                    source_id="media-1",
                    state=MediaReconciliationState.NO_CHANGE,
                    evidence_ids=(evidence[0].evidence_id,),
                    reason="partial binding",
                )
        with self.assertRaises(RecordedMediaApplicationAdapterError):
            CanonicalRecordedFrameApplicationAdapter(
                PartialApplication()
            ).resolve_recorded_frame(
                frame=_frame(),speech_context=(_speech(),)
            )

    def test_canonical_exception_is_sanitized(self):
        adapter=CanonicalRecordedFrameApplicationAdapter(
            _Application(RuntimeError(r"private C:\Users\secret\media.db"))
        )
        with self.assertRaises(RecordedMediaApplicationAdapterError) as caught:
            adapter.resolve_recorded_frame(frame=_frame(),speech_context=())
        self.assertNotIn("secret",str(caught.exception))
        self.assertNotIn("media.db",str(caught.exception))

    def test_tampered_frame_or_speech_fails_before_application_call(self):
        application=DynamicApplication()
        adapter=CanonicalRecordedFrameApplicationAdapter(application)
        frame=_frame()
        object.__setattr__(frame,"confidence",object())
        with self.assertRaises(RecordedMediaApplicationAdapterError):
            adapter.resolve_recorded_frame(frame=frame,speech_context=())
        self.assertEqual(application.calls,[])

        speech=_speech()
        object.__setattr__(speech,"text",object())
        with self.assertRaises(RecordedMediaApplicationAdapterError):
            adapter.resolve_recorded_frame(frame=_frame(),speech_context=(speech,))
        self.assertEqual(application.calls,[])

    def test_application_receives_no_board_or_speech_dto_objects(self):
        class InspectingApplication(DynamicApplication):
            def reconcile_media_evidence_batch(self, *, current_chess_ref, evidence):
                self.assertion=all(type(item) is MediaEvidence for item in evidence)
                return super().reconcile_media_evidence_batch(
                    current_chess_ref=current_chess_ref,evidence=evidence
                )
        app=InspectingApplication()
        frame=_frame()
        speech=(_speech(),)
        CanonicalRecordedFrameApplicationAdapter(app).resolve_recorded_frame(
            frame=frame,speech_context=speech
        )
        self.assertTrue(app.assertion)
        self.assertEqual(frame.source_id,"media-1")
        self.assertEqual(speech[0].text,"Хід кінь f3")

    def test_adapter_contains_no_chess_parser_or_rules_authority(self):
        source=Path(
            inspect.getsourcefile(CanonicalRecordedFrameApplicationAdapter)
        ).read_text(encoding="utf-8").lower()
        for token in (
            "chesscore","set_fen","parse_san","parse_uci",
            "pseudo_moves","legal_moves",
        ):
            self.assertNotIn(token,source)


if __name__ == "__main__":
    unittest.main()
