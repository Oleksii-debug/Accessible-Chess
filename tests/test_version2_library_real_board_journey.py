from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
from acs.version2_windows_file_workflows import Version2WindowsFileActionDelegate
from acs.version2_windows_import_event_mailbox import Version2ImportUiEventMailbox


PGN = '[Event "Library real board journey"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'


class Version2LibraryRealBoardJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "library-source.pgn"
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
            board_position_projector=self.api.set_fen,
        )
        self.api.bind_version2_application(self.app)
        self.mailbox = Version2ImportUiEventMailbox()
        self.dialogs = SimpleNamespace(
            open_pgn=lambda: self.source,
            save_pgn_as=lambda *_: self.root / "saved.pgn",
            select_library_import=lambda: self.source,
        )
        self.files = Version2WindowsFileActionDelegate(
            dialogs=self.dialogs,
            get_pgn_session=lambda: self.app.session,
            set_pgn_session=self.app.set_document,
            import_services_factory=self.app.worker_factory(self.root / "library.acsdb"),
            event_sink=self.mailbox,
            next_delegate=lambda *_: None,
        )
        self.app.bind_files(self.files)
        self.addCleanup(lambda: self.files.shutdown(timeout=5))

    def _import_library_game(self) -> str:
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        snapshot = self.app.snapshot()["library"]
        self.assertEqual(snapshot["import"]["phase"], "completed")
        self.assertEqual(snapshot["import"]["processed_games"], 1)
        before = self.database.get_game(1)["pgn_text"]
        searched = self.app.browser_command("library", "library.search", {"player": "alpha"})
        self.assertEqual(searched["kind"], "render")
        return before

    def test_library_record_reaches_real_release_board_and_tracks_review_navigation(self) -> None:
        database_pgn = self._import_library_game()

        opened = self.app.browser_command("library", "library.open_game")
        self.assertEqual(opened["kind"], "delegated")
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")
        self.assertIsNotNone(self.app.session)

        selected = self.app.browser_command("pgn", "pgn.select", {"node_id": "g0:main/m0"})
        self.assertEqual(selected["kind"], "selection")
        first_fen = self.app.pgn_commands.current_fen()

        review = self.app.browser_command("review", "pgn.open_on_board")
        self.assertEqual(review["kind"], "review")
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(self.api.get_state()["fen"], first_fen)

        advanced = self.app.browser_command("review", "pgn.board_next_move")
        self.assertEqual(advanced["kind"], "review")
        second_fen = self.app.pgn_commands.current_fen()
        self.assertNotEqual(second_fen, first_fen)
        self.assertEqual(self.api.get_state()["fen"], second_fen)

        # Library records are detached for review: the canonical source stays unchanged.
        self.assertEqual(self.database.get_game(1)["pgn_text"], database_pgn)


if __name__ == "__main__":
    unittest.main()
