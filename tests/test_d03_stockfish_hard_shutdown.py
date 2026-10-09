from __future__ import annotations

import subprocess
import unittest

from acs.engine import UCIEngine
from acs.engine_ports import EngineContractError, EngineContractErrorCode


class _RecordingStdin:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.flush_count = 0

    def write(self, text: str) -> None:
        self.writes.append(text)

    def flush(self) -> None:
        self.flush_count += 1


class _StubbornProcess:
    """Ignores terminate and exits only after kill, like a stuck child process."""

    def __init__(self) -> None:
        self.returncode = None
        self.stdin = _RecordingStdin()
        self.stdout = ()
        self.terminate_count = 0
        self.kill_count = 0
        self.wait_count = 0

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminate_count += 1

    def kill(self) -> None:
        self.kill_count += 1
        self.returncode = -9

    def wait(self, timeout=None):
        self.wait_count += 1
        if self.returncode is None:
            raise subprocess.TimeoutExpired("stockfish", timeout or 0)
        return self.returncode


class _StubbornTransactionHarness(UCIEngine):
    def __init__(self) -> None:
        super().__init__("stockfish")
        self.sent: list[str] = []
        self.started: list[_StubbornProcess] = []

    def start(self) -> None:
        if self.proc is None:
            proc = _StubbornProcess()
            self.proc = proc
            self.reader = None
            self.started.append(proc)

    def send(self, command: str) -> None:
        self.sent.append(command)

    def _drain(self) -> None:
        return None


class D03StockfishHardShutdownTests(unittest.TestCase):
    def test_close_kills_and_reaps_process_when_graceful_and_terminate_stall(self) -> None:
        engine = UCIEngine("stockfish")
        proc = _StubbornProcess()
        engine.proc = proc

        engine.close()

        self.assertTrue(engine._closed)
        self.assertIsNone(engine.proc)
        self.assertIn("quit\n", proc.stdin.writes)
        self.assertEqual(proc.terminate_count, 1)
        self.assertEqual(proc.kill_count, 1)
        self.assertGreaterEqual(proc.wait_count, 3)
        self.assertIsNotNone(proc.poll())

    def test_failed_transaction_hard_kills_stubborn_process_before_retry(self) -> None:
        engine = _StubbornTransactionHarness()
        engine.q.put("readyok")
        engine.q.put("bestmove e9")

        with self.assertRaises(EngineContractError) as caught:
            engine.best_move("fen", skill_level=10, movetime_ms=50)

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)
        failed = engine.started[0]
        self.assertIsNone(engine.proc)
        self.assertEqual(failed.terminate_count, 1)
        self.assertEqual(failed.kill_count, 1)
        self.assertGreaterEqual(failed.wait_count, 2)
        self.assertIsNotNone(failed.poll())
        self.assertFalse(engine._closed)

        engine.q.put("readyok")
        engine.q.put("bestmove e2e4")
        self.assertEqual(engine.best_move("fen", movetime_ms=50), "e2e4")
        self.assertEqual(len(engine.started), 2)
        self.assertIsNot(engine.started[0], engine.started[1])


if __name__ == "__main__":
    unittest.main()
