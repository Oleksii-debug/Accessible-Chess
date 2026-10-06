from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import acs.version2_release_app as release_app


class Version2CompositionPublicationBoundaryTests(unittest.TestCase):
    def _layout(self, root: Path):
        return SimpleNamespace(
            root=root,
            settings_path=root / "settings.json",
            library_path=root / "library.acsdb",
        )

    def _exercise_failure(self, *, boundary: str, message: str) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = mock.Mock(name="engine_runtime")
            runtime.provider = mock.Mock(name="engine_provider")
            analysis = mock.Mock(name="analysis")
            continuous = mock.Mock(name="continuous")
            engine_play = mock.Mock(name="engine_play")
            settings = mock.Mock(name="settings")
            settings.data = {"language": "uk"}
            settings.get.side_effect = (
                lambda key, default=None: settings.data.get(key, default)
            )
            sound_runtime = mock.Mock(name="sound_runtime")
            game_sounds = mock.Mock(name="game_sounds")
            api = mock.Mock(name="api")
            database = mock.Mock(name="database")
            candidate = mock.Mock(name="candidate")
            resume = mock.Mock(name="resume_coordinator")
            share_registry = mock.Mock(name="share_v2_action_registry")

            if boundary == "restore":
                resume.restore.side_effect = RuntimeError(message)
            elif boundary == "registry":
                share_registry.side_effect = RuntimeError(message)
            elif boundary == "bind":
                api.bind_version2_application.side_effect = RuntimeError(message)
            else:
                raise AssertionError(f"unknown failure boundary: {boundary}")

            with ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "_prepare_version2_user_data",
                        return_value=self._layout(root),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "Version2GameTreeResumeCoordinator",
                        return_value=resume,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "AnalysisService",
                        return_value=analysis,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "ContinuousAnalysisService",
                        return_value=continuous,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "EnginePlayService",
                        return_value=engine_play,
                    )
                )
                stack.enter_context(
                    mock.patch.object(release_app, "Settings", return_value=settings)
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "SoundRuntime",
                        return_value=sound_runtime,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "GameSoundRuntime",
                        return_value=game_sounds,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "Version2ReleaseAccessibleChessAPI",
                        return_value=api,
                    )
                )
                database_factory = stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "AcsDatabase",
                        return_value=database,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "Version2Application",
                        return_value=candidate,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "BookProgressStore",
                        return_value=mock.Mock(),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "EngineAssistedWorkflowService",
                        return_value=mock.Mock(),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        release_app,
                        "_share_v2_action_registry",
                        new=share_registry,
                    )
                )

                composed_api, build_application, composed_runtime, native_runtime_factory = (
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=object(),
                        defer_ui=True,
                    )
                )
                self.assertIs(composed_api, api)
                self.assertIs(composed_runtime, runtime)

                with self.assertRaisesRegex(RuntimeError, message):
                    build_application()

                database.close.assert_called_once_with()
                continuous.close.assert_called_once_with()
                analysis.close.assert_called_once_with()
                runtime.close.assert_called_once_with()

                with self.assertRaisesRegex(
                    RuntimeError,
                    "Version 2 application construction previously failed",
                ):
                    build_application()
                database_factory.assert_called_once_with(root / "library.acsdb")

                with self.assertRaisesRegex(
                    RuntimeError,
                    "Version 2 application must be constructed on the native UI first",
                ):
                    native_runtime_factory(object())

            resume.restore.assert_called_once_with(candidate)
            if boundary == "restore":
                share_registry.assert_not_called()
                api.bind_version2_application.assert_not_called()
            elif boundary == "registry":
                share_registry.assert_called_once_with(api, candidate)
                api.bind_version2_application.assert_not_called()
            else:
                share_registry.assert_called_once_with(api, candidate)
                api.bind_version2_application.assert_called_once_with(candidate)

    def test_resume_failure_never_publishes_partial_application(self) -> None:
        self._exercise_failure(
            boundary="restore",
            message="resume restore failed",
        )

    def test_registry_failure_never_publishes_partial_application(self) -> None:
        self._exercise_failure(
            boundary="registry",
            message="registry share failed",
        )

    def test_bind_failure_never_publishes_partial_application(self) -> None:
        self._exercise_failure(
            boundary="bind",
            message="application bind failed",
        )


if __name__ == "__main__":
    unittest.main()
