from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import acs.version2_release_app as release_app


class Version2CompositionStartupCleanupTests(unittest.TestCase):
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
                mock.patch.object(release_app, "_prepare_version2_user_data", return_value=self._layout(root)),
                mock.patch.object(release_app, "AnalysisService", side_effect=RuntimeError("analysis init failed")),
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
            engine_play = mock.Mock()
            with (
                mock.patch.object(release_app, "_prepare_version2_user_data", return_value=self._layout(root)),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(release_app, "ContinuousAnalysisService", return_value=continuous),
                mock.patch.object(release_app, "EnginePlayService", return_value=engine_play),
                mock.patch.object(release_app, "Settings", side_effect=RuntimeError("settings init failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "settings init failed"):
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            continuous.close.assert_called_once_with()
            analysis.close.assert_called_once_with()
            runtime.close.assert_called_once_with()

    def test_cleanup_failure_preserves_primary_startup_error_and_continues_unwind(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            analysis = mock.Mock()
            continuous = mock.Mock()
            continuous.close.side_effect = RuntimeError("cleanup failed")
            with (
                mock.patch.object(release_app, "_prepare_version2_user_data", return_value=self._layout(root)),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(release_app, "ContinuousAnalysisService", return_value=continuous),
                mock.patch.object(release_app, "EnginePlayService", return_value=mock.Mock()),
                mock.patch.object(release_app, "Settings", side_effect=RuntimeError("primary startup failure")),
            ):
                with self.assertRaisesRegex(RuntimeError, "primary startup failure"):
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            continuous.close.assert_called_once_with()
            analysis.close.assert_called_once_with()
            runtime.close.assert_called_once_with()

    def test_database_construction_failure_closes_complete_engine_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock()
            runtime.provider = mock.Mock()
            analysis = mock.Mock()
            continuous = mock.Mock()
            engine_play = mock.Mock()
            settings = mock.Mock()
            settings.data = {"language": "uk"}
            settings.get.side_effect = lambda key, default=None: settings.data.get(key, default)
            sound_runtime = mock.Mock()
            game_sounds = mock.Mock()
            api = mock.Mock()

            with (
                mock.patch.object(release_app, "_prepare_version2_user_data", return_value=self._layout(root)),
                mock.patch.object(release_app, "AnalysisService", return_value=analysis),
                mock.patch.object(release_app, "ContinuousAnalysisService", return_value=continuous),
                mock.patch.object(release_app, "EnginePlayService", return_value=engine_play),
                mock.patch.object(release_app, "Settings", return_value=settings),
                mock.patch.object(release_app, "SoundRuntime", return_value=sound_runtime),
                mock.patch.object(release_app, "GameSoundRuntime", return_value=game_sounds),
                mock.patch.object(release_app, "Version2ReleaseAccessibleChessAPI", return_value=api),
                mock.patch.object(release_app, "AcsDatabase", side_effect=OSError("database init failed")),
            ):
                with self.assertRaisesRegex(OSError, "database init failed"):
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                    )

            continuous.close.assert_called_once_with()
            analysis.close.assert_called_once_with()
            runtime.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
