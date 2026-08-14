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


if __name__ == '__main__':
    unittest.main()
