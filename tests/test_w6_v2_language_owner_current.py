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
from acs.version2_release_ui import (
    Version2ReleaseAccessibleChessAPI,
    run_version2_release_window,
)


PGN = (
    '[Event "Language owner"]\n'
    '[White "Петренко"]\n'
    '[Black "Smith"]\n'
    '[Result "*"]\n\n'
    '1. e4 e5 *\n'
)


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
        self.destroyed = False

    def evaluate_js(self, source) -> None:
        self.sources.append(source)

    def destroy(self) -> None:
        self.destroyed = True


class _WebView:
    def __init__(self) -> None:
        self.window = _Window()

    def create_window(self, _title, **_kwargs):
        return self.window

    def start(self, **_kwargs) -> None:
        self.window.events.before_show.fire()
        self.window.events.loaded.fire()


class _HostApplication:
    def __init__(self, *, language: UILanguage = UILanguage.UA) -> None:
        from acs.version2_profile import (
            build_version2_router,
            build_version2_shell,
            build_version2_webview_adapter,
        )

        self.shell = build_version2_shell(language=language)
        self.router = build_version2_router(self.shell, lambda action, payload: {"action": action})
        self.adapter = build_version2_webview_adapter(self.shell, self.router)
        self._focus = ""
        self.closed = False

    def snapshot(self):
        return {**self.adapter.snapshot(), "pgn": None, "library": {}, "books": None}

    def browser_command(self, _area, _command, _payload=None):
        return {"kind": "ok", "payload": {}}

    def drain_events(self):
        return ()

    def record_focus(self, token):
        self._focus = token

    def native_command(self, _value):
        return None

    def shutdown(self):
        self.closed = True
        return True


class W6Version2LanguageOwnerCurrentTests(unittest.TestCase):
    def _real_application(self, root: Path, settings: Settings):
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
        )
        api.bind_version2_application(application)
        return api, application, analysis

    def _materialize_real_pgn_and_books(self, application: Version2Application, root: Path) -> None:
        application.set_document(PgnDocumentSession.from_text(PGN))
        book = root / "language-owner.md"
        book.write_text(
            "# Мовний тест\n\nАбзац для перевірки реальної Books projection.\n",
            encoding="utf-8",
        )
        application.open_book(book)
        snapshot = application.snapshot()
        self.assertIsNotNone(snapshot["pgn"])
        self.assertIsNotNone(snapshot["books"])
        application.drain_events()

    def _assert_all_snapshot_languages(self, application: Version2Application, expected: str) -> None:
        snapshot = application.snapshot()
        self.assertEqual(snapshot["document"]["lang"], expected)
        self.assertEqual(snapshot["pgn"]["document"]["lang"], expected)
        self.assertEqual(snapshot["library"]["document"]["lang"], expected)
        self.assertEqual(snapshot["books"]["document"]["lang"], expected)

    def _close_real_application(self, api, application, analysis) -> None:
        application.shutdown()
        analysis.close()
        api.close_analysis()

    def test_production_factory_initializes_stage1_and_v2_from_one_settings_language(self) -> None:
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
                mock.patch.object(
                    release_app,
                    "EngineAssistedWorkflowService",
                    return_value=mock.MagicMock(),
                ),
                mock.patch.object(release_app, "SoundRuntime", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "GameSoundRuntime", return_value=mock.MagicMock()),
                mock.patch.object(
                    release_app,
                    "Version2ReleaseAccessibleChessAPI",
                    return_value=api,
                ) as api_class,
                mock.patch.object(release_app, "AcsDatabase", return_value=database),
                mock.patch.object(
                    release_app,
                    "Version2Application",
                    return_value=application,
                ) as application_class,
                mock.patch.object(release_app, "_share_v2_action_registry"),
            ):
                release_app.create_version2_release_application(
                    runtime_factory=lambda _config: runtime,
                    sound_playback=object(),
                )

            self.assertEqual(api_class.call_args.kwargs.get("lang"), "en")
            self.assertEqual(
                application_class.call_args.kwargs.get("language"),
                UILanguage.EN,
            )

    def test_live_switch_persists_for_restart_and_syncs_real_surfaces_silently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(root / "settings.json")
            api, application, analysis = self._real_application(root, settings)
            self._materialize_real_pgn_and_books(application, root)
            self._assert_all_snapshot_languages(application, "uk")
            native_refresh = mock.Mock(return_value=True)
            api.bind_version2_language_refresh(native_refresh)
            try:
                result = api.set_language("en")
                self.assertTrue(result["ok"])
                self.assertEqual(Settings(root / "settings.json").get("language"), "en")
                self.assertEqual(api.lang, "en")
                self.assertEqual(application.shell.language, UILanguage.EN)
                self.assertEqual(application.pgn.projection.language, UILanguage.EN)
                self.assertEqual(application.library.projection.language, UILanguage.EN)
                self.assertEqual(application.books.projection.language, UILanguage.EN)
                self._assert_all_snapshot_languages(application, "en")
                native_refresh.assert_called_once_with()

                events = application.drain_events()
                self.assertEqual(events, ({"kind": "language", "payload": {}},))
                self.assertNotIn("announcement", events[0]["payload"])
                self.assertNotIn("message", events[0]["payload"])
            finally:
                self._close_real_application(api, application, analysis)

    def test_persistence_failure_restores_settings_memory_and_leaves_real_surfaces_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(root / "settings.json")
            api, application, analysis = self._real_application(root, settings)
            self._materialize_real_pgn_and_books(application, root)
            settings.save = mock.Mock(side_effect=OSError("disk unavailable"))
            try:
                result = api.set_language("en")
                self.assertFalse(result["ok"])
                self.assertEqual(settings.get("language"), "uk")
                self.assertEqual(api.lang, "uk")
                self.assertEqual(application.shell.language, UILanguage.UA)
                self.assertEqual(application.pgn.projection.language, UILanguage.UA)
                self.assertEqual(application.library.projection.language, UILanguage.UA)
                self.assertEqual(application.books.projection.language, UILanguage.UA)
                self._assert_all_snapshot_languages(application, "uk")
                self.assertFalse(application.drain_events())
            finally:
                self._close_real_application(api, application, analysis)

    def test_host_refresh_failure_rolls_back_durable_settings_real_surfaces_and_native_menu(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(root / "settings.json")
            api, application, analysis = self._real_application(root, settings)
            self._materialize_real_pgn_and_books(application, root)
            native_refresh = mock.Mock(side_effect=[False, True])
            api.bind_version2_language_refresh(native_refresh)
            try:
                result = api.set_language("en")
                self.assertFalse(result["ok"])
                self.assertEqual(Settings(root / "settings.json").get("language"), "uk")
                self.assertEqual(settings.get("language"), "uk")
                self.assertEqual(api.lang, "uk")
                self.assertEqual(application.shell.language, UILanguage.UA)
                self.assertEqual(application.pgn.projection.language, UILanguage.UA)
                self.assertEqual(application.library.projection.language, UILanguage.UA)
                self.assertEqual(application.books.projection.language, UILanguage.UA)
                self._assert_all_snapshot_languages(application, "uk")
                self.assertEqual(native_refresh.call_count, 2)

                events = application.drain_events()
                self.assertEqual(events, ({"kind": "language", "payload": {}},))
                self.assertNotIn("announcement", events[0]["payload"])
                self.assertNotIn("message", events[0]["payload"])
            finally:
                self._close_real_application(api, application, analysis)

    def test_release_window_uses_shell_language_for_initial_menu_and_binds_live_refresh_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = Version2ReleaseAccessibleChessAPI(
                keymap_path=root / "keymap.json",
                settings=mock.Mock(),
                lang="en",
            )
            application = _HostApplication(language=UILanguage.EN)
            webview = _WebView()
            installs = []

            run_version2_release_window(
                api,
                application,
                webview_module=webview,
                menu_installer=lambda window, controller: installs.append((window, controller)) or True,
            )

            self.assertEqual(len(installs), 1)
            controller = installs[0][1]
            self.assertEqual(controller.spec()[0].label, "&File")
            self.assertIsNotNone(api._version2_language_refresh)
            self.assertTrue(application.closed)


if __name__ == "__main__":
    unittest.main()
