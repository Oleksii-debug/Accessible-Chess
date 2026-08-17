import threading
import time
import unittest

from acs.analysis_service import AnalysisService


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


if __name__ == '__main__':
    unittest.main()
