import unittest

from acs.clock_service import TimeControl
from acs.engine_play_service import (
    EngineGameConfig,
    EngineGameHandoff,
    EngineGameIntent,
    EngineLevel,
    EnginePlayService,
    EngineSideMode,
    ResolvedEngineGameConfig,
    choose_engine_side,
    dispatch_lifecycle_handoff,
    level_policy,
    resolve_engine_game_config,
)
from acs.engine_ports import (
    EngineContractError,
    EngineContractErrorCode,
    EngineMoveRequest,
    EngineMoveResult,
)
from acs.game_lifecycle import EndReason, GameLifecycle, GameStatus


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
        with self.assertRaises(EngineContractError) as caught:
            EngineGameConfig(time_control='5+0')
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_CONFIG)
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

    def test_lifecycle_dispatch_routes_takeback_without_mutating_board_or_history(self):
        lifecycle = GameLifecycle()
        requested = dispatch_lifecycle_handoff(
            lifecycle,
            EngineGameHandoff(EngineGameIntent.REQUEST_TAKEBACK, actor='w'),
        )
        self.assertEqual(requested.takeback_requested_by, 'w')
        accepted = dispatch_lifecycle_handoff(
            lifecycle,
            EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor='b'),
        )
        self.assertIsNone(accepted.takeback_requested_by)
        self.assertEqual(accepted.status, GameStatus.ACTIVE)
        self.assertIsNone(accepted.outcome)

    def test_lifecycle_dispatch_routes_draw_and_resign_to_canonical_service(self):
        draw = GameLifecycle()
        dispatch_lifecycle_handoff(draw, EngineGameHandoff(EngineGameIntent.OFFER_DRAW, actor='w'))
        drawn = dispatch_lifecycle_handoff(draw, EngineGameHandoff(EngineGameIntent.ACCEPT_DRAW, actor='b'))
        self.assertEqual(drawn.status, GameStatus.FINISHED)
        self.assertEqual(drawn.outcome.reason, EndReason.DRAW_AGREEMENT)
        self.assertEqual(drawn.outcome.result, '1/2-1/2')

        resignation = GameLifecycle()
        resigned = dispatch_lifecycle_handoff(
            resignation,
            EngineGameHandoff(EngineGameIntent.RESIGN, actor='b'),
        )
        self.assertEqual(resigned.status, GameStatus.FINISHED)
        self.assertEqual(resigned.outcome.reason, EndReason.RESIGNATION)
        self.assertEqual(resigned.outcome.result, '1-0')
        self.assertEqual(resigned.outcome.winner, 'w')

    def test_lifecycle_dispatch_rejects_non_lifecycle_handoff_and_wrong_types(self):
        lifecycle = GameLifecycle()
        analysis = EngineGameHandoff(EngineGameIntent.ANALYZE_CURRENT_GAME, fen='fen')
        with self.assertRaisesRegex(ValueError, 'not a lifecycle intent'):
            dispatch_lifecycle_handoff(lifecycle, analysis)
        with self.assertRaisesRegex(TypeError, 'GameLifecycle'):
            dispatch_lifecycle_handoff(object(), EngineGameHandoff(EngineGameIntent.RESIGN, actor='w'))
        with self.assertRaisesRegex(TypeError, 'EngineGameHandoff'):
            dispatch_lifecycle_handoff(lifecycle, object())

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
        with self.assertRaises(EngineContractError) as caught:
            EngineGameHandoff(EngineGameIntent.ANALYZE_CURRENT_GAME, actor='x', fen='fen')
        self.assertEqual(
            caught.exception.code,
            EngineContractErrorCode.INVALID_HANDOFF,
        )

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
        with self.assertRaises(EngineContractError) as caught:
            service.choose_move(EngineMoveRequest('   '))
        self.assertEqual(
            caught.exception.code,
            EngineContractErrorCode.INVALID_REQUEST,
        )
        self.assertEqual(engine.calls, [])

    def test_level_and_config_fields_reject_scalar_coercion(self):
        for invalid in (True, False, "5", 5.0, None):
            with self.subTest(level=invalid):
                with self.assertRaises(EngineContractError) as caught:
                    level_policy(invalid)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_CONFIG,
                )
                with self.assertRaises(EngineContractError) as config_error:
                    EngineGameConfig(level=invalid)
                self.assertEqual(
                    config_error.exception.code,
                    EngineContractErrorCode.INVALID_CONFIG,
                )

        for invalid_side in (True, 1, [], {}):
            with self.subTest(engine_side=invalid_side):
                with self.assertRaises(EngineContractError) as caught:
                    EngineGameConfig(engine_side=invalid_side)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_CONFIG,
                )

    def test_public_level_and_resolved_config_dtos_validate_their_fields(self):
        invalid_levels = (
            (True, 0, 100),
            (1, 0.0, 100),
            (0, 0, 100),
            (1, 21, 100),
            (1, 0, 49),
        )
        for values in invalid_levels:
            with self.subTest(values=values):
                with self.assertRaises(EngineContractError) as caught:
                    EngineLevel(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_CONFIG,
                )

        policy = level_policy(5)
        control = TimeControl(0)
        invalid_resolved = (
            ("white", policy, control),
            (True, policy, control),
            ("w", object(), control),
            ("b", policy, object()),
        )
        for values in invalid_resolved:
            with self.subTest(values=values):
                with self.assertRaises(EngineContractError) as caught:
                    ResolvedEngineGameConfig(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_CONFIG,
                )

    def test_move_request_rejects_coercion_and_normalizes_fen(self):
        request = EngineMoveRequest("  fen-current  ", level=-5, movetime_ms=-1)
        self.assertEqual(request.fen, "fen-current")
        self.assertEqual(request.level, -5)
        self.assertEqual(request.movetime_ms, -1)

        invalid_requests = (
            (True, 5, None),
            (None, 5, None),
            (b"fen", 5, None),
            ("fen", True, None),
            ("fen", "5", None),
            ("fen", 5.0, None),
            ("fen", 5, True),
            ("fen", 5, "100"),
            ("fen", 5, 100.0),
        )
        for values in invalid_requests:
            with self.subTest(values=values):
                with self.assertRaises(EngineContractError) as caught:
                    EngineMoveRequest(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )

    def test_move_result_rejects_coercion_and_invalid_bounds(self):
        normalized = EngineMoveResult("  e2e4  ", 5, 100)
        self.assertEqual(normalized.move, "e2e4")

        invalid_results = (
            (True, 5, 100),
            ("", 5, 100),
            ([], 5, 100),
            ("e2e4", True, 100),
            ("e2e4", 0, 100),
            ("e2e4", 11, 100),
            ("e2e4", 5, True),
            ("e2e4", 5, 49),
        )
        for values in invalid_results:
            with self.subTest(values=values):
                with self.assertRaises(EngineContractError) as caught:
                    EngineMoveResult(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_RESULT,
                )

    def test_handoff_shapes_reject_irrelevant_or_coerced_payloads(self):
        invalid = (
            (True, None, None, None),
            ([], None, None, None),
            (EngineGameIntent.RESIGN, True, None, None),
            (EngineGameIntent.RESIGN, "w", "fen", None),
            (EngineGameIntent.RESIGN, "w", None, "node"),
            (EngineGameIntent.ANALYZE_CURRENT_GAME, None, True, None),
            (EngineGameIntent.ANALYZE_CURRENT_GAME, None, "fen", "node"),
            (EngineGameIntent.OPEN_FINAL_REVIEW, None, None, 7),
            (EngineGameIntent.OPEN_FINAL_REVIEW, None, "fen", "node"),
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(EngineContractError) as caught:
                    EngineGameHandoff(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_HANDOFF,
                )

    def test_random_side_chooser_and_service_constructor_are_exact(self):
        for mode in ("white", "black", "random"):
            with self.subTest(mode=mode):
                with self.assertRaises(EngineContractError) as not_callable:
                    choose_engine_side(mode, random_choice=object())
                self.assertEqual(
                    not_callable.exception.code,
                    EngineContractErrorCode.INVALID_PROVIDER,
                )
        for invalid_result in (True, 1, None, [], {}):
            with self.subTest(random_result=invalid_result):
                with self.assertRaises(EngineContractError) as caught:
                    choose_engine_side(
                        "random",
                        random_choice=lambda choices, value=invalid_result: value,
                    )
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_PROVIDER,
                )

        with self.assertRaises(EngineContractError) as factory_error:
            EnginePlayService(object())
        self.assertEqual(
            factory_error.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )
        with self.assertRaises(EngineContractError) as ownership_error:
            EnginePlayService(lambda: FakeMoveEngine(), owns_engine="yes")
        self.assertEqual(
            ownership_error.exception.code,
            EngineContractErrorCode.INVALID_CONFIG,
        )

    def test_service_rejects_wrong_request_or_incompatible_provider(self):
        with self.assertRaisesRegex(TypeError, "EngineMoveRequest"):
            EnginePlayService(lambda: FakeMoveEngine()).choose_move(object())

        for invalid_provider in (object(), FakeMoveEngine):
            service = EnginePlayService(
                lambda value=invalid_provider: value,
            )
            with self.subTest(provider=invalid_provider):
                with self.assertRaises(EngineContractError) as caught:
                    service.choose_move(EngineMoveRequest("fen"))
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_PROVIDER,
                )

    def test_provider_move_output_is_validated_before_result_is_exposed(self):
        for invalid_move in (True, 7, "", "   ", []):
            engine = FakeMoveEngine(invalid_move)
            service = EnginePlayService(lambda: engine)
            with self.subTest(move=invalid_move):
                with self.assertRaises(EngineContractError) as caught:
                    service.choose_move(EngineMoveRequest("fen"))
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_RESULT,
                )
                self.assertEqual(len(engine.calls), 1)


if __name__ == '__main__':
    unittest.main()
