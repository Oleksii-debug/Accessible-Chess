from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_actions import FullProductActionRouter
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.pgn_document import PgnDocumentSession
from acs.pgn_document_webview_projection import PgnDocumentWebViewProjection
from acs.pgn_workspace import PgnWorkspace
from acs.version2_application import Version2Application


PGN = """[Event "Recovered"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 *
"""


class PgnDocumentWarningReachabilityTests(unittest.TestCase):
    @staticmethod
    def _router(language: UILanguage = UILanguage.EN) -> FullProductActionRouter:
        return FullProductActionRouter(
            AccessibleShellState(language=language),
            lambda _action, _payload: None,
        )

    @staticmethod
    def _warning_session() -> PgnDocumentSession:
        workspace = PgnWorkspace.from_text(PGN)
        return PgnDocumentSession(
            workspace,
            global_warnings=(
                "Recovered damaged source.\n"
                r"Source C:\Users\Oleksii\private\input.pgn" "\n"
                "Mirror /home/oleksii/private/input.pgn",
            ),
            source_overwrite_safe=False,
            saved_digest=None,
        )

    def test_document_recovery_warning_reuses_selectable_sanitized_warning_surface(self) -> None:
        projection = PgnDocumentWebViewProjection(
            self._warning_session(),
            self._router(),
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()
        warnings = snapshot["game"]["warnings"]

        self.assertEqual("PGN warnings", snapshot["game"]["warnings_heading"])
        self.assertEqual(1, len(warnings))
        self.assertIn("Recovered damaged source.", warnings[0])
        self.assertIn("[local path hidden]", warnings[0])
        self.assertNotIn("Users", warnings[0])
        self.assertNotIn("/home/", warnings[0])
        self.assertNotIn("Oleksii", warnings[0])

    def test_clean_document_does_not_invent_warning(self) -> None:
        session = PgnDocumentSession.from_text(PGN)
        projection = PgnDocumentWebViewProjection(
            session,
            self._router(),
            language=UILanguage.EN,
        )

        self.assertEqual((), projection.snapshot()["game"]["warnings"])

    def test_save_as_clears_document_warning_without_rebuilding_projection(self) -> None:
        session = self._warning_session()
        projection = PgnDocumentWebViewProjection(
            session,
            self._router(),
            language=UILanguage.EN,
        )
        self.assertTrue(projection.snapshot()["game"]["warnings"])

        with tempfile.TemporaryDirectory() as folder:
            session.save_as(Path(folder) / "recovered.pgn")

        self.assertEqual((), projection.snapshot()["game"]["warnings"])

    def test_projection_follows_current_session_workspace_after_document_replacement(self) -> None:
        session = PgnDocumentSession.from_text(PGN)
        projection = PgnDocumentWebViewProjection(
            session,
            self._router(),
            language=UILanguage.EN,
        )
        self.assertEqual("*", projection.snapshot()["game"]["result"])

        session.set_result("1-0")

        self.assertEqual("1-0", projection.snapshot()["game"]["result"])

    def test_version2_application_binds_document_aware_projection(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args: None,
                )
                session = self._warning_session()

                app.set_document(session)

                self.assertIs(app.session, session)
                self.assertIsInstance(app.pgn.projection, PgnDocumentWebViewProjection)
                snapshot = app.pgn.projection.snapshot()
                self.assertIn("Recovered damaged source.", snapshot["game"]["warnings"][0])
                self.assertNotIn("Users", repr(snapshot))
                self.assertEqual("pgn", app.shell.current_route.route_id)
            finally:
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
