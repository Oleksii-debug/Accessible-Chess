from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI, run_version2_release_window


class _Event:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in tuple(self.handlers):
            handler()


class _Events:
    def __init__(self) -> None:
        self.before_show = _Event()
        self.loaded = _Event()


class _Window:
    def __init__(self) -> None:
        self.events = _Events()
        self.sources = []

    def evaluate_js(self, source):
        self.sources.append(source)


class _WebView:
    def __init__(self) -> None:
        self.window = _Window()

    def create_window(self, *_args, **_kwargs):
        return self.window

    def start(self, **_kwargs):
        self.window.events.before_show.fire()
        self.window.events.loaded.fire()


class W6Version2LanguageRenderRefreshTests(unittest.TestCase):
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
            position_sink=lambda _fen: {"ok": True},
        )
        api.bind_version2_application(application)
        return api, application, analysis

    def test_success_rebuilds_native_menu_and_wakes_browser_without_announcement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = mock.Mock()
            api, application, analysis = self._runtime(root, settings)
            refresh = mock.Mock(return_value=True)
            api.bind_version2_language_refresh(refresh)
            try:
                result = api.set_language("en")
                self.assertTrue(result["ok"])
                settings.set.assert_called_once_with("language", "en")
                refresh.assert_called_once_with()
                self.assertEqual(api.lang, "en")
                self.assertEqual(application.snapshot()["document"]["lang"], "en")
                self.assertEqual(
                    application.drain_events(),
                    ({"kind": "language", "payload": {}},),
                    "language-only refresh must wake the V2 poller without spoken text",
                )
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()

    def test_native_menu_refresh_failure_rolls_back_and_refreshes_previous_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = mock.Mock()
            api, application, analysis = self._runtime(root, settings)
            refresh = mock.Mock(side_effect=[False, True])
            api.bind_version2_language_refresh(refresh)
            try:
                result = api.set_language("en")
                self.assertFalse(result["ok"])
                self.assertEqual(
                    settings.set.call_args_list,
                    [mock.call("language", "en"), mock.call("language", "uk")],
                )
                self.assertEqual(refresh.call_count, 2)
                self.assertEqual(api.lang, "uk")
                self.assertEqual(application.snapshot()["document"]["lang"], "uk")
                self.assertEqual(
                    application.drain_events(),
                    ({"kind": "language", "payload": {}},),
                    "rollback must wake the renderer so stale new-language labels cannot remain",
                )
            finally:
                application.shutdown()
                analysis.close()
                api.close_analysis()

    def test_release_window_binds_language_refresh_to_the_same_native_menu_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = mock.Mock()
            api, application, analysis = self._runtime(root, settings)
            webview = _WebView()
            menu_installer = mock.Mock(return_value=True)
            try:
                run_version2_release_window(
                    api,
                    application,
                    webview_module=webview,
                    menu_installer=menu_installer,
                )
                self.assertEqual(menu_installer.call_count, 1)
                callback = api._version2_language_refresh
                self.assertIsNotNone(callback)
                self.assertTrue(callback())
                self.assertEqual(menu_installer.call_count, 2)
                first_window, first_controller = menu_installer.call_args_list[0].args
                second_window, second_controller = menu_installer.call_args_list[1].args
                self.assertIs(first_window, second_window)
                self.assertIs(first_controller, second_controller)
            finally:
                analysis.close()
                api.close_analysis()


if __name__ == "__main__":
    unittest.main()
