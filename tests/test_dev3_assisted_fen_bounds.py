from __future__ import annotations

import unittest

from acs.analysis_service import ANALYSIS_MAX_FEN_LENGTH, AnalysisService
from acs.bookdocument import Position
from acs.engine_assisted_workflows import (
    AudienceAnalysisResult,
    EngineAssistedWorkflowService,
    EngineVisibility,
)
from acs.engine_ports import EngineContractError, RawAnalysisLine
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep


FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


class _Engine:
    def __init__(self):
        self.calls: list[tuple[str, int, int]] = []

    def analyze(self, fen, multipv=5, depth=16):
        self.calls.append((fen, multipv, depth))
        return [RawAnalysisLine(depth=depth, score_kind="cp", score_value=1, pv=("e2e4",))]

    def close(self):
        return None


def _session() -> ExerciseSession:
    return ExerciseSession(
        ExerciseDefinition(
            exercise_id="bounded-fen",
            start_fen=FEN,
            steps=(ExerciseStep(frozenset({"e4"})),),
        )
    )


class AssistedFenBoundsTests(unittest.TestCase):
    def _service(self):
        engine = _Engine()
        analysis = AnalysisService(lambda: engine)
        return EngineAssistedWorkflowService(analysis), analysis, engine

    def test_oversized_teacher_fen_fails_before_revision_or_engine_work(self):
        oversized = "x" * (ANALYSIS_MAX_FEN_LENGTH + 1)
        revision_calls: list[int] = []
        service, analysis, engine = self._service()

        def revision_provider():
            revision_calls.append(1)
            return 2

        try:
            with self.assertRaises(EngineContractError):
                service.analyze_teacher(
                    oversized,
                    visibility=EngineVisibility.HIDDEN,
                    context_revision=1,
                    revision_provider=revision_provider,
                )
        finally:
            analysis.close()

        self.assertEqual(revision_calls, [])
        self.assertEqual(engine.calls, [])

    def test_training_and_book_paths_reject_oversized_fen_before_engine_work(self):
        oversized = "x" * (ANALYSIS_MAX_FEN_LENGTH + 1)
        # BookDocument only requires four FEN fields at this semantic layer. This
        # deliberately remains structurally acceptable there while exceeding the
        # engine-assistance resource boundary.
        oversized_book_fen = "8/8/8/8/8/8/4K3/7k w - " + ("x" * ANALYSIS_MAX_FEN_LENGTH)
        self.assertGreater(len(oversized_book_fen), ANALYSIS_MAX_FEN_LENGTH)
        block = Position(fen=oversized_book_fen)
        session = _session()
        before = session.snapshot()
        service, analysis, engine = self._service()
        try:
            with self.assertRaises(EngineContractError):
                service.analyze_training(session, oversized)
            with self.assertRaises(EngineContractError):
                service.analyze_book_block(block)
        finally:
            analysis.close()

        self.assertEqual(session.snapshot(), before)
        self.assertEqual(engine.calls, [])

    def test_audience_result_rejects_oversized_fen(self):
        oversized = "x" * (ANALYSIS_MAX_FEN_LENGTH + 1)
        with self.assertRaises(EngineContractError):
            AudienceAnalysisResult(
                oversized,
                0,
                EngineVisibility.HIDDEN,
                True,
            )

    def test_exact_boundary_remains_valid_for_stale_teacher_precheck(self):
        boundary = "x" * ANALYSIS_MAX_FEN_LENGTH
        service, analysis, engine = self._service()
        try:
            result = service.analyze_teacher(
                boundary,
                visibility=EngineVisibility.HIDDEN,
                context_revision=1,
                revision_provider=lambda: 2,
            )
        finally:
            analysis.close()

        self.assertTrue(result.stale)
        self.assertEqual(result.fen, boundary)
        self.assertEqual(engine.calls, [])


if __name__ == "__main__":
    unittest.main()
