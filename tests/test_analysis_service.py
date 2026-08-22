import threading
import time
import unittest

from acs.analysis_service import AnalysisLine, AnalysisResult, AnalysisService
from acs.engine_ports import (
    EngineContractError,
    EngineContractErrorCode,
    RawAnalysisLine,
)


class FakeEngine:
    def __init__(self, gate=None):
        self.gate = gate
        self.closed = False

    def analyze(self, fen, multipv=5, depth=16):
        if self.gate is not None:
            self.gate.wait(timeout=2)
        return [
            (depth, ('cp', 34), ['e2e4', 'e7e5']),
            (depth - 1, ('mate', 3), ['d2d4', 'd7d5']),
        ][:multipv]

    def close(self):
        self.closed = True


class AnalysisServiceTests(unittest.TestCase):
    def test_normal_multipv_result_is_structured(self):
        service = AnalysisService(lambda: FakeEngine())
        result = service.analyze('fen-a', multipv=2, depth=14)
        self.assertFalse(result.stale)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.lines), 2)
        self.assertEqual(result.lines[0].multipv, 1)
        self.assertEqual(result.lines[0].score_kind, 'cp')
        self.assertEqual(result.lines[0].pv, ('e2e4', 'e7e5'))
        self.assertEqual(result.lines[1].score_kind, 'mate')

    def test_position_change_invalidates_in_flight_result(self):
        gate = threading.Event()
        service = AnalysisService(lambda: FakeEngine(gate))
        holder = {}

        def work():
            holder['result'] = service.analyze('fen-old', multipv=2, depth=12)

        thread = threading.Thread(target=work)
        thread.start()
        time.sleep(0.05)
        service.invalidate('fen-new')
        gate.set()
        thread.join(timeout=2)

        self.assertIn('result', holder)
        self.assertTrue(holder['result'].stale)
        self.assertEqual(holder['result'].lines, ())

    def test_newer_analysis_supersedes_older_generation(self):
        service = AnalysisService(lambda: FakeEngine())
        first_generation = service.invalidate('fen-a')
        result = service.analyze('fen-b', multipv=1, depth=8)
        self.assertGreater(result.generation, first_generation)
        self.assertFalse(result.stale)
        self.assertEqual(result.fen, 'fen-b')

    def test_engine_errors_are_returned_not_raised(self):
        class BrokenEngine:
            def analyze(self, *args, **kwargs):
                raise RuntimeError('engine offline')

            def close(self):
                pass

        result = AnalysisService(lambda: BrokenEngine()).analyze('fen-x')
        self.assertFalse(result.stale)
        self.assertEqual(result.error, 'engine offline')
        self.assertEqual(result.lines, ())

    def test_concurrent_requests_share_one_serialized_provider_and_old_result_is_stale(self):
        entered = threading.Event()
        release = threading.Event()
        active_lock = threading.Lock()
        state = {'factory_calls': 0, 'active': 0, 'max_active': 0, 'calls': []}

        class SerialProbeEngine:
            def analyze(self, fen, multipv=5, depth=16):
                with active_lock:
                    state['active'] += 1
                    state['max_active'] = max(state['max_active'], state['active'])
                    state['calls'].append(fen)
                if fen == 'fen-old':
                    entered.set()
                    release.wait(timeout=2)
                time.sleep(0.02)
                with active_lock:
                    state['active'] -= 1
                return [(depth, ('cp', 1), ['e2e4'])]

            def close(self):
                pass

        def factory():
            state['factory_calls'] += 1
            return SerialProbeEngine()

        service = AnalysisService(factory)
        results = {}

        first = threading.Thread(
            target=lambda: results.setdefault('old', service.analyze('fen-old'))
        )
        first.start()
        self.assertTrue(entered.wait(timeout=2))

        second = threading.Thread(
            target=lambda: results.setdefault('new', service.analyze('fen-new'))
        )
        second.start()
        time.sleep(0.05)
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(state['factory_calls'], 1)
        self.assertEqual(state['max_active'], 1)
        self.assertEqual(state['calls'], ['fen-old', 'fen-new'])
        self.assertTrue(results['old'].stale)
        self.assertFalse(results['new'].stale)
        self.assertEqual(results['new'].fen, 'fen-new')

    def test_close_invalidates_inflight_waits_for_provider_and_prevents_resurrection(self):
        entered = threading.Event()
        release = threading.Event()
        state = {'factory_calls': 0}
        engine = FakeEngine(release)

        original_analyze = engine.analyze

        def blocking_analyze(*args, **kwargs):
            entered.set()
            return original_analyze(*args, **kwargs)

        engine.analyze = blocking_analyze

        def factory():
            state['factory_calls'] += 1
            return engine

        service = AnalysisService(factory)
        holder = {}
        worker = threading.Thread(
            target=lambda: holder.setdefault('result', service.analyze('fen-live'))
        )
        worker.start()
        self.assertTrue(entered.wait(timeout=2))

        closer = threading.Thread(target=service.close)
        closer.start()
        time.sleep(0.05)

        late = service.analyze('fen-after-close')
        self.assertEqual(late.error, AnalysisService.CLOSED_ERROR)
        self.assertEqual(late.lines, ())
        self.assertEqual(state['factory_calls'], 1)
        self.assertFalse(engine.closed)

        release.set()
        worker.join(timeout=2)
        closer.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertTrue(holder['result'].stale)
        self.assertTrue(engine.closed)
        self.assertEqual(state['factory_calls'], 1)

        again = service.analyze('fen-never-start')
        self.assertEqual(again.error, AnalysisService.CLOSED_ERROR)
        self.assertEqual(state['factory_calls'], 1)

    def test_close_is_idempotent_for_owned_provider(self):
        engine = FakeEngine()
        service = AnalysisService(lambda: engine)
        service.analyze('fen-a')
        service.close()
        service.close()
        self.assertTrue(engine.closed)

    def test_raw_analysis_line_rejects_coercion_and_normalizes_text(self):
        line = RawAnalysisLine(12, " cp ", -34, (" e2e4 ", "e7e5"))
        self.assertEqual(line.score_kind, "cp")
        self.assertEqual(line.pv, ("e2e4", "e7e5"))

        invalid = (
            (True, "cp", 1, ("e2e4",)),
            (-1, "cp", 1, ("e2e4",)),
            (1, True, 1, ("e2e4",)),
            (1, "wdl", 1, ("e2e4",)),
            (1, "cp", True, ("e2e4",)),
            (1, "cp", 1, ["e2e4"]),
            (1, "cp", 1, (True,)),
            (1, "cp", 1, ("   ",)),
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(EngineContractError) as caught:
                    RawAnalysisLine(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_RESULT,
                )

    def test_analysis_line_and_result_dtos_are_exact_and_detached(self):
        line = AnalysisLine(1, 12, "cp", 34, ("e2e4", "e7e5"))
        result = AnalysisResult("  fen-a  ", 1, False, (line,))
        self.assertEqual(result.fen, "fen-a")

        payload = result.as_dict()
        payload["lines"][0]["pv"].append("g1f3")
        self.assertEqual(result.lines[0].pv, ("e2e4", "e7e5"))

        for multipv in (True, 0, 11, "1"):
            with self.subTest(multipv=multipv):
                with self.assertRaises(EngineContractError) as caught:
                    AnalysisLine(multipv, 12, "cp", 1, ("e2e4",))
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_RESULT,
                )

        invalid_results = (
            (True, 1, False, (), None),
            ("fen", True, False, (), None),
            ("fen", -1, False, (), None),
            ("fen", 1, 1, (), None),
            ("fen", 1, False, [], None),
            ("fen", 1, False, (object(),), None),
            ("fen", 1, False, (), "   "),
            ("fen", 1, False, (), 7),
            ("fen", 1, True, (line,), None),
            ("fen", 1, False, (line,), "provider failed"),
        )
        for values in invalid_results:
            with self.subTest(result=values):
                with self.assertRaises(EngineContractError) as caught:
                    AnalysisResult(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_RESULT,
                )

    def test_constructor_and_request_inputs_reject_scalar_coercion(self):
        with self.assertRaises(EngineContractError) as factory_error:
            AnalysisService(object())
        self.assertEqual(
            factory_error.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )
        with self.assertRaises(EngineContractError) as ownership_error:
            AnalysisService(lambda: FakeEngine(), owns_engine="yes")
        self.assertEqual(
            ownership_error.exception.code,
            EngineContractErrorCode.INVALID_CONFIG,
        )

        factory_calls = []
        service = AnalysisService(
            lambda: factory_calls.append(1) or FakeEngine(),
        )
        invalid_requests = (
            (True, 5, 16),
            ("   ", 5, 16),
            ("fen", True, 16),
            ("fen", "5", 16),
            ("fen", 5.0, 16),
            ("fen", 5, True),
            ("fen", 5, "16"),
            ("fen", 5, 16.0),
        )
        for values in invalid_requests:
            with self.subTest(request=values):
                with self.assertRaises(EngineContractError) as caught:
                    service.analyze(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )
        for invalid_fen in (True, "   ", b"fen"):
            with self.subTest(invalidate=invalid_fen):
                with self.assertRaises(EngineContractError) as caught:
                    service.invalidate(invalid_fen)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )
        self.assertEqual(factory_calls, [])
        self.assertEqual(service.invalidate(" fen-current "), 1)

    def test_integer_analysis_limits_keep_the_existing_clamp_policy(self):
        calls = []

        class RecordingLimitsEngine(FakeEngine):
            def analyze(self, fen, multipv=5, depth=16):
                calls.append((fen, multipv, depth))
                return []

        service = AnalysisService(lambda: RecordingLimitsEngine())
        result = service.analyze("  fen-a  ", multipv=99, depth=0)

        self.assertIsNone(result.error)
        self.assertEqual(result.fen, "fen-a")
        self.assertEqual(calls, [("fen-a", 10, 1)])

    def test_provider_factory_and_output_shapes_fail_without_incidental_errors(self):
        for provider in (object(), FakeEngine):
            with self.subTest(provider=provider):
                result = AnalysisService(lambda value=provider: value).analyze("fen")
                self.assertEqual(
                    result.error,
                    "engine factory returned an incompatible analysis provider",
                )
                self.assertEqual(result.lines, ())

        class OutputEngine:
            def __init__(self, output):
                self.output = output

            def analyze(self, fen, multipv=5, depth=16):
                return self.output

            def close(self):
                pass

        invalid_outputs = (
            (None, 5),
            ("not-lines", 5),
            (iter(()), 5),
            ([(1, ("cp", 1), ["e2e4"])] * 2, 1),
            ([[1, ("cp", 1), ["e2e4"]]], 5),
            ([(True, ("cp", 1), ["e2e4"])], 5),
            ([(1, ["cp", 1], ["e2e4"])], 5),
            ([(1, ("wdl", 1), ["e2e4"])], 5),
            ([(1, ("cp", True), ["e2e4"])], 5),
            ([(1, ("cp", 1), [7])], 5),
        )
        for output, multipv in invalid_outputs:
            with self.subTest(output=output):
                result = AnalysisService(
                    lambda value=output: OutputEngine(value),
                ).analyze("fen", multipv=multipv)
                self.assertIsNotNone(result.error)
                self.assertEqual(result.lines, ())

    def test_raw_and_legacy_provider_results_are_snapshotted(self):
        shared_pv = ["e2e4", "e7e5"]

        class MixedEngine:
            def analyze(self, fen, multipv=5, depth=16):
                return [
                    (depth, ("cp", 34), shared_pv),
                    RawAnalysisLine(depth - 1, "mate", -3, ("d2d4",)),
                ]

            def close(self):
                pass

        result = AnalysisService(lambda: MixedEngine()).analyze(
            "fen",
            multipv=2,
        )
        shared_pv.append("g1f3")

        self.assertIsNone(result.error)
        self.assertEqual(result.lines[0].pv, ("e2e4", "e7e5"))
        self.assertEqual(result.lines[1].score_kind, "mate")
        self.assertEqual(result.lines[1].score_value, -3)

    def test_blank_provider_exception_uses_a_nonempty_error_fallback(self):
        class SilentFailureEngine:
            def analyze(self, fen, multipv=5, depth=16):
                raise RuntimeError()

            def close(self):
                pass

        result = AnalysisService(lambda: SilentFailureEngine()).analyze("fen")

        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(result.lines, ())


if __name__ == '__main__':
    unittest.main()
