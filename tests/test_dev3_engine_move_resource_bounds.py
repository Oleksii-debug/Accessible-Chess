from __future__ import annotations

import unittest

from acs.engine_play_service import EnginePlayService
from acs.engine_ports import (
    ENGINE_FEN_MAX_LENGTH,
    ENGINE_MOVE_MAX_MOVETIME_MS,
    EngineContractError,
    EngineMoveRequest,
    EngineMoveResult,
)


class _MoveEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        self.calls.append((fen, skill_level, movetime_ms))
        return "e2e4"

    def close(self):
        return None


class EngineMoveResourceBoundsTests(unittest.TestCase):
    def test_oversized_fen_is_rejected_before_service_factory(self):
        oversized = "x" * (ENGINE_FEN_MAX_LENGTH + 1)
        factory_calls: list[int] = []

        def factory():
            factory_calls.append(1)
            return _MoveEngine()

        service = EnginePlayService(factory)
        try:
            with self.assertRaises(EngineContractError):
                request = EngineMoveRequest(oversized)
                service.choose_move(request)
        finally:
            service.close()
        self.assertEqual(factory_calls, [])

    def test_exact_fen_and_movetime_bounds_reach_provider_unchanged(self):
        fen = "x" * ENGINE_FEN_MAX_LENGTH
        engine = _MoveEngine()
        service = EnginePlayService(lambda: engine)
        try:
            result = service.choose_move(
                EngineMoveRequest(
                    "  " + fen + "  ",
                    level=5,
                    movetime_ms=ENGINE_MOVE_MAX_MOVETIME_MS,
                )
            )
        finally:
            service.close()
        self.assertEqual(result.movetime_ms, ENGINE_MOVE_MAX_MOVETIME_MS)
        self.assertEqual(engine.calls[0][0], fen)
        self.assertEqual(engine.calls[0][2], ENGINE_MOVE_MAX_MOVETIME_MS)

    def test_oversized_movetime_is_rejected_before_service_factory(self):
        factory_calls: list[int] = []

        def factory():
            factory_calls.append(1)
            return _MoveEngine()

        with self.assertRaises(EngineContractError):
            request = EngineMoveRequest(
                "fen",
                movetime_ms=ENGINE_MOVE_MAX_MOVETIME_MS + 1,
            )
            EnginePlayService(factory).choose_move(request)
        self.assertEqual(factory_calls, [])

    def test_low_custom_movetime_keeps_existing_minimum_clamp_policy(self):
        engine = _MoveEngine()
        service = EnginePlayService(lambda: engine)
        try:
            request = EngineMoveRequest("fen", movetime_ms=-1)
            result = service.choose_move(request)
        finally:
            service.close()
        self.assertEqual(request.movetime_ms, -1)
        self.assertEqual(result.movetime_ms, 50)
        self.assertEqual(engine.calls[0][2], 50)

    def test_result_dto_cannot_claim_out_of_contract_movetime(self):
        with self.assertRaises(EngineContractError):
            EngineMoveResult("e2e4", 5, ENGINE_MOVE_MAX_MOVETIME_MS + 1)
        self.assertEqual(
            EngineMoveResult("e2e4", 5, ENGINE_MOVE_MAX_MOVETIME_MS).movetime_ms,
            ENGINE_MOVE_MAX_MOVETIME_MS,
        )


if __name__ == "__main__":
    unittest.main()
