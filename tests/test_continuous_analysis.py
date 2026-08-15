import threading
import time
import unittest

from acs.analysis_service import AnalysisService
from acs.continuous_analysis import ContinuousAnalysisService


class RecordingEngine:
    def __init__(self, first_gate=None):
        self.first_gate = first_gate
        self.calls = []
        self.closed = False
        self.first_started = threading.Event()

    def analyze(self, fen, multipv=5, depth=16):
        self.calls.append((fen, multipv, depth))
        if len(self.calls) == 1 and self.first_gate is not None:
            self.first_started.set()
            self.first_gate.wait(timeout=2)
        return [(depth, ('cp', len(self.calls)), [fen]) for _ in range(multipv)]

    def close(self):
        self.closed = True


def wait_until(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ContinuousAnalysisTests(unittest.TestCase):
    def test_start_defaults_to_multipv5_and_publishes_current_result(self):
        engine = RecordingEngine(); results = []
        service = ContinuousAnalysisService(AnalysisService(lambda: engine), results.append)
        try:
            revision = service.start('fen-a')
            self.assertTrue(wait_until(lambda: len(results) == 1))
            state = service.state()
            self.assertEqual(revision, 1); self.assertTrue(state.running); self.assertEqual(state.fen, 'fen-a')
            self.assertEqual(state.multipv, 5); self.assertEqual(state.depth, 16); self.assertEqual(len(results[0].lines), 5)
            self.assertEqual(engine.calls, [('fen-a', 5, 16)])
        finally: service.close()

    def test_position_change_suppresses_stale_result_and_analyzes_latest(self):
        gate = threading.Event(); engine = RecordingEngine(gate); results = []
        service = ContinuousAnalysisService(AnalysisService(lambda: engine), results.append)
        try:
            service.start('fen-old', multipv=2, depth=10); self.assertTrue(engine.first_started.wait(timeout=1))
            service.update_position('fen-middle'); service.update_position('fen-new'); gate.set()
            self.assertTrue(wait_until(lambda: len(results) == 1)); self.assertEqual(results[0].fen, 'fen-new')
            self.assertEqual([call[0] for call in engine.calls], ['fen-old', 'fen-new'])
        finally: service.close()

    def test_configure_reanalyzes_current_position_with_new_limits(self):
        engine = RecordingEngine(); results = []
        service = ContinuousAnalysisService(AnalysisService(lambda: engine), results.append)
        try:
            service.start('fen-a', multipv=2, depth=8); self.assertTrue(wait_until(lambda: len(results) == 1))
            service.configure(multipv=5, depth=22); self.assertTrue(wait_until(lambda: len(results) == 2))
            self.assertEqual(engine.calls[-1], ('fen-a', 5, 22)); self.assertEqual(len(results[-1].lines), 5)
        finally: service.close()

    def test_stop_invalidates_in_flight_work_and_restart_is_clean(self):
        gate = threading.Event(); engine = RecordingEngine(gate); results = []
        service = ContinuousAnalysisService(AnalysisService(lambda: engine), results.append)
        try:
            service.start('fen-old'); self.assertTrue(engine.first_started.wait(timeout=1)); service.stop(); gate.set(); time.sleep(0.05)
            self.assertEqual(results, []); self.assertFalse(service.state().running)
            service.start('fen-restart', multipv=3, depth=12); self.assertTrue(wait_until(lambda: len(results) == 1)); self.assertEqual(results[0].fen, 'fen-restart')
        finally: service.close()

    def test_closed_service_rejects_new_work_and_closes_engine(self):
        engine = RecordingEngine(); service = ContinuousAnalysisService(AnalysisService(lambda: engine))
        service.start('fen-a'); self.assertTrue(wait_until(lambda: service.state().last_result is not None)); service.close(); self.assertTrue(engine.closed)
        with self.assertRaises(RuntimeError): service.start('fen-b')
        with self.assertRaises(RuntimeError): service.update_position('fen-b')
        with self.assertRaises(RuntimeError): service.configure(depth=20)

    def test_invalid_inputs_and_limits_are_normalized(self):
        service = ContinuousAnalysisService(AnalysisService(lambda: RecordingEngine()))
        try:
            with self.assertRaises(ValueError): service.start('   ')
            service.start('fen-a', multipv=99, depth=0); self.assertTrue(wait_until(lambda: service.state().last_result is not None))
            state = service.state(); self.assertEqual(state.multipv, 10); self.assertEqual(state.depth, 1)
            with self.assertRaises(ValueError): service.update_position('')
        finally: service.close()

    def test_callback_failure_does_not_kill_worker(self):
        engine = RecordingEngine(); seen = []
        def sink(result): seen.append(result.fen); raise RuntimeError('presentation sink failed')
        service = ContinuousAnalysisService(AnalysisService(lambda: engine), sink)
        try:
            service.start('fen-a'); self.assertTrue(wait_until(lambda: seen == ['fen-a']))
            service.update_position('fen-b'); self.assertTrue(wait_until(lambda: seen == ['fen-a', 'fen-b']))
        finally: service.close()


if __name__ == '__main__': unittest.main()
