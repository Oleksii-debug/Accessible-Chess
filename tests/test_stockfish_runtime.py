import queue
import tempfile
import unittest
from pathlib import Path

from acs.analysis_service import AnalysisService
from acs.engine import UCIEngine
from acs.engine_play_service import EnginePlayService
from acs.engine_ports import (
    ChessEnginePort,
    EngineContractError,
    EngineContractErrorCode,
    EngineMoveRequest,
    RawAnalysisLine,
)
from acs.stockfish_runtime import (
    PACKAGED_STOCKFISH_RELATIVE_PATH,
    StockfishInvalidExecutableError,
    StockfishNotFoundError,
    StockfishProviderError,
    StockfishRuntime,
    StockfishRuntimeConfig,
    StockfishRuntimeConfigError,
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


class FakeStdin:
    def __init__(self):
        self.writes = []
        self.flush_count = 0

    def write(self, value):
        self.writes.append(value)
        return len(value)

    def flush(self):
        self.flush_count += 1


class FakeProcess:
    def __init__(self, stdout=()):
        self.stdin = FakeStdin()
        self.stdout = list(stdout)
        self.returncode = None
        self.wait_count = 0
        self.terminate_count = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_count += 1
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminate_count += 1
        self.returncode = -15


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

    def test_invalid_filesystem_syntax_has_a_typed_resolution_error(self):
        with self.assertRaisesRegex(
            StockfishInvalidExecutableError,
            "Cannot resolve configured Stockfish path",
        ):
            resolve_stockfish_path(
                StockfishRuntimeConfig(configured_path="bad\x00path"),
            )

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

    def test_runtime_config_and_constructor_reject_coercive_values(self):
        for field_name in ("configured_path", "application_dir"):
            for invalid in (True, 7, 7.0, b"path", object(), "", "   "):
                with self.subTest(field=field_name, value=invalid):
                    with self.assertRaises(StockfishRuntimeConfigError):
                        StockfishRuntimeConfig(**{field_name: invalid})

        with self.assertRaises(StockfishRuntimeConfigError):
            resolve_stockfish_path(object())
        with self.assertRaises(StockfishRuntimeConfigError):
            StockfishRuntime(object())
        with self.assertRaises(StockfishRuntimeConfigError):
            StockfishRuntime(StockfishRuntimeConfig(), engine_builder=object())

    def test_falsey_callable_builder_is_not_replaced(self):
        class FalseyBuilder:
            def __init__(self):
                self.paths = []
                self.engine = FakeEngine()

            def __bool__(self):
                return False

            def __call__(self, path):
                self.paths.append(path)
                return self.engine

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = self._make_engine_file(root)
            builder = FalseyBuilder()
            runtime = StockfishRuntime(
                StockfishRuntimeConfig(application_dir=root),
                engine_builder=builder,
            )
            self.assertIs(runtime.provider(), builder.engine)
            self.assertEqual(builder.paths, [str(expected.resolve())])
            runtime.close()
            self.assertEqual(builder.engine.close_count, 1)

    def test_incompatible_builder_result_fails_explicitly_and_can_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_engine_file(root)
            valid = FakeEngine()
            outputs = [object(), valid]

            def builder(path):
                return outputs.pop(0)

            runtime = StockfishRuntime(
                StockfishRuntimeConfig(application_dir=root),
                engine_builder=builder,
            )
            with self.assertRaisesRegex(StockfishProviderError, "incompatible"):
                runtime.provider()
            self.assertIs(runtime.provider(), valid)
            runtime.close()
            self.assertEqual(valid.close_count, 1)

    def test_failed_provider_close_is_retryable_without_reopening_runtime(self):
        class FlakyCloseEngine(FakeEngine):
            def close(self):
                self.close_count += 1
                if self.close_count == 1:
                    raise RuntimeError("temporary close failure")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_engine_file(root)
            engine = FlakyCloseEngine()
            runtime = StockfishRuntime(
                StockfishRuntimeConfig(application_dir=root),
                engine_builder=lambda path: engine,
            )
            self.assertIs(runtime.provider(), engine)

            with self.assertRaisesRegex(RuntimeError, "temporary close failure"):
                runtime.close()
            with self.assertRaisesRegex(StockfishRuntimeError, "closed"):
                runtime.provider()

            runtime.close()
            runtime.close()
            self.assertEqual(engine.close_count, 2)

    def test_uci_constructor_and_requests_reject_command_injection_and_coercion(self):
        for invalid_path in (True, 7, b"path", object(), "", "   ", "a\nb"):
            with self.subTest(path=invalid_path):
                with self.assertRaises(EngineContractError) as caught:
                    UCIEngine(invalid_path)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_CONFIG,
                )
        with self.assertRaises(EngineContractError) as factory_error:
            UCIEngine("stockfish", process_factory=object())
        self.assertEqual(
            factory_error.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )

        engine = ScriptedUCI([])
        invalid_analysis = (
            (True, 5, 16),
            ("   ", 5, 16),
            ("fen\nquit", 5, 16),
            ("fen", True, 16),
            ("fen", "5", 16),
            ("fen", 5.0, 16),
            ("fen", 5, True),
            ("fen", 5, "16"),
            ("fen", 5, 16.0),
        )
        for values in invalid_analysis:
            with self.subTest(analysis=values):
                with self.assertRaises(EngineContractError) as caught:
                    engine.analyze(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )
        invalid_moves = (
            (True, 10, 500),
            ("fen\risready", 10, 500),
            ("fen", True, 500),
            ("fen", "10", 500),
            ("fen", 10.0, 500),
            ("fen", 10, True),
            ("fen", 10, "500"),
            ("fen", 10, 500.0),
        )
        for values in invalid_moves:
            with self.subTest(move=values):
                with self.assertRaises(EngineContractError) as caught:
                    engine.best_move(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )
        self.assertEqual(engine.sent, [])

        direct = UCIEngine("stockfish")
        for command in (True, "", "   ", "isready\nquit", "uci\rquit"):
            with self.subTest(command=command):
                with self.assertRaises(EngineContractError) as caught:
                    direct.send(command)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )

    def test_uci_analysis_ignores_incomplete_or_out_of_contract_info_lines(self):
        engine = ScriptedUCI([
            "readyok",
            "info multipv 1 score cp 1 pv e2e4",
            "info depth 18 multipv 1 pv e2e4",
            "info depth 18 multipv 0 score cp 1 pv e2e4",
            "info depth 18 multipv 3 score cp 1 pv e2e4",
            "info depth 18 multipv 1 score cp 1 pv e9",
            "info depth 17 multipv 2 score mate -3 pv d2d4 d7d5",
            "bestmovefoo e2e4",
            "bestmove e2e4",
        ])

        lines = engine.analyze("fen", multipv=2, depth=18)

        self.assertEqual(len(lines), 1)
        self.assertEqual(
            (lines[0].depth, lines[0].score_kind, lines[0].score_value),
            (17, "mate", -3),
        )
        self.assertEqual(lines[0].pv, ("d2d4", "d7d5"))

    def test_uci_bestmove_requires_an_exact_move_token(self):
        for token in ("(none)", "0000"):
            with self.subTest(token=token):
                engine = ScriptedUCI(["readyok", f"bestmove {token}"])
                self.assertIsNone(engine.best_move("fen"))

        valid = ScriptedUCI([
            "readyok",
            "bestmovefoo e2e4",
            "bestmove e7e8q ponder a7a6",
        ])
        self.assertEqual(valid.best_move("fen"), "e7e8q")

        for response in ("bestmove e9", "bestmove"):
            with self.subTest(response=response):
                invalid = ScriptedUCI(["readyok", response])
                with self.assertRaises(EngineContractError) as caught:
                    invalid.best_move("fen")
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_RESULT,
                )

        invalid_analysis = ScriptedUCI(["readyok", "bestmove e9"])
        with self.assertRaises(EngineContractError) as analysis_error:
            invalid_analysis.analyze("fen")
        self.assertEqual(
            analysis_error.exception.code,
            EngineContractErrorCode.INVALID_RESULT,
        )

    def test_uci_process_factory_output_is_validated_and_retryable(self):
        valid = FakeProcess(("uciok\n", "readyok\n"))
        outputs = [object(), valid]

        def factory(*args, **kwargs):
            return outputs.pop(0)

        engine = UCIEngine("stockfish", process_factory=factory)
        with self.assertRaises(EngineContractError) as caught:
            engine.start()
        self.assertEqual(
            caught.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )
        self.assertIsNone(engine.proc)

        engine.start()
        self.assertIs(engine.proc, valid)
        self.assertEqual(valid.stdin.writes[:2], ["uci\n", "isready\n"])
        engine.close()
        self.assertEqual(valid.stdin.writes[-1], "quit\n")
        self.assertEqual(valid.wait_count, 1)

    def test_uci_handshake_failure_discards_process_without_closing_adapter(self):
        class FailingHandshakeEngine(UCIEngine):
            def _wait(self, token, timeout):
                raise RuntimeError("handshake failed")

        proc = FakeProcess()
        engine = FailingHandshakeEngine(
            "stockfish",
            process_factory=lambda *args, **kwargs: proc,
        )
        with self.assertRaisesRegex(RuntimeError, "handshake failed"):
            engine.start()

        self.assertIsNone(engine.proc)
        self.assertIsNone(engine.reader)
        self.assertEqual(proc.terminate_count, 1)
        self.assertEqual(proc.wait_count, 1)
        self.assertFalse(engine._closed)
        engine.close()


if __name__ == "__main__":
    unittest.main()
