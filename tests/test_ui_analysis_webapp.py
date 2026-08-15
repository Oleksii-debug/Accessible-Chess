from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


class FakeContinuousAnalysis:
    def __init__(self) -> None:
        self.running = False
        self.fen = None
        self.multipv = 5
        self.depth = 16
        self.last_result = None
        self.started = []
        self.updated = []
        self.stopped = 0
        self.closed = 0

    def start(self, fen: str, multipv: int = 5, depth: int = 16) -> int:
        self.running = True
        self.fen = fen
        self.multipv = multipv
        self.depth = depth
        self.started.append((fen, multipv, depth))
        return len(self.started)

    def update_position(self, fen: str) -> int:
        self.fen = fen
        self.updated.append(fen)
        return len(self.updated)

    def stop(self) -> int:
        self.running = False
        self.stopped += 1
        return self.stopped

    def close(self) -> None:
        self.running = False
        self.closed += 1

    def state(self):
        return SimpleNamespace(
            running=self.running,
            fen=self.fen,
            multipv=self.multipv,
            depth=self.depth,
            last_result=self.last_result,
        )

    def set_result(self, fen: str, *, stale: bool = False, error: str | None = None) -> None:
        lines = tuple(
            SimpleNamespace(
                multipv=i,
                depth=18 + i,
                score_kind="cp",
                score_value=10 * i,
                pv=(f"move{i}a", f"move{i}b"),
            )
            for i in range(1, 6)
        )
        self.last_result = SimpleNamespace(fen=fen, stale=stale, error=error, lines=lines)


class UIAnalysisWebAppTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        fake = FakeContinuousAnalysis()
        api = KeymapAwareAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json",
            continuous_analysis=fake,
        )
        return api, fake

    def test_engine_enable_starts_real_service_with_multipv_five(self):
        api, fake = self.make_api()
        result = api.toggle_engine()
        self.assertTrue(result["ok"])
        self.assertEqual(len(fake.started), 1)
        self.assertEqual(fake.started[0][1:], (5, 16))
        self.assertTrue(result["analysis"]["enabled"])
        self.assertEqual(result["analysis"]["multipv"], 5)
        self.assertNotIn("migration", result["engineStatus"].lower())
        self.assertNotIn("перенос", result["engineStatus"].lower())

    def test_real_five_pv_lines_are_projected_without_live_announcement_spam(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen)
        state = api.get_state()
        self.assertEqual(len(state["analysis"]["lines"]), 5)
        self.assertIn("Варіант 5", state["engineStatus"])
        # get_state projects analysis into aria-live=off engine content; it must
        # not overwrite the user's latest explicit announcement.
        prior = api.announcement
        api.get_state()
        self.assertEqual(api.announcement, prior)

    def test_stale_result_is_suppressed_after_position_change(self):
        api, fake = self.make_api()
        api.toggle_engine()
        old_fen = api.get_state()["fen"]
        fake.set_result(old_fen)
        api.make_move("e4")
        state = api.get_state()
        self.assertNotEqual(state["fen"], old_fen)
        self.assertEqual(state["analysis"]["lines"], [])
        self.assertTrue(state["analysis"]["stale"])
        self.assertIn(state["fen"], fake.updated)

    def test_history_review_position_is_sent_to_analysis_without_mutating_live_board(self):
        api, fake = self.make_api()
        api.make_move("e4")
        api.make_move("e5")
        live_fen = api.board.fen()
        api.toggle_engine()
        api.review_previous()
        reviewed = api.get_state()["fen"]
        self.assertNotEqual(reviewed, live_fen)
        self.assertEqual(api.board.fen(), live_fen)
        self.assertEqual(fake.updated[-1], reviewed)

    def test_central_registry_pv_actions_read_full_variations(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen)
        result = api.dispatch_action("analysis.pv3")
        self.assertTrue(result["ok"])
        self.assertIn("Варіант 3", result["announcement"])
        self.assertIn("move3a move3b", result["announcement"])
        self.assertEqual(
            api.keymap_resolve_binding("analysis", "Alt+3")["actionId"],
            "analysis.pv3",
        )

    def test_evaluation_and_best_move_use_current_analysis(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen)
        evaluation = api.dispatch_action("board.evaluation")
        best = api.dispatch_action("board.best_move")
        self.assertIn("Оцінка", evaluation["announcement"])
        self.assertIn("move1a", best["announcement"])

    def test_play_best_is_explicitly_unwired_not_faked(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen)
        result = api.dispatch_action("board.play_best")
        self.assertFalse(result["ok"])
        self.assertIn("контракт", result["announcement"])

    def test_engine_error_is_visible_and_disable_stops_service(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen, error="engine unavailable")
        state = api.get_state()
        self.assertIn("engine unavailable", state["engineStatus"])
        disabled = api.toggle_engine()
        self.assertTrue(disabled["ok"])
        self.assertEqual(fake.stopped, 1)
        self.assertFalse(disabled["analysis"]["enabled"])


if __name__ == "__main__":
    unittest.main()
