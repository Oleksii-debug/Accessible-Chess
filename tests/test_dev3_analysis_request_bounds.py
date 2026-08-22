import unittest

from acs.analysis_service import (
    ANALYSIS_MAX_FEN_LENGTH,
    AnalysisResult,
    AnalysisService,
)
from acs.engine_ports import EngineContractError, EngineContractErrorCode


class _RecordingEngine:
    def __init__(self, calls):
        self._calls = calls

    def analyze(self, fen, multipv=5, depth=16):
        self._calls.append((fen, multipv, depth))
        return []

    def close(self):
        pass


class AnalysisRequestBoundsTests(unittest.TestCase):
    def test_exact_fen_boundary_is_accepted_and_normalized_before_provider(self):
        calls = []
        factory_calls = []

        def factory():
            factory_calls.append(1)
            return _RecordingEngine(calls)

        service = AnalysisService(factory)
        fen = "x" * ANALYSIS_MAX_FEN_LENGTH
        result = service.analyze(f"  {fen}  ", multipv=1, depth=1)

        self.assertEqual(factory_calls, [1])
        self.assertEqual(calls, [(fen, 1, 1)])
        self.assertEqual(result.fen, fen)
        self.assertFalse(result.stale)
        self.assertIsNone(result.error)
        self.assertEqual(result.lines, ())

    def test_oversized_fen_is_rejected_before_engine_factory_or_generation_change(self):
        factory_calls = []
        service = AnalysisService(
            lambda: factory_calls.append(1) or _RecordingEngine([])
        )
        oversized = "x" * (ANALYSIS_MAX_FEN_LENGTH + 1)

        with self.assertRaises(EngineContractError) as analyze_error:
            service.analyze(oversized, multipv=1, depth=1)
        self.assertEqual(
            analyze_error.exception.code,
            EngineContractErrorCode.INVALID_REQUEST,
        )
        self.assertEqual(factory_calls, [])

        # Invalidating to an oversized position must fail before publishing a
        # new generation/current-FEN identity.
        self.assertEqual(service.invalidate("fen-valid"), 1)
        with self.assertRaises(EngineContractError) as invalidate_error:
            service.invalidate(oversized)
        self.assertEqual(
            invalidate_error.exception.code,
            EngineContractErrorCode.INVALID_REQUEST,
        )
        result = service.analyze("fen-valid", multipv=1, depth=1)
        self.assertEqual(result.generation, 2)

    def test_result_dto_rejects_oversized_fen_fail_closed(self):
        oversized = "x" * (ANALYSIS_MAX_FEN_LENGTH + 1)
        with self.assertRaises(EngineContractError) as caught:
            AnalysisResult(oversized, 1, False, ())
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)

    def test_non_text_and_blank_inputs_keep_invalid_request_contract(self):
        service = AnalysisService(lambda: _RecordingEngine([]))
        for value in (True, b"fen", "   "):
            with self.subTest(value=value):
                with self.assertRaises(EngineContractError) as caught:
                    service.analyze(value, multipv=1, depth=1)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )


if __name__ == "__main__":
    unittest.main()
