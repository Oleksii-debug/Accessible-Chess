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


PGN = '[Event "External review"]\n[Result "*"]\n\n1. d4 d5 2. c4 e6 *\n'
BOOK_PGN = '[Event "Book review"]\n[Result "*"]\n\n1. c4 e5 2. Nc3 Nf6 *\n'


class Version2ReviewPresentationIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pgn_path = self.root / "review.pgn"
        self.pgn_path.write_text(PGN, encoding="utf-8")
        self.book_path = self.root / "study.md"
        self.book_path.write_text(
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
            board_position_projector=self.api.v2_project_review_fen,
        )
        self.api.bind_version2_application(self.app)

    @staticmethod
    def _history_identity(api: Version2ReleaseAccessibleChessAPI):
        return tuple(
            (
                record.node_id,
                record.parent_id,
                record.active_child,
                record.snapshot.fen,
                record.snapshot.san,
                record.snapshot.side,
                record.snapshot.last_move,
            )
            for record in api.review_history.tree_nodes()
        )

    def _live_identity(self):
        return (
            self.api.board.fen(),
            tuple(self.api.sans),
            tuple(self.api.move_sides),
            self.api.live_history_node,
            self._history_identity(self.api),
        )

    def _seed_live_game(self):
        result = self.api.make_move("e4")
        self.assertTrue(result["ok"])
        return self._live_identity()

    def test_pgn_review_uses_same_64_square_board_without_mutating_live_game(self) -> None:
        live = self._seed_live_game()
        self.app.set_document(PgnDocumentSession.open(self.pgn_path))
        reviewed_fen = self.app.pgn_commands.current_fen()
        self.assertNotEqual(reviewed_fen, live[0])

        opened = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual(opened["kind"], "review")
        state = self.api.get_state()
        self.assertEqual(state["fen"], reviewed_fen)
        self.assertEqual(len(state["board"]), 64)
        self.assertEqual(self._live_identity(), live)

        # The ordinary Stage 1 Move Edit and reset/editor commands must not mutate
        # the hidden live game while the shared board is displaying PGN review.
        move = self.api.make_move("d4")
        self.assertFalse(move["ok"])
        reset = self.api.set_fen(reviewed_fen)
        self.assertFalse(reset["ok"])
        new_game = self.api.new_game()
        self.assertFalse(new_game["ok"])
        self.assertEqual(self._live_identity(), live)

        advanced = self.app.browser_command("review", "pgn.board_next_move")
        self.assertEqual(advanced["kind"], "review")
        self.assertEqual(self.api.get_state()["fen"], self.app.pgn_commands.current_fen())
        self.assertEqual(self._live_identity(), live)

        # Direct application dispatch models native-menu routing, which does not
        # cross v2_browser_command.  Lifecycle state alone must deactivate the
        # cached review projection and reveal the untouched live board.
        returned = self.app.browser_command("review", "pgn.return")
        self.assertEqual(returned["kind"], "review")
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual(self.api.get_state()["fen"], live[0])
        self.assertEqual(self._live_identity(), live)

    def test_book_review_reuses_the_same_non_mutating_projection_and_exact_return(self) -> None:
        live = self._seed_live_game()
        self.app.open_book(self.book_path)
        selected = self.app.browser_command("books", "book.next_game")
        self.assertNotEqual(selected["kind"], "error")
        origin = self.app.reader.location()

        opened = self.app.browser_command("books", "book.open_position")
        self.assertEqual(opened["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        reviewed_fen = self.app.book_workflow.view().current_fen
        self.assertEqual(self.api.get_state()["fen"], reviewed_fen)
        self.assertEqual(len(self.api.get_state()["board"]), 64)
        self.assertEqual(self._live_identity(), live)

        advanced = self.app.browser_command("review", "book.board_next_move")
        self.assertEqual(advanced["kind"], "review")
        self.assertEqual(self.api.get_state()["fen"], self.app.book_workflow.view().current_fen)
        self.assertEqual(self._live_identity(), live)

        returned = self.app.browser_command("review", "book.return")
        self.assertEqual(returned["kind"], "review")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(self.api.get_state()["fen"], live[0])
        self.assertEqual(self._live_identity(), live)

    def test_review_projection_fails_closed_on_invalid_fen_without_live_mutation(self) -> None:
        live = self._seed_live_game()
        before_announcement = self.api.announcement

        bad = self.api.v2_project_review_fen("not a fen")

        self.assertEqual(bad, {"ok": False})
        self.assertEqual(self.api.announcement, before_announcement)
        self.assertEqual(self._live_identity(), live)
        self.assertEqual(self.api.get_state()["fen"], live[0])

    def test_browser_return_clears_cached_projection_eagerly(self) -> None:
        live = self._seed_live_game()
        self.app.set_document(PgnDocumentSession.open(self.pgn_path))
        self.assertEqual(self.api.v2_browser_command("review", "pgn.open_on_board")["kind"], "review")
        self.assertNotEqual(self.api.get_state()["fen"], live[0])

        returned = self.api.v2_browser_command("review", "pgn.return")

        self.assertEqual(returned["kind"], "review")
        self.assertIsNone(self.api._v2_review_fen)
        self.assertEqual(self.api.get_state()["fen"], live[0])
        self.assertEqual(self._live_identity(), live)


if __name__ == "__main__":
    unittest.main()
