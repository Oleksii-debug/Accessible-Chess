from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.engine_game_session import EngineTurnState
from acs.pgn_document import PgnDocumentSession
from acs.version2_application import Version2Application
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


PGN = '[Event "Review isolation"]\n[Result "*"]\n\n1. d4 d5 2. c4 e6 *\n'


class _RetryProbeSession:
    def __init__(self) -> None:
        self.resume_calls = 0

    def resume(self) -> None:
        self.resume_calls += 1

    def snapshot(self):
        return SimpleNamespace(
            config=SimpleNamespace(
                engine_side="b",
                level=SimpleNamespace(level=5),
                time_control=SimpleNamespace(
                    initial_ms=0,
                    increment_ms=0,
                    untimed=True,
                ),
            ),
            turn_state=EngineTurnState.HUMAN,
            clock=SimpleNamespace(white_ms=0, black_ms=0),
        )


class Version2ExternalReviewLiveStateIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "review.pgn"
        self.source.write_text(PGN, encoding="utf-8")
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.api = Version2ReleaseAccessibleChessAPI(keymap_path=self.root / "keymap.json")
        self.addCleanup(self.api.close_analysis)
        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=self.api.v2_board_dispatch,
            board_position_projector=self.api.project_review_fen,
        )
        self.api.bind_version2_application(self.app)

    @staticmethod
    def _history_identity(api: Version2ReleaseAccessibleChessAPI):
        return tuple(
            (
                record.node_id,
                record.parent_id,
                record.snapshot.fen,
                record.snapshot.san,
                record.snapshot.side,
                record.snapshot.last_move,
            )
            for record in api.review_history.tree_nodes()
        )

    def _open_external_review_after_live_e4(self):
        played = self.api.make_move("e4")
        self.assertTrue(played["ok"])
        live = {
            "fen": self.api.board.fen(),
            "sans": tuple(self.api.sans),
            "node": self.api.live_history_node,
            "history": self._history_identity(self.api),
        }
        self.app.set_document(PgnDocumentSession.open(self.source))
        reviewed_fen = self.app.pgn_commands.current_fen()
        self.assertNotEqual(reviewed_fen, live["fen"])
        opened = self.app.browser_command("review", "pgn.open_on_board")
        self.assertEqual(opened["kind"], "review")
        return live, reviewed_fen

    def _assert_live_identity(self, live) -> None:
        self.assertEqual(self.api.board.fen(), live["fen"])
        self.assertEqual(tuple(self.api.sans), live["sans"])
        self.assertEqual(self.api.live_history_node, live["node"])
        self.assertEqual(self._history_identity(self.api), live["history"])

    def test_pgn_review_projects_accessible_board_without_replacing_live_game(self) -> None:
        live, reviewed_fen = self._open_external_review_after_live_e4()

        state = self.api.get_state()
        self.assertEqual(state["fen"], reviewed_fen)
        self.assertEqual(len(state["board"]), 64)
        self.assertFalse(state["atHistoryEnd"])
        self.assertEqual(state["historyLength"], 0)
        self.assertEqual(state["moves"], "Ходів ще немає")
        self.assertEqual(state["lastMove"], "Останнього ходу немає")

        current = self.api.dispatch_action("board.current", "e2")
        self.assertTrue(current["ok"])
        self.assertIn("білий пішак", current["announcement"])
        self._assert_live_identity(live)

        returned = self.app.browser_command("review", "pgn.return")
        self.assertEqual(returned["kind"], "review")
        self.assertEqual(self.api.get_state()["fen"], live["fen"])
        self._assert_live_identity(live)

    def test_all_direct_live_mutation_entry_points_fail_closed_during_external_review(self) -> None:
        live, _ = self._open_external_review_after_live_e4()

        attempts = (
            lambda: self.api.make_move("d4"),
            lambda: self.api.make_move("s"),
            self.api.new_game,
            self.api.clear_board,
            lambda: self.api.set_fen(self.api.start_fen),
            lambda: self.api.set_turn("b"),
            lambda: self.api.set_position_text("white king e1; black king e8", "w"),
            self.api.undo,
            self.api.redo,
            lambda: self.api.activate_square("e2"),
            self.api.start_engine_game,
            self.api.stop_engine_game,
            self.api.engine_takeback,
            self.api.offer_draw_engine_game,
            self.api.resign_engine_game,
        )
        for attempt in attempts:
            with self.subTest(attempt=attempt):
                result = attempt()
                self.assertFalse(result["ok"])
                self._assert_live_identity(live)

    def test_review_guard_runs_before_stage1_engine_side_effects(self) -> None:
        live, _ = self._open_external_review_after_live_e4()
        self.api._engine_game_phase = "stopped"
        before_phase = self.api._engine_game_phase

        result = self.api.make_move("d4")

        self.assertFalse(result["ok"])
        self.assertEqual(self.api._engine_game_phase, before_phase)
        self._assert_live_identity(live)

    def test_engine_retry_guard_runs_before_session_resume(self) -> None:
        live, _ = self._open_external_review_after_live_e4()
        probe = _RetryProbeSession()
        self.api._engine_session = probe
        self.api._engine_game_phase = "error"
        self.api._engine_game_error = "simulated paused engine"

        result = self.api.retry_engine_move()

        self.assertFalse(result["ok"])
        self.assertEqual(probe.resume_calls, 0)
        self.assertTrue(self.app.pgn_board_active)
        self._assert_live_identity(live)

    def test_external_review_analysis_origin_never_becomes_live_history_origin(self) -> None:
        live, _ = self._open_external_review_after_live_e4()
        self.api.analysis_ui._fen = self.api.start_fen
        self.api._analysis_origin_node_id = 0
        self.api._external_review_fen = self.api.start_fen

        self.assertFalse(self.api._analysis_origin_matches())
        self._assert_live_identity(live)

    def test_invalid_external_review_fen_fails_without_changing_live_state(self) -> None:
        played = self.api.make_move("e4")
        self.assertTrue(played["ok"])
        live_fen = self.api.board.fen()
        live_history = self._history_identity(self.api)

        result = self.api.project_review_fen("not-a-fen")

        self.assertFalse(result["ok"])
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(self._history_identity(self.api), live_history)
        self.assertEqual(self.api.get_state()["fen"], live_fen)


if __name__ == "__main__":
    unittest.main()
