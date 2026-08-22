import unittest

from acs.engine_play_service import (
    EngineGameHandoff,
    EngineGameIntent,
    EnginePlayService,
)
from acs.engine_ports import (
    ENGINE_MAX_FEN_LENGTH,
    EngineContractError,
    EngineContractErrorCode,
    EngineMoveRequest,
)


class _MoveEngine:
    def __init__(self):
        self.calls = []
        self.closed = False

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        self.calls.append((fen, skill_level, movetime_ms))
        return "e2e4"

    def close(self):
        self.closed = True


class EnginePlayFenBoundsTests(unittest.TestCase):
    def test_move_request_accepts_exact_boundary_and_normalizes(self):
        fen = "x" * ENGINE_MAX_FEN_LENGTH
        request = EngineMoveRequest(f"  {fen}  ")
        self.assertEqual(request.fen, fen)
        self.assertEqual(len(request.fen), 512)

    def test_move_request_rejects_oversized_fen_before_provider_creation(self):
        factory_calls = []

        def factory():
            factory_calls.append(1)
            return _MoveEngine()

        service = EnginePlayService(factory)
        with self.assertRaises(EngineContractError) as caught:
            service.choose_move(EngineMoveRequest("x" * (ENGINE_MAX_FEN_LENGTH + 1)))
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertEqual(factory_calls, [])

    def test_analysis_handoff_accepts_exact_boundary(self):
        fen = "y" * ENGINE_MAX_FEN_LENGTH
        handoff = EngineGameHandoff(
            EngineGameIntent.ANALYZE_CURRENT_GAME,
            fen=f"  {fen}  ",
        )
        self.assertEqual(handoff.fen, fen)
        self.assertEqual(len(handoff.fen), 512)

    def test_analysis_handoff_rejects_oversized_fen(self):
        with self.assertRaises(EngineContractError) as caught:
            EngineGameHandoff(
                EngineGameIntent.ANALYZE_CURRENT_GAME,
                fen="z" * (ENGINE_MAX_FEN_LENGTH + 1),
            )
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_HANDOFF)

    def test_shared_engine_bound_matches_analysis_contract(self):
        from acs.analysis_service import ANALYSIS_MAX_FEN_LENGTH

        self.assertEqual(ENGINE_MAX_FEN_LENGTH, ANALYSIS_MAX_FEN_LENGTH)


if __name__ == "__main__":
    unittest.main()
