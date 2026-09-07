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
from acs.version2_application import Version2Application
import acs.version2_release_app as release_app
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


class Version2PersistedLanguageIntegrationTests(unittest.TestCase):
    def test_production_factory_uses_persisted_language_for_stage1_and_v2(self) -> None:
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

    def _runtime(self, root: Path, settings: mock.Mock):
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
            board_dispatch=lambda *_args, **_kwargs: {"ok": True},
            board_position_projector=lambda _fen: None,
        )
        api.bind_version2_application(application)
        return api, application, analysis

    def test_runtime_language_change_persists_and_synchronizes_v2_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = mock.Mock()
            api, application, analysis = self._runtime(root, settings)
            try:
                result = api.set_language("en")
                self.assertTrue(result["ok"])
                settings.set.assert_called_once_with("language", "en")
                self.assertEqual(api.lang, "en")
                self.assertEqual(api.keymap_service.editor.lang, "en")
                snapshot = application.snapshot()
                self.assertEqual(snapshot["document"]["lang"], "en")
                self.assertEqual(snapshot["library"]["document"]["lang"], "en")
                self.assertEqual(application.shell.language, UILanguage.EN)
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()

    def test_persistence_failure_rolls_back_all_live_language_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = mock.Mock()
            settings.set.side_effect = RuntimeError("disk failure")
            api, application, analysis = self._runtime(root, settings)
            try:
                result = api.set_language("en")
                self.assertFalse(result["ok"])
                self.assertEqual(api.lang, "uk")
                self.assertEqual(api.keymap_service.editor.lang, "uk")
                snapshot = application.snapshot()
                self.assertEqual(snapshot["document"]["lang"], "uk")
                self.assertEqual(snapshot["library"]["document"]["lang"], "uk")
                self.assertEqual(application.shell.language, UILanguage.UA)
                self.assertNotIn("disk failure", result["announcement"])
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()

    def test_invalid_language_does_not_persist_or_split_v2_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = mock.Mock()
            api, application, analysis = self._runtime(root, settings)
            try:
                result = api.set_language("xx")
                self.assertFalse(result["ok"])
                settings.set.assert_not_called()
                self.assertEqual(api.lang, "uk")
                self.assertEqual(application.shell.language, UILanguage.UA)
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()


if __name__ == "__main__":
    unittest.main()
