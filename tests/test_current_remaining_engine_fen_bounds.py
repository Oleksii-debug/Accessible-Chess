from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.continuous_analysis import ContinuousAnalysisService, ContinuousAnalysisState
from acs.engine_game_session import EngineGameSessionCoordinator, EngineNoMoveHandoff
from acs.engine_play_service import EngineGameHandoff, EngineGameIntent
from acs.engine_ports import EngineContractError, EngineContractErrorCode, EngineMoveRequest
from acs.input_limits import MAX_FEN_CHARS


class CurrentRemainingEngineFenBoundsTests(unittest.TestCase):
    class HostileText(str):
        touched = False

        def __len__(self):
            type(self).touched = True
            raise AssertionError("rejected FEN length hook must not execute")

        def strip(self, *args, **kwargs):
            type(self).touched = True
            raise AssertionError("rejected FEN strip hook must not execute")

    def setUp(self) -> None:
        self.HostileText.touched = False

    def test_move_request_rejects_active_fen_before_hooks(self) -> None:
        hostile = self.HostileText("fen")

        with self.assertRaises(EngineContractError) as caught:
            EngineMoveRequest(hostile)  # type: ignore[arg-type]

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertFalse(self.HostileText.touched)

    def test_move_request_rejects_oversized_raw_fen(self) -> None:
        with self.assertRaises(EngineContractError) as caught:
            EngineMoveRequest("x" * (MAX_FEN_CHARS + 1))

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)

    def test_continuous_state_rejects_active_fen_before_hooks(self) -> None:
        hostile = self.HostileText("fen")

        with self.assertRaises(EngineContractError) as caught:
            ContinuousAnalysisState(False, hostile, 5, 16, 0, None)  # type: ignore[arg-type]

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_SESSION)
        self.assertFalse(self.HostileText.touched)

    def test_continuous_start_rejects_oversized_fen_before_worker_or_provider(self) -> None:
        factory_calls: list[int] = []

        def factory():
            factory_calls.append(1)
            raise AssertionError("rejected FEN must not construct an engine provider")

        analysis = AnalysisService(factory)
        service = ContinuousAnalysisService(analysis)
        self.addCleanup(service.close)

        with self.assertRaises(EngineContractError) as caught:
            service.start("x" * (MAX_FEN_CHARS + 1))

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertEqual(factory_calls, [])
        self.assertIsNone(service._worker)
        self.assertFalse(service.state().running)

    def test_continuous_normalizer_rejects_active_fen_before_hooks(self) -> None:
        hostile = self.HostileText("fen")

        with self.assertRaises(EngineContractError) as caught:
            ContinuousAnalysisService._normalize_fen(hostile)  # type: ignore[arg-type]

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertFalse(self.HostileText.touched)

    def test_no_move_handoff_rejects_active_and_oversized_fen(self) -> None:
        hostile = self.HostileText("fen")

        with self.assertRaises(EngineContractError) as active:
            EngineNoMoveHandoff(hostile, "w", "node")  # type: ignore[arg-type]
        self.assertEqual(active.exception.code, EngineContractErrorCode.INVALID_HANDOFF)
        self.assertFalse(self.HostileText.touched)

        with self.assertRaises(EngineContractError) as oversized:
            EngineNoMoveHandoff("x" * (MAX_FEN_CHARS + 1), "w", "node")
        self.assertEqual(oversized.exception.code, EngineContractErrorCode.INVALID_HANDOFF)

    def test_session_fen_provider_rejects_active_fen_before_hooks(self) -> None:
        hostile = self.HostileText("fen")
        coordinator = EngineGameSessionCoordinator.__new__(EngineGameSessionCoordinator)
        coordinator._fen_provider = lambda: hostile

        with self.assertRaises(EngineContractError) as caught:
            coordinator._current_fen()

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)
        self.assertFalse(self.HostileText.touched)

    def test_session_fen_provider_rejects_oversized_raw_fen(self) -> None:
        coordinator = EngineGameSessionCoordinator.__new__(EngineGameSessionCoordinator)
        coordinator._fen_provider = lambda: "x" * (MAX_FEN_CHARS + 1)

        with self.assertRaises(EngineContractError) as caught:
            coordinator._current_fen()

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)

    def test_analysis_game_handoff_rejects_active_and_oversized_fen(self) -> None:
        hostile = self.HostileText("fen")

        with self.assertRaises(EngineContractError) as active:
            EngineGameHandoff(EngineGameIntent.ANALYZE_CURRENT_GAME, fen=hostile)  # type: ignore[arg-type]
        self.assertEqual(active.exception.code, EngineContractErrorCode.INVALID_HANDOFF)
        self.assertFalse(self.HostileText.touched)

        with self.assertRaises(EngineContractError) as oversized:
            EngineGameHandoff(
                EngineGameIntent.ANALYZE_CURRENT_GAME,
                fen="x" * (MAX_FEN_CHARS + 1),
            )
        self.assertEqual(oversized.exception.code, EngineContractErrorCode.INVALID_HANDOFF)

    def test_exact_raw_representation_boundary_remains_valid_for_engine_dtos(self) -> None:
        boundary = "x" * MAX_FEN_CHARS

        self.assertEqual(EngineMoveRequest(boundary).fen, boundary)
        state = ContinuousAnalysisState(False, boundary, 5, 16, 0, None)
        self.assertEqual(state.fen, boundary)
        self.assertEqual(
            EngineNoMoveHandoff(boundary, "b", "node").fen,
            boundary,
        )
        self.assertEqual(
            EngineGameHandoff(
                EngineGameIntent.ANALYZE_CURRENT_GAME,
                fen=boundary,
            ).fen,
            boundary,
        )


if __name__ == "__main__":
    unittest.main()
