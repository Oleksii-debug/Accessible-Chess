from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.pgn_document import PgnDocumentSession
from acs.version2_application import Version2Application
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
import acs.version2_release_app as release_app


PGN = '[Event "W5 projection"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'


class Version2BoardProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.projected: list[str] = []

        def sink(fen: str):
            self.projected.append(fen)
            return {"ok": True}

        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_args, **_kwargs: {"ok": True},
            position_sink=sink,
        )
        source = self.root / "game.pgn"
        source.write_text(PGN, encoding="utf-8")
        self.app.set_document(PgnDocumentSession.open(source))

    def test_open_on_board_projects_exact_selected_canonical_fen(self) -> None:
        self.app.browser_command("pgn", "pgn.select", {"node_id": "g0:main/m0"})
        expected = self.app.pgn_commands.current_fen()

        result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual(result["kind"], "review")
        self.assertEqual(self.projected, [expected])
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")

    def test_open_on_board_fails_closed_when_canonical_board_rejects_position(self) -> None:
        self.app._position_sink = lambda _fen: {"ok": False}
        before_cursor = self.app.session.workspace.cursor

        result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual(result["kind"], "error")
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")
        self.assertEqual(self.app.session.workspace.cursor, before_cursor)

    def test_failed_navigation_restores_pgn_cursor_and_previous_board_position(self) -> None:
        self.app.browser_command("review", "pgn.open_on_board")
        before_cursor = self.app.session.workspace.cursor
        before_fen = self.app.pgn_commands.current_fen()
        calls: list[str] = []

        def reject_once(fen: str):
            calls.append(fen)
            if len(calls) == 1:
                return {"ok": False}
            return {"ok": True}

        self.app._position_sink = reject_once
        result = self.app.browser_command("review", "pgn.board_next_move")

        self.assertEqual(result["kind"], "error")
        self.assertEqual(self.app.session.workspace.cursor, before_cursor)
        self.assertEqual(self.app.pgn_commands.current_fen(), before_fen)
        self.assertEqual(calls[-1], before_fen)
        self.assertTrue(self.app.pgn_board_active)


class Version2LanguageCompositionTests(unittest.TestCase):
    def test_production_factory_uses_one_persisted_language_and_trusted_position_sink(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            layout = SimpleNamespace(
                root=root,
                settings_path=root / "settings.json",
                library_path=root / "library.acsdb",
            )
            settings = mock.Mock()
            settings.data = {"language": "en"}
            settings.get.side_effect = lambda key, default=None: settings.data.get(key, default)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            api = mock.MagicMock()
            application = mock.MagicMock()
            database = mock.MagicMock()

            with (
                mock.patch.object(release_app, "_prepare_version2_user_data", return_value=layout),
                mock.patch.object(release_app, "Settings", return_value=settings),
                mock.patch.object(release_app, "AnalysisService", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "ContinuousAnalysisService", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "EnginePlayService", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "SoundRuntime", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "GameSoundRuntime", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "Version2ReleaseAccessibleChessAPI", return_value=api) as api_class,
                mock.patch.object(release_app, "AcsDatabase", return_value=database),
                mock.patch.object(release_app, "Version2Application", return_value=application) as application_class,
                mock.patch.object(release_app, "_share_v2_action_registry"),
            ):
                release_app.create_version2_release_application(
                    runtime_factory=lambda _config: runtime,
                    sound_playback=object(),
                )

            self.assertEqual(api_class.call_args.kwargs.get("lang"), "en")
            self.assertEqual(application_class.call_args.kwargs.get("language"), UILanguage.EN)
            self.assertIs(application_class.call_args.kwargs.get("position_sink"), api.set_fen)

    def test_runtime_language_change_persists_and_synchronizes_live_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            settings = mock.Mock()
            api = Version2ReleaseAccessibleChessAPI(
                keymap_path=root / "keymap.json",
                settings=settings,
            )
            application = Version2Application(
                database,
                progress_store=BookProgressStore(root / "book-progress.json"),
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_args, **_kwargs: {"ok": True},
                position_sink=lambda _fen: {"ok": True},
            )
            source = root / "game.pgn"
            source.write_text(PGN, encoding="utf-8")
            application.set_document(PgnDocumentSession.open(source))
            book = root / "study.md"
            book.write_text("# Study\n\nA paragraph.\n", encoding="utf-8")
            application.open_book(book)
            api.bind_version2_application(application)
            try:
                result = api.set_language("en")
                self.assertTrue(result["ok"])
                settings.set.assert_called_once_with("language", "en")
                self.assertEqual(api.lang, "en")
                snapshot = application.snapshot()
                self.assertEqual(snapshot["document"]["lang"], "en")
                self.assertEqual(snapshot["pgn"]["document"]["lang"], "en")
                self.assertEqual(snapshot["library"]["document"]["lang"], "en")
                self.assertEqual(snapshot["books"]["document"]["lang"], "en")
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()

    def test_settings_failure_rolls_language_back_across_stage1_and_v2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            settings = mock.Mock()

            def persist(key, value):
                if key == "language" and value == "en":
                    raise OSError("simulated persistence failure")

            settings.set.side_effect = persist
            api = Version2ReleaseAccessibleChessAPI(
                keymap_path=root / "keymap.json",
                settings=settings,
            )
            application = Version2Application(
                database,
                progress_store=BookProgressStore(root / "book-progress.json"),
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_args, **_kwargs: {"ok": True},
                position_sink=lambda _fen: {"ok": True},
            )
            api.bind_version2_application(application)
            try:
                result = api.set_language("en")
                self.assertFalse(result["ok"])
                self.assertEqual(api.lang, "uk")
                snapshot = application.snapshot()
                self.assertEqual(snapshot["document"]["lang"], "uk")
                self.assertEqual(snapshot["library"]["document"]["lang"], "uk")
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()


if __name__ == "__main__":
    unittest.main()
