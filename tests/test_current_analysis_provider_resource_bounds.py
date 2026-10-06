from __future__ import annotations

import unittest
from collections.abc import Sequence

from acs.analysis_service import (
    ANALYSIS_MAX_LINES,
    ANALYSIS_MAX_PV_PLIES,
    AnalysisLine,
    AnalysisResult,
    AnalysisService,
)
from acs.engine_ports import EngineContractError, EngineContractErrorCode


class ExplosiveSequence(Sequence):
    """Advertise a size without permitting element materialization."""

    def __init__(self, size: int) -> None:
        self._size = size
        self.getitem_calls = 0

    def __len__(self) -> int:
        return self._size

    def __getitem__(self, index):
        self.getitem_calls += 1
        raise AssertionError("oversized provider sequence must fail before iteration")


class OutputEngine:
    def __init__(self, output) -> None:
        self.output = output

    def analyze(self, fen, multipv=5, depth=16):
        return self.output

    def close(self) -> None:
        pass


class CurrentAnalysisProviderResourceBoundsTests(unittest.TestCase):
    def test_provider_line_sequence_fails_before_materialization_when_over_requested_width(self) -> None:
        output = ExplosiveSequence(ANALYSIS_MAX_LINES + 1)
        service = AnalysisService(lambda: OutputEngine(output))
        self.addCleanup(service.close)

        result = service.analyze("fen", multipv=ANALYSIS_MAX_LINES)

        self.assertEqual(
            result.error,
            "analysis provider returned more lines than requested",
        )
        self.assertEqual(result.lines, ())
        self.assertEqual(output.getitem_calls, 0)

    def test_requested_multipv_is_enforced_before_provider_materialization(self) -> None:
        output = ExplosiveSequence(2)
        service = AnalysisService(lambda: OutputEngine(output))
        self.addCleanup(service.close)

        result = service.analyze("fen", multipv=1)

        self.assertEqual(
            result.error,
            "analysis provider returned more lines than requested",
        )
        self.assertEqual(result.lines, ())
        self.assertEqual(output.getitem_calls, 0)

    def test_legacy_pv_fails_before_materialization_when_over_bound(self) -> None:
        pv = ExplosiveSequence(ANALYSIS_MAX_PV_PLIES + 1)
        service = AnalysisService(
            lambda: OutputEngine(((12, ("cp", 20), pv),))
        )
        self.addCleanup(service.close)

        result = service.analyze("fen", multipv=1)

        self.assertEqual(result.error, "legacy analysis PV exceeds supported bound")
        self.assertEqual(result.lines, ())
        self.assertEqual(pv.getitem_calls, 0)

    def test_exact_provider_and_pv_bounds_remain_valid(self) -> None:
        pv = tuple("e2e4" for _ in range(ANALYSIS_MAX_PV_PLIES))
        output = tuple(
            (12, ("cp", index), pv)
            for index in range(ANALYSIS_MAX_LINES)
        )
        service = AnalysisService(lambda: OutputEngine(output))
        self.addCleanup(service.close)

        result = service.analyze("fen", multipv=ANALYSIS_MAX_LINES)

        self.assertIsNone(result.error)
        self.assertFalse(result.stale)
        self.assertEqual(len(result.lines), ANALYSIS_MAX_LINES)
        self.assertTrue(
            all(len(line.pv) == ANALYSIS_MAX_PV_PLIES for line in result.lines)
        )

    def test_analysis_line_rejects_pv_beyond_application_bound(self) -> None:
        with self.assertRaises(EngineContractError) as caught:
            AnalysisLine(
                1,
                12,
                "cp",
                0,
                tuple("e2e4" for _ in range(ANALYSIS_MAX_PV_PLIES + 1)),
            )

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)

    def test_analysis_result_rejects_more_than_supported_lines(self) -> None:
        line = AnalysisLine(1, 12, "cp", 0, ("e2e4",))

        with self.assertRaises(EngineContractError) as caught:
            AnalysisResult(
                "fen",
                1,
                False,
                tuple(line for _ in range(ANALYSIS_MAX_LINES + 1)),
            )

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)


if __name__ == "__main__":
    unittest.main()
