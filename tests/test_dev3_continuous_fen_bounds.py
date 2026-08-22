from __future__ import annotations

import time
import unittest

from acs.analysis_service import ANALYSIS_MAX_FEN_LENGTH, AnalysisService
from acs.continuous_analysis import ContinuousAnalysisService, ContinuousAnalysisState
from acs.engine_ports import EngineContractError, RawAnalysisLine


class _Engine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def analyze(self, fen, multipv=5, depth=16):
        self.calls.append((fen, multipv, depth))
        return [
            RawAnalysisLine(
                depth=depth,
                score_kind="cp",
                score_value=0,
                pv=("e2e4",),
            )
            for _ in range(multipv)
        ]

    def close(self):
        return None


class _RecordingAnalysis(AnalysisService):
    def __init__(self, engine: _Engine) -> None:
        super().__init__(lambda: engine)
        self.invalidations: list[str | None] = []

    def invalidate(self, fen: str | None = None) -> int:
        self.invalidations.append(fen)
        return super().invalidate(fen)


def _wait(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ContinuousFenBoundsTests(unittest.TestCase):
    def test_oversized_start_fails_before_worker_invalidation_or_state_mutation(self):
        engine = _Engine()
        analysis = _RecordingAnalysis(engine)
        service = ContinuousAnalysisService(analysis)
        oversized = "x" * (ANALYSIS_MAX_FEN_LENGTH + 1)
        before = service.state()
        try:
            with self.assertRaises(EngineContractError):
                service.start(oversized)
            self.assertEqual(service.state(), before)
            self.assertIsNone(service._worker)
            self.assertEqual(analysis.invalidations, [])
            self.assertEqual(engine.calls, [])
        finally:
            service.close()

    def test_oversized_update_fails_before_invalidation_and_preserves_live_state(self):
        engine = _Engine()
        analysis = _RecordingAnalysis(engine)
        service = ContinuousAnalysisService(analysis)
        oversized = "x" * (ANALYSIS_MAX_FEN_LENGTH + 1)
        try:
            service.start("fen-a", multipv=1, depth=4)
            self.assertTrue(_wait(lambda: service.state().last_result is not None))
            before = service.state()
            invalidations_before = tuple(analysis.invalidations)

            with self.assertRaises(EngineContractError):
                service.update_position(oversized)

            self.assertEqual(service.state(), before)
            self.assertEqual(tuple(analysis.invalidations), invalidations_before)
            self.assertEqual(engine.calls, [("fen-a", 1, 4)])
        finally:
            service.close()

    def test_state_dto_rejects_oversized_fen(self):
        oversized = "x" * (ANALYSIS_MAX_FEN_LENGTH + 1)
        with self.assertRaises(EngineContractError):
            ContinuousAnalysisState(False, oversized, 5, 16, 0, None)
        with self.assertRaises(EngineContractError):
            ContinuousAnalysisState(True, oversized, 5, 16, 0, None)

    def test_exact_fen_boundary_remains_valid_and_is_normalized(self):
        boundary = "x" * ANALYSIS_MAX_FEN_LENGTH
        engine = _Engine()
        analysis = _RecordingAnalysis(engine)
        service = ContinuousAnalysisService(analysis)
        try:
            revision = service.start("  " + boundary + "  ", multipv=1, depth=4)
            self.assertEqual(revision, 1)
            self.assertTrue(_wait(lambda: service.state().last_result is not None))
            state = service.state()
            self.assertEqual(state.fen, boundary)
            self.assertEqual(analysis.invalidations[0], boundary)
            self.assertEqual(engine.calls, [(boundary, 1, 4)])
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
