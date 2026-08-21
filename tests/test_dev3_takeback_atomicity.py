import unittest

from acs.clock_service import ChessClock, ClockSnapshot, ClockState, TimeControl
from acs.engine_game_session import EngineGameSessionCoordinator
from acs.engine_play_service import EngineGameConfig, EngineGameHandoff, EngineGameIntent, EnginePlayService
from acs.engine_ports import EngineContractError, EngineContractErrorCode


class _MoveEngine:
    def best_move(self, fen, skill_level=10, movetime_ms=500):
        return "e2e4"

    def close(self):
        pass


class _Time:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class Dev3TakebackAtomicityTests(unittest.TestCase):
    def _session(self, *, undo, restore=None, control=TimeControl(10_000), now=None):
        state = {"side": "w", "fen": "fen-w", "node": "node-2"}
        clock_factory = None
        if now is not None:
            clock_factory = lambda configured: ChessClock(configured, now=now)
        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: _MoveEngine()),
            fen_provider=lambda: state["fen"],
            side_to_move_provider=lambda: state["side"],
            commit_engine_move=lambda move: None,
            history_node_provider=lambda: state["node"],
            undo_committed_move=undo,
            clock_restore_provider=restore,
            clock_factory=clock_factory,
        )
        session.start(EngineGameConfig(engine_side="black", time_control=control))
        session.handle_handoff(
            EngineGameHandoff(EngineGameIntent.REQUEST_TAKEBACK, actor="w")
        )
        return session, state

    def test_undo_failure_preserves_pending_takeback_and_clock(self):
        attempts = []
        now = _Time()

        def failing_undo():
            attempts.append("undo")
            raise RuntimeError("canonical undo failed")

        session, state = self._session(undo=failing_undo, now=now)
        before = session.snapshot()

        with self.assertRaisesRegex(RuntimeError, "canonical undo failed"):
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="b")
            )

        after = session.snapshot()
        self.assertEqual(attempts, ["undo"])
        self.assertEqual(after.lifecycle.takeback_requested_by, "w")
        self.assertEqual(after.clock, before.clock)
        self.assertEqual(state["side"], "w")
        self.assertEqual(state["fen"], "fen-w")
        self.assertEqual(state["node"], "node-2")

    def test_invalid_clock_provider_cannot_clear_lifecycle_or_mutate_clock(self):
        undo_calls = []
        session, _state = self._session(
            undo=lambda: undo_calls.append("undo"),
            restore=lambda: object(),
        )
        before = session.snapshot()

        with self.assertRaises(EngineContractError) as caught:
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="b")
            )

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)
        after = session.snapshot()
        self.assertEqual(undo_calls, ["undo"])
        self.assertEqual(after.lifecycle.takeback_requested_by, "w")
        self.assertEqual(after.clock, before.clock)

    def test_incompatible_post_undo_clock_snapshot_fails_closed_for_session_state(self):
        undo_calls = []
        incompatible = ClockSnapshot(1_000, 1_000, "w", ClockState.RUNNING)
        session, _state = self._session(
            undo=lambda: undo_calls.append("undo"),
            restore=lambda: incompatible,
            control=TimeControl(0),
        )
        before = session.snapshot()

        with self.assertRaises(EngineContractError) as caught:
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="b")
            )

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)
        self.assertEqual(undo_calls, ["undo"])
        after = session.snapshot()
        self.assertEqual(after.lifecycle.takeback_requested_by, "w")
        self.assertEqual(after.clock, before.clock)

    def test_historical_clock_provider_observes_restored_canonical_ply(self):
        state_ref = {}
        order = []
        restored = ClockSnapshot(8_250, 9_500, "w", ClockState.RUNNING)

        def undo():
            state = state_ref["state"]
            order.append("undo")
            state["side"] = "w"
            state["fen"] = "fen-restored"
            state["node"] = "node-0"

        def restore():
            state = state_ref["state"]
            order.append(f"restore:{state['fen']}:{state['node']}")
            return restored

        session, state = self._session(undo=undo, restore=restore)
        state_ref["state"] = state
        after = session.handle_handoff(
            EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="b")
        )

        self.assertEqual(order, ["undo", "restore:fen-restored:node-0"])
        self.assertIsNone(after.lifecycle.takeback_requested_by)
        self.assertEqual(after.clock.white_ms, 8_250)
        self.assertEqual(after.clock.black_ms, 9_500)
        self.assertEqual(after.clock.active, "w")
        self.assertEqual(after.clock.state, ClockState.RUNNING)
        self.assertEqual(state["fen"], "fen-restored")
        self.assertEqual(state["node"], "node-0")


if __name__ == "__main__":
    unittest.main()
