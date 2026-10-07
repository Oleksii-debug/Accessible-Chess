import ast
import inspect
import math
import unittest

import acs.media_preprocess as module
from acs.media_preprocess import (
    AdaptiveSamplingPolicy, BoardFrameEvidence, BoardOrientation, BoardVisionPort,
    FrameDisposition, MAX_HINTS, MAX_SAMPLES, PreprocessCacheKey, PreprocessCheckpoint,
    PreprocessContractError, PreprocessErrorCode, PreprocessStatus,
    FrameSampleRequest, RecordedMediaPreprocessPlan, RecordedMediaPreprocessRun,
    RecordedMediaSourceRevision, SpeechContextPort, SpeechEvidence,
    deserialize_checkpoint, serialize_checkpoint,
)


class RecordedMediaPreprocessTests(unittest.TestCase):
    def source(self, revision="source-v1", duration=2500):
        return RecordedMediaSourceRevision("video-1", revision, "opaque-ref", duration)

    def plan(self, **kw):
        return RecordedMediaPreprocessPlan.build(self.source(kw.pop("revision", "source-v1"), kw.pop("duration", 2500)),
            board_revision=kw.pop("board_revision", "vision-v1"), speech_revision="speech-v1",
            policy=AdaptiveSamplingPolicy(1000, 200, 400, revision="policy-v1"), **kw)

    def board(self, t, revision="source-v1", disposition=FrameDisposition.STABLE):
        return BoardFrameEvidence("video-1", revision, t, disposition, BoardOrientation.WHITE_BOTTOM,
            .95, f"opaque:{t}" if disposition in (FrameDisposition.STABLE, FrameDisposition.AMBIGUOUS) else None,
            tuple([.9] * 64))

    def speech(self, revision="source-v1", start=0, end=500):
        return SpeechEvidence("video-1", revision, start, end, "Knight to f3 is discussed.", True, .8)

    def test_sampling_is_deterministic_includes_end_and_refines_transition(self):
        p = self.plan(transition_hints_ms=(1000,))
        self.assertEqual([r.timestamp_ms for r in p.requests], [0, 600, 800, 1000, 1200, 1400, 2000, 2500])
        self.assertTrue(next(r for r in p.requests if r.timestamp_ms == 1000).refined)
        self.assertEqual(p.digest(), self.plan(transition_hints_ms=(1000,)).digest())

    def test_sampling_rejects_out_of_bounds_and_unbounded_contract(self):
        with self.assertRaises(PreprocessContractError) as c: self.plan(transition_hints_ms=(2501,))
        self.assertEqual(c.exception.code, PreprocessErrorCode.INVALID)
        with self.assertRaises(PreprocessContractError) as c: AdaptiveSamplingPolicy(max_samples=MAX_SAMPLES + 1)
        self.assertEqual(c.exception.code, PreprocessErrorCode.LIMIT)
        with self.assertRaises(PreprocessContractError) as c: AdaptiveSamplingPolicy(1, 1, 0, max_samples=100).requests(500)
        self.assertEqual(c.exception.code, PreprocessErrorCode.LIMIT)

    def test_transition_hint_limit_does_not_exhaust_untrusted_iterable(self):
        def guarded_hints():
            for _ in range(MAX_HINTS + 1):
                yield 0
            raise AssertionError("hint iterable was consumed past the fail-closed limit")

        with self.assertRaises(PreprocessContractError) as c:
            AdaptiveSamplingPolicy().requests(1000, guarded_hints())
        self.assertEqual(c.exception.code, PreprocessErrorCode.LIMIT)

    def test_sampling_exact_limit_accepts_actual_baseline_count(self):
        requests = AdaptiveSamplingPolicy(1000, 200, 0, max_samples=2).requests(1000)
        self.assertEqual([r.timestamp_ms for r in requests], [0, 1000])

    def test_manual_plan_rejects_cache_mismatch_and_invalid_request_order(self):
        source = self.source(duration=1000)
        bad_key = PreprocessCacheKey("other", "source-v1", "vision-v1", None, "policy-v1")
        with self.assertRaises(PreprocessContractError) as c:
            RecordedMediaPreprocessPlan(source, bad_key, (FrameSampleRequest(0),))
        self.assertEqual(c.exception.code, PreprocessErrorCode.SOURCE_MISMATCH)
        good_key = PreprocessCacheKey("video-1", "source-v1", "vision-v1", None, "policy-v1")
        for requests in ((), (FrameSampleRequest(1000), FrameSampleRequest(0)), (FrameSampleRequest(1001),)):
            with self.subTest(requests=requests):
                with self.assertRaises(PreprocessContractError):
                    RecordedMediaPreprocessPlan(source, good_key, requests)

    def test_cache_identity_invalidates_on_source_or_recognizer_revision(self):
        a = self.plan().cache_key.fingerprint(); b = self.plan(revision="source-v2").cache_key.fingerprint()
        c = self.plan(board_revision="vision-v2").cache_key.fingerprint()
        self.assertNotEqual(a, b); self.assertNotEqual(a, c)

    def test_board_evidence_requires_opaque_ref_but_transition_may_have_none(self):
        with self.assertRaises(PreprocessContractError) as c:
            BoardFrameEvidence("video-1", "source-v1", 0, FrameDisposition.STABLE, confidence=.5)
        self.assertEqual(c.exception.code, PreprocessErrorCode.INVALID_STATE)
        self.assertIsNone(self.board(0, disposition=FrameDisposition.TRANSITION).observation_ref)

    def test_square_confidence_is_exactly_64_and_finite(self):
        with self.assertRaises(PreprocessContractError):
            BoardFrameEvidence("video-1", "source-v1", 0, FrameDisposition.STABLE,
                               observation_ref="x", square_confidence=tuple([.5] * 63))
        bad = [.5] * 64; bad[4] = math.inf
        with self.assertRaises(PreprocessContractError):
            BoardFrameEvidence("video-1", "source-v1", 0, FrameDisposition.STABLE,
                               observation_ref="x", square_confidence=tuple(bad))

    def test_speech_is_typed_bounded_and_partial_supported(self):
        partial = SpeechEvidence("video-1", "source-v1", 10, 30, "partial", False, .4)
        self.assertFalse(partial.is_final)
        with self.assertRaises(PreprocessContractError):
            SpeechEvidence("video-1", "source-v1", 30, 10, "bad", True)

    def test_run_advances_only_on_exact_requested_evidence(self):
        run = RecordedMediaPreprocessRun(self.plan(duration=2000))
        self.assertEqual(run.current_request.timestamp_ms, 0)
        with self.assertRaises(PreprocessContractError) as c: run.accept_board(self.board(1000))
        self.assertEqual(c.exception.code, PreprocessErrorCode.REQUEST_MISMATCH)
        self.assertEqual(run.current_request.timestamp_ms, 0)
        run.accept_board(self.board(0)); self.assertEqual(run.current_request.timestamp_ms, 1000)

    def test_run_rejects_stale_revision(self):
        run = RecordedMediaPreprocessRun(self.plan())
        with self.assertRaises(PreprocessContractError) as c: run.accept_board(self.board(0, "stale"))
        self.assertEqual(c.exception.code, PreprocessErrorCode.REVISION_MISMATCH)

    def test_provider_failure_can_retry_without_progress_corruption(self):
        run = RecordedMediaPreprocessRun(self.plan(duration=1000)); before = run.current_request
        self.assertEqual(run.current_request, before)  # adapter failed before accept()
        run.accept_board(self.board(before.timestamp_ms)); self.assertNotEqual(run.current_request, before)

    def test_speech_does_not_advance_board_cursor_and_checks_bounds(self):
        run = RecordedMediaPreprocessRun(self.plan(duration=1000)); before = run.current_request
        run.accept_speech(self.speech()); self.assertEqual(run.current_request, before)
        with self.assertRaises(PreprocessContractError): run.accept_speech(self.speech(start=900, end=1001))
        with self.assertRaises(PreprocessContractError) as c: run.accept_speech(self.speech(revision="stale"))
        self.assertEqual(c.exception.code, PreprocessErrorCode.REVISION_MISMATCH)

    def test_cancel_checkpoint_resumes_exact_same_request(self):
        plan = self.plan(duration=2000); run = RecordedMediaPreprocessRun(plan)
        run.accept_board(self.board(0)); checkpoint = run.cancel()
        self.assertIs(checkpoint.status, PreprocessStatus.CANCELED)
        self.assertIsNone(run.current_request)
        with self.assertRaises(PreprocessContractError): run.accept_speech(self.speech())
        resumed = RecordedMediaPreprocessRun(plan, checkpoint)
        self.assertEqual(resumed.current_request.timestamp_ms, 1000)

    def test_checkpoint_refuses_changed_source_recognizer_or_policy(self):
        plan = self.plan(duration=2000); checkpoint = RecordedMediaPreprocessRun(plan).cancel()
        for changed in (self.plan(duration=2000, revision="source-v2"),
                        self.plan(duration=2000, board_revision="vision-v2"),
                        RecordedMediaPreprocessPlan.build(self.source(duration=2000), board_revision="vision-v1",
                            speech_revision="speech-v1", policy=AdaptiveSamplingPolicy(500, 200, 400, revision="policy-v2"))):
            with self.subTest(changed=changed.digest()):
                with self.assertRaises(PreprocessContractError) as c: RecordedMediaPreprocessRun(changed, checkpoint)
                self.assertEqual(c.exception.code, PreprocessErrorCode.CHECKPOINT_MISMATCH)

    def test_checkpoint_rejects_skipped_board_progress_finished_running_and_wrong_type(self):
        plan = self.plan(duration=1000)
        base = RecordedMediaPreprocessRun(plan).checkpoint()
        with self.assertRaises(PreprocessContractError):
            PreprocessCheckpoint(base.source_id, base.source_revision, base.cache_fingerprint, base.plan_digest,
                                 1, base.total, 0, 0, PreprocessStatus.RUNNING)
        with self.assertRaises(PreprocessContractError):
            PreprocessCheckpoint(base.source_id, base.source_revision, base.cache_fingerprint, base.plan_digest,
                                 base.total, base.total, base.total, 0, PreprocessStatus.RUNNING)
        with self.assertRaises(PreprocessContractError) as c:
            RecordedMediaPreprocessRun(plan, object())
        self.assertEqual(c.exception.code, PreprocessErrorCode.INVALID)

    def test_checkpoint_roundtrip_unicode_and_reject_duplicate_unknown_fields(self):
        plan = RecordedMediaPreprocessPlan.build(RecordedMediaSourceRevision("урок-1", "версія-1", "opaque", 1000),
                                                  board_revision="vision-v1")
        text = serialize_checkpoint(RecordedMediaPreprocessRun(plan).cancel())
        self.assertIn("урок-1", text); self.assertEqual(deserialize_checkpoint(text).source_id, "урок-1")
        with self.assertRaises(PreprocessContractError) as c:
            deserialize_checkpoint(text[:-1] + ',"status":"running"}')
        self.assertEqual(c.exception.code, PreprocessErrorCode.INVALID_SCHEMA)
        with self.assertRaises(PreprocessContractError): deserialize_checkpoint(text[:-1] + ',"extra":1}')

    def test_run_completes_only_after_every_frame_request(self):
        plan = self.plan(duration=2000); run = RecordedMediaPreprocessRun(plan)
        for request in plan.requests: run.accept_board(self.board(request.timestamp_ms))
        self.assertIs(run.status, PreprocessStatus.COMPLETE); self.assertIsNone(run.current_request)
        with self.assertRaises(PreprocessContractError): run.accept_board(self.board(2000))

    def test_ports_are_replaceable_structural_contracts(self):
        class Vision:
            revision_id = "vision-v1"
            def observe(self, source_ref, timestamp_ms): return self_board(timestamp_ms)
        class Speech:
            revision_id = "speech-v1"
            def evidence_for_range(self, source_ref, start_ms, end_ms): return (self_speech(start=start_ms, end=end_ms),)
        self_board, self_speech = self.board, self.speech
        vision: BoardVisionPort = Vision(); speech: SpeechContextPort = Speech()
        self.assertEqual(vision.observe("opaque", 0).timestamp_ms, 0)
        self.assertTrue(tuple(speech.evidence_for_range("opaque", 0, 500))[0].is_final)

    def test_module_has_no_chess_rules_or_provider_network_dependency(self):
        tree = ast.parse(inspect.getsource(module)); roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): roots.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: roots.add(node.module.split('.')[0])
        self.assertTrue(roots.isdisjoint({"chess", "chesscore", "gametree", "pgn", "requests", "urllib", "http", "socket", "subprocess"}))


if __name__ == "__main__": unittest.main()
