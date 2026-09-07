from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_document import PgnDocumentSession
from acs.version2_application import Version2Application


PGN = '[Event "W3 board projection"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'


class Version2PgnBoardProjectionEvidenceTests(unittest.TestCase):
    """Release-journey evidence only; Product repair remains owned by PR #441."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.board_calls = []
        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda action, payload=None: self.board_calls.append((action, payload)) or {"ok": True},
        )
        source = self.root / "game.pgn"
        source.write_text(PGN, encoding="utf-8")
        self.app.set_document(PgnDocumentSession.open(source))

    def test_open_on_board_projects_selected_canonical_position_to_board_runtime(self):
        self.app.browser_command("pgn", "pgn.select", {"node_id": "g0:main/m0"})
        before = self.app.pgn_commands.current_fen()

        result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual(result["kind"], "review")
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertTrue(
            self.board_calls,
            "opening a PGN position on the release board must project the canonical selected position into the real board runtime",
        )
        self.assertEqual(before, self.app.pgn_commands.current_fen())

    def test_board_review_navigation_reprojects_each_canonical_position(self):
        self.app.browser_command("review", "pgn.open_on_board")
        calls_after_open = len(self.board_calls)

        self.app.browser_command("review", "pgn.board_next_move")
        after_next = self.app.pgn_commands.current_fen()
        self.app.browser_command("review", "pgn.board_previous_move")
        after_previous = self.app.pgn_commands.current_fen()

        self.assertNotEqual(after_next, after_previous)
        self.assertGreater(
            len(self.board_calls),
            calls_after_open,
            "PGN board navigation must update the real board runtime rather than only moving the hidden PGN cursor",
        )


if __name__ == "__main__":
    unittest.main()
