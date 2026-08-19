import unittest

from acs.clock_service import ChessClock, ClockSnapshot, ClockState, TimeControl
from acs.engine_game_session import (
    EngineGameSessionCoordinator,
    EngineGameSessionSnapshot,
    EngineNoMoveHandoff,
    EngineNoMoveResolution,
    EngineTurnState,
)
from acs.engine_play_service import (
    EngineGameConfig,
    EngineGameHandoff,
    EngineGameIntent,
    EnginePlayService,
    resolve_engine_game_config,
)
from acs.engine_ports import EngineContractError, EngineContractErrorCode
from acs.game_lifecycle import EndReason, GameLifecycle, GameStatus


class FakeTime:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeMoveEngine:
    def __init__(self, move='e7e5'):
        self.move = move
        self.calls = []

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        self.calls.append((fen, skill_level, movetime_ms))
        return self.move

    def close(self):
        pass


class EngineGameSessionTests(unittest.TestCase):
    def make_session(
        self,
        *,
        engine_side='black',
        move='e7e5',
        time_control=None,
        now=None,
        clock_restore_provider=None,
        no_move_resolver=None,
    ):
        state = {'fen': 'fen-w', 'side': 'w', 'history': 'node-0', 'moves': [], 'undos': 0}
        analysis = []
        review = []
        engine = FakeMoveEngine(move)

        def commit_engine_move(uci):
            state['moves'].append(uci)
            state['side'] = 'w' if state['side'] == 'b' else 'b'
            state['fen'] = 'fen-' + state['side']
            state['history'] = 'node-' + str(len(state['moves']))

        def undo():
            state['undos'] += 1
            state['side'] = 'w' if state['side'] == 'b' else 'b'

        kwargs = {}
        if now is not None:
            kwargs['clock_factory'] = lambda control: ChessClock(control, now=now)

        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: engine),
            fen_provider=lambda: state['fen'],
            side_to_move_provider=lambda: state['side'],
            commit_engine_move=commit_engine_move,
            history_node_provider=lambda: state['history'],
            undo_committed_move=undo,
            clock_restore_provider=clock_restore_provider,
            no_move_resolver=no_move_resolver,
            analysis_handoff=analysis.append,
            review_handoff=review.append,
            **kwargs,
        )
        snap = session.start(
            EngineGameConfig(
                level=6,
                engine_side=engine_side,
                time_control=time_control or TimeControl(0, 0),
            )
        )
        return session, snap, state, engine, analysis, review

    def test_start_resolves_turn_without_owning_board(self):
        session, snap, state, engine, analysis, review = self.make_session(engine_side='black')
        self.assertEqual(snap.side_to_move, 'w')
        self.assertEqual(snap.turn_state, EngineTurnState.HUMAN)
        self.assertEqual(snap.config.level.level, 6)
        self.assertTrue(snap.config.time_control.untimed)

    def test_engine_turn_request_commits_through_callback_and_reschedules(self):
        session, snap, state, engine, analysis, review = self.make_session(engine_side='white', move='e2e4')
        self.assertEqual(snap.turn_state, EngineTurnState.ENGINE)
        result = session.request_engine_move()
        self.assertEqual(result.move, 'e2e4')
        self.assertEqual(state['moves'], ['e2e4'])
        self.assertEqual(session.snapshot().side_to_move, 'b')
        self.assertEqual(session.snapshot().turn_state, EngineTurnState.HUMAN)
        self.assertEqual(engine.calls[0][0], 'fen-w')

    def test_engine_move_rejected_on_human_turn(self):
        session, snap, state, engine, analysis, review = self.make_session(engine_side='black')
        with self.assertRaisesRegex(ValueError, 'not the engine turn'):
            session.request_engine_move()
        self.assertEqual(state['moves'], [])

    def test_human_commit_expires_pending_requests_and_advances_turn(self):
        session, snap, state, engine, analysis, review = self.make_session(engine_side='black')
        session.handle_handoff(EngineGameHandoff(EngineGameIntent.OFFER_DRAW, actor='w'))
        state['side'] = 'b'
        after = session.on_human_move_committed('w')
        self.assertIsNone(after.lifecycle.draw_offered_by)
        self.assertEqual(after.turn_state, EngineTurnState.ENGINE)

    def test_accept_takeback_uses_injected_history_hook(self):
        session, snap, state, engine, analysis, review = self.make_session()
        session.handle_handoff(EngineGameHandoff(EngineGameIntent.REQUEST_TAKEBACK, actor='w'))
        session.handle_handoff(EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor='b'))
        self.assertEqual(state['undos'], 1)
        self.assertIsNone(session.snapshot().lifecycle.takeback_requested_by)

    def test_takeback_preflights_missing_undo_hook_before_mutating_lifecycle(self):
        engine = FakeMoveEngine()
        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: engine),
            fen_provider=lambda: 'fen',
            side_to_move_provider=lambda: 'w',
            commit_engine_move=lambda move: None,
            history_node_provider=lambda: 'node',
        )
        session.start(EngineGameConfig())
        session.handle_handoff(EngineGameHandoff(EngineGameIntent.REQUEST_TAKEBACK, actor='w'))
        with self.assertRaisesRegex(ValueError, 'takeback undo hook is not configured'):
            session.handle_handoff(EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor='b'))
        self.assertEqual(session.snapshot().lifecycle.takeback_requested_by, 'w')

    def test_analysis_and_final_review_route_without_ui_or_history_ownership(self):
        session, snap, state, engine, analysis, review = self.make_session()
        analysis_handoff = session.analyze_current_game()
        review_handoff = session.open_final_review()
        self.assertEqual(analysis_handoff.fen, 'fen-w')
        self.assertEqual(review_handoff.history_node_id, 'node-0')
        self.assertEqual(analysis, [analysis_handoff])
        self.assertEqual(review, [review_handoff])

    def test_position_outcome_finishes_session_and_freezes_clock(self):
        now = FakeTime()
        session, snap, state, engine, analysis, review = self.make_session(
            time_control=TimeControl(10_000), now=now
        )
        now.advance(2)
        finished = session.sync_position_outcome('1/2-1/2', EndReason.STALEMATE)
        self.assertEqual(finished.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(finished.turn_state, EngineTurnState.FINISHED)
        frozen = finished.clock.white_ms
        now.advance(30)
        self.assertEqual(session.snapshot().clock.white_ms, frozen)
        with self.assertRaisesRegex(ValueError, 'finished'):
            session.on_human_move_committed('w')

    def test_resignation_finishes_session_via_canonical_lifecycle(self):
        session, snap, state, engine, analysis, review = self.make_session()
        finished = session.handle_handoff(EngineGameHandoff(EngineGameIntent.RESIGN, actor='w'))
        self.assertEqual(finished.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(finished.lifecycle.outcome.result, '0-1')
        self.assertEqual(finished.turn_state, EngineTurnState.FINISHED)

    def test_timed_human_move_charges_time_awards_increment_and_switches(self):
        now = FakeTime()
        session, snap, state, engine, analysis, review = self.make_session(
            engine_side='black', time_control=TimeControl(10_000, 2_000), now=now
        )
        session.assert_move_allowed('w')
        now.advance(3)
        state['side'] = 'b'
        after = session.on_human_move_committed('w')
        self.assertEqual(after.clock.white_ms, 9_000)
        self.assertEqual(after.clock.black_ms, 10_000)
        self.assertEqual(after.clock.active, 'b')
        self.assertEqual(after.turn_state, EngineTurnState.ENGINE)

    def test_flag_before_engine_move_finishes_without_calling_engine(self):
        now = FakeTime()
        session, snap, state, engine, analysis, review = self.make_session(
            engine_side='white', time_control=TimeControl(1_000), now=now
        )
        now.advance(2)
        with self.assertRaisesRegex(ValueError, 'finished'):
            session.request_engine_move()
        self.assertEqual(engine.calls, [])
        after = session.snapshot()
        self.assertEqual(after.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(after.lifecycle.outcome.reason, EndReason.TIMEOUT)
        self.assertEqual(after.clock.flagged, 'w')

    def test_no_legal_engine_move_uses_neutral_terminal_resolution(self):
        handoffs = []

        def resolve(handoff):
            handoffs.append(handoff)
            return EngineNoMoveResolution('1/2-1/2', EndReason.STALEMATE)

        session, snap, state, engine, analysis, review = self.make_session(
            engine_side='white', move=None, no_move_resolver=resolve
        )
        result = session.request_engine_move()
        self.assertIsNone(result.move)
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(handoffs[0].fen, 'fen-w')
        self.assertEqual(handoffs[0].history_node_id, 'node-0')
        after = session.snapshot()
        self.assertEqual(after.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(after.lifecycle.outcome.reason, EndReason.STALEMATE)

    def test_no_legal_engine_move_without_resolver_does_not_guess_outcome(self):
        session, snap, state, engine, analysis, review = self.make_session(engine_side='white', move=None)
        result = session.request_engine_move()
        self.assertIsNone(result.move)
        self.assertEqual(session.snapshot().lifecycle.status, GameStatus.ACTIVE)

    def test_takeback_can_restore_exact_historical_clock_and_resume(self):
        now = FakeTime()
        restored_clock = ClockSnapshot(10_000, 10_000, 'w', ClockState.RUNNING)
        session, snap, state, engine, analysis, review = self.make_session(
            time_control=TimeControl(10_000, 1_000),
            now=now,
            clock_restore_provider=lambda: restored_clock,
        )
        now.advance(2)
        state['side'] = 'b'
        session.on_human_move_committed('w')
        session.handle_handoff(EngineGameHandoff(EngineGameIntent.REQUEST_TAKEBACK, actor='w'))
        after = session.handle_handoff(EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor='b'))
        self.assertEqual(state['undos'], 1)
        self.assertEqual(after.side_to_move, 'w')
        self.assertEqual(after.clock.white_ms, 10_000)
        self.assertEqual(after.clock.black_ms, 10_000)
        self.assertEqual(after.clock.active, 'w')
        self.assertEqual(after.clock.state, ClockState.RUNNING)
        now.advance(1)
        self.assertEqual(session.snapshot().clock.white_ms, 9_000)

    def test_reset_after_finished_game_restarts_lifecycle_and_clock(self):
        now = FakeTime()
        session, snap, state, engine, analysis, review = self.make_session(
            time_control=TimeControl(12_000, 500), now=now
        )
        session.handle_handoff(EngineGameHandoff(EngineGameIntent.RESIGN, actor='w'))
        reset = session.reset()
        self.assertEqual(reset.lifecycle.status, GameStatus.ACTIVE)
        self.assertEqual(reset.clock.white_ms, 12_000)
        self.assertEqual(reset.clock.black_ms, 12_000)
        self.assertEqual(reset.clock.active, 'w')
        self.assertEqual(reset.clock.state, ClockState.RUNNING)

    def test_unconfigured_secondary_handoff_fails_explicitly(self):
        engine = FakeMoveEngine()
        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: engine),
            fen_provider=lambda: 'fen',
            side_to_move_provider=lambda: 'w',
            commit_engine_move=lambda move: None,
            history_node_provider=lambda: 'node',
        )
        session.start(EngineGameConfig())
        with self.assertRaisesRegex(ValueError, 'analysis handoff is not configured'):
            session.handle_handoff(EngineGameHandoff(EngineGameIntent.ANALYZE_CURRENT_GAME, fen='fen'))

    def test_no_move_handoff_and_resolution_dtos_are_exact(self):
        handoff = EngineNoMoveHandoff("  fen  ", "w", "  node-1  ")
        self.assertEqual(handoff.fen, "fen")
        self.assertEqual(handoff.history_node_id, "node-1")

        invalid_handoffs = (
            (True, "w", "node"),
            ("fen", True, "node"),
            ("fen", "w", 7),
            ("fen", "w", "   "),
        )
        for values in invalid_handoffs:
            with self.subTest(handoff=values):
                with self.assertRaises(EngineContractError) as caught:
                    EngineNoMoveHandoff(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_HANDOFF,
                )

        checkmate = EngineNoMoveResolution("1-0", EndReason.CHECKMATE, "w")
        stalemate = EngineNoMoveResolution("1/2-1/2", EndReason.STALEMATE)
        self.assertEqual(checkmate.winner, "w")
        self.assertIsNone(stalemate.winner)

        invalid_resolutions = (
            ("1/2-1/2", EndReason.CHECKMATE, None),
            ("1-0", EndReason.STALEMATE, "w"),
            ("1/2-1/2", EndReason.INSUFFICIENT_MATERIAL, None),
            ("1-0", "checkmate", "w"),
        )
        for values in invalid_resolutions:
            with self.subTest(resolution=values):
                with self.assertRaises(EngineContractError) as caught:
                    EngineNoMoveResolution(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_RESULT,
                )

    def test_session_snapshot_rejects_inconsistent_nested_state(self):
        config = resolve_engine_game_config(
            EngineGameConfig(engine_side="white"),
        )
        active = GameLifecycle().snapshot()
        stopped = ClockSnapshot(0, 0, None, ClockState.STOPPED)
        valid = EngineGameSessionSnapshot(
            config,
            "w",
            EngineTurnState.ENGINE,
            active,
            stopped,
        )
        self.assertEqual(valid.turn_state, EngineTurnState.ENGINE)

        finished_lifecycle = GameLifecycle().resign("b")
        flagged = ClockSnapshot(0, 1_000, None, ClockState.FLAGGED, "w")
        wrong_active_clock = ClockSnapshot(
            1_000,
            1_000,
            "b",
            ClockState.RUNNING,
        )
        active_clock = ClockSnapshot(
            1_000,
            1_000,
            "w",
            ClockState.RUNNING,
        )
        noncanonical_untimed = ClockSnapshot(
            1_000,
            1_000,
            None,
            ClockState.STOPPED,
        )
        timed_config = resolve_engine_game_config(
            EngineGameConfig(engine_side="white", time_control=TimeControl(1_000)),
        )
        invalid = (
            (object(), "w", EngineTurnState.ENGINE, active, stopped),
            (config, True, EngineTurnState.ENGINE, active, stopped),
            (config, "w", "engine", active, stopped),
            (config, "w", EngineTurnState.ENGINE, object(), stopped),
            (config, "w", EngineTurnState.ENGINE, active, object()),
            (config, "w", EngineTurnState.HUMAN, active, stopped),
            (config, "w", EngineTurnState.ENGINE, active, flagged),
            (config, "w", EngineTurnState.HUMAN, finished_lifecycle, stopped),
            (config, "w", EngineTurnState.ENGINE, active, wrong_active_clock),
            (config, "w", EngineTurnState.ENGINE, active, noncanonical_untimed),
            (
                timed_config,
                "w",
                EngineTurnState.ENGINE,
                active,
                stopped,
            ),
            (
                timed_config,
                "w",
                EngineTurnState.FINISHED,
                finished_lifecycle,
                active_clock,
            ),
        )
        for values in invalid:
            with self.subTest(snapshot=values):
                with self.assertRaises(EngineContractError) as caught:
                    EngineGameSessionSnapshot(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_SESSION,
                )

    def test_coordinator_constructor_validates_required_and_optional_providers(self):
        service = EnginePlayService(lambda: FakeMoveEngine())
        base = {
            "fen_provider": lambda: "fen",
            "side_to_move_provider": lambda: "w",
            "commit_engine_move": lambda move: None,
            "history_node_provider": lambda: "node",
        }
        with self.assertRaisesRegex(TypeError, "EnginePlayService"):
            EngineGameSessionCoordinator(object(), **base)

        for name in tuple(base):
            invalid = dict(base, **{name: object()})
            with self.subTest(provider=name):
                with self.assertRaises(EngineContractError) as caught:
                    EngineGameSessionCoordinator(service, **invalid)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_PROVIDER,
                )

        optional = (
            "undo_committed_move",
            "clock_restore_provider",
            "no_move_resolver",
            "analysis_handoff",
            "review_handoff",
        )
        for name in optional:
            with self.subTest(provider=name):
                with self.assertRaises(EngineContractError) as caught:
                    EngineGameSessionCoordinator(
                        service,
                        **base,
                        **{name: object()},
                    )
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_PROVIDER,
                )

        with self.assertRaises(EngineContractError) as lifecycle_error:
            EngineGameSessionCoordinator(service, **base, lifecycle=object())
        self.assertEqual(
            lifecycle_error.exception.code,
            EngineContractErrorCode.INVALID_CONFIG,
        )
        with self.assertRaises(EngineContractError) as clock_factory_error:
            EngineGameSessionCoordinator(service, **base, clock_factory=object())
        self.assertEqual(
            clock_factory_error.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )

    def test_failed_start_does_not_reset_injected_lifecycle_or_start_session(self):
        lifecycle = GameLifecycle()
        lifecycle.offer_draw("w")
        before = lifecycle.snapshot()
        service = EnginePlayService(lambda: FakeMoveEngine())
        coordinator = EngineGameSessionCoordinator(
            service,
            fen_provider=lambda: "fen",
            side_to_move_provider=lambda: "w",
            commit_engine_move=lambda move: None,
            history_node_provider=lambda: "node",
            lifecycle=lifecycle,
            clock_factory=lambda control: object(),
        )

        with self.assertRaises(EngineContractError) as caught:
            coordinator.start(EngineGameConfig())

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)
        self.assertEqual(lifecycle.snapshot(), before)
        with self.assertRaisesRegex(ValueError, "has not started"):
            coordinator.snapshot()

    def test_falsey_callable_clock_factory_is_not_replaced(self):
        class FalseyClockFactory:
            def __init__(self):
                self.calls = []

            def __bool__(self):
                return False

            def __call__(self, control):
                self.calls.append(control)
                return ChessClock(control)

        factory = FalseyClockFactory()
        coordinator = EngineGameSessionCoordinator(
            EnginePlayService(lambda: FakeMoveEngine()),
            fen_provider=lambda: "fen",
            side_to_move_provider=lambda: "w",
            commit_engine_move=lambda move: None,
            history_node_provider=lambda: "node",
            clock_factory=factory,
        )

        snapshot = coordinator.start(EngineGameConfig())

        self.assertEqual(factory.calls, [TimeControl(0)])
        self.assertEqual(snapshot.side_to_move, "w")

    def test_failed_reset_side_preflight_preserves_lifecycle_state(self):
        lifecycle = GameLifecycle()
        state = {"side": "w"}
        coordinator = EngineGameSessionCoordinator(
            EnginePlayService(lambda: FakeMoveEngine()),
            fen_provider=lambda: "fen",
            side_to_move_provider=lambda: state["side"],
            commit_engine_move=lambda move: None,
            history_node_provider=lambda: "node",
            lifecycle=lifecycle,
        )
        coordinator.start(EngineGameConfig())
        before = lifecycle.offer_draw("w")
        state["side"] = True

        with self.assertRaises(EngineContractError) as caught:
            coordinator.reset()

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)
        self.assertEqual(lifecycle.snapshot(), before)

    def test_side_fen_and_history_providers_do_not_coerce_values(self):
        session, snap, state, engine, analysis, review = self.make_session(
            engine_side="white",
        )

        state["fen"] = True
        with self.assertRaises(EngineContractError) as fen_error:
            session.request_engine_move()
        self.assertEqual(
            fen_error.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )
        self.assertEqual(engine.calls, [])

        state["fen"] = "fen-w"
        state["history"] = 7
        with self.assertRaises(EngineContractError) as history_error:
            session.open_final_review()
        self.assertEqual(
            history_error.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )

        state["history"] = "node-0"
        state["side"] = "W"
        with self.assertRaises(EngineContractError) as side_error:
            session.snapshot()
        self.assertEqual(
            side_error.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )

    def test_engine_move_is_rechecked_for_timeout_before_commit(self):
        now = FakeTime()
        session, snap, state, engine, analysis, review = self.make_session(
            engine_side="white",
            time_control=TimeControl(1_000),
            now=now,
        )
        original = engine.best_move

        def slow_best_move(fen, skill_level=10, movetime_ms=500):
            now.advance(2)
            return original(fen, skill_level, movetime_ms)

        engine.best_move = slow_best_move
        with self.assertRaisesRegex(ValueError, "clock flagged before move commit"):
            session.request_engine_move()

        self.assertEqual(state["moves"], [])
        finished = session.snapshot()
        self.assertEqual(finished.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(finished.lifecycle.outcome.reason, EndReason.TIMEOUT)
        self.assertEqual(finished.clock.flagged, "w")

    def test_engine_move_is_rejected_when_position_changes_during_provider_call(self):
        session, snap, state, engine, analysis, review = self.make_session(
            engine_side="white",
        )
        original = engine.best_move

        def stale_best_move(fen, skill_level=10, movetime_ms=500):
            state["fen"] = "different-fen-with-same-side"
            return original(fen, skill_level, movetime_ms)

        engine.best_move = stale_best_move
        with self.assertRaises(EngineContractError) as caught:
            session.request_engine_move()

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_SESSION)
        self.assertEqual(state["moves"], [])
        self.assertEqual(session.snapshot().lifecycle.status, GameStatus.ACTIVE)

    def test_prestart_position_outcome_does_not_mutate_injected_lifecycle(self):
        lifecycle = GameLifecycle()
        before = lifecycle.snapshot()
        coordinator = EngineGameSessionCoordinator(
            EnginePlayService(lambda: FakeMoveEngine()),
            fen_provider=lambda: "fen",
            side_to_move_provider=lambda: "w",
            commit_engine_move=lambda move: None,
            history_node_provider=lambda: "node",
            lifecycle=lifecycle,
        )

        with self.assertRaisesRegex(ValueError, "has not started"):
            coordinator.sync_position_outcome(
                "1-0",
                EndReason.CHECKMATE,
                "w",
            )

        self.assertEqual(lifecycle.snapshot(), before)

    def test_invalid_no_move_resolver_result_does_not_finish_lifecycle(self):
        session, snap, state, engine, analysis, review = self.make_session(
            engine_side="white",
            move=None,
            no_move_resolver=lambda handoff: object(),
        )

        with self.assertRaises(EngineContractError) as caught:
            session.request_engine_move()

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)
        self.assertEqual(session.snapshot().lifecycle.status, GameStatus.ACTIVE)

    def test_wrong_handoff_type_is_rejected_without_state_change(self):
        session, snap, state, engine, analysis, review = self.make_session()
        before = session.snapshot()

        with self.assertRaisesRegex(TypeError, "EngineGameHandoff"):
            session.handle_handoff(object())

        self.assertEqual(session.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
