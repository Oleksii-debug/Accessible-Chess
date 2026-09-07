from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_document import PgnDocumentSession
from acs.version2_application import Version2Application
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


PGN = '[Event "Review isolation"]\n[Result "*"]\n\n1. d4 d5 2. c4 e6 *\n'


class Version2PgnReviewLiveStateIsolationTests(unittest.TestCase):
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
            board_position_projector=self.api._project_review_fen,
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

    def test_pgn_review_projection_must_not_replace_live_game_or_history(self) -> None:
        played = self.api.make_move("e4")
        self.assertTrue(played["ok"])
        live_fen = self.api.board.fen()
        live_sans = tuple(self.api.sans)
        live_node = self.api.live_history_node
        live_history = self._history_identity(self.api)
        self.assertEqual(len(live_sans), 1)

        self.app.set_document(PgnDocumentSession.open(self.source))
        reviewed_fen = self.app.pgn_commands.current_fen()
        self.assertNotEqual(reviewed_fen, live_fen)

        opened = self.app.browser_command("review", "pgn.open_on_board")
        self.assertEqual(opened["kind"], "review")
        self.assertEqual(self.api.get_state()["fen"], reviewed_fen)

        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)
        self.assertEqual(self._history_identity(self.api), live_history)

        blocked = self.api.make_move("e5")
        self.assertFalse(blocked["ok"])
        self.assertEqual(self.api.get_state()["fen"], reviewed_fen)
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)
        self.assertEqual(self._history_identity(self.api), live_history)

        returned = self.app.browser_command("review", "pgn.return")
        self.assertEqual(returned["kind"], "review")
        self.assertEqual(self.api.get_state()["fen"], live_fen)
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)
        self.assertEqual(self._history_identity(self.api), live_history)


if __name__ == "__main__":
    unittest.main()
