from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.chesscore import Board, sq_name
from acs.clock_service import ClockSnapshot, ClockState
from acs.engine_play_service import EnginePlayService
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


class Stage1EnginePlayUiTests(unittest.TestCase):
    def make_api(self, engine: _LegalMoveEngine | None = None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        selected = engine or _LegalMoveEngine()
        service = EnginePlayService(lambda: selected)
        api = Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json",
            engine_play_service=service,
        )
        self.addCleanup(api.close_analysis)
        return api, selected

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
        self.assertEqual(engine.calls[0][1:], (6, 325))
        self.assertIn("Stockfish зіграв", played["announcement"])

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
        self.assertIn("window.confirm", html)
        self.assertIn("setInterval(refreshAnalysis,700)", html)


if __name__ == "__main__":
    unittest.main()
