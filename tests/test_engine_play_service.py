import unittest

from acs.engine_play_service import EnginePlayService, choose_engine_side, level_policy
from acs.engine_ports import EngineMoveRequest


class FakeMoveEngine:
    def __init__(self, move='e2e4'):
        self.move = move
        self.calls = []
        self.closed = False

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        self.calls.append((fen, skill_level, movetime_ms))
        return self.move

    def close(self):
        self.closed = True


class EnginePlayServiceTests(unittest.TestCase):
    def test_level_policy_clamps_user_levels_1_to_10(self):
        self.assertEqual(level_policy(-5).level, 1)
        self.assertEqual(level_policy(99).level, 10)
        self.assertEqual(level_policy(1).skill_level, 0)
        self.assertEqual(level_policy(10).skill_level, 20)
        self.assertLess(level_policy(3).movetime_ms, level_policy(8).movetime_ms)

    def test_side_selection_supports_white_black_and_deterministic_random(self):
        self.assertEqual(choose_engine_side('white'), 'w')
        self.assertEqual(choose_engine_side('W'), 'w')
        self.assertEqual(choose_engine_side('black'), 'b')
        self.assertEqual(choose_engine_side('b'), 'b')
        self.assertEqual(choose_engine_side('random', random_choice=lambda choices: choices[1]), 'b')
        with self.assertRaisesRegex(ValueError, 'white, black, or random'):
            choose_engine_side('blue')

    def test_choose_move_maps_level_to_provider_without_ui_knowledge(self):
        engine = FakeMoveEngine('g1f3')
        service = EnginePlayService(lambda: engine)
        result = service.choose_move(EngineMoveRequest('fen-a', level=7))
        policy = level_policy(7)
        self.assertEqual(result.move, 'g1f3')
        self.assertEqual(result.level, 7)
        self.assertEqual(result.movetime_ms, policy.movetime_ms)
        self.assertEqual(engine.calls, [('fen-a', policy.skill_level, policy.movetime_ms)])

    def test_custom_movetime_is_bounded_and_keeps_level_policy(self):
        engine = FakeMoveEngine()
        service = EnginePlayService(lambda: engine)
        result = service.choose_move(EngineMoveRequest('fen-b', level=2, movetime_ms=1))
        self.assertEqual(result.movetime_ms, 50)
        self.assertEqual(engine.calls[0][1], level_policy(2).skill_level)
        self.assertEqual(engine.calls[0][2], 50)

    def test_provider_is_reused_and_close_is_idempotent(self):
        engine = FakeMoveEngine()
        factory_calls = []

        def factory():
            factory_calls.append(1)
            return engine

        service = EnginePlayService(factory)
        service.choose_move(EngineMoveRequest('fen-a'))
        service.choose_move(EngineMoveRequest('fen-b'))
        self.assertEqual(len(factory_calls), 1)
        service.close()
        service.close()
        self.assertTrue(engine.closed)

    def test_no_legal_move_is_not_an_error(self):
        engine = FakeMoveEngine(None)
        result = EnginePlayService(lambda: engine).choose_move(EngineMoveRequest('mate-fen', level=10))
        self.assertIsNone(result.move)

    def test_empty_fen_is_rejected_before_provider_call(self):
        engine = FakeMoveEngine()
        service = EnginePlayService(lambda: engine)
        with self.assertRaisesRegex(ValueError, 'fen must not be empty'):
            service.choose_move(EngineMoveRequest('   '))
        self.assertEqual(engine.calls, [])


if __name__ == '__main__':
    unittest.main()
