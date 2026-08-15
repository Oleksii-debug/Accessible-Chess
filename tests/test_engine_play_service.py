import unittest

from acs.clock_service import TimeControl
from acs.engine_play_service import (
    EngineGameConfig,
    EngineGameHandoff,
    EngineGameIntent,
    EnginePlayService,
    EngineSideMode,
    choose_engine_side,
    level_policy,
    resolve_engine_game_config,
)
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

    def test_all_ten_levels_are_stable_monotonic_policies(self):
        policies = [level_policy(level) for level in range(1, 11)]
        self.assertEqual([p.level for p in policies], list(range(1, 11)))
        self.assertEqual([p.skill_level for p in policies], sorted(p.skill_level for p in policies))
        self.assertEqual([p.movetime_ms for p in policies], sorted(p.movetime_ms for p in policies))
        self.assertEqual(len({(p.skill_level, p.movetime_ms) for p in policies}), 10)

    def test_side_selection_supports_white_black_and_deterministic_random(self):
        self.assertEqual(choose_engine_side('white'), 'w')
        self.assertEqual(choose_engine_side('W'), 'w')
        self.assertEqual(choose_engine_side(EngineSideMode.BLACK), 'b')
        self.assertEqual(choose_engine_side('b'), 'b')
        self.assertEqual(choose_engine_side('random', random_choice=lambda choices: choices[1]), 'b')
        with self.assertRaisesRegex(ValueError, 'white, black, or random'):
            choose_engine_side('blue')

    def test_random_side_provider_is_validated(self):
        with self.assertRaisesRegex(ValueError, "must return 'w' or 'b'"):
            choose_engine_side('random', random_choice=lambda choices: 'x')

    def test_engine_game_config_uses_canonical_clock_time_control(self):
        control = TimeControl(initial_ms=5 * 60_000, increment_ms=3_000)
        config = EngineGameConfig(level=7, engine_side='white', time_control=control)
        resolved = resolve_engine_game_config(config)
        self.assertEqual(config.engine_side, EngineSideMode.WHITE)
        self.assertEqual(resolved.engine_side, 'w')
        self.assertEqual(resolved.level, level_policy(7))
        self.assertIs(resolved.time_control, control)
        self.assertEqual(resolved.time_control.increment_ms, 3_000)

    def test_engine_game_config_supports_untimed_and_random_side(self):
        config = EngineGameConfig(level=1, engine_side=EngineSideMode.RANDOM)
        resolved = resolve_engine_game_config(config, random_choice=lambda choices: choices[0])
        self.assertEqual(resolved.engine_side, 'w')
        self.assertTrue(resolved.time_control.untimed)

    def test_engine_game_config_rejects_invalid_start_contract(self):
        with self.assertRaisesRegex(ValueError, 'between 1 and 10'):
            EngineGameConfig(level=0)
        with self.assertRaisesRegex(ValueError, 'white, black, or random'):
            EngineGameConfig(engine_side='either')
        with self.assertRaisesRegex(TypeError, 'clock_service.TimeControl'):
            EngineGameConfig(time_control='5+0')
        with self.assertRaisesRegex(TypeError, 'EngineGameConfig'):
            resolve_engine_game_config(object())

    def test_lifecycle_handoffs_require_actor_and_keep_stable_intents(self):
        intents = (
            EngineGameIntent.REQUEST_TAKEBACK,
            EngineGameIntent.ACCEPT_TAKEBACK,
            EngineGameIntent.DECLINE_TAKEBACK,
            EngineGameIntent.OFFER_DRAW,
            EngineGameIntent.ACCEPT_DRAW,
            EngineGameIntent.DECLINE_DRAW,
            EngineGameIntent.RESIGN,
        )
        for intent in intents:
            with self.subTest(intent=intent):
                handoff = EngineGameHandoff(intent, actor='w')
                self.assertEqual(handoff.intent, intent)
                self.assertEqual(handoff.actor, 'w')
                with self.assertRaisesRegex(ValueError, 'requires actor'):
                    EngineGameHandoff(intent)

    def test_analyze_current_game_handoff_requires_and_normalizes_fen(self):
        handoff = EngineGameHandoff(EngineGameIntent.ANALYZE_CURRENT_GAME, fen='  fen-current  ')
        self.assertEqual(handoff.fen, 'fen-current')
        with self.assertRaisesRegex(ValueError, 'requires fen'):
            EngineGameHandoff(EngineGameIntent.ANALYZE_CURRENT_GAME, fen='   ')

    def test_final_review_handoff_requires_stable_history_identity(self):
        handoff = EngineGameHandoff('open_final_review', history_node_id='  node-42  ')
        self.assertEqual(handoff.intent, EngineGameIntent.OPEN_FINAL_REVIEW)
        self.assertEqual(handoff.history_node_id, 'node-42')
        with self.assertRaisesRegex(ValueError, 'requires history_node_id'):
            EngineGameHandoff(EngineGameIntent.OPEN_FINAL_REVIEW)

    def test_handoff_rejects_unknown_intent_and_invalid_optional_actor(self):
        with self.assertRaisesRegex(ValueError, 'unknown engine game intent'):
            EngineGameHandoff('launch_online_match')
        with self.assertRaisesRegex(ValueError, "actor must be 'w', 'b', or None"):
            EngineGameHandoff(EngineGameIntent.ANALYZE_CURRENT_GAME, actor='x', fen='fen')

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
