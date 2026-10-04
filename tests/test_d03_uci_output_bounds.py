from __future__ import annotations

import unittest

from acs.engine import UCIEngine
from acs.engine_ports import EngineContractError, EngineContractErrorCode


class _FakeStdin:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, value: str) -> int:
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, stdout: list[str]) -> None:
        self.stdin = _FakeStdin()
        self.stdout = list(stdout)
        self.returncode = None
        self.terminate_count = 0
        self.wait_count = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_count += 1
        self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminate_count += 1
        self.returncode = -15


class D03UCIOutputBoundsTests(unittest.TestCase):
    def _engine_with_processes(self, *processes: _FakeProcess) -> UCIEngine:
        pending = list(processes)

        def factory(*args, **kwargs):
            if not pending:
                raise AssertionError("unexpected process creation")
            return pending.pop(0)

        return UCIEngine("stockfish", process_factory=factory)

    def test_oversized_output_line_fails_closed_and_adapter_can_retry(self):
        oversized = _FakeProcess(["x" * 20000, "uciok", "readyok"])
        healthy = _FakeProcess(["uciok", "readyok"])
        engine = self._engine_with_processes(oversized, healthy)

        with self.assertRaises(EngineContractError) as caught:
            engine.start()
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)
        self.assertIsNone(engine.proc)
        self.assertGreaterEqual(oversized.terminate_count, 1)

        engine.start()
        self.assertIs(engine.proc, healthy)
        engine.close()

    def test_stdout_flood_fails_closed_before_pending_queue_can_grow_without_bound(self):
        flood = [f"id name flood-{index}" for index in range(600)]
        flooded = _FakeProcess(flood + ["uciok", "readyok"])
        healthy = _FakeProcess(["uciok", "readyok"])
        engine = self._engine_with_processes(flooded, healthy)

        with self.assertRaises(EngineContractError) as caught:
            engine.start()
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)
        self.assertIsNone(engine.proc)
        self.assertGreaterEqual(flooded.terminate_count, 1)
        self.assertLessEqual(engine.q.maxsize, 256)

        engine.start()
        self.assertIs(engine.proc, healthy)
        engine.close()

    def test_normal_handshake_volume_remains_supported(self):
        normal_lines = [f"option name Option {index} type check default false" for index in range(64)]
        process = _FakeProcess(normal_lines + ["uciok", "readyok"])
        engine = self._engine_with_processes(process)

        engine.start()
        self.assertIs(engine.proc, process)
        engine.close()


if __name__ == "__main__":
    unittest.main()
