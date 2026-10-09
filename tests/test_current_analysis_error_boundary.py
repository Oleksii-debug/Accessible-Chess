from __future__ import annotations

import unittest

from acs.analysis_service import (
    ANALYSIS_MAX_ERROR_CHARS,
    AnalysisResult,
    AnalysisService,
)
from acs.engine_ports import EngineContractError


class RaisingStringError(RuntimeError):
    def __str__(self) -> str:
        raise AssertionError("provider exception __str__ must be contained")


class RaisingEngine:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def analyze(self, fen, multipv=5, depth=16):
        raise self.exc

    def close(self) -> None:
        pass


class CurrentAnalysisErrorBoundaryTests(unittest.TestCase):
    def test_provider_exception_with_broken_str_returns_stable_error_result(self) -> None:
        result = AnalysisService(
            lambda: RaisingEngine(RaisingStringError())
        ).analyze("fen")

        self.assertFalse(result.stale)
        self.assertEqual(result.lines, ())
        self.assertEqual(result.error, "RaisingStringError")

    def test_blank_multiline_and_oversized_provider_errors_use_type_fallback(self) -> None:
        cases = (
            RuntimeError(),
            RuntimeError("first\nsecond"),
            RuntimeError("x" * (ANALYSIS_MAX_ERROR_CHARS + 1)),
        )
        for exc in cases:
            with self.subTest(exc=type(exc).__name__, args=exc.args):
                result = AnalysisService(
                    lambda value=exc: RaisingEngine(value)
                ).analyze("fen")
                self.assertEqual(result.error, "RuntimeError")
                self.assertEqual(result.lines, ())

    def test_short_provider_error_text_is_preserved(self) -> None:
        result = AnalysisService(
            lambda: RaisingEngine(RuntimeError("engine offline"))
        ).analyze("fen")

        self.assertEqual(result.error, "engine offline")
        self.assertEqual(result.lines, ())

    def test_analysis_result_rejects_unbounded_or_multiline_error_text(self) -> None:
        invalid = (
            "x" * (ANALYSIS_MAX_ERROR_CHARS + 1),
            "first\nsecond",
            "first\rsecond",
        )
        for error in invalid:
            with self.subTest(error=repr(error[:24])):
                with self.assertRaises(EngineContractError):
                    AnalysisResult("fen", 1, False, (), error)

    def test_error_boundary_accepts_exact_limit_single_line_text(self) -> None:
        error = "x" * ANALYSIS_MAX_ERROR_CHARS
        result = AnalysisResult("fen", 1, False, (), error)
        self.assertEqual(result.error, error)


if __name__ == "__main__":
    unittest.main()
