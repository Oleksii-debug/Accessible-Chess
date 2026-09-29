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
from acs.settings import Settings
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
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

    def test_document_warning_is_rescrubbed_after_live_language_change(self) -> None:
        projection = PgnDocumentWebViewProjection(
            self._warning_session(),
            self._router(),
            language=UILanguage.EN,
        )
        self.assertIn(
            "[local path hidden]",
            projection.snapshot()["game"]["warnings"][0],
        )

        event = projection.set_language(UILanguage.UA)

        self.assertEqual("render", event.kind)
        warning = event.payload["game"]["warnings"][0]
        self.assertEqual("Попередження PGN", event.payload["game"]["warnings_heading"])
        self.assertIn("[локальний шлях приховано]", warning)
        self.assertNotIn("[local path hidden]", warning)
        self.assertNotIn("Users", warning)
        self.assertNotIn("/home/", warning)

    def test_document_warning_survives_post_action_render(self) -> None:
        projection = PgnDocumentWebViewProjection(
            self._warning_session(),
            self._router(),
            language=UILanguage.EN,
        )

        event = projection.copy_selection()

        self.assertEqual("selection", event.kind)
        warnings = event.payload["snapshot"]["game"]["warnings"]
        self.assertTrue(
            any("Recovered damaged source." in warning for warning in warnings)
        )

    def test_real_invalid_utf8_open_warning_reaches_accessible_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "legacy source.pgn"
            source.write_bytes(PGN.encode("utf-8") + b"\n{broken byte: \xff}\n")

            session = PgnDocumentSession.open(source)
            self.assertFalse(session.view().source_overwrite_safe)
            self.assertTrue(session.view().global_warnings)
            projection = PgnDocumentWebViewProjection(
                session,
                self._router(),
                language=UILanguage.EN,
            )

            warnings = projection.snapshot()["game"]["warnings"]

            self.assertTrue(
                any("Invalid UTF-8 bytes were replaced" in warning for warning in warnings)
            )
            self.assertTrue(session.dirty)

    def test_real_recovered_file_warning_reaches_whole_application_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "legacy whole product.pgn"
            source.write_bytes(PGN.encode("utf-8") + b"\n{broken byte: \xff}\n")
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args: None,
                    language=UILanguage.EN,
                )

                app.set_document(PgnDocumentSession.open(source))
                snapshot = app.snapshot()

                self.assertEqual("pgn", app.shell.current_route.route_id)
                self.assertTrue(snapshot["document_dirty"])
                self.assertIsNotNone(snapshot["pgn"])
                warnings = snapshot["pgn"]["game"]["warnings"]
                self.assertTrue(
                    any("Invalid UTF-8 bytes were replaced" in warning for warning in warnings)
                )
                self.assertNotIn(str(source), repr(snapshot["pgn"]))
            finally:
                analysis.close()
                database.close()

    def test_release_language_transaction_rescrubs_real_recovery_warning(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "private recovery.pgn"
            source.write_bytes(PGN.encode("utf-8") + b"\n{broken byte: \xff}\n")
            settings = Settings(root / "settings.json")
            settings.set("language", "en")
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            api = Version2ReleaseAccessibleChessAPI(
                keymap_path=root / "keymap.json",
                settings=settings,
                lang="en",
            )
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args: None,
                    language=UILanguage.EN,
                )
                app.set_document(PgnDocumentSession.open(source))
                api.bind_version2_application(app)

                before = app.snapshot()["pgn"]["game"]["warnings"][0]
                self.assertIn("Invalid UTF-8 bytes were replaced", before)
                result = api.set_language("uk")
                after = app.snapshot()["pgn"]["game"]["warnings"][0]

                self.assertTrue(result["ok"])
                self.assertEqual(UILanguage.UA, app.pgn.projection.language)
                self.assertEqual("Попередження PGN", app.snapshot()["pgn"]["game"]["warnings_heading"])
                self.assertNotIn(str(source), after)
                self.assertNotIn("[local path hidden]", after)
            finally:
                analysis.close()
                api.close_analysis()
                database.close()

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

    def test_browser_warning_renderer_is_persistent_selectable_text_not_live_region(self) -> None:
        renderer = (
            Path(__file__).resolve().parents[1] / "web" / "full_product_pgn.js"
        ).read_text(encoding="utf-8")

        self.assertIn("function renderWarnings(host, game)", renderer)
        self.assertIn('section.setAttribute("aria-live", "off");', renderer)
        self.assertIn('section.appendChild(node("h3", game.warnings_heading || ""));', renderer)
        self.assertIn('const list = node("ul");', renderer)
        self.assertIn(
            'warnings.forEach(function (warning) { list.appendChild(node("li", warning)); });',
            renderer,
        )
        self.assertIn("element.textContent = String(text);", renderer)

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
