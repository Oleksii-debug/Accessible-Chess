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
from acs.settings import Settings
from acs.version2_application import Version2Application
import acs.version2_release_app as release_app
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


PGN = '[Event "Language"]\n[Result "*"]\n\n1. e4 e5 *\n'


class Version2LanguageConsistencyTests(unittest.TestCase):
    def test_factory_uses_one_persisted_language_for_stage1_and_v2(self) -> None:
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

            self.assertEqual(api_class.call_args.kwargs["lang"], "en")
            self.assertEqual(application_class.call_args.kwargs["language"], UILanguage.EN)
            self.assertIs(application_class.call_args.kwargs["board_position_projector"], api.set_fen)

    def _real_runtime(self, root: Path, settings: object):
        database = AcsDatabase(root / "library.acsdb")
        analysis = AnalysisService(lambda: None)
        api = Version2ReleaseAccessibleChessAPI(
            keymap_path=root / "keymap.json",
            settings=settings,
        )
        application = Version2Application(
            database,
            progress_store=BookProgressStore(root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(analysis),
            board_dispatch=api.v2_board_dispatch,
            board_position_projector=api.set_fen,
        )
        api.bind_version2_application(application)
        return database, analysis, api, application

    def test_runtime_change_persists_and_updates_shell_pgn_library_and_books(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings_path = root / "settings.json"
            settings = Settings(settings_path)
            _database, analysis, api, application = self._real_runtime(root, settings)
            pgn = root / "game.pgn"
            pgn.write_text(PGN, encoding="utf-8")
            application.set_document(PgnDocumentSession.open(pgn))
            book = root / "study.md"
            book.write_text("# Study\n\nText paragraph.\n", encoding="utf-8")
            application.open_book(book)
            try:
                result = api.set_language("en")

                self.assertTrue(result["ok"])
                self.assertEqual(api.lang, "en")
                snapshot = application.snapshot()
                self.assertEqual(snapshot["document"]["lang"], "en")
                self.assertEqual(snapshot["pgn"]["document"]["lang"], "en")
                self.assertEqual(snapshot["library"]["document"]["lang"], "en")
                self.assertEqual(snapshot["books"]["document"]["lang"], "en")
                self.assertEqual(snapshot["library"]["heading"], "Game library")
                self.assertEqual(snapshot["library"]["import"]["heading"], "Import into library")
                self.assertEqual(snapshot["books"]["heading"], "Chess book reader")
                self.assertEqual(Settings(settings_path).get("language"), "en")
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()

    def test_persistence_failure_rolls_stage1_v2_and_in_memory_setting_back(self) -> None:
        class FailingSettings:
            def __init__(self) -> None:
                self.data = {"language": "uk"}

            def get(self, key, default=None):
                return self.data.get(key, default)

            def set(self, key, value):
                self.data[key] = value
                raise RuntimeError("synthetic persistence failure")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = FailingSettings()
            _database, analysis, api, application = self._real_runtime(root, settings)
            try:
                result = api.set_language("en")

                self.assertFalse(result["ok"])
                self.assertEqual(api.lang, "uk")
                self.assertEqual(application.snapshot()["document"]["lang"], "uk")
                self.assertEqual(application.library.projection.language, UILanguage.UA)
                self.assertEqual(settings.data["language"], "uk")
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()

    def test_surface_failure_after_mutation_is_rolled_back_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings_path = root / "settings.json"
            settings = Settings(settings_path)
            _database, analysis, api, application = self._real_runtime(root, settings)
            projection = application.library.projection
            original = projection.set_language

            def failing(language):
                if language is UILanguage.EN:
                    projection._language = language
                    raise RuntimeError("synthetic render failure")
                return original(language)

            projection.set_language = failing
            try:
                result = api.set_language("en")

                self.assertFalse(result["ok"])
                self.assertEqual(api.lang, "uk")
                self.assertEqual(application.snapshot()["document"]["lang"], "uk")
                self.assertEqual(projection.language, UILanguage.UA)
                self.assertEqual(Settings(settings_path).get("language"), "uk")
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()

    def test_invalid_language_changes_nothing_and_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings_path = root / "settings.json"
            settings = Settings(settings_path)
            _database, analysis, api, application = self._real_runtime(root, settings)
            try:
                result = api.set_language("de")

                self.assertFalse(result["ok"])
                self.assertEqual(api.lang, "uk")
                self.assertEqual(application.snapshot()["document"]["lang"], "uk")
                self.assertEqual(Settings(settings_path).get("language"), "uk")
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()


if __name__ == "__main__":
    unittest.main()
