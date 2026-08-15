import unittest

from acs.clock_service import TimeControl
from acs.engine_game_session import EngineGameSessionCoordinator, EngineTurnState
from acs.engine_play_service import EngineGameConfig, EngineGameHandoff, EngineGameIntent, EnginePlayService
from acs.game_lifecycle import EndReason, GameStatus


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
    def make_session(self, *, engine_side='black', move='e7e5'):
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

        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: engine),
            fen_provider=lambda: state['fen'],
            side_to_move_provider=lambda: state['side'],
            commit_engine_move=commit_engine_move,
            history_node_provider=lambda: state['history'],
            undo_committed_move=undo,
            analysis_handoff=analysis.append,
            review_handoff=review.append,
        )
        snap = session.start(EngineGameConfig(level=6, engine_side=engine_side, time_control=TimeControl(0, 0)))
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

    def test_analysis_and_final_review_route_without_ui_or_history_ownership(self):
        session, snap, state, engine, analysis, review = self.make_session()
        analysis_handoff = session.analyze_current_game()
        review_handoff = session.open_final_review()
        self.assertEqual(analysis_handoff.fen, 'fen-w')
        self.assertEqual(review_handoff.history_node_id, 'node-0')
        self.assertEqual(analysis, [analysis_handoff])
        self.assertEqual(review, [review_handoff])

    def test_position_outcome_finishes_session(self):
        session, snap, state, engine, analysis, review = self.make_session()
        finished = session.sync_position_outcome('1/2-1/2', EndReason.STALEMATE)
        self.assertEqual(finished.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(finished.turn_state, EngineTurnState.FINISHED)
        with self.assertRaisesRegex(ValueError, 'finished'):
            session.on_human_move_committed('w')

    def test_resignation_finishes_session_via_canonical_lifecycle(self):
        session, snap, state, engine, analysis, review = self.make_session()
        finished = session.handle_handoff(EngineGameHandoff(EngineGameIntent.RESIGN, actor='w'))
        self.assertEqual(finished.lifecycle.status, GameStatus.FINISHED)
        self.assertEqual(finished.lifecycle.outcome.result, '0-1')
        self.assertEqual(finished.turn_state, EngineTurnState.FINISHED)

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


if __name__ == '__main__':
    unittest.main()
