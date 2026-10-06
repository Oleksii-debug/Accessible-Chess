from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import acs.version2_release_app as release_app


class Version2CompositionStartupCleanupCurrentTests(unittest.TestCase):
    def _layout(self, root: Path):
        return SimpleNamespace(
            root=root,
            settings_path=root / "settings.json",
            library_path=root / "library.acsdb",
        )

    def test_analysis_construction_failure_closes_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            with (
                mock.patch.object(
                    release_app,
                    "_prepare_version2_user_data",
                    return_value=self._layout(root),
                ),
                mock.patch.object(
                    release_app,
                    "AnalysisService",
                    side_effect=RuntimeError("analysis init failed"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "analysis init failed"):
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            runtime.close.assert_called_once_with()

    def test_settings_construction_failure_closes_partial_engine_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            analysis = mock.Mock()
            continuous = mock.Mock()
            with (
                mock.patch.object(
                    release_app,
                    "_prepare_version2_user_data",
                    return_value=self._layout(root),
                ),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(
                    release_app,
                    "ContinuousAnalysisService",
                    return_value=continuous,
                ),
                mock.patch.object(
                    release_app,
                    "EnginePlayService",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "Settings",
                    side_effect=RuntimeError("settings init failed"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "settings init failed"):
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            continuous.close.assert_called_once_with()
            analysis.close.assert_called_once_with()
            runtime.close.assert_called_once_with()

    def test_cleanup_failure_preserves_primary_error_and_continues_unwind(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            analysis = mock.Mock()
            continuous = mock.Mock()
            continuous.close.side_effect = RuntimeError("cleanup failed")
            with (
                mock.patch.object(
                    release_app,
                    "_prepare_version2_user_data",
                    return_value=self._layout(root),
                ),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(
                    release_app,
                    "ContinuousAnalysisService",
                    return_value=continuous,
                ),
                mock.patch.object(
                    release_app,
                    "EnginePlayService",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "Settings",
                    side_effect=RuntimeError("primary startup failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "primary startup failure"):
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            continuous.close.assert_called_once_with()
            analysis.close.assert_called_once_with()
            runtime.close.assert_called_once_with()

    def test_abort_class_startup_failure_preserves_primary_and_contains_abort_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            analysis = mock.Mock()
            continuous = mock.Mock()

            class StartupAbort(BaseException):
                pass

            class CleanupAbort(BaseException):
                pass

            primary = StartupAbort("primary startup abort")
            continuous.close.side_effect = CleanupAbort("cleanup abort")
            with (
                mock.patch.object(
                    release_app,
                    "_prepare_version2_user_data",
                    return_value=self._layout(root),
                ),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(
                    release_app,
                    "ContinuousAnalysisService",
                    return_value=continuous,
                ),
                mock.patch.object(
                    release_app,
                    "EnginePlayService",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(release_app, "Settings", side_effect=primary),
            ):
                with self.assertRaises(StartupAbort) as caught:
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            self.assertIs(caught.exception, primary)
            continuous.close.assert_called_once_with()
            analysis.close.assert_called_once_with()
            runtime.close.assert_called_once_with()

    def test_abort_class_close_guard_install_failure_retires_unbound_runtime(self) -> None:
        class GuardAbort(BaseException):
            pass

        runtime = mock.Mock()
        runtime.shutdown.return_value = True
        application = mock.Mock()
        owner = mock.Mock()
        dialogs = mock.Mock()
        primary = GuardAbort("guard abort")

        with mock.patch.object(
            release_app,
            "_install_unsaved_pgn_close_guard",
            side_effect=primary,
        ):
            with self.assertRaises(GuardAbort) as caught:
                release_app._install_close_guard_or_shutdown(
                    runtime,
                    application,
                    owner,
                    dialogs,
                )

        self.assertIs(caught.exception, primary)
        runtime.shutdown.assert_called_once_with()

    def test_abort_class_close_guard_failure_preserves_primary_when_runtime_cleanup_aborts(self) -> None:
        class GuardAbort(BaseException):
            pass

        class CleanupAbort(BaseException):
            pass

        runtime = mock.Mock()
        runtime.shutdown.side_effect = CleanupAbort("cleanup abort")
        application = mock.Mock()
        owner = mock.Mock()
        dialogs = mock.Mock()
        primary = GuardAbort("guard abort")

        with mock.patch.object(
            release_app,
            "_install_unsaved_pgn_close_guard",
            side_effect=primary,
        ):
            with self.assertRaises(GuardAbort) as caught:
                release_app._install_close_guard_or_shutdown(
                    runtime,
                    application,
                    owner,
                    dialogs,
                )

        self.assertIs(caught.exception, primary)
        runtime.shutdown.assert_called_once_with()

    def test_book_worker_construction_abort_retires_existing_file_runtime(self) -> None:
        class BookWorkerAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            analysis = mock.Mock()
            continuous = mock.Mock()
            settings = mock.Mock()
            settings.data = {"language": "uk"}
            settings.get.side_effect = lambda key, default=None: settings.data.get(key, default)
            api = mock.Mock()
            application = mock.Mock()
            application.shell.language = release_app.UILanguage.UA
            application.pgn_commands.export_selected = mock.Mock()
            file_runtime = mock.Mock()
            file_runtime.shutdown.return_value = True
            resume = mock.Mock()
            primary = BookWorkerAbort("book worker construction abort")

            with (
                mock.patch.object(
                    release_app,
                    "_prepare_version2_user_data",
                    return_value=self._layout(root),
                ),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(
                    release_app,
                    "ContinuousAnalysisService",
                    return_value=continuous,
                ),
                mock.patch.object(
                    release_app,
                    "EnginePlayService",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(release_app, "Settings", return_value=settings),
                mock.patch.object(
                    release_app,
                    "PackagedSoundAssetResolver",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "_sound_variant_provider",
                    return_value=lambda: "default",
                ),
                mock.patch.object(release_app, "SoundRuntime", return_value=mock.Mock()),
                mock.patch.object(
                    release_app,
                    "GameSoundRuntime",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "LocalProfileStore",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "Version2ProfileAccessibleChessAPI",
                    return_value=api,
                ),
                mock.patch.object(
                    release_app,
                    "Version2GameTreeResumeCoordinator",
                    return_value=resume,
                ),
                mock.patch.object(release_app, "AcsDatabase", return_value=mock.Mock()),
                mock.patch.object(
                    release_app,
                    "BookProgressStore",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "EngineAssistedWorkflowService",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "Version2Application",
                    return_value=application,
                ),
                mock.patch.object(
                    release_app,
                    "_share_v2_action_registry",
                    return_value=None,
                ),
                mock.patch.object(
                    release_app,
                    "Version2WindowsFileWorkflowRuntime",
                    return_value=file_runtime,
                ),
                mock.patch.object(
                    release_app,
                    "Version2WinFormsUiPoster",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "Version2BookOpenWorker",
                    side_effect=primary,
                ),
            ):
                _api, build_application, _engine, native_runtime_factory = (
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                        defer_ui=True,
                    )
                )
                build_application()
                with self.assertRaises(BookWorkerAbort) as caught:
                    native_runtime_factory(mock.Mock())

            self.assertIs(caught.exception, primary)
            file_runtime.shutdown.assert_called_once_with()
            application.bind_book_open_worker.assert_not_called()

    def test_database_construction_failure_closes_engine_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            analysis = mock.Mock()
            continuous = mock.Mock()
            settings = mock.Mock()
            settings.data = {"language": "uk"}
            settings.get.side_effect = lambda key, default=None: settings.data.get(key, default)
            with (
                mock.patch.object(
                    release_app,
                    "_prepare_version2_user_data",
                    return_value=self._layout(root),
                ),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(
                    release_app,
                    "ContinuousAnalysisService",
                    return_value=continuous,
                ),
                mock.patch.object(
                    release_app,
                    "EnginePlayService",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(release_app, "Settings", return_value=settings),
                mock.patch.object(release_app, "SoundRuntime", return_value=mock.Mock()),
                mock.patch.object(
                    release_app,
                    "GameSoundRuntime",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "Version2ReleaseAccessibleChessAPI",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "AcsDatabase",
                    side_effect=OSError("database init failed"),
                ),
            ):
                with self.assertRaisesRegex(OSError, "database init failed"):
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            continuous.close.assert_called_once_with()
            analysis.close.assert_called_once_with()
            runtime.close.assert_called_once_with()

    def test_database_cleanup_failure_does_not_mask_application_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            analysis = mock.Mock()
            continuous = mock.Mock()
            settings = mock.Mock()
            settings.data = {"language": "uk"}
            settings.get.side_effect = lambda key, default=None: settings.data.get(key, default)
            database = mock.Mock()
            database.close.side_effect = RuntimeError("database cleanup failed")
            with (
                mock.patch.object(
                    release_app,
                    "_prepare_version2_user_data",
                    return_value=self._layout(root),
                ),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(
                    release_app,
                    "ContinuousAnalysisService",
                    return_value=continuous,
                ),
                mock.patch.object(
                    release_app,
                    "EnginePlayService",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(release_app, "Settings", return_value=settings),
                mock.patch.object(release_app, "SoundRuntime", return_value=mock.Mock()),
                mock.patch.object(
                    release_app,
                    "GameSoundRuntime",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "Version2ReleaseAccessibleChessAPI",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(release_app, "AcsDatabase", return_value=database),
                mock.patch.object(
                    release_app,
                    "EngineAssistedWorkflowService",
                    return_value=mock.Mock(),
                ),
                mock.patch.object(
                    release_app,
                    "Version2Application",
                    side_effect=RuntimeError("application init failed"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "application init failed"):
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            database.close.assert_called_once_with()
            continuous.close.assert_called_once_with()
            analysis.close.assert_called_once_with()
            runtime.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
