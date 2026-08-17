import unittest

from acs.clock_service import ChessClock, ClockState, TimeControl
from acs.engine_game_session import EngineGameSessionCoordinator, EngineTurnState
from acs.engine_play_service import EngineGameConfig, EngineGameHandoff, EngineGameIntent, EnginePlayService
from acs.game_lifecycle import GameStatus


class FixedTime:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class FakeEngine:
    def __init__(self, move):
        self.move = move
        self.calls = []

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        self.calls.append((fen, skill_level, movetime_ms))
        return self.move

    def close(self):
        pass


class EngineGameCommitCoherenceTests(unittest.TestCase):
    def _session(self, *, engine_side='white', commit=None):
        now = FixedTime()
        state = {'side': 'w', 'fen': 'start', 'history': 'node-0'}
        engine = FakeEngine('e2e4' if engine_side == 'white' else 'e7e5')

        if commit is None:
            def commit(move):
                state['side'] = 'b' if state['side'] == 'w' else 'w'
                state['fen'] = 'after-' + move
                state['history'] = 'node-1'

        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: engine),
            fen_provider=lambda: state['fen'],
            side_to_move_provider=lambda: state['side'],
            commit_engine_move=commit,
            history_node_provider=lambda: state['history'],
            clock_factory=lambda control: ChessClock(control, now=now),
        )
        session.start(
            EngineGameConfig(
                engine_side=engine_side,
                time_control=TimeControl(10_000, 1_000),
            )
        )
        return session, state, engine

    def test_engine_noop_commit_cannot_advance_lifecycle_or_clock(self):
        def noop_commit(move):
            return None

        session, state, engine = self._session(engine_side='white', commit=noop_commit)
        before = session.snapshot()
        self.assertEqual(before.turn_state, EngineTurnState.ENGINE)
        self.assertEqual(before.clock.active, 'w')

        with self.assertRaisesRegex(ValueError, 'canonical side to move did not advance after engine move commit'):
            session.request_engine_move()

        after = session.snapshot()
        self.assertEqual(engine.calls[0][0], 'start')
        self.assertEqual(state['side'], 'w')
        self.assertEqual(state['fen'], 'start')
        self.assertEqual(after.lifecycle.status, GameStatus.ACTIVE)
        self.assertEqual(after.clock.active, 'w')
        self.assertEqual(after.clock.state, ClockState.RUNNING)
        self.assertEqual(after.turn_state, EngineTurnState.ENGINE)

    def test_human_postcommit_before_board_mutation_fails_without_expiring_offer_or_switching_clock(self):
        session, state, engine = self._session(engine_side='black')
        session.handle_handoff(EngineGameHandoff(EngineGameIntent.OFFER_DRAW, actor='w'))
        before = session.snapshot()
        self.assertEqual(before.lifecycle.draw_offered_by, 'w')
        self.assertEqual(before.clock.active, 'w')

        with self.assertRaisesRegex(ValueError, 'canonical side to move did not advance after human move commit'):
            session.on_human_move_committed('w')

        after = session.snapshot()
        self.assertEqual(state['side'], 'w')
        self.assertEqual(after.lifecycle.status, GameStatus.ACTIVE)
        self.assertEqual(after.lifecycle.draw_offered_by, 'w')
        self.assertEqual(after.clock.active, 'w')
        self.assertEqual(after.clock.state, ClockState.RUNNING)

    def test_normal_human_and_engine_commits_require_and_preserve_exact_turn_transition(self):
        session, state, engine = self._session(engine_side='black')
        session.assert_move_allowed('w')
        state['side'] = 'b'
        state['fen'] = 'after-e2e4'
        human = session.on_human_move_committed('w')
        self.assertEqual(human.side_to_move, 'b')
        self.assertEqual(human.turn_state, EngineTurnState.ENGINE)
        self.assertEqual(human.clock.active, 'b')

        result = session.request_engine_move()
        self.assertEqual(result.move, 'e7e5')
        final = session.snapshot()
        self.assertEqual(state['side'], 'w')
        self.assertEqual(state['fen'], 'after-e7e5')
        self.assertEqual(final.turn_state, EngineTurnState.HUMAN)
        self.assertEqual(final.clock.active, 'w')
        self.assertEqual(final.lifecycle.status, GameStatus.ACTIVE)


if __name__ == '__main__':
    unittest.main()
