import tempfile
import threading
import unittest
from pathlib import Path

from acs.release_app import create_release_api


class _FakeLine:
    def __init__(self, multipv):
        self.multipv = multipv
        self.depth = 12
        self.score_kind = 'cp'
        self.score_value = multipv * 10
        self.pv = ('e2e4', 'e7e5')


class _FakeEngine:
    def __init__(self):
        self.closed = False
        self.analyze_calls = 0
        self.best_move_calls = 0
        self.analyzed = threading.Event()

    def analyze(self, fen, multipv=5, depth=16):
        self.analyze_calls += 1
        self.analyzed.set()
        return tuple(_FakeLine(i) for i in range(1, multipv + 1))

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        self.best_move_calls += 1
        return 'e2e4'

    def close(self):
        self.closed = True


class _FakeRuntime:
    instances = []

    def __init__(self, config):
        self.config = config
        self.engine = _FakeEngine()
        self.closed = False
        self.__class__.instances.append(self)

    def provider(self):
        return self.engine

    def close(self):
        self.closed = True
        self.engine.close()


class ReleaseStockfishCompositionTests(unittest.TestCase):
    def test_release_api_composes_real_analysis_service_and_multipv5(self):
        _FakeRuntime.instances.clear()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = create_release_api(application_dir=td, runtime_factory=_FakeRuntime)
            try:
                result = api.toggle_engine()
                self.assertTrue(result['ok'])
                # User-facing speech stays concise; the semantic contract below
                # is what proves this is real MultiPV 5 rather than a Boolean placeholder.
                self.assertEqual(result['announcement'], 'Аналіз Stockfish увімкнено.')
                state = api.get_state()
                self.assertTrue(state['engineEnabled'])
                self.assertEqual(state['analysis']['multipv'], 5)
                self.assertNotIn('ще переноситься', state['engineStatus'])
                self.assertNotIn('migration is still in progress', state['engineStatus'])
            finally:
                api.close_analysis()
                runtime.close()
        self.assertTrue(_FakeRuntime.instances[0].closed)

    def test_release_source_contains_no_legacy_stockfish_placeholder(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'acs' / 'webapp_keymap.py').read_text(encoding='utf-8')
        self.assertNotIn('MultiPV ще переноситься', text)
        self.assertNotIn('migration is still in progress', text)

    def test_analysis_and_engine_game_share_the_one_runtime_provider(self):
        _FakeRuntime.instances.clear()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = create_release_api(application_dir=td, runtime_factory=_FakeRuntime)
            try:
                played = api.start_engine_game("black", 5, 0, 0)
                self.assertTrue(played["ok"], played)
                self.assertEqual(runtime.engine.best_move_calls, 1)

                toggled = api.toggle_engine()
                self.assertTrue(toggled["ok"], toggled)
                self.assertTrue(runtime.engine.analyzed.wait(1))
                self.assertEqual(runtime.engine.analyze_calls, 1)
                self.assertIs(runtime.provider(), runtime.engine)
            finally:
                api.close_analysis()
                runtime.close()


if __name__ == '__main__':
    unittest.main()
