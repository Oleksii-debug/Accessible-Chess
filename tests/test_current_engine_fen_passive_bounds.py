from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisResult, AnalysisService
from acs.book_board_workflow import BookBoardWorkflow, BookBoardWorkflowCode, BookBoardWorkflowError
from acs.engine_assisted_workflows import (
    AudienceAnalysisResult,
    EngineAssistedWorkflowService,
    EngineVisibility,
)
from acs.engine_ports import EngineContractError, EngineContractErrorCode
from acs.input_limits import MAX_FEN_CHARS
from acs.training import ExerciseSession


class CurrentEngineFenPassiveBoundsTests(unittest.TestCase):
    class HostileText(str):
        touched = False

        def __len__(self):
            type(self).touched = True
            raise AssertionError("rejected FEN length hook must not execute")

        def strip(self, *args, **kwargs):
            type(self).touched = True
            raise AssertionError("rejected FEN strip hook must not execute")

    @staticmethod
    def _analysis(factory_calls: list[int]) -> AnalysisService:
        def factory():
            factory_calls.append(1)
            raise AssertionError("rejected FEN must not construct an engine provider")

        return AnalysisService(factory)

    def test_analysis_service_rejects_active_text_before_hooks_or_provider(self) -> None:
        factory_calls: list[int] = []
        analysis = self._analysis(factory_calls)
        self.addCleanup(analysis.close)
        hostile = self.HostileText("8/8/8/8/8/8/4K3/7k w - - 0 1")
        self.HostileText.touched = False

        with self.assertRaises(EngineContractError) as caught:
            analysis.analyze(hostile)  # type: ignore[arg-type]

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertFalse(self.HostileText.touched)
        self.assertEqual(factory_calls, [])

    def test_analysis_service_rejects_oversized_fen_before_provider_or_generation(self) -> None:
        factory_calls: list[int] = []
        analysis = self._analysis(factory_calls)
        self.addCleanup(analysis.close)
        before_generation = analysis._generation

        with self.assertRaises(EngineContractError) as caught:
            analysis.analyze("x" * (MAX_FEN_CHARS + 1))

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertEqual(analysis._generation, before_generation)
        self.assertEqual(factory_calls, [])

    def test_analysis_result_rejects_active_and_oversized_fen_before_normalization(self) -> None:
        hostile = self.HostileText("position")
        self.HostileText.touched = False

        with self.assertRaises(EngineContractError) as active:
            AnalysisResult(hostile, 0, True, ())  # type: ignore[arg-type]
        self.assertEqual(active.exception.code, EngineContractErrorCode.INVALID_RESULT)
        self.assertFalse(self.HostileText.touched)

        with self.assertRaises(EngineContractError) as oversized:
            AnalysisResult("x" * (MAX_FEN_CHARS + 1), 0, True, ())
        self.assertEqual(oversized.exception.code, EngineContractErrorCode.INVALID_RESULT)

    def test_audience_result_rejects_active_and_oversized_fen_before_normalization(self) -> None:
        hostile = self.HostileText("position")
        self.HostileText.touched = False

        with self.assertRaises(EngineContractError) as active:
            AudienceAnalysisResult(
                hostile,  # type: ignore[arg-type]
                0,
                EngineVisibility.HIDDEN,
                True,
            )
        self.assertEqual(active.exception.code, EngineContractErrorCode.INVALID_RESULT)
        self.assertFalse(self.HostileText.touched)

        with self.assertRaises(EngineContractError) as oversized:
            AudienceAnalysisResult(
                "x" * (MAX_FEN_CHARS + 1),
                0,
                EngineVisibility.HIDDEN,
                True,
            )
        self.assertEqual(oversized.exception.code, EngineContractErrorCode.INVALID_RESULT)

    def test_assisted_training_rejects_oversized_fen_before_session_snapshot(self) -> None:
        factory_calls: list[int] = []
        analysis = self._analysis(factory_calls)
        self.addCleanup(analysis.close)
        assisted = EngineAssistedWorkflowService(analysis)

        class HostileSession(ExerciseSession):
            touched = False

            def snapshot(self):
                type(self).touched = True
                raise AssertionError("session snapshot must not execute for rejected FEN")

        hostile_session = HostileSession.__new__(HostileSession)
        HostileSession.touched = False

        with self.assertRaises(EngineContractError) as caught:
            assisted.analyze_training(
                hostile_session,
                "x" * (MAX_FEN_CHARS + 1),
            )

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertFalse(HostileSession.touched)
        self.assertEqual(factory_calls, [])

    def test_teacher_rejects_oversized_fen_before_revision_provider(self) -> None:
        factory_calls: list[int] = []
        revision_calls: list[int] = []
        analysis = self._analysis(factory_calls)
        self.addCleanup(analysis.close)
        assisted = EngineAssistedWorkflowService(analysis)

        def revision_provider():
            revision_calls.append(1)
            raise AssertionError("revision provider must not run for rejected FEN")

        with self.assertRaises(EngineContractError) as caught:
            assisted.analyze_teacher(
                "x" * (MAX_FEN_CHARS + 1),
                visibility=EngineVisibility.HIDDEN,
                context_revision=0,
                revision_provider=revision_provider,
            )

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertEqual(revision_calls, [])
        self.assertEqual(factory_calls, [])

    def test_bookboard_preflight_rejects_active_and_oversized_fen_before_board(self) -> None:
        hostile = self.HostileText("8/8/8/8/8/8/4K3/7k w - - 0 1")
        self.HostileText.touched = False

        with self.assertRaises(BookBoardWorkflowError) as active:
            BookBoardWorkflow._canonical_fen(hostile)
        self.assertEqual(active.exception.code, BookBoardWorkflowCode.INVALID_POSITION)
        self.assertFalse(self.HostileText.touched)

        with self.assertRaises(BookBoardWorkflowError) as oversized:
            BookBoardWorkflow._canonical_fen("x" * (MAX_FEN_CHARS + 1))
        self.assertEqual(oversized.exception.code, BookBoardWorkflowCode.INVALID_POSITION)

    def test_exact_raw_boundary_remains_available_to_non_chess_engine_boundary(self) -> None:
        boundary = "x" * MAX_FEN_CHARS

        self.assertEqual(AnalysisService._normalize_fen(boundary), boundary)
        result = AudienceAnalysisResult(
            boundary,
            0,
            EngineVisibility.HIDDEN,
            True,
        )
        self.assertEqual(result.fen, boundary)


if __name__ == "__main__":
    unittest.main()
