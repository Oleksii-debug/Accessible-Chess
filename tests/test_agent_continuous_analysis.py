from __future__ import annotations

import asyncio
import threading
import time
import unittest

from acs.analysis_service import AnalysisService
from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk
from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chesscore import Board
from acs.continuous_analysis import ContinuousAnalysisService


class _RecordingEngine:
    def __init__(self, gate: threading.Event | None = None) -> None:
        self.gate = gate
        self.calls: list[tuple[str, int, int]] = []
        self.started = threading.Event()
        self.closed = False

    def analyze(self, fen, multipv=5, depth=16):
        self.calls.append((fen, multipv, depth))
        self.started.set()
        if self.gate is not None:
            self.gate.wait(timeout=2)
        return [
            (depth, ("cp", 20 + index), ["e2e4", "e7e5"])
            for index in range(multipv)
        ]

    def close(self):
        self.closed = True


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class AgentContinuousAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.board = Board()
        self.engine = _RecordingEngine()
        self.analysis = AnalysisService(lambda: self.engine)
        self.continuous = ContinuousAnalysisService(self.analysis)
        self.executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=self.executor,
            board_provider=lambda: self.board,
            board_commands_provider=self._board_commands,
            continuous_analysis=self.continuous,
        ).register_all()

    def tearDown(self) -> None:
        self.continuous.close()

    def _board_commands(self) -> BoardCommandService:
        board = self.board
        legal = tuple(
            MoveView(
                move.frm,
                move.to,
                board.san(move),
                bool(board.board[move.to]) or move.en_passant,
            )
            for move in board.legal_moves()
        )
        attacks = {}
        for target in range(64):
            origins = tuple(board.attackers_of(target))
            if origins:
                attacks[target] = origins
        last = board.last_move
        last_view = None if last is None else MoveView(last.frm, last.to)
        return BoardCommandService(
            BoardSnapshot(
                tuple(board.board),
                board.turn,
                legal,
                attacks,
                last_view,
            )
        )

    def execute(self, tool_id: str, arguments=None):
        return asyncio.run(
            self.executor.execute(
                ToolCall(
                    call_id=f"call-{tool_id}",
                    tool_id=tool_id,
                    arguments=arguments or {},
                )
            )
        )

    def test_continuous_engine_tools_have_explicit_risk_and_no_fen_input(self) -> None:
        specs = {
            spec.tool_id: spec
            for spec in self.executor.specs()
            if spec.tool_id.startswith("engine.")
        }
        self.assertEqual(
            set(specs),
            {
                "engine.request_analysis",
                "engine.analysis_status",
                "engine.cancel_analysis",
            },
        )
        self.assertIs(
            specs["engine.request_analysis"].risk,
            ToolRisk.LOCAL_WRITE,
        )
        self.assertIs(
            specs["engine.cancel_analysis"].risk,
            ToolRisk.LOCAL_WRITE,
        )
        self.assertIs(
            specs["engine.analysis_status"].risk,
            ToolRisk.READ_ONLY,
        )
        for spec in specs.values():
            self.assertNotIn("fen", spec.input_schema)

    def test_request_uses_current_canonical_board_and_status_reads_result(self) -> None:
        canonical = self.board.fen()
        requested = self.execute(
            "engine.request_analysis",
            {"multipv": 2, "depth": 12},
        )
        self.assertTrue(requested.ok, requested.error)
        self.assertEqual(requested.output["requestedFen"], canonical)
        self.assertEqual(requested.output["currentFen"], canonical)
        self.assertTrue(requested.output["positionCurrent"])
        self.assertEqual((requested.output["multipv"], requested.output["depth"]), (2, 12))

        self.assertTrue(
            _wait_until(lambda: self.continuous.state().last_result is not None)
        )
        status = self.execute("engine.analysis_status")
        self.assertTrue(status.ok, status.error)
        self.assertTrue(status.output["positionCurrent"])
        self.assertEqual(status.output["result"]["fen"], canonical)
        self.assertEqual(len(status.output["result"]["lines"]), 2)
        self.assertEqual(self.engine.calls, [(canonical, 2, 12)])

    def test_status_suppresses_result_after_canonical_board_moves(self) -> None:
        self.assertTrue(self.execute("engine.request_analysis").ok)
        self.assertTrue(
            _wait_until(lambda: self.continuous.state().last_result is not None)
        )
        previous = self.continuous.state().fen
        self.board.push_text("e4")
        self.assertNotEqual(self.board.fen(), previous)

        status = self.execute("engine.analysis_status")
        self.assertTrue(status.ok, status.error)
        self.assertFalse(status.output["positionCurrent"])
        self.assertIsNone(status.output["result"])
        self.assertEqual(status.output["requestedFen"], previous)
        self.assertEqual(status.output["currentFen"], self.board.fen())

    def test_new_request_after_move_rebinds_to_current_position(self) -> None:
        self.assertTrue(self.execute("engine.request_analysis").ok)
        self.assertTrue(
            _wait_until(lambda: self.continuous.state().last_result is not None)
        )
        self.board.push_text("d4")
        canonical = self.board.fen()

        requested = self.execute(
            "engine.request_analysis",
            {"multipv": 3, "depth": 9},
        )
        self.assertTrue(requested.ok, requested.error)
        self.assertEqual(requested.output["requestedFen"], canonical)
        self.assertTrue(requested.output["positionCurrent"])
        self.assertIsNone(requested.output["result"])
        self.assertTrue(
            _wait_until(
                lambda: (
                    self.continuous.state().last_result is not None
                    and self.continuous.state().last_result.fen == canonical
                )
            )
        )

    def test_cancel_invalidates_in_flight_result(self) -> None:
        self.continuous.close()
        gate = threading.Event()
        self.engine = _RecordingEngine(gate)
        self.analysis = AnalysisService(lambda: self.engine)
        self.continuous = ContinuousAnalysisService(self.analysis)
        self.executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=self.executor,
            board_provider=lambda: self.board,
            board_commands_provider=self._board_commands,
            continuous_analysis=self.continuous,
        ).register_all()

        requested = self.execute("engine.request_analysis")
        self.assertTrue(requested.ok, requested.error)
        self.assertTrue(self.engine.started.wait(timeout=1))

        cancelled = self.execute("engine.cancel_analysis")
        self.assertTrue(cancelled.ok, cancelled.error)
        self.assertFalse(cancelled.output["running"])
        self.assertIsNone(cancelled.output["result"])
        gate.set()
        time.sleep(0.05)
        status = self.execute("engine.analysis_status")
        self.assertTrue(status.ok, status.error)
        self.assertFalse(status.output["running"])
        self.assertIsNone(status.output["result"])

    def test_arguments_fail_closed_and_never_accept_arbitrary_fen(self) -> None:
        for arguments in (
            {"fen": Board.START},
            {"multipv": True},
            {"multipv": 0},
            {"multipv": 11},
            {"depth": True},
            {"depth": 0},
            {"depth": 41},
            {"multipv": 3, "unknown": 1},
        ):
            with self.subTest(arguments=arguments):
                result = self.execute("engine.request_analysis", arguments)
                self.assertFalse(result.ok)
                self.assertIsNone(result.output)

        for tool_id in ("engine.analysis_status", "engine.cancel_analysis"):
            with self.subTest(tool_id=tool_id):
                result = self.execute(tool_id, {"unexpected": True})
                self.assertFalse(result.ok)
                self.assertIsNone(result.output)

    def test_without_continuous_service_lifecycle_tools_are_absent(self) -> None:
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: self.board,
            board_commands_provider=self._board_commands,
        ).register_all()
        ids = {spec.tool_id for spec in executor.specs()}
        self.assertFalse(
            {
                "engine.request_analysis",
                "engine.analysis_status",
                "engine.cancel_analysis",
            }
            & ids
        )


if __name__ == "__main__":
    unittest.main()
