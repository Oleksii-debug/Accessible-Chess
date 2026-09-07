from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


BOOK_PGN = '[Event "Book review isolation"]\n[Result "*"]\n\n1. d4 d5 2. c4 e6 *\n'


class Version2BookReviewLiveStateIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / "study.md"
        self.book.write_text(
            "# Study\n\nBefore.\n\n```pgn\n" + BOOK_PGN + "```\n\nAfter.\n",
            encoding="utf-8",
        )
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

    def test_book_review_projection_must_not_replace_live_game_or_history(self) -> None:
        played = self.api.make_move("e4")
        self.assertTrue(played["ok"])
        live_fen = self.api.board.fen()
        live_sans = tuple(self.api.sans)
        live_node = self.api.live_history_node
        live_history = self._history_identity(self.api)
        self.assertEqual(len(live_sans), 1)

        self.app.open_book(self.book)
        self.app.browser_command("books", "book.next_game")
        origin = self.app.reader.location()

        opened = self.app.browser_command("books", "book.open_position")
        self.assertEqual(opened["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        reviewed_fen = self.app.book_workflow.view().current_fen
        self.assertNotEqual(reviewed_fen, live_fen)

        self.assertEqual(self.api.get_state()["fen"], reviewed_fen)
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)
        self.assertEqual(self._history_identity(self.api), live_history)

        advanced = self.app.browser_command("review", "book.board_next_move")
        self.assertEqual(advanced["kind"], "review")
        advanced_fen = self.app.book_workflow.view().current_fen
        self.assertNotEqual(advanced_fen, reviewed_fen)
        self.assertEqual(self.api.get_state()["fen"], advanced_fen)
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)
        self.assertEqual(self._history_identity(self.api), live_history)

        returned = self.app.browser_command("review", "book.return")
        self.assertEqual(returned["kind"], "review")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(self.api.get_state()["fen"], live_fen)
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)
        self.assertEqual(self._history_identity(self.api), live_history)


if __name__ == "__main__":
    unittest.main()
