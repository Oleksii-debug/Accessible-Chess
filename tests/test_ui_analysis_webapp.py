from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from acs.chesscore import Board
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
        self.configured = []

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

    def configure(self, *, multipv=None, depth=None) -> int:
        self.multipv = multipv
        self.depth = depth
        self.last_result = None
        self.configured.append((multipv, depth))
        return len(self.configured)

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
        pvs = (
            ("e2e4", "e7e5"),
            ("d2d4", "d7d5"),
            ("c2c4", "e7e5"),
            ("g1f3", "d7d5"),
            ("b2b3", "e7e5"),
        )
        lines = tuple(
            SimpleNamespace(
                multipv=i,
                depth=18 + i,
                score_kind="cp",
                score_value=10 * i,
                pv=pvs[i - 1],
            )
            for i in range(1, self.multipv + 1)
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

    def test_missing_composed_engine_is_explicit_not_fake_enabled_state(self):
        with tempfile.TemporaryDirectory() as temp:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(temp) / "keymap.json")
            state = api.get_state()
            self.assertFalse(state["engineEnabled"])
            self.assertIn("недоступний", state["engineStatus"])
            result = api.toggle_engine()
            self.assertFalse(result["ok"])
            self.assertFalse(result["engineEnabled"])

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
        self.assertIn("c 4", result["announcement"])
        self.assertNotIn("c2c4", result["announcement"])
        self.assertEqual(api.keymap_resolve_binding("analysis", "Alt+3")["actionId"], "analysis.pv3")

    def test_evaluation_and_best_move_use_current_analysis(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen)
        evaluation = api.dispatch_action("board.evaluation")
        best = api.dispatch_action("board.best_move")
        self.assertIn("Оцінка", evaluation["announcement"])
        self.assertIn("e 4", best["announcement"])
        self.assertNotIn("e2e4", best["announcement"])

    def test_play_best_is_explicitly_unavailable_not_faked(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen)
        result = api.dispatch_action("board.play_best")
        self.assertFalse(result["ok"])
        self.assertIn("недоступна", result["announcement"])

    def test_engine_error_is_concise_and_disable_stops_service(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen, error="engine unavailable")
        state = api.get_state()
        self.assertEqual(state["engineStatus"], "Помилка Stockfish.")
        self.assertNotIn("engine unavailable", state["engineStatus"])
        disabled = api.toggle_engine()
        self.assertTrue(disabled["ok"])
        self.assertEqual(fake.stopped, 1)
        self.assertFalse(disabled["analysis"]["enabled"])

    def test_settings_restart_and_locked_target_are_real_service_operations(self):
        api, fake = self.make_api()
        api.toggle_engine()
        start_fen = api.get_state()["fen"]
        configured = api.configure_analysis(3, 24)
        self.assertTrue(configured["ok"])
        self.assertEqual(fake.configured, [(3, 24)])
        self.assertEqual((configured["analysis"]["multipv"], configured["analysis"]["depth"]), (3, 24))

        fake.set_result(start_fen)
        locked = api.toggle_analysis_lock()
        self.assertTrue(locked["analysis"]["targetLocked"])
        api.make_move("e4")
        moved = api.get_state()
        self.assertEqual(moved["analysis"]["fen"], start_fen)
        self.assertFalse(moved["analysis"]["stale"])
        self.assertEqual(fake.updated, [])

        followed = api.toggle_analysis_lock()
        self.assertFalse(followed["analysis"]["targetLocked"])
        self.assertEqual(fake.updated[-1], api.board.fen())
        restarted = api.restart_analysis()
        self.assertTrue(restarted["ok"])
        self.assertEqual(fake.started[-1][1:], (3, 24))

    def test_pv_exploration_is_temporary_and_return_restores_exact_origin(self):
        api, fake = self.make_api()
        api.toggle_engine()
        origin_fen = api.get_state()["fen"]
        origin_node = api.review_history.cursor_node_id
        fake.set_result(origin_fen)

        explored = api.explore_analysis_pv()

        self.assertTrue(explored["ok"])
        self.assertTrue(explored["analysisViewingTemporaryPosition"])
        self.assertNotEqual(explored["fen"], origin_fen)
        self.assertEqual(api.board.fen(), origin_fen)
        self.assertEqual(api.review_history.cursor_node_id, origin_node)
        advanced = api.step_analysis_exploration(1)
        self.assertEqual(advanced["analysis"]["explorationPly"], 2)

        returned = api.return_from_analysis()

        self.assertTrue(returned["ok"])
        self.assertEqual(returned["fen"], origin_fen)
        self.assertFalse(returned["analysisViewingTemporaryPosition"])
        self.assertEqual(api.review_history.cursor_node_id, origin_node)

    def test_temporary_exploration_blocks_canonical_mutation(self):
        api, fake = self.make_api()
        api.toggle_engine()
        origin_fen = api.get_state()["fen"]
        fake.set_result(origin_fen)
        self.assertTrue(api.explore_analysis_pv()["ok"])

        for operation in (
            lambda: api.make_move("e4"),
            api.undo,
            api.new_game,
            lambda: api.set_fen(origin_fen),
            lambda: api.activate_square("e2"),
        ):
            with self.subTest(operation=operation):
                result = operation()
                self.assertFalse(result["ok"])
                self.assertIn("поверніться", result["announcement"].lower())
                self.assertEqual(api.board.fen(), origin_fen)

        self.assertTrue(api.return_from_analysis()["ok"])

    def test_canonical_reset_releases_obsolete_locked_target(self):
        api, fake = self.make_api()
        api.toggle_engine()
        api.get_state()
        self.assertTrue(api.toggle_analysis_lock()["ok"])
        board = Board()
        board.push_text("e4")

        reset = api.set_fen(board.fen())

        self.assertTrue(reset["ok"])
        self.assertFalse(reset["analysis"]["targetLocked"])
        self.assertEqual(reset["analysis"]["fen"], board.fen())
        self.assertEqual(fake.updated[-1], board.fen())

    def test_explicit_line_insertion_preserves_mainline_and_is_idempotent(self):
        api, fake = self.make_api()
        api.toggle_engine()
        origin_fen = api.get_state()["fen"]
        fake.set_result(origin_fen)
        original_line = tuple(snapshot.fen for snapshot in api.review_history.active_line())

        inserted = api.insert_analysis_line()

        self.assertTrue(inserted["ok"])
        self.assertEqual(api.review_history.node_count, 3)
        self.assertEqual(
            tuple(snapshot.fen for snapshot in api.review_history.active_line()),
            original_line,
        )
        repeated = api.insert_analysis_line()
        self.assertTrue(repeated["ok"])
        self.assertEqual(api.review_history.node_count, 3)
        self.assertIn("вже існує", repeated["announcement"])

    def test_web_state_contains_san_and_never_raw_uci_or_provider_path(self):
        api, fake = self.make_api()
        api.toggle_engine()
        fen = api.get_state()["fen"]
        fake.set_result(fen)
        state = api.get_state()
        rendered = str(state["analysis"])
        self.assertIn("'e4'", rendered)
        self.assertNotIn("e2e4", rendered)

        fake.set_result(fen, error=r"C:\\private\\stockfish.exe failed")
        failed = api.get_state()
        self.assertEqual(failed["analysis"]["error"], "engine_error")
        self.assertNotIn("private", str(failed))


if __name__ == "__main__":
    unittest.main()
