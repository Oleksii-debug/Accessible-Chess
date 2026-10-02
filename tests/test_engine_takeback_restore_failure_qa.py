from __future__ import annotations

"""QA-only executable reproduction for #1060, never a Product acceptance gate.

The four expected failures describe distinct post-undo errors present in the
frozen Product.  An unexpected success is intentionally a failing unittest
result: it signals that the corresponding bug has been repaired and the
regression should be converted into a normal passing assertion.

No replacement Board, chess rule, clock implementation, or synthetic recovery
path is introduced by these tests.
"""

import tempfile
import unittest
from pathlib import Path

from acs.clock_service import ChessClock, ClockSnapshot, ClockState, TimeControl
from acs.engine_game_session import EngineGameSessionCoordinator
from acs.engine_play_service import (
    EngineGameConfig,
    EngineGameHandoff,
    EngineGameIntent,
    EnginePlayService,
)
from acs.engine_ports import EngineContractError
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from tests.test_engine_game_session import FakeMoveEngine
from tests.test_stage1_engine_play_ui import _LegalMoveEngine


class TakebackRestoreFailureQaTests(unittest.TestCase):
    def make_coordinator(self, provider):
        state = {"fen": "fen-w", "side": "w", "node": "node-0", "moves": []}

        def commit(move):
            state["moves"].append(move)
            state["fen"] = "fen-b"
            state["side"] = "b"
            state["node"] = "node-1"

        def undo():
            state["moves"].pop()
            state["fen"] = "fen-w"
            state["side"] = "w"
            state["node"] = "node-0"

        engine = FakeMoveEngine("e2e4")
        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: engine),
            fen_provider=lambda: state["fen"],
            side_to_move_provider=lambda: state["side"],
            history_node_provider=lambda: state["node"],
            commit_engine_move=commit,
            undo_committed_move=undo,
            clock_restore_provider=provider,
            timeout_mating_capability_provider=lambda _side: True,
            clock_factory=lambda control: ChessClock(control, now=lambda: 100.0),
        )
        session.start(
            EngineGameConfig(
                level=6,
                engine_side="white",
                time_control=TimeControl(10_000, 0),
            )
        )
        selected = session.request_engine_move()
        self.assertEqual(selected.move, "e2e4")
        self.assertEqual(state["moves"], ["e2e4"])
        session.handle_handoff(
            EngineGameHandoff(EngineGameIntent.REQUEST_TAKEBACK, actor="b")
        )
        return session, state

    @staticmethod
    def state_tuple(state):
        return (
            tuple(state["moves"]),
            state["fen"],
            state["side"],
            state["node"],
        )

    @staticmethod
    def valid_restore():
        return ClockSnapshot(10_000, 10_000, "w", ClockState.RUNNING)

    def test_success_control_restores_historical_clock_and_board(self):
        session, state = self.make_coordinator(self.valid_restore)
        accepted = session.handle_handoff(
            EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
        )
        self.assertEqual(self.state_tuple(state), ((), "fen-w", "w", "node-0"))
        self.assertEqual(accepted.clock.active, "w")
        self.assertEqual(accepted.clock.state, ClockState.RUNNING)
        self.assertIsNone(accepted.lifecycle.takeback_requested_by)

    @unittest.expectedFailure  # #1060: provider failure after canonical undo.
    def test_restore_provider_exception_must_not_leave_board_undone(self):
        def fail():
            raise RuntimeError("injected restored-ply lookup failure")

        session, state = self.make_coordinator(fail)
        before = self.state_tuple(state)
        with self.assertRaisesRegex(RuntimeError, "restored-ply lookup failure"):
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
            )
        self.assertEqual(self.state_tuple(state), before)

    @unittest.expectedFailure  # #1060: invalid historical snapshot after undo.
    def test_incompatible_provider_result_must_not_leave_board_undone(self):
        session, state = self.make_coordinator(lambda: "not a ClockSnapshot")
        before = self.state_tuple(state)
        with self.assertRaises(EngineContractError):
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
            )
        self.assertEqual(self.state_tuple(state), before)

    def make_stage1(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        engine = _LegalMoveEngine()
        api = Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(tmp.name) / "keymap.json",
            engine_play_service=EnginePlayService(lambda: engine),
        )
        self.addCleanup(api.close_analysis)
        started = api.start_engine_game("white", 6, 5, 0)
        self.assertTrue(started["ok"], started)
        played = api.make_move("e4")
        self.assertTrue(played["ok"], played)
        self.assertEqual(len(api.sans), 2)
        return api

    @staticmethod
    def stage1_state(api):
        return (
            api.board.fen(),
            tuple(api.sans),
            tuple(api.move_sides),
            api.review_history.export_tree(),
            tuple(api.redo_meta),
            tuple(api.board.redo_stack),
            tuple(api._engine_clock_history),
        )

    def test_success_control_stage1_normal_takeback(self):
        api = self.make_stage1()
        completed = api.engine_takeback()
        self.assertTrue(completed["ok"], completed)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.board.fen(), api.board.START)

    @unittest.expectedFailure  # #1060: active Stage1 loses Board/history on lookup error.
    def test_active_stage1_restore_failure_preserves_full_board_history(self):
        api = self.make_stage1()
        before = self.stage1_state(api)
        session = api._engine_session
        self.assertIsNotNone(session)

        def fail():
            raise RuntimeError("injected history lookup failure")

        session._clock_restore_provider = fail
        result = api.engine_takeback()
        self.assertFalse(result["ok"], result)
        self.assertEqual(self.stage1_state(api), before)

    @unittest.expectedFailure  # #1060: finished-game reset error after undo.
    def test_finished_stage1_reset_failure_preserves_full_board_history(self):
        api = self.make_stage1()
        resigned = api.resign_engine_game()
        self.assertTrue(resigned["ok"], resigned)
        before = self.stage1_state(api)
        session = api._engine_session
        self.assertIsNotNone(session)

        def fail_reset(**_kwargs):
            raise RuntimeError("injected reset failure after undo")

        session.reset = fail_reset
        result = api.engine_takeback()
        self.assertFalse(result["ok"], result)
        self.assertEqual(self.stage1_state(api), before)


if __name__ == "__main__":
    unittest.main()
