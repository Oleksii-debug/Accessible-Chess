import ast
import inspect
import unittest

import acs.media_preprocess_executor as executor_module
from acs.media_preprocess import (
    AdaptiveSamplingPolicy,
    BoardFrameEvidence,
    FrameDisposition,
    PreprocessContractError,
    PreprocessErrorCode,
    PreprocessStatus,
    RecordedMediaPreprocessPlan,
    RecordedMediaSourceRevision,
    SpeechEvidence,
)
from acs.media_preprocess_executor import (
    FixtureBoardVisionPort,
    FixtureSpeechContextPort,
    RecordedMediaPreprocessExecutor,
)


class ExecutorTests(unittest.TestCase):
    def plan(self, speech=True):
        source = RecordedMediaSourceRevision("v1", "source-v1", "opaque-local-ref", 2000)
        return RecordedMediaPreprocessPlan.build(
            source,
            board_revision="vision-v1",
            speech_revision="speech-v1" if speech else None,
            policy=AdaptiveSamplingPolicy(1000, 200, 0),
        )

    def board(self, t):
        return BoardFrameEvidence("v1", "source-v1", t, FrameDisposition.STABLE,
                                  confidence=.9, observation_ref=f"fixture:{t}")

    def test_fixture_executor_processes_exact_plan_to_completion(self):
        plan = self.plan(speech=False)
        port = FixtureBoardVisionPort("vision-v1", [self.board(r.timestamp_ms) for r in plan.requests])
        executor = RecordedMediaPreprocessExecutor(plan, port)
        seen = []
        while executor.status is PreprocessStatus.RUNNING:
            result = executor.step_board(); seen.append(result.board_evidence.timestamp_ms)
        self.assertEqual(seen, [0, 1000, 2000])
        self.assertIs(executor.status, PreprocessStatus.COMPLETE)
        self.assertIsNone(executor.step_board())

    def test_provider_failure_does_not_advance_progress_and_can_retry(self):
        plan = self.plan(speech=False)
        port = FixtureBoardVisionPort("vision-v1", [self.board(1000), self.board(2000)])
        executor = RecordedMediaPreprocessExecutor(plan, port)
        before = executor.run.checkpoint()
        with self.assertRaises(PreprocessContractError): executor.step_board()
        self.assertEqual(executor.run.checkpoint(), before)

    def test_revision_mismatch_fails_before_provider_use(self):
        plan = self.plan(speech=False)
        with self.assertRaises(PreprocessContractError) as c:
            RecordedMediaPreprocessExecutor(plan, FixtureBoardVisionPort("vision-v2", []))
        self.assertEqual(c.exception.code, PreprocessErrorCode.REVISION_MISMATCH)

    def test_speech_context_is_bounded_context_and_does_not_move_board_cursor(self):
        plan = self.plan()
        boards = FixtureBoardVisionPort("vision-v1", [self.board(r.timestamp_ms) for r in plan.requests])
        speech = FixtureSpeechContextPort("speech-v1", [
            SpeechEvidence("v1", "source-v1", 100, 400, "candidate words", False, .4),
            SpeechEvidence("v1", "source-v1", 100, 500, "Knight f3", True, .9),
        ])
        executor = RecordedMediaPreprocessExecutor(plan, boards, speech_port=speech)
        before = executor.run.current_request
        accepted = executor.collect_speech(0, 600)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(executor.run.current_request, before)

    def test_invalid_speech_batch_does_not_publish_partial_checkpoint_progress(self):
        plan = self.plan()
        boards = FixtureBoardVisionPort("vision-v1", [self.board(r.timestamp_ms) for r in plan.requests])

        class MixedSpeech:
            revision_id = "speech-v1"
            def evidence_for_range(self, source_ref, start_ms, end_ms):
                return (
                    SpeechEvidence("v1", "source-v1", 100, 200, "valid first", True, .9),
                    SpeechEvidence("v1", "stale", 200, 300, "invalid second", True, .9),
                )

        executor = RecordedMediaPreprocessExecutor(plan, boards, speech_port=MixedSpeech())
        before = executor.run.checkpoint()
        with self.assertRaises(PreprocessContractError) as caught:
            executor.collect_speech(0, 600)
        self.assertEqual(caught.exception.code, PreprocessErrorCode.REVISION_MISMATCH)
        self.assertEqual(executor.run.checkpoint(), before)

    def test_interrupted_speech_provider_stream_does_not_publish_partial_progress(self):
        plan = self.plan()
        boards = FixtureBoardVisionPort("vision-v1", [self.board(r.timestamp_ms) for r in plan.requests])

        class InterruptedSpeech:
            revision_id = "speech-v1"
            def evidence_for_range(self, source_ref, start_ms, end_ms):
                def stream():
                    yield SpeechEvidence("v1", "source-v1", 100, 200, "valid first", True, .9)
                    raise RuntimeError("provider stream interrupted")
                return stream()

        executor = RecordedMediaPreprocessExecutor(plan, boards, speech_port=InterruptedSpeech())
        before = executor.run.checkpoint()
        with self.assertRaisesRegex(RuntimeError, "provider stream interrupted"):
            executor.collect_speech(0, 600)
        self.assertEqual(executor.run.checkpoint(), before)

    def test_cancelled_run_rejects_speech_before_provider_invocation(self):
        plan = self.plan()
        boards = FixtureBoardVisionPort("vision-v1", [self.board(r.timestamp_ms) for r in plan.requests])

        class ExplodingSpeech:
            revision_id = "speech-v1"
            called = False
            def evidence_for_range(self, source_ref, start_ms, end_ms):
                self.called = True
                raise AssertionError("provider must not be called after cancellation")

        speech = ExplodingSpeech()
        executor = RecordedMediaPreprocessExecutor(plan, boards, speech_port=speech)
        executor.cancel()
        with self.assertRaises(PreprocessContractError) as caught:
            executor.collect_speech(0, 600)
        self.assertEqual(caught.exception.code, PreprocessErrorCode.INVALID_STATE)
        self.assertFalse(speech.called)

    def test_invalid_speech_range_fails_before_provider_use(self):
        plan = self.plan()
        boards = FixtureBoardVisionPort("vision-v1", [self.board(r.timestamp_ms) for r in plan.requests])

        class ExplodingSpeech:
            revision_id = "speech-v1"
            called = False
            def evidence_for_range(self, source_ref, start_ms, end_ms):
                self.called = True
                raise AssertionError("provider must not be called for invalid range")

        speech = ExplodingSpeech()
        executor = RecordedMediaPreprocessExecutor(plan, boards, speech_port=speech)
        for start, end in ((-1, 10), (20, 10), (0, 2001), (True, 10)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(PreprocessContractError) as c:
                    executor.collect_speech(start, end)
                self.assertEqual(c.exception.code, PreprocessErrorCode.INVALID)
        self.assertFalse(speech.called)

    def test_executor_has_no_chess_rules_or_provider_network_dependency(self):
        tree = ast.parse(inspect.getsource(executor_module)); roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): roots.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: roots.add(node.module.split('.')[0])
        self.assertTrue(roots.isdisjoint({"chess", "chesscore", "gametree", "pgn", "requests", "urllib", "http", "socket", "subprocess"}))

    def test_cancel_and_resume_executor_from_checkpoint(self):
        plan = self.plan(speech=False)
        boards = FixtureBoardVisionPort("vision-v1", [self.board(r.timestamp_ms) for r in plan.requests])
        first = RecordedMediaPreprocessExecutor(plan, boards)
        self.assertEqual(first.step_board().board_evidence.timestamp_ms, 0)
        checkpoint = first.cancel()
        resumed = RecordedMediaPreprocessExecutor(plan, boards, checkpoint=checkpoint)
        self.assertEqual(resumed.step_board().board_evidence.timestamp_ms, 1000)

    def test_speech_port_requirement_matches_plan_revision_contract(self):
        with self.assertRaises(PreprocessContractError) as c:
            RecordedMediaPreprocessExecutor(self.plan(), FixtureBoardVisionPort("vision-v1", []))
        self.assertEqual(c.exception.code, PreprocessErrorCode.INVALID_STATE)


if __name__ == "__main__":
    unittest.main()
