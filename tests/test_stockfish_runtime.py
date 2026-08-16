import queue
import subprocess
import tempfile
import unittest
from pathlib import Path

from acs.analysis_service import AnalysisService
from acs.engine import UCIEngine
from acs.engine_play_service import EnginePlayService
from acs.engine_ports import ChessEnginePort, EngineMoveRequest, RawAnalysisLine
from acs.stockfish_runtime import (
    PACKAGED_STOCKFISH_RELATIVE_PATH,
    StockfishInvalidExecutableError,
    StockfishNotFoundError,
    StockfishRuntime,
    StockfishRuntimeConfig,
    StockfishRuntimeError,
    resolve_stockfish_path,
)


class FakeEngine:
    def __init__(self):
        self.close_count = 0
        self.analysis_calls = []
        self.move_calls = []

    def analyze(self, fen, multipv=5, depth=16):
        self.analysis_calls.append((fen, multipv, depth))
        return [RawAnalysisLine(depth, "cp", i * 10, ("e2e4",)) for i in range(multipv)]

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        self.move_calls.append((fen, skill_level, movetime_ms))
        return "e2e4"

    def close(self):
        self.close_count += 1


class ScriptedUCI(UCIEngine):
    def __init__(self, lines):
        super().__init__("ignored.exe")
        self.sent = []
        for line in lines:
            self.q.put(line)

    def start(self):
        return None

    def send(self, command):
        self.sent.append(command)

    def _drain(self):
        return None


class RecordingStdin:
    def __init__(self):
        self.writes = []
        self.flushes = 0

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        self.flushes += 1


class ShutdownProcess:
    """Release-facing fake that can ignore quit/terminate until kill escalation."""

    def __init__(self, *, waits_before_exit=0, stdout=()):
        self.stdin = RecordingStdin()
        self.stdout = stdout
        self._alive = True
        self.waits_before_exit = int(waits_before_exit)
        self.wait_calls = 0
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return None if self._alive else 0

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.wait_calls <= self.waits_before_exit:
            raise subprocess.TimeoutExpired("stockfish", timeout)
        self._alive = False
        return 0

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1
        self._alive = False


class FailingHandshakeUCI(UCIEngine):
    def _wait(self, token, timeout):
        raise RuntimeError("forced handshake failure")


class StockfishRuntimeTests(unittest.TestCase):
    def _make_engine_file(self, root: Path, relative=PACKAGED_STOCKFISH_RELATIVE_PATH) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-stockfish-binary")
        return path

    def test_packaged_relative_path_is_stable_and_resolves_from_application_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = self._make_engine_file(root)
            actual = resolve_stockfish_path(StockfishRuntimeConfig(application_dir=root))
            self.assertEqual(expected.resolve(), actual)
            self.assertEqual(Path("engines/stockfish/stockfish.exe"), PACKAGED_STOCKFISH_RELATIVE_PATH)

    def test_explicit_configured_path_is_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packaged = self._make_engine_file(root)
            configured = root / "custom" / "sf.exe"
            configured.parent.mkdir()
            configured.write_bytes(b"custom")
            actual = resolve_stockfish_path(
                StockfishRuntimeConfig(configured_path=configured, application_dir=root)
            )
            self.assertEqual(configured.resolve(), actual)
            self.assertNotEqual(packaged.resolve(), actual)

    def test_missing_engine_has_clear_error_without_fallback_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(StockfishNotFoundError, "not found"):
                resolve_stockfish_path(StockfishRuntimeConfig(application_dir=tmp))
        with self.assertRaisesRegex(StockfishNotFoundError, "application_dir"):
            resolve_stockfish_path(StockfishRuntimeConfig())

    def test_empty_engine_is_rejected_as_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / PACKAGED_STOCKFISH_RELATIVE_PATH
            path.parent.mkdir(parents=True)
            path.write_bytes(b"")
            with self.assertRaisesRegex(StockfishInvalidExecutableError, "empty or corrupt"):
                resolve_stockfish_path(StockfishRuntimeConfig(application_dir=root))

    def test_runtime_reuses_exactly_one_provider_and_owns_close_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_engine_file(root)
            built = []

            def builder(path):
                engine = FakeEngine()
                built.append((path, engine))
                return engine

            runtime = StockfishRuntime(StockfishRuntimeConfig(application_dir=root), engine_builder=builder)
            first = runtime.provider()
            second = runtime.provider()
            self.assertIs(first, second)
            self.assertEqual(1, len(built))
            self.assertIsInstance(first, ChessEnginePort)
            runtime.close()
            runtime.close()
            self.assertEqual(1, first.close_count)
            with self.assertRaisesRegex(StockfishRuntimeError, "closed"):
                runtime.provider()

    def test_analysis_and_play_services_share_runtime_without_duplicate_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_engine_file(root)
            fake = FakeEngine()
            runtime = StockfishRuntime(
                StockfishRuntimeConfig(application_dir=root),
                engine_builder=lambda path: fake,
            )
            analysis = AnalysisService(runtime.provider, owns_engine=False)
            play = EnginePlayService(runtime.provider, owns_engine=False)
            result = analysis.analyze("fen-a")
            move = play.choose_move(EngineMoveRequest("fen-b", level=5, movetime_ms=200))
            self.assertFalse(result.stale)
            self.assertEqual(5, len(result.lines))
            self.assertEqual("e2e4", move.move)
            analysis.close()
            play.close()
            self.assertEqual(0, fake.close_count)
            self.assertIs(runtime.provider(), fake)
            runtime.close()
            self.assertEqual(1, fake.close_count)

    def test_uci_analysis_uses_readiness_multipv5_and_returns_typed_depth_eval_pv(self):
        engine = ScriptedUCI([
            "readyok",
            "info depth 18 multipv 1 score cp 34 pv e2e4 e7e5",
            "info depth 17 multipv 2 score cp 12 pv d2d4 d7d5",
            "info depth 16 multipv 3 score cp 5 pv g1f3 g8f6",
            "info depth 15 multipv 4 score cp -3 pv c2c4 e7e5",
            "info depth 14 multipv 5 score mate 7 pv b2b3 e7e5",
            "bestmove e2e4",
        ])
        lines = engine.analyze("fen", depth=18)
        self.assertEqual(5, len(lines))
        self.assertTrue(all(isinstance(line, RawAnalysisLine) for line in lines))
        self.assertEqual((18, "cp", 34, ("e2e4", "e7e5")), (
            lines[0].depth, lines[0].score_kind, lines[0].score_value, lines[0].pv
        ))
        self.assertIn("setoption name MultiPV value 5", engine.sent)
        self.assertIn("isready", engine.sent)
        self.assertIn("go depth 18", engine.sent)

    def test_uci_bestmove_uses_same_adapter_and_readiness_boundary(self):
        engine = ScriptedUCI(["readyok", "bestmove g1f3"])
        move = engine.best_move("fen", skill_level=12, movetime_ms=300)
        self.assertEqual("g1f3", move)
        self.assertIn("setoption name Skill Level value 12", engine.sent)
        self.assertIn("isready", engine.sent)
        self.assertIn("go movetime 300", engine.sent)

    def test_uci_close_escalates_quit_terminate_kill_and_waits_for_exit(self):
        proc = ShutdownProcess(waits_before_exit=2)
        engine = UCIEngine("ignored.exe")
        engine.proc = proc

        engine.close()
        engine.close()

        self.assertEqual(["quit\n"], proc.stdin.writes)
        self.assertEqual(1, proc.terminate_calls)
        self.assertEqual(1, proc.kill_calls)
        self.assertGreaterEqual(proc.wait_calls, 3)
        self.assertEqual(0, proc.poll())
        self.assertIsNone(engine.proc)

    def test_failed_uci_handshake_cleans_child_and_allows_clean_retry_state(self):
        first = ShutdownProcess(waits_before_exit=1, stdout=("boot",))
        engine = FailingHandshakeUCI("ignored.exe", process_factory=lambda *args, **kwargs: first)

        with self.assertRaisesRegex(RuntimeError, "forced handshake failure"):
            engine.start()

        self.assertIsNone(engine.proc)
        self.assertEqual(["uci\n", "quit\n"], first.stdin.writes)
        self.assertEqual(1, first.terminate_calls)
        self.assertEqual(0, first.kill_calls)
        self.assertEqual(0, first.poll())

        # The adapter itself is still usable after an initialization failure;
        # only explicit close permanently closes its ownership boundary.
        replacement = ShutdownProcess(waits_before_exit=0, stdout=("boot",))
        engine._process_factory = lambda *args, **kwargs: replacement
        with self.assertRaisesRegex(RuntimeError, "forced handshake failure"):
            engine.start()
        self.assertIsNone(engine.proc)
        self.assertEqual(["uci\n", "quit\n"], replacement.stdin.writes)
        self.assertEqual(0, replacement.poll())
        engine.close()


if __name__ == "__main__":
    unittest.main()
