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


PGN = '[Event "Retry isolation"]\n[Result "*"]\n\n1. d4 d5 *\n'


class _RetryProbeSession:
    def __init__(self) -> None:
        self.resume_calls = 0

    def resume(self) -> None:
        self.resume_calls += 1

    def snapshot(self):
        return SimpleNamespace(turn_state=EngineTurnState.HUMAN)


class Version2ReviewEngineRetryIsolationEvidenceTests(unittest.TestCase):
    """RED-first proof that review must block engine recovery side effects."""

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
            board_position_projector=self.api.v2_project_review_fen,
        )
        self.api.bind_version2_application(self.app)

    def test_engine_retry_is_blocked_before_session_resume_during_external_review(self) -> None:
        played = self.api.make_move("e4")
        self.assertTrue(played["ok"])
        live_identity = (
            self.api.board.fen(),
            tuple(self.api.sans),
            self.api.live_history_node,
        )

        self.app.set_document(PgnDocumentSession.open(self.source))
        opened = self.app.browser_command("review", "pgn.open_on_board")
        self.assertEqual(opened["kind"], "review")
        self.assertTrue(self.app.pgn_board_active)
        self.assertNotEqual(self.api.get_state()["fen"], live_identity[0])

        probe = _RetryProbeSession()
        self.api._engine_session = probe
        self.api._engine_game_phase = "error"
        self.api._engine_game_error = "simulated paused engine"

        result = self.api.retry_engine_move()

        self.assertFalse(result["ok"])
        self.assertEqual(
            probe.resume_calls,
            0,
            "engine retry resumed a live-game provider behind external PGN/Book review",
        )
        self.assertEqual(
            (self.api.board.fen(), tuple(self.api.sans), self.api.live_history_node),
            live_identity,
        )
        self.assertTrue(self.app.pgn_board_active)


if __name__ == "__main__":
    unittest.main()
