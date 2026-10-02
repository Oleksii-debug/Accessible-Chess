from __future__ import annotations

"""Real-clock cross-lineage acceptance on the isolated #1059 + #1021 QA tree.

These tests exercise the actual switch_after_move clock implementation and the
actual Stage1 Board/history/sound handoff. The QA tree is never a release
candidate and does not change either independent source owner.
"""

import tempfile
import unittest
from pathlib import Path

from acs.chesscore import Board
from acs.clock_service import ClockState
from acs.engine_play_service import EngineGameHandoff, EngineGameIntent, EnginePlayService
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from tests.test_stage1_engine_play_ui import _LegalMoveEngine, _RecordingGameSounds


class _TimedSamples:
    def __init__(self, *samples: float) -> None:
        self.samples = list(samples)

    def __call__(self) -> float:
        if not self.samples:
            raise AssertionError("unexpected monotonic time sample")
        return self.samples.pop(0)


class ClockEngineSerialAcceptanceTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        engine = _LegalMoveEngine()
        sounds = _RecordingGameSounds()
        api = Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json",
            engine_play_service=EnginePlayService(lambda: engine),
            game_sounds=sounds,
        )
        self.addCleanup(api.close_analysis)
        started = api.start_engine_game("white", 5, 1, 2)
        self.assertTrue(started["ok"], started)
        session = api._engine_session
        self.assertIsNotNone(session)
        clock = session._clock
        self.assertIsNotNone(clock)
        anchor = clock._last_tick
        self.assertIsNotNone(anchor)
        clock._now = lambda: clock._last_tick if clock._last_tick is not None else anchor
        return api, engine, sounds, session, clock

    @staticmethod
    def inject_switch_samples(clock, actual_switch, side_to_inject, final):
        """Keep real switch implementation; replace only its three clock reads."""
        used = False

        def call(side):
            nonlocal used
            if side != side_to_inject or used:
                return actual_switch(side)
            used = True
            anchor = clock._last_tick
            clock._now = _TimedSamples(anchor, anchor + 0.05, final(anchor))
            try:
                return actual_switch(side)
            finally:
                # Leave the owner able to recover, inspect and retry after a
                # rejected operation. The faulty provider has been replaced.
                clock._now = lambda: clock._last_tick if clock._last_tick is not None else anchor + 0.052

        return call

    def test_human_final_sample_failure_rolls_back_real_board_and_increment(self):
        api, engine, sounds, session, clock = self.make_api()
        pending = session.handle_handoff(
            EngineGameHandoff(EngineGameIntent.OFFER_DRAW, actor="w")
        )
        self.assertEqual(pending.lifecycle.draw_offered_by, "w")
        before_tree = api.review_history.export_tree()
        actual_switch = clock.switch_after_move
        clock.switch_after_move = self.inject_switch_samples(
            clock, actual_switch, "w", lambda _anchor: float("nan")
        )

        failed = api.make_move("e4")

        self.assertFalse(failed["ok"], failed)
        self.assertEqual(failed["engineGame"]["phase"], "error")
        self.assertTrue(failed["engineGame"]["canRetry"])
        self.assertEqual(failed["historyLength"], 0)
        self.assertEqual(api.board.fen(), Board.START)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.review_history.export_tree(), before_tree)
        self.assertEqual(api.board.redo_stack, [])
        self.assertEqual(engine.calls, [])
        self.assertEqual(sounds.move_events, [])
        self.assertEqual(sounds.end_events, 0)
        after = session.snapshot()
        self.assertEqual(after.lifecycle.draw_offered_by, "w")
        self.assertEqual(after.clock.active, "w")
        # Stage1 deliberately pauses a recoverable clock in the error phase.
        self.assertEqual(after.clock.state, ClockState.PAUSED)
        self.assertGreaterEqual(after.clock.white_ms, 59_949)
        self.assertLess(after.clock.white_ms, 60_000)
        self.assertEqual(after.clock.black_ms, 60_000)

        clock.switch_after_move = actual_switch
        retried = api.retry_engine_move()
        self.assertTrue(retried["ok"], retried)
        self.assertEqual(retried["engineGame"]["phase"], "active")
        self.assertEqual(session.snapshot().lifecycle.draw_offered_by, "w")

    def test_engine_final_sample_failure_keeps_only_accepted_human_move(self):
        api, engine, sounds, session, clock = self.make_api()
        actual_switch = clock.switch_after_move
        clock.switch_after_move = self.inject_switch_samples(
            clock, actual_switch, "b", lambda _anchor: float("nan")
        )

        reply = api.make_move("e4")

        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["engineGame"]["phase"], "error")
        self.assertTrue(reply["engineGame"]["canRetry"])
        self.assertEqual(reply["historyLength"], 1)
        self.assertEqual(api.sans, ["e4"])
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(len(sounds.move_events), 1)
        self.assertEqual(sounds.end_events, 0)
        after = session.snapshot()
        self.assertEqual(after.clock.active, "b")
        # Stage1 deliberately pauses a recoverable clock in the error phase.
        self.assertEqual(after.clock.state, ClockState.PAUSED)
        self.assertGreaterEqual(after.clock.black_ms, 59_949)
        self.assertLess(after.clock.black_ms, 60_000)
        self.assertEqual(after.clock.white_ms, 62_000)

        clock.switch_after_move = actual_switch
        retried = api.retry_engine_move()
        self.assertTrue(retried["ok"], retried)
        self.assertEqual(retried["historyLength"], 2)
        self.assertEqual(retried["engineGame"]["phase"], "active")
        self.assertEqual(api.board.turn, "w")
        self.assertEqual(len(engine.calls), 2)
        self.assertEqual(len(sounds.move_events), 2)

    def test_real_final_sample_next_player_flag_preserves_accepted_human_move(self):
        api, engine, sounds, session, clock = self.make_api()
        clock.set_remaining("b", 1)
        actual_switch = clock.switch_after_move
        clock.switch_after_move = self.inject_switch_samples(
            clock, actual_switch, "w", lambda anchor: anchor + 0.052
        )

        played = api.make_move("e4")

        self.assertTrue(played["ok"], played)
        self.assertEqual(played["historyLength"], 1)
        self.assertEqual(api.sans, ["e4"])
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(engine.calls, [])
        self.assertEqual(len(sounds.move_events), 1)
        self.assertEqual(sounds.end_events, 1)
        self.assertEqual(played["engineGame"]["phase"], "finished")
        self.assertEqual(session.snapshot().clock.flagged, "b")
        self.assertEqual(session.snapshot().lifecycle.outcome.result, "1-0")


if __name__ == "__main__":
    unittest.main()
