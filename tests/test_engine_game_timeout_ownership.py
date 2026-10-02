import unittest

from acs.clock_service import ChessClock, TimeControl
from acs.engine_game_session import EngineGameSessionCoordinator
from acs.engine_play_service import EngineGameConfig, EnginePlayService
from acs.engine_ports import EngineContractError, EngineContractErrorCode
from acs.game_lifecycle import EndReason, GameStatus


class FakeTime:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class QuietEngine:
    def best_move(self, fen, skill_level=10, movetime_ms=500):
        return 'e2e4'

    def close(self):
        pass


class EngineGameTimeoutOwnershipTests(unittest.TestCase):
    def make_session(self, provider):
        now = FakeTime()
        state = {'side': 'w'}
        lifecycle_calls = []

        def capability(flagged_side):
            lifecycle_calls.append(flagged_side)
            return provider(flagged_side)

        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: QuietEngine()),
            fen_provider=lambda: 'fen-w',
            side_to_move_provider=lambda: state['side'],
            commit_engine_move=lambda move: None,
            history_node_provider=lambda: 'node-0',
            timeout_mating_capability_provider=capability,
            clock_factory=lambda control: ChessClock(control, now=now),
        )
        session.start(
            EngineGameConfig(
                engine_side='white',
                time_control=TimeControl(1_000),
            )
        )
        return session, now, lifecycle_calls

    def test_flag_with_mating_capability_is_decisive_timeout(self):
        session, now, calls = self.make_session(lambda flagged: True)
        now.advance(2)

        snapshot = session.snapshot()

        self.assertEqual(calls, ['w'])
        self.assertEqual(snapshot.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(snapshot.lifecycle.outcome.reason, EndReason.TIMEOUT)
        self.assertEqual(snapshot.lifecycle.outcome.result, '0-1')
        self.assertEqual(snapshot.lifecycle.outcome.winner, 'b')

    def test_flag_without_mating_capability_is_draw(self):
        session, now, calls = self.make_session(lambda flagged: False)
        now.advance(2)

        snapshot = session.snapshot()

        self.assertEqual(calls, ['w'])
        self.assertEqual(snapshot.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(snapshot.lifecycle.outcome.reason, EndReason.TIMEOUT)
        self.assertEqual(snapshot.lifecycle.outcome.result, '1/2-1/2')
        self.assertIsNone(snapshot.lifecycle.outcome.winner)

    def test_unknown_mating_capability_does_not_guess_result(self):
        session, now, calls = self.make_session(lambda flagged: None)
        now.advance(2)

        with self.assertRaises(EngineContractError) as caught:
            session.snapshot()

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_SESSION)
        self.assertEqual(calls, ['w'])
        self.assertEqual(session._lifecycle.snapshot().status, GameStatus.ACTIVE)

    def test_invalid_mating_capability_provider_output_fails_closed(self):
        session, now, calls = self.make_session(lambda flagged: 1)
        now.advance(2)

        with self.assertRaises(EngineContractError) as caught:
            session.snapshot()

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)
        self.assertEqual(session._lifecycle.snapshot().status, GameStatus.ACTIVE)

    def test_explicit_sync_timeout_accepts_exact_resolved_fact(self):
        session, now, calls = self.make_session(lambda flagged: None)
        now.advance(2)

        snapshot = session.sync_timeout(opponent_can_mate=False)

        self.assertEqual(calls, [])
        self.assertEqual(snapshot.lifecycle.outcome.result, '1/2-1/2')
        self.assertEqual(snapshot.lifecycle.outcome.reason, EndReason.TIMEOUT)

    def test_explicit_sync_timeout_rejects_non_boolean_fact(self):
        session, now, calls = self.make_session(lambda flagged: True)
        now.advance(2)

        with self.assertRaises(EngineContractError) as caught:
            session.sync_timeout(opponent_can_mate=1)

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertEqual(session._lifecycle.snapshot().status, GameStatus.ACTIVE)


if __name__ == '__main__':
    unittest.main()
