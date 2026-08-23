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
