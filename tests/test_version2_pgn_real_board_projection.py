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


PGN = '[Event "W5 board projection"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'


class Version2PgnRealBoardProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "game.pgn"
        self.source.write_text(PGN, encoding="utf-8")
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)

    def _application(self, projector):
        return Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_args, **_kwargs: {"ok": True},
            board_position_projector=projector,
        )

    def _open_document(self, app: Version2Application) -> None:
        app.set_document(PgnDocumentSession.open(self.source))

    def test_open_on_board_projects_exact_selected_fen_into_real_release_board(self) -> None:
        api = Version2ReleaseAccessibleChessAPI(keymap_path=self.root / "keymap.json")
        self.addCleanup(api.close_analysis)
        app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=api.v2_board_dispatch,
            board_position_projector=api.set_fen,
        )
        api.bind_version2_application(app)
        self._open_document(app)
        app.browser_command("pgn", "pgn.select", {"node_id": "g0:main/m0"})
        expected = app.pgn_commands.current_fen()

        result = app.browser_command("review", "pgn.open_on_board")

        self.assertEqual(result["kind"], "review")
        self.assertTrue(app.pgn_board_active)
        self.assertEqual(app.shell.current_route.route_id, "board")
        self.assertEqual(api.get_state()["fen"], expected)
        self.assertEqual(app.pgn_commands.current_fen(), expected)

    def test_review_navigation_reprojects_each_canonical_position(self) -> None:
        calls: list[str] = []

        def projector(fen: str):
            calls.append(fen)
            return {"ok": True}

        app = self._application(projector)
        self._open_document(app)
        self.assertEqual(app.browser_command("review", "pgn.open_on_board")["kind"], "review")
        first = calls[-1]

        self.assertEqual(app.browser_command("review", "pgn.board_next_move")["kind"], "review")
        second = calls[-1]
        self.assertEqual(second, app.pgn_commands.current_fen())
        self.assertNotEqual(second, first)

        self.assertEqual(app.browser_command("review", "pgn.board_previous_move")["kind"], "review")
        self.assertEqual(calls[-1], app.pgn_commands.current_fen())
        self.assertEqual(calls[-1], first)

    def test_projection_failure_rolls_back_cursor_and_previous_board_position(self) -> None:
        calls: list[str] = []

        def projector(fen: str):
            calls.append(fen)
            if len(calls) == 2:
                return {"ok": False}
            return {"ok": True}

        app = self._application(projector)
        self._open_document(app)
        self.assertEqual(app.browser_command("review", "pgn.open_on_board")["kind"], "review")
        before_cursor = app.session.workspace.cursor
        before_fen = app.pgn_commands.current_fen()

        result = app.browser_command("review", "pgn.board_next_move")

        self.assertEqual(result["kind"], "error")
        self.assertEqual(app.session.workspace.cursor, before_cursor)
        self.assertEqual(app.pgn_commands.current_fen(), before_fen)
        self.assertEqual(len(calls), 3)
        self.assertNotEqual(calls[1], before_fen)
        self.assertEqual(calls[2], before_fen)
        self.assertTrue(app.pgn_board_active)
        self.assertEqual(app.shell.current_route.route_id, "board")

    def test_missing_projector_fails_closed_without_switching_to_board(self) -> None:
        app = self._application(None)
        self._open_document(app)

        result = app.browser_command("review", "pgn.open_on_board")

        self.assertEqual(result["kind"], "error")
        self.assertFalse(app.pgn_board_active)
        self.assertEqual(app.shell.current_route.route_id, "pgn")

    def test_invalid_projector_contract_is_rejected_at_construction(self) -> None:
        with self.assertRaisesRegex(TypeError, "board_position_projector"):
            self._application(object())


if __name__ == "__main__":
    unittest.main()
