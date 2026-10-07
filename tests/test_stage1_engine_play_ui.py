from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.chesscore import Board, sq_name
from acs.clock_service import ClockSnapshot, ClockState
from acs.engine_play_service import (
    EngineGameHandoff,
    EngineGameIntent,
    EnginePlayService,
)
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


class _LegalMoveEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.failures_remaining = 0
        self.closed = False

    def best_move(
        self,
        fen: str,
        skill_level: int = 10,
        movetime_ms: int = 500,
    ) -> str | None:
        self.calls.append((fen, skill_level, movetime_ms))
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError(r"C:\private\stockfish crashed")
        board = Board(fen)
        legal = board.legal_moves()
        if not legal:
            return None
        move = legal[0]
        promotion = (move.promotion or "").lower()
        return f"{sq_name(move.frm)}{sq_name(move.to)}{promotion}"

    def close(self) -> None:
        self.closed = True


class _RecordingGameSounds:
    def __init__(self) -> None:
        self.move_events = []
        self.end_events = 0
        self.mate_events = 0
        self.draw_events = 0

    def start(self) -> None:
        pass

    def move(self, facts) -> None:
        self.move_events.append(facts)

    def checkmate(self) -> None:
        self.mate_events += 1

    def draw(self) -> None:
        self.draw_events += 1

    def low_time(self) -> None:
        pass

    def end(self) -> None:
        self.end_events += 1

    def illegal(self) -> None:
        pass


class _FakeTime:
    def __init__(self, value: float) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


class Stage1EnginePlayUiTests(unittest.TestCase):
    def make_api(
        self,
        engine: _LegalMoveEngine | None = None,
        *,
        game_sounds=None,
    ):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        selected = engine or _LegalMoveEngine()
        service = EnginePlayService(lambda: selected)
        api = Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json",
            engine_play_service=service,
            game_sounds=game_sounds,
        )
        self.addCleanup(api.close_analysis)
        return api, selected

    def test_position_piece_edit_commits_then_ends_active_engine_game(self) -> None:
        api, _engine = self.make_api()
        self.assertTrue(api.start_engine_game("white", 4, 0, 0)["ok"])
        self.assertIsNotNone(api._engine_session)

        edited = api.edit_position_piece("a3", "N")

        self.assertTrue(edited["ok"])
        self.assertEqual(api.board.board[16], "N")
        self.assertIsNone(api._engine_session)
        self.assertEqual(api._engine_game_phase, "idle")
        self.assertFalse(edited["engineGame"]["active"])

    def test_failed_clear_board_preserves_active_engine_game_and_board(self) -> None:
        api, _engine = self.make_api()
        self.assertTrue(api.start_engine_game("white", 4, 0, 0)["ok"])
        prior_session = api._engine_session
        prior_phase = api._engine_game_phase
        prior_fen = api.board.fen()
        original = api._prepare_root_state

        def fail(*_args, **_kwargs):
            raise RuntimeError("simulated clear-root failure")

        api._prepare_root_state = fail
        try:
            result = api.clear_board()
        finally:
            api._prepare_root_state = original

        self.assertFalse(result["ok"])
        self.assertIs(api._engine_session, prior_session)
        self.assertEqual(api._engine_game_phase, prior_phase)
        self.assertEqual(api.board.fen(), prior_fen)

    def test_failed_engine_game_restart_preserves_existing_session_lifecycle(self) -> None:
        api, _engine = self.make_api()
        started = api.start_engine_game("white", 4, 0, 0)
        self.assertTrue(started["ok"])
        prior_session = api._engine_session
        prior_phase = api._engine_game_phase
        prior_fen = api.board.fen()
        original = api._prepare_root_state

        def fail(*_args, **_kwargs):
            raise RuntimeError("simulated replacement-root failure")

        api._prepare_root_state = fail
        try:
            result = api.start_engine_game("black", 6, 0, 0)
        finally:
            api._prepare_root_state = original

        self.assertFalse(result["ok"])
        self.assertIs(api._engine_session, prior_session)
        self.assertEqual(api._engine_game_phase, prior_phase)
        self.assertEqual(api.board.fen(), prior_fen)

    def test_engine_game_start_aborts_if_standard_position_reset_cannot_publish(self) -> None:
        api, engine = self.make_api()
        self.assertTrue(api.make_move("e4")["ok"])
        before_fen = api.board.fen()
        before_tree = api.review_history.export_tree()
        original = api._prepare_root_state

        def fail(*_args, **_kwargs):
            raise RuntimeError("simulated root publication failure")

        api._prepare_root_state = fail
        try:
            result = api.start_engine_game("white", 4, 0, 0)
        finally:
            api._prepare_root_state = original

        self.assertFalse(result["ok"])
        self.assertIn("стандартну позицію", result["announcement"])
        self.assertEqual(api.board.fen(), before_fen)
        self.assertEqual(api.review_history.export_tree(), before_tree)
        self.assertIsNone(api._engine_session)
        self.assertEqual(api._engine_game_phase, "idle")
        self.assertEqual(engine.calls, [])

    def test_engine_reply_history_failure_is_atomic_and_pauses_session(self) -> None:
        api, engine = self.make_api()
        standard_fen = api.board.fen()
        standard_tree = api.review_history.export_tree()
        original = api._prepare_live_presentation

        def fail(*_args, **_kwargs):
            raise RuntimeError("simulated engine history failure")

        api._prepare_live_presentation = fail
        try:
            result = api.start_engine_game("black", 4, 0, 0)
        finally:
            api._prepare_live_presentation = original

        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), standard_fen)
        self.assertEqual(api.review_history.export_tree(), standard_tree)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.move_sides, [])
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(api._engine_game_phase, "error")

    def test_human_white_move_gets_one_legal_engine_reply(self) -> None:
        api, engine = self.make_api()

        started = api.start_engine_game("white", 4, 0, 0)
        self.assertTrue(started["ok"], started)
        self.assertEqual(started["engineGame"]["humanSide"], "w")
        self.assertEqual(started["engineGame"]["engineSide"], "b")
        self.assertEqual(started["engineGame"]["turn"], "human")
        self.assertEqual(started["historyLength"], 0)
        self.assertEqual(engine.calls, [])

        played = api.make_move("e4")

        self.assertTrue(played["ok"], played)
        self.assertEqual(played["historyLength"], 2)
        self.assertEqual(api.board.turn, "w")
        self.assertEqual(played["engineGame"]["turn"], "human")
        self.assertEqual(len(engine.calls), 1)
        expected_after_e4 = Board()
        expected_after_e4.push_text("e4")
        self.assertEqual(engine.calls[0][0], expected_after_e4.fen())
        self.assertEqual(engine.calls[0][1:], (6, 325))
        self.assertIn("Stockfish зіграв", played["announcement"])

    def test_timed_text_move_expiring_after_preflight_is_rolled_back(self) -> None:
        sounds = _RecordingGameSounds()
        api, engine = self.make_api(game_sounds=sounds)
        started = api.start_engine_game("white", 5, 1, 0)
        self.assertTrue(started["ok"], started)
        session = api._engine_session
        self.assertIsNotNone(session)
        clock = session._clock
        self.assertIsNotNone(clock)
        now = _FakeTime(clock._last_tick)
        clock._now = now
        clock.set_remaining("w", 1)
        before_tree = api.review_history.export_tree()
        original_guard = api._human_engine_move_guard

        def race_guard():
            result = original_guard()
            if result is None:
                now.advance(0.002)
            return result

        api._human_engine_move_guard = race_guard
        expired = api.make_move("e4")

        self.assertFalse(expired["ok"], expired)
        self.assertIn("Час вичерпано", expired["announcement"])
        self.assertEqual(expired["historyLength"], 0)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.board.turn, "w")
        self.assertEqual(api.review_history.export_tree(), before_tree)
        self.assertEqual(api.board.redo_stack, [])
        self.assertEqual(engine.calls, [])
        self.assertEqual(sounds.move_events, [])
        self.assertEqual(sounds.end_events, 1)
        api.get_state()
        api.get_state()
        self.assertEqual(sounds.end_events, 1)
        self.assertEqual(len(api._engine_clock_history), 1)
        self.assertEqual(api._engine_clock_history[0].flagged, "w")
        self.assertEqual(expired["engineGame"]["phase"], "finished")

    def test_timed_board_move_expiring_after_preflight_is_rolled_back(self) -> None:
        api, engine = self.make_api()
        started = api.start_engine_game("white", 5, 1, 0)
        self.assertTrue(started["ok"], started)
        session = api._engine_session
        self.assertIsNotNone(session)
        clock = session._clock
        self.assertIsNotNone(clock)
        now = _FakeTime(clock._last_tick)
        clock._now = now
        clock.set_remaining("w", 1)
        before_tree = api.review_history.export_tree()
        original_guard = api._human_engine_move_guard
        guard_calls = 0

        def race_guard():
            nonlocal guard_calls
            result = original_guard()
            guard_calls += 1
            if result is None and guard_calls == 2:
                now.advance(0.002)
            return result

        api._human_engine_move_guard = race_guard
        selected = api.activate_square("e2")
        self.assertTrue(selected["ok"], selected)
        expired = api.activate_square("e4")

        self.assertFalse(expired["ok"], expired)
        self.assertIn("Час вичерпано", expired["announcement"])
        self.assertEqual(expired["historyLength"], 0)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.board.turn, "w")
        self.assertEqual(api.review_history.export_tree(), before_tree)
        self.assertEqual(api.board.redo_stack, [])
        self.assertIsNone(api.selected_source)
        self.assertEqual(engine.calls, [])
        self.assertEqual(expired["engineGame"]["phase"], "finished")

    def test_human_clock_acceptance_exception_rolls_back_without_move_sound(self) -> None:
        sounds = _RecordingGameSounds()
        api, engine = self.make_api(game_sounds=sounds)
        started = api.start_engine_game("white", 5, 5, 0)
        self.assertTrue(started["ok"], started)
        session = api._engine_session
        self.assertIsNotNone(session)
        clock = session._clock
        self.assertIsNotNone(clock)
        pending = session.handle_handoff(
            EngineGameHandoff(EngineGameIntent.OFFER_DRAW, actor="w")
        )
        self.assertEqual(pending.lifecycle.draw_offered_by, "w")
        before_tree = api.review_history.export_tree()

        def fail_switch(_side):
            raise RuntimeError("clock acceptance failed")

        clock.switch_after_move = fail_switch
        failed = api.make_move("e4")

        self.assertFalse(failed["ok"], failed)
        self.assertIn("Хід скасовано", failed["announcement"])
        self.assertEqual(failed["historyLength"], 0)
        self.assertEqual(api.board.fen(), Board.START)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.move_sides, [])
        self.assertEqual(api.review_history.export_tree(), before_tree)
        self.assertEqual(api.board.redo_stack, [])
        self.assertEqual(engine.calls, [])
        self.assertEqual(sounds.move_events, [])
        self.assertEqual(sounds.end_events, 0)
        self.assertEqual(failed["engineGame"]["phase"], "error")
        self.assertTrue(failed["engineGame"]["canStop"])
        self.assertTrue(failed["engineGame"]["canRetry"])
        self.assertEqual(session.snapshot().lifecycle.draw_offered_by, "w")

        retried = api.retry_engine_move()
        self.assertTrue(retried["ok"], retried)
        self.assertEqual(retried["engineGame"]["phase"], "active")
        self.assertEqual(retried["engineGame"]["turn"], "human")
        self.assertEqual(engine.calls, [])
        self.assertEqual(session.snapshot().lifecycle.draw_offered_by, "w")

    def test_engine_move_expiring_during_clock_switch_is_rolled_back(self) -> None:
        sounds = _RecordingGameSounds()
        api, engine = self.make_api(game_sounds=sounds)
        started = api.start_engine_game("white", 5, 1, 0)
        self.assertTrue(started["ok"], started)
        session = api._engine_session
        self.assertIsNotNone(session)
        clock = session._clock
        self.assertIsNotNone(clock)
        now = _FakeTime(clock._last_tick)
        clock._now = now
        clock.set_remaining("b", 1)
        original_switch = clock.switch_after_move

        def expire_engine_on_switch(side):
            if side == "b":
                now.advance(0.002)
            return original_switch(side)

        clock.switch_after_move = expire_engine_on_switch
        played = api.make_move("e4")

        self.assertTrue(played["ok"], played)
        self.assertIn("Час вичерпано", played["announcement"])
        self.assertEqual(played["historyLength"], 1)
        self.assertEqual(len(api.sans), 1)
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(api.board.redo_stack, [])
        self.assertIsNone(api.selected_source)
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(len(sounds.move_events), 1)
        self.assertEqual(sounds.end_events, 1)
        self.assertEqual(played["engineGame"]["phase"], "finished")
        self.assertEqual(len(api._engine_clock_history), 2)
        self.assertEqual(api._engine_clock_history[-1].flagged, "b")


    def test_accepted_human_move_survives_immediate_engine_flag(self) -> None:
        sounds = _RecordingGameSounds()
        api, engine = self.make_api(game_sounds=sounds)
        self.assertTrue(api.start_engine_game("white", 5, 1, 0)["ok"])
        session = api._engine_session
        clock = session._clock
        now = _FakeTime(clock._last_tick)
        clock._now = now
        clock.set_remaining("b", 1)
        original_switch = clock.switch_after_move

        def expire_next_player(side):
            switched = original_switch(side)
            if side == "w":
                now.advance(0.002)
                return clock.snapshot()
            return switched

        clock.switch_after_move = expire_next_player
        played = api.make_move("e4")

        self.assertTrue(played["ok"], played)
        self.assertEqual(played["historyLength"], 1)
        self.assertEqual(api.sans, ["e4"])
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(played["engineGame"]["phase"], "finished")
        self.assertEqual(session.snapshot().lifecycle.outcome.result, "1-0")
        self.assertEqual(engine.calls, [])
        self.assertEqual(len(sounds.move_events), 1)
        self.assertEqual(sounds.end_events, 1)
        self.assertEqual(api._engine_clock_history[-1].flagged, "b")

    def test_accepted_engine_move_survives_immediate_human_flag(self) -> None:
        sounds = _RecordingGameSounds()
        api, engine = self.make_api(game_sounds=sounds)
        self.assertTrue(api.start_engine_game("white", 5, 1, 0)["ok"])
        session = api._engine_session
        clock = session._clock
        now = _FakeTime(clock._last_tick)
        clock._now = now
        original_switch = clock.switch_after_move

        def expire_next_player(side):
            if side == "b":
                clock.set_remaining("w", 1)
            switched = original_switch(side)
            if side == "b":
                now.advance(0.002)
                return clock.snapshot()
            return switched

        clock.switch_after_move = expire_next_player
        played = api.make_move("e4")

        self.assertTrue(played["ok"], played)
        self.assertEqual(played["historyLength"], 2)
        self.assertEqual(len(api.sans), 2)
        self.assertEqual(api.board.turn, "w")
        self.assertEqual(played["engineGame"]["phase"], "finished")
        self.assertEqual(session.snapshot().lifecycle.outcome.result, "0-1")
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(len(sounds.move_events), 2)
        self.assertEqual(sounds.end_events, 1)
        self.assertEqual(api._engine_clock_history[-1].flagged, "w")

    def test_engine_timeout_while_thinking_finishes_without_error_phase(self) -> None:
        sounds = _RecordingGameSounds()
        api, engine = self.make_api(game_sounds=sounds)
        started = api.start_engine_game("white", 5, 1, 0)
        self.assertTrue(started["ok"], started)
        session = api._engine_session
        self.assertIsNotNone(session)
        clock = session._clock
        self.assertIsNotNone(clock)
        now = _FakeTime(clock._last_tick)
        clock._now = now
        clock.set_remaining("b", 1)
        original_best_move = engine.best_move

        def expire_while_thinking(fen, skill_level=10, movetime_ms=500):
            now.advance(0.002)
            return original_best_move(fen, skill_level, movetime_ms)

        engine.best_move = expire_while_thinking
        played = api.make_move("e4")

        self.assertTrue(played["ok"], played)
        self.assertIn("Час вичерпано", played["announcement"])
        self.assertEqual(played["historyLength"], 1)
        self.assertEqual(len(api.sans), 1)
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(len(sounds.move_events), 1)
        self.assertEqual(sounds.end_events, 1)
        self.assertEqual(played["engineGame"]["phase"], "finished")
        self.assertFalse(played["engineGame"]["canRetry"])
        self.assertEqual(len(api._engine_clock_history), 2)
        self.assertEqual(api._engine_clock_history[-1].flagged, "b")

    def test_human_black_receives_opening_engine_move_before_focus_handoff(self) -> None:
        api, engine = self.make_api()

        started = api.start_engine_game("black", 5, 0, 0)

        self.assertTrue(started["ok"], started)
        self.assertEqual(started["historyLength"], 1)
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(started["engineGame"]["humanSide"], "b")
        self.assertEqual(started["engineGame"]["turn"], "human")
        self.assertEqual(len(engine.calls), 1)
        self.assertIn("Ваш хід", started["announcement"])

    def test_timed_game_projects_canonical_clock_settings(self) -> None:
        api, _engine = self.make_api()

        started = api.start_engine_game("white", 6, 5, 3)

        self.assertTrue(started["ok"], started)
        game = started["engineGame"]
        self.assertEqual(game["initialMinutes"], 5)
        self.assertEqual(game["incrementSeconds"], 3)
        self.assertEqual(game["whiteClock"], "5:00")
        self.assertEqual(game["blackClock"], "5:00")
        self.assertEqual(game["clockStatus"], "Час: білі 5:00, чорні 5:00.")

    def test_clock_display_does_not_drop_a_second_for_partial_milliseconds(self) -> None:
        self.assertEqual(Stage1ReleaseAccessibleChessAPI._clock_text(300_000), "5:00")
        self.assertEqual(Stage1ReleaseAccessibleChessAPI._clock_text(299_999), "5:00")
        self.assertEqual(Stage1ReleaseAccessibleChessAPI._clock_text(299_000), "4:59")
        self.assertEqual(Stage1ReleaseAccessibleChessAPI._clock_text(0), "0:00")

    def test_engine_failure_preserves_human_move_and_retry_continues(self) -> None:
        engine = _LegalMoveEngine()
        engine.failures_remaining = 1
        api, _ = self.make_api(engine)
        api.start_engine_game("white", 5, 5, 0)

        failed_reply = api.make_move("e4")

        self.assertTrue(failed_reply["ok"], failed_reply)
        self.assertEqual(failed_reply["historyLength"], 1)
        self.assertEqual(api.board.turn, "b")
        self.assertEqual(failed_reply["engineGame"]["phase"], "error")
        self.assertTrue(failed_reply["engineGame"]["canRetry"])
        self.assertNotIn("RuntimeError", failed_reply["announcement"])
        self.assertNotIn("C:\\private", failed_reply["announcement"])

        retried = api.retry_engine_move()

        self.assertTrue(retried["ok"], retried)
        self.assertEqual(retried["historyLength"], 2)
        self.assertEqual(retried["engineGame"]["phase"], "active")
        self.assertEqual(retried["engineGame"]["turn"], "human")

    def test_paused_failure_can_be_stopped_and_manual_play_can_continue(self) -> None:
        engine = _LegalMoveEngine()
        engine.failures_remaining = 1
        api, _ = self.make_api(engine)
        api.start_engine_game("white", 5, 0, 0)
        failed_reply = api.make_move("e4")

        self.assertTrue(failed_reply["engineGame"]["canStop"])
        stopped = api.stop_engine_game()
        continued = api.make_move("e5")

        self.assertTrue(stopped["ok"], stopped)
        self.assertEqual(stopped["engineGame"]["phase"], "stopped")
        self.assertFalse(stopped["engineGame"]["canStop"])
        self.assertTrue(continued["ok"], continued)
        self.assertEqual(continued["mode"], "analysis")
        self.assertEqual(continued["historyLength"], 2)
        self.assertEqual(len(engine.calls), 1)

    def test_draw_offer_uses_lifecycle_and_stockfish_declines_concisely(self) -> None:
        api, engine = self.make_api()
        api.start_engine_game("white", 5, 0, 0)

        offered = api.offer_draw_engine_game()

        self.assertTrue(offered["ok"], offered)
        self.assertIn("відхилив", offered["announcement"])
        self.assertEqual(offered["engineGame"]["phase"], "active")
        self.assertTrue(offered["engineGame"]["canOfferDraw"])
        self.assertIsNone(api._engine_session.snapshot().lifecycle.draw_offered_by)
        self.assertEqual(engine.calls, [])

    def test_takeback_returns_to_human_turn_without_second_board(self) -> None:
        api, _engine = self.make_api()
        api.start_engine_game("white", 5, 0, 0)
        api.make_move("e4")

        taken_back = api.engine_takeback()

        self.assertTrue(taken_back["ok"], taken_back)
        self.assertEqual(taken_back["historyLength"], 0)
        self.assertEqual(api.board.fen(), Board.START)
        self.assertEqual(taken_back["engineGame"]["turn"], "human")
        self.assertIn("Ваш хід", taken_back["announcement"])

    def test_timed_takeback_restores_historical_clock_instead_of_resetting(self) -> None:
        api, _engine = self.make_api()
        api.start_engine_game("white", 5, 5, 3)
        api.make_move("e4")
        api._engine_clock_history[0] = ClockSnapshot(
            210_000,
            220_000,
            "w",
            ClockState.RUNNING,
        )

        taken_back = api.engine_takeback()

        self.assertTrue(taken_back["ok"], taken_back)
        self.assertEqual(taken_back["historyLength"], 0)
        self.assertEqual(taken_back["engineGame"]["whiteClock"], "3:30")
        self.assertEqual(taken_back["engineGame"]["blackClock"], "3:40")

    def test_resign_finishes_lifecycle_and_blocks_more_moves(self) -> None:
        api, _engine = self.make_api()
        api.start_engine_game("white", 5, 0, 0)

        resigned = api.resign_engine_game()
        blocked = api.make_move("e4")

        self.assertTrue(resigned["ok"], resigned)
        self.assertEqual(resigned["engineGame"]["phase"], "finished")
        self.assertIn("Stockfish переміг", resigned["engineGameStatus"])
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["historyLength"], 0)

    def test_engine_game_settings_reject_active_scalar_subclasses_without_hooks(self) -> None:
        api, engine = self.make_api()
        calls = []

        class ActiveText(str):
            def strip(self):
                calls.append("strip")
                raise AssertionError("active text hook must not run")

            def __str__(self):
                calls.append("str")
                raise AssertionError("active text hook must not run")

        for kwargs in (
            {"human_side": ActiveText("white"), "level": 5, "initial_minutes": 0, "increment_seconds": 0},
            {"human_side": "white", "level": ActiveText("5"), "initial_minutes": 0, "increment_seconds": 0},
        ):
            with self.subTest(kwargs=kwargs):
                before = api.board.fen()
                result = api.start_engine_game(**kwargs)
                self.assertFalse(result["ok"])
                self.assertEqual(api.board.fen(), before)
                self.assertEqual(engine.calls, [])

        self.assertEqual(calls, [])

    def test_engine_game_numeric_text_requires_bounded_ascii_digits(self) -> None:
        api, engine = self.make_api()

        unicode_digits = api.start_engine_game("white", "５", 0, 0)
        oversized = api.start_engine_game("white", "5" * 33, 0, 0)

        self.assertFalse(unicode_digits["ok"])
        self.assertFalse(oversized["ok"])
        self.assertEqual(engine.calls, [])

    def test_invalid_time_configuration_is_atomic_and_concise(self) -> None:
        api, engine = self.make_api()
        before = api.board.fen()

        result = api.start_engine_game("white", 5, 0, 3)

        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertEqual(result["historyLength"], 0)
        self.assertEqual(engine.calls, [])
        self.assertNotIn("ValueError", result["announcement"])

    def test_release_html_has_separate_accessible_engine_game_workflow(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('<h3 id="h-engine-play">Гра проти Stockfish</h3>', html)
        self.assertIn('id="engine-play-status" class="block" aria-live="off"', html)
        self.assertIn('id="engine-play-clocks" class="block" aria-live="off"', html)
        self.assertIn('<dialog id="engine-game-dialog"', html)
        for label in (
            "engine-human-side-label",
            "engine-level-label",
            "engine-time-preset-label",
            "engine-minutes-label",
            "engine-increment-label",
        ):
            self.assertIn(f'id="{label}"', html)
        for control in (
            "engine-human-side",
            "engine-level",
            "engine-time-preset",
            "engine-minutes",
            "engine-increment",
            "engine-game-start",
            "engine-play-stop",
            "engine-play-takeback",
            "engine-play-draw",
            "engine-play-resign",
            "engine-play-retry",
        ):
            self.assertIn(f'id="{control}"', html)
        for preset in (
            "0+0", "1+0", "2+1", "3+0", "3+2", "5+0", "5+3",
            "10+0", "10+5", "15+10", "30+0", "30+20", "custom",
        ):
            self.assertIn(f'<option value="{preset}"', html)
        self.assertIn("apiAction('start_engine_game'", html)
        self.assertIn("apiAction('engine_takeback')", html)
        self.assertIn("apiAction('offer_draw_engine_game')", html)
        self.assertIn("apiAction('retry_engine_move')", html)
        self.assertIn("function syncEngineTimeControl()", html)
        self.assertIn("function confirmResignEngineGame()", html)
        self.assertIn("function applyEngineGameLanguage(en)", html)
        self.assertIn("applyEngineGameLanguage(next==='en')", html)
        self.assertIn("en?'Play against Stockfish':'Гра проти Stockfish'", html)
        self.assertIn("en?'New game against Stockfish':'Нова гра проти Stockfish'", html)
        self.assertIn("en?'Random side':'Випадкову сторону'", html)
        self.assertIn("en?'No clock':'Без годинника'", html)
        self.assertIn("window.confirm", html)
        self.assertIn(
            "document.documentElement.lang==='en'?'Starting Stockfish…':'Запуск Stockfish…'",
            html,
        )
        self.assertIn(
            "document.documentElement.lang==='en'?'Could not start the game.':'Не вдалося почати гру.'",
            html,
        )
        self.assertNotIn(
            "setText('engine-game-dialog-status','Запуск Stockfish…')",
            html,
        )
        self.assertNotIn(
            "r&&r.announcement||'Не вдалося почати гру.'",
            html,
        )
        self.assertIn("setInterval(refreshAnalysis,700)", html)


if __name__ == "__main__":
    unittest.main()
