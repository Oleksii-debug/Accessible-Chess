from __future__ import annotations

"""Strict #1060 takeback compensation acceptance on the integration successor.

All seven formerly reproduced recovery failures are ordinary tests here.
No synthetic chess history or clock snapshot is introduced.
"""

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from acs.clock_service import ChessClock, ClockError, ClockSnapshot, ClockState, TimeControl
from acs.engine_game_session import EngineGameSessionCoordinator, TakebackTransaction
from acs.engine_play_service import (
    EngineGameConfig,
    EngineGameHandoff,
    EngineGameIntent,
    EnginePlayService,
)
from acs.engine_ports import EngineContractError
from acs import stage1_release_ui_core as _stage1_core
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

        def prepare_takeback():
            prior = {
                "moves": list(state["moves"]), "fen": state["fen"],
                "side": state["side"], "node": state["node"],
            }
            def rollback():
                state["moves"][:] = prior["moves"]
                state["fen"] = prior["fen"]
                state["side"] = prior["side"]
                state["node"] = prior["node"]
            return TakebackTransaction(undo, rollback, lambda: None)

        engine = FakeMoveEngine("e2e4")
        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: engine),
            fen_provider=lambda: state["fen"],
            side_to_move_provider=lambda: state["side"],
            history_node_provider=lambda: state["node"],
            commit_engine_move=commit,
            undo_committed_move=undo,
            clock_restore_provider=provider,
            takeback_transaction=prepare_takeback,
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

    def test_incompatible_provider_result_must_not_leave_board_undone(self):
        session, state = self.make_coordinator(lambda: "not a ClockSnapshot")
        before = self.state_tuple(state)
        with self.assertRaises(EngineContractError):
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
            )
        self.assertEqual(self.state_tuple(state), before)

    def test_resume_time_source_failure_must_not_leave_board_undone(self):
        session, state = self.make_coordinator(self.valid_restore)
        before = self.state_tuple(state)
        samples = iter((100.0, 100.0, float("nan")))
        session._clock._now = lambda: next(samples)
        with self.assertRaises(ClockError):
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
            )
        self.assertEqual(self.state_tuple(state), before)

    def test_wrong_side_historical_clock_must_not_accept_takeback(self):
        session, state = self.make_coordinator(
            lambda: ClockSnapshot(10_000, 10_000, "b", ClockState.RUNNING)
        )
        before_board = self.state_tuple(state)
        before_lifecycle = session._lifecycle.snapshot()
        before_clock = session._clock.snapshot()
        with self.assertRaises(EngineContractError):
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
            )
        # The provider supplied a structurally valid clock, but it belongs
        # to the wrong post-undo side. The attempted command must not silently
        # publish Board, lifecycle or clock mutations before rejecting it.
        self.assertEqual(self.state_tuple(state), before_board)
        self.assertEqual(session._lifecycle.snapshot(), before_lifecycle)
        self.assertEqual(session._clock.snapshot(), before_clock)

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
            tuple(api.board.undo_stack),
            tuple(api.board.redo_stack),
            api.board.last_move,
            tuple(api.sans),
            tuple(api.move_sides),
            api.review_history.export_tree(),
            api.review_history.cursor_node_id,
            api.selected_source,
            tuple(api.redo_meta),
            tuple(api._engine_clock_history),
        )

    def test_success_control_stage1_normal_takeback(self):
        api = self.make_stage1()
        completed = api.engine_takeback()
        self.assertTrue(completed["ok"], completed)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.board.fen(), api.board.START)

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


    def test_second_undo_failure_must_not_publish_partial_takeback(self):
        api = self.make_stage1()
        before = self.stage1_state(api)
        base = _stage1_core.Stage1ReleaseAccessibleChessAPI.__mro__[1]
        original_undo = base.undo
        calls = 0

        def fail_second_undo(instance):
            nonlocal calls
            calls += 1
            if calls == 2:
                return {"ok": False, "announcement": "injected second undo failure"}
            return original_undo(instance)

        with patch.object(base, "undo", fail_second_undo):
            result = api.engine_takeback()
        self.assertEqual(calls, 2)
        self.assertFalse(result["ok"], result)
        self.assertEqual(self.stage1_state(api), before)




    def test_retry_after_failed_history_provider_preserves_original_request(self):
        calls = 0

        def provider():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary historical clock read failure")
            return self.valid_restore()

        session, state = self.make_coordinator(provider)
        before = self.state_tuple(state)
        before_clock = session._clock.snapshot()
        before_lifecycle = session._lifecycle.snapshot()
        accept = EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
        with self.assertRaisesRegex(RuntimeError, "temporary historical clock"):
            session.handle_handoff(accept)
        self.assertEqual(self.state_tuple(state), before)
        self.assertEqual(session._clock.snapshot(), before_clock)
        self.assertEqual(session._lifecycle.snapshot(), before_lifecycle)
        self.assertEqual(session._lifecycle.snapshot().takeback_requested_by, "b")
        restored = session.handle_handoff(accept)
        self.assertEqual(calls, 2)
        self.assertEqual(self.state_tuple(state), ((), "fen-w", "w", "node-0"))
        self.assertIsNone(restored.lifecycle.takeback_requested_by)
        self.assertEqual(restored.clock.active, "w")

    def test_historical_provider_without_compensation_fails_before_undo(self):
        session, state = self.make_coordinator(self.valid_restore)
        previous_factory = session._takeback_transaction
        session._takeback_transaction = None
        before = self.state_tuple(state)
        lifecycle_before = session._lifecycle.snapshot()
        with self.assertRaises(EngineContractError):
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
            )
        self.assertEqual(self.state_tuple(state), before)
        self.assertEqual(session._lifecycle.snapshot(), lifecycle_before)
        session._takeback_transaction = previous_factory
        accepted = session.handle_handoff(
            EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
        )
        self.assertIsNone(accepted.lifecycle.takeback_requested_by)

    def test_failure_after_clock_and_lifecycle_publication_compensates(self):
        session, state = self.make_coordinator(self.valid_restore)
        before = self.state_tuple(state)
        clock_before = session._clock.snapshot()
        lifecycle_before = session._lifecycle.snapshot()
        original_snapshot = session.snapshot
        calls = 0

        def fail_once():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("injected final snapshot failure")
            return original_snapshot()

        session.snapshot = fail_once
        accept = EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
        with self.assertRaisesRegex(RuntimeError, "final snapshot failure"):
            session.handle_handoff(accept)
        self.assertEqual(self.state_tuple(state), before)
        self.assertEqual(session._clock.snapshot(), clock_before)
        self.assertEqual(session._lifecycle.snapshot(), lifecycle_before)
        accepted = session.handle_handoff(accept)
        self.assertEqual(accepted.side_to_move, "w")

    def test_successful_takeback_rejects_duplicate_acceptance(self):
        session, state = self.make_coordinator(self.valid_restore)
        accept = EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
        session.handle_handoff(accept)
        final_state = self.state_tuple(state)
        with self.assertRaises(Exception):
            session.handle_handoff(accept)
        self.assertEqual(self.state_tuple(state), final_state)

    def test_stage1_failed_lookup_then_retry_preserves_san_and_clock_history(self):
        api = self.make_stage1()
        before = self.stage1_state(api)
        session = api._engine_session
        self.assertIsNotNone(session)
        original_provider = session._clock_restore_provider
        calls = 0

        def once():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary Stage1 history failure")
            return original_provider()

        session._clock_restore_provider = once
        failed = api.engine_takeback()
        self.assertFalse(failed["ok"], failed)
        self.assertEqual(self.stage1_state(api), before)
        self.assertEqual(
            session._lifecycle.snapshot().takeback_requested_by,
            api._engine_human_side(),
        )
        retried = api.engine_takeback()
        self.assertTrue(retried["ok"], retried)
        self.assertEqual(calls, 2)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.board.fen(), api.board.START)
        self.assertEqual(len(api._engine_clock_history), 1)
        self.assertIsNone(session._lifecycle.snapshot().takeback_requested_by)


    def test_commit_failure_after_valid_restore_rewinds_all_three_owners(self):
        session, state = self.make_coordinator(self.valid_restore)
        board_before = self.state_tuple(state)
        clock_before = session._clock.snapshot()
        lifecycle_before = session._lifecycle.snapshot()
        original_factory = session._takeback_transaction
        attempts = 0

        def prepare():
            token = original_factory()
            def commit():
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("injected takeback commit failure")
                token.commit()
            return TakebackTransaction(token.undo, token.rollback, commit)

        session._takeback_transaction = prepare
        accept = EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
        with self.assertRaisesRegex(RuntimeError, "commit failure"):
            session.handle_handoff(accept)
        self.assertEqual(self.state_tuple(state), board_before)
        self.assertEqual(session._clock.snapshot(), clock_before)
        self.assertEqual(session._lifecycle.snapshot(), lifecycle_before)
        taken_back = session.handle_handoff(accept)
        self.assertEqual(attempts, 2)
        self.assertIsNone(taken_back.lifecycle.takeback_requested_by)

    def test_invalid_transaction_factory_fails_before_irreversible_undo(self):
        session, state = self.make_coordinator(self.valid_restore)
        original = session._takeback_transaction
        board_before = self.state_tuple(state)
        pending_before = session._lifecycle.snapshot()
        session._takeback_transaction = lambda: object()
        accept = EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
        with self.assertRaises(EngineContractError):
            session.handle_handoff(accept)
        self.assertEqual(self.state_tuple(state), board_before)
        self.assertEqual(session._lifecycle.snapshot(), pending_before)
        session._takeback_transaction = original
        self.assertEqual(session.handle_handoff(accept).side_to_move, "w")

    def test_rollback_failure_is_explicit_and_does_not_clear_lifecycle_request(self):
        session, state = self.make_coordinator(self.valid_restore)
        original = session._takeback_transaction
        pending_before = session._lifecycle.snapshot()
        clock_before = session._clock.snapshot()
        def prepare():
            token = original()
            def invalid_rollback():
                raise RuntimeError("injected rollback failure")
            return TakebackTransaction(token.undo, invalid_rollback, token.commit)
        session._takeback_transaction = prepare
        def fail_provider():
            raise RuntimeError("injected provider failure")
        session._clock_restore_provider = fail_provider
        with self.assertRaises(EngineContractError) as raised:
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="w")
            )
        self.assertIn("compensation failed", str(raised.exception))
        self.assertEqual(session._lifecycle.snapshot(), pending_before)
        self.assertEqual(session._clock.snapshot(), clock_before)
        # The callback explicitly refused compensation: never assert that
        # Board/history is safe or claim the failed takeback succeeded.
        self.assertNotEqual(self.state_tuple(state)[0], ("e2e4",))

    def test_unrecoverable_active_takeback_disables_all_moves_and_retries(self):
        api = self.make_stage1()
        session = api._engine_session
        original_factory = session._takeback_transaction

        def unsafe_transaction():
            original = original_factory()
            def failed_rollback():
                raise RuntimeError("injected Board compensation failure")
            return TakebackTransaction(original.undo, failed_rollback, original.commit)

        session._takeback_transaction = unsafe_transaction
        def failed_provider():
            raise RuntimeError("injected post-undo clock lookup failure")
        session._clock_restore_provider = failed_provider
        rejected = api.engine_takeback()
        self.assertFalse(rejected["ok"], rejected)
        self.assertTrue(api._engine_takeback_unsafe)
        projection = api._engine_game_projection()
        self.assertFalse(projection["canRetry"], projection)
        self.assertFalse(projection["canTakeback"], projection)
        self.assertTrue(projection["canStop"], projection)
        self.assertEqual(projection["status"], api._engine_game_error)

        unsafe_board = api.board.fen()
        unsafe_history = api.review_history.export_tree()
        for rejected_action in (
            lambda: api.retry_engine_move(),
            lambda: api.engine_takeback(),
            lambda: api.make_move("e4"),
            lambda: api.undo(),
            lambda: api.redo(),
            lambda: api.activate_square("e2"),
            lambda: api.set_turn("b"),
            lambda: api.set_fen(api.board.START),
            lambda: api.set_position_text("reset position"),
            lambda: api.insert_analysis_move(),
            lambda: api.insert_analysis_line(),
        ):
            result = rejected_action()
            self.assertFalse(result["ok"], result)
            self.assertEqual(result.get("announcement"), api._takeback_recovery_message())
            self.assertEqual(api.board.fen(), unsafe_board)
            self.assertEqual(api.review_history.export_tree(), unsafe_history)

        self.assertTrue(api.stop_engine_game()["ok"])
        with patch.object(api, "_temporary_exploration_error", return_value={
            "ok": False, "announcement": "finish exploration before reset",
        }):
            self.assertFalse(api.new_game()["ok"])
            self.assertFalse(api.clear_board()["ok"])
            self.assertTrue(api._engine_takeback_unsafe)
        self.assertFalse(api.make_move("e4")["ok"])
        self.assertTrue(api._engine_takeback_unsafe)
        self.assertTrue(api.new_game()["ok"])
        self.assertFalse(api._engine_takeback_unsafe)
        self.assertTrue(api.make_move("e4")["ok"])

    def test_unrecoverable_finished_reset_keeps_safe_lock_and_stop(self):
        api = self.make_stage1()
        self.assertTrue(api.resign_engine_game()["ok"])
        session = api._engine_session
        with patch.object(session, "reset", side_effect=RuntimeError("reset failed after undo")):
            with patch.object(
                api, "_restore_engine_takeback_state",
                side_effect=RuntimeError("Board recovery refused"),
            ):
                rejected = api.engine_takeback()

        self.assertFalse(rejected["ok"], rejected)
        self.assertTrue(api._engine_takeback_unsafe)
        projection = api._engine_game_projection()
        self.assertFalse(projection["canRetry"], projection)
        self.assertFalse(projection["canTakeback"], projection)
        self.assertTrue(projection["canStop"], projection)
        self.assertFalse(api.engine_takeback()["ok"])
        self.assertTrue(api.stop_engine_game()["ok"])
        self.assertTrue(api.new_game()["ok"])
        self.assertFalse(api._engine_takeback_unsafe)

    def test_stage1_second_undo_failure_then_clean_retry(self):
        api = self.make_stage1()
        original = self.stage1_state(api)
        base = _stage1_core.Stage1ReleaseAccessibleChessAPI.__mro__[1]
        original_undo = base.undo
        calls = 0
        def fail_once_on_second(instance):
            nonlocal calls
            calls += 1
            if calls == 2:
                return {"ok": False, "announcement": "temporary undo failure"}
            return original_undo(instance)
        with patch.object(base, "undo", fail_once_on_second):
            failure = api.engine_takeback()
        self.assertFalse(failure["ok"], failure)
        self.assertEqual(self.stage1_state(api), original)
        recovered = api.engine_takeback()
        self.assertTrue(recovered["ok"], recovered)
        self.assertEqual(api.board.fen(), api.board.START)
        self.assertEqual(api.sans, [])


    def test_failed_stage1_takeback_has_no_success_sound_before_retry(self):
        api = self.make_stage1()
        class Sounds:
            resumed = 0
            def resume_after_takeback(self):
                self.resumed += 1
            def move(self, *_args):
                pass
            def end(self):
                pass
            def illegal(self):
                pass
        sounds = Sounds()
        api._game_sounds = sounds
        session = api._engine_session
        original_provider = session._clock_restore_provider
        def unavailable():
            raise RuntimeError("injected clock history outage")
        session._clock_restore_provider = unavailable
        failure = api.engine_takeback()
        self.assertFalse(failure["ok"], failure)
        self.assertEqual(sounds.resumed, 0)
        self.assertNotIn("Ходи повернено", failure["announcement"])
        session._clock_restore_provider = original_provider
        accepted = api.engine_takeback()
        self.assertTrue(accepted["ok"], accepted)
        self.assertEqual(sounds.resumed, 1)


    def test_untimed_legacy_undo_without_transaction_rejects_before_mutation(self):
        state = {"undos": 0}
        def undo():
            state["undos"] += 1
        session = EngineGameSessionCoordinator(
            EnginePlayService(lambda: FakeMoveEngine("e2e4")),
            fen_provider=lambda: "fen-w",
            side_to_move_provider=lambda: "w",
            history_node_provider=lambda: "node-0",
            commit_engine_move=lambda _move: None,
            undo_committed_move=undo,
        )
        session.start(
            EngineGameConfig(
                engine_side="black",
                time_control=TimeControl(0, 0),
            )
        )
        session.handle_handoff(
            EngineGameHandoff(EngineGameIntent.REQUEST_TAKEBACK, actor="w")
        )
        pending = session._lifecycle.snapshot()
        with self.assertRaises(EngineContractError):
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.ACCEPT_TAKEBACK, actor="b")
            )
        self.assertEqual(state["undos"], 0)
        self.assertEqual(session._lifecycle.snapshot(), pending)


if __name__ == "__main__":
    unittest.main()
