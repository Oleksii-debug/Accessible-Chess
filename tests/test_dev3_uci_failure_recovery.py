import unittest
from unittest.mock import patch

from acs.engine import UCIEngine
from acs.engine_ports import EngineContractError, EngineContractErrorCode


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminate_count = 0
        self.wait_count = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_count += 1
        self.returncode = -15

    def wait(self, timeout=None):
        self.wait_count += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class TransactionHarness(UCIEngine):
    def __init__(self, *, crash_on_go=False):
        super().__init__("stockfish")
        self.sent = []
        self.started = []
        self.crash_on_go = crash_on_go

    def start(self):
        if self._closed:
            raise RuntimeError("Stockfish adapter is closed")
        if self.proc is None:
            self.proc = FakeProcess()
            self.started.append(self.proc)

    def send(self, command):
        self.sent.append(command)
        if self.crash_on_go and command.startswith("go "):
            self.proc.returncode = 23

    def _drain(self):
        return None


class FastTimeoutHarness(TransactionHarness):
    def _configure_request_options(self, *, multipv, skill_level):
        return None


class Dev3UCIFailureRecoveryTests(unittest.TestCase):
    def test_malformed_bestmove_discards_process_and_retry_starts_clean_provider(self):
        engine = TransactionHarness()
        engine.q.put("readyok")
        engine.q.put("bestmove e9")

        with self.assertRaises(EngineContractError) as caught:
            engine.best_move("fen", skill_level=10, movetime_ms=50)

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)
        first = engine.started[0]
        self.assertIsNone(engine.proc)
        self.assertEqual(first.terminate_count, 1)
        self.assertFalse(engine._closed)

        engine.q.put("readyok")
        engine.q.put("bestmove e2e4")
        self.assertEqual(
            engine.best_move("fen", skill_level=10, movetime_ms=50),
            "e2e4",
        )
        self.assertEqual(len(engine.started), 2)
        self.assertIsNot(engine.started[0], engine.started[1])

    def test_process_exit_during_search_fails_fast_discards_and_can_retry(self):
        engine = TransactionHarness(crash_on_go=True)
        engine.q.put("readyok")

        with self.assertRaisesRegex(RuntimeError, "exited during bestmove search"):
            engine.best_move("fen", skill_level=10, movetime_ms=50)

        first = engine.started[0]
        self.assertIsNone(engine.proc)
        self.assertEqual(first.wait_count, 1)
        self.assertFalse(engine._closed)

        engine.crash_on_go = False
        engine.q.put("readyok")
        engine.q.put("bestmove g1f3")
        self.assertEqual(engine.best_move("fen", movetime_ms=50), "g1f3")
        self.assertEqual(len(engine.started), 2)

    def test_search_timeout_discards_process_without_terminally_closing_adapter(self):
        engine = FastTimeoutHarness()
        with patch("acs.engine.time.monotonic", side_effect=[0.0, 10.0]):
            with self.assertRaisesRegex(RuntimeError, "did not return bestmove"):
                engine.best_move("fen", movetime_ms=50)

        failed = engine.started[0]
        self.assertIsNone(engine.proc)
        self.assertEqual(failed.terminate_count, 1)
        self.assertFalse(engine._closed)


if __name__ == "__main__":
    unittest.main()
