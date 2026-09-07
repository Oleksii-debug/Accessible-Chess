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
BOOK_PGN = '[Event "Book review isolation"]\n[Result "*"]\n\n1. d4 d5 2. c4 e6 *\n'


class Version2SharedReviewProjectionIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pgn_source = self.root / "review.pgn"
        self.pgn_source.write_text(PGN, encoding="utf-8")
        self.book_source = self.root / "study.md"
        self.book_source.write_text(
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
            board_position_projector=self.api.project_review_position,
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

    def _play_live_e4_and_snapshot(self):
        played = self.api.make_move("e4")
        self.assertTrue(played["ok"])
        return (
            self.api.board.fen(),
            tuple(self.api.sans),
            self.api.live_history_node,
            self._history_identity(self.api),
        )

    def _assert_live_unchanged(self, identity) -> None:
        live_fen, live_sans, live_node, live_history = identity
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)
        self.assertEqual(self._history_identity(self.api), live_history)

    def test_pgn_review_uses_presentation_projection_without_live_mutation(self) -> None:
        live = self._play_live_e4_and_snapshot()
        self.app.set_document(PgnDocumentSession.open(self.pgn_source))
        reviewed_fen = self.app.pgn_commands.current_fen()
        self.assertNotEqual(reviewed_fen, live[0])

        opened = self.app.browser_command("review", "pgn.open_on_board")
        self.assertEqual(opened["kind"], "review")
        self.assertEqual(self.api.get_state()["fen"], reviewed_fen)
        self._assert_live_unchanged(live)

        # A review projection must behave like review, not like a writable clone
        # of the live game. Move Input remains blocked while the projection is active.
        blocked = self.api.make_move("d4")
        self.assertFalse(blocked["ok"])
        self._assert_live_unchanged(live)

        advanced = self.app.browser_command("review", "pgn.board_next_move")
        self.assertEqual(advanced["kind"], "review")
        advanced_fen = self.app.pgn_commands.current_fen()
        self.assertEqual(self.api.get_state()["fen"], advanced_fen)
        self._assert_live_unchanged(live)

        returned = self.app.browser_command("review", "pgn.return")
        self.assertEqual(returned["kind"], "review")
        self.assertEqual(self.api.get_state()["fen"], live[0])
        self._assert_live_unchanged(live)

        # Once review ends, ordinary canonical play resumes on the untouched game.
        resumed = self.api.make_move("e5")
        self.assertTrue(resumed["ok"])
        self.assertEqual(tuple(self.api.sans), ("e4", "e5"))

    def test_book_review_reuses_the_same_non_mutating_projection(self) -> None:
        live = self._play_live_e4_and_snapshot()
        self.app.open_book(self.book_source)
        self.app.browser_command("books", "book.next_game")
        origin = self.app.reader.location()

        opened = self.app.browser_command("books", "book.open_position")
        self.assertEqual(opened["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        reviewed_fen = self.app.book_workflow.view().current_fen
        self.assertNotEqual(reviewed_fen, live[0])
        self.assertEqual(self.api.get_state()["fen"], reviewed_fen)
        self._assert_live_unchanged(live)

        advanced = self.app.browser_command("review", "book.board_next_move")
        self.assertEqual(advanced["kind"], "review")
        advanced_fen = self.app.book_workflow.view().current_fen
        self.assertEqual(self.api.get_state()["fen"], advanced_fen)
        self._assert_live_unchanged(live)

        returned = self.app.browser_command("review", "book.return")
        self.assertEqual(returned["kind"], "review")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(self.api.get_state()["fen"], live[0])
        self._assert_live_unchanged(live)

    def test_direct_set_fen_remains_a_canonical_position_mutation(self) -> None:
        self._play_live_e4_and_snapshot()
        start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        loaded = self.api.set_fen(start_fen)
        self.assertTrue(loaded["ok"])
        self.assertEqual(self.api.board.fen(), start_fen)
        self.assertEqual(tuple(self.api.sans), ())
        self.assertEqual(len(self.api.review_history.tree_nodes()), 1)


if __name__ == "__main__":
    unittest.main()
