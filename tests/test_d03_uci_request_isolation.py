from __future__ import annotations

import queue
import unittest

from acs.engine import UCIEngine
from acs.engine_ports import (
    ENGINE_FEN_MAX_LENGTH,
    ENGINE_MOVE_MAX_MOVETIME_MS,
    EngineContractError,
    EngineContractErrorCode,
)


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminate_count = 0
        self.wait_count = 0

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminate_count += 1
        self.returncode = -15

    def wait(self, timeout=None):
        self.wait_count += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _RequestFailureProbe(UCIEngine):
    """Successful-start probe whose first request synchronization fails."""

    def __init__(self) -> None:
        super().__init__("stockfish")
        self.proc = _FakeProcess()

    def start(self) -> None:
        return None

    def _configure_request_options(self, *, multipv: int, skill_level: int) -> None:
        raise RuntimeError("simulated request synchronization failure")

    def _drain(self) -> None:
        return None


class _ScriptedUCI(UCIEngine):
    def __init__(self, lines: tuple[str, ...]) -> None:
        super().__init__("stockfish")
        self.sent: list[str] = []
        self.q = queue.Queue()
        for line in lines:
            self.q.put(line)

    def start(self) -> None:
        return None

    def send(self, command: str) -> None:
        self.sent.append(command)

    def _wait(self, token: str, timeout: float) -> str:
        return token

    def _drain(self) -> None:
        return None


class _RecoveringUCI(UCIEngine):
    """Same adapter identity, fresh subprocess after one failed request."""

    def __init__(self) -> None:
        super().__init__("stockfish")
        self.sent: list[str] = []
        self.processes: list[_FakeProcess] = []
        self.start_count = 0
        self.configure_count = 0

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        self.start_count += 1
        proc = _FakeProcess()
        self.processes.append(proc)
        self.proc = proc
        self.reader = None

    def send(self, command: str) -> None:
        self.sent.append(command)

    def _configure_request_options(self, *, multipv: int, skill_level: int) -> None:
        self.configure_count += 1
        if self.configure_count == 1:
            raise RuntimeError("simulated request synchronization failure")
        self.sent.append(f"setoption name Skill Level value {skill_level}")
        self.sent.append(f"setoption name MultiPV value {multipv}")
        self.q.put("bestmove e2e4")


class D03UCIRequestIsolationTests(unittest.TestCase):
    def test_failed_search_transaction_discards_uncertain_process(self) -> None:
        for method_name in ("analyze", "best_move"):
            with self.subTest(method=method_name):
                engine = _RequestFailureProbe()
                proc = engine.proc
                self.assertIsNotNone(proc)

                with self.assertRaisesRegex(
                    RuntimeError,
                    "simulated request synchronization failure",
                ):
                    getattr(engine, method_name)("fen")

                self.assertIsNone(engine.proc)
                self.assertIsNone(engine.reader)
                self.assertEqual(proc.terminate_count, 1)
                self.assertEqual(proc.wait_count, 1)
                self.assertFalse(engine._closed)

    def test_same_adapter_restarts_with_fresh_process_after_request_failure(self) -> None:
        engine = _RecoveringUCI()

        with self.assertRaisesRegex(
            RuntimeError,
            "simulated request synchronization failure",
        ):
            engine.best_move("fen")

        first = engine.processes[0]
        self.assertIsNone(engine.proc)
        self.assertEqual(first.terminate_count, 1)

        move = engine.best_move("fen")

        self.assertEqual(move, "e2e4")
        self.assertEqual(engine.start_count, 2)
        self.assertEqual(len(engine.processes), 2)
        self.assertIs(engine.proc, engine.processes[1])
        self.assertIsNot(engine.processes[0], engine.processes[1])
        self.assertEqual(engine.processes[1].terminate_count, 0)
        self.assertFalse(engine._closed)

    def test_invalid_bestmove_discards_uncertain_process(self) -> None:
        engine = _ScriptedUCI(("bestmove e9",))
        proc = _FakeProcess()
        engine.proc = proc

        with self.assertRaises(EngineContractError) as caught:
            engine.best_move("fen")

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)
        self.assertIsNone(engine.proc)
        self.assertEqual(proc.terminate_count, 1)
        self.assertEqual(proc.wait_count, 1)

    def test_direct_uci_rejects_oversized_fen_before_provider_commands(self) -> None:
        engine = _ScriptedUCI(("bestmove e2e4",))

        with self.assertRaises(EngineContractError) as caught:
            engine.best_move("x" * (ENGINE_FEN_MAX_LENGTH + 1))

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertEqual(engine.sent, [])

    def test_direct_uci_movetime_is_bounded_by_shared_request_contract(self) -> None:
        engine = _ScriptedUCI(("bestmove e2e4",))

        move = engine.best_move(
            "fen",
            movetime_ms=ENGINE_MOVE_MAX_MOVETIME_MS + 999,
        )

        self.assertEqual(move, "e2e4")
        self.assertIn(
            f"go movetime {ENGINE_MOVE_MAX_MOVETIME_MS}",
            engine.sent,
        )
        self.assertNotIn(
            f"go movetime {ENGINE_MOVE_MAX_MOVETIME_MS + 999}",
            engine.sent,
        )


if __name__ == "__main__":
    unittest.main()
