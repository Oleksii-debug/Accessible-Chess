from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from acs.acsdb import AcsDatabase
from acs.full_product_ui_shell import UILanguage
from acs.library_export_service import LibraryExportRequest, LibraryExportService
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery
from acs.version2_application import Version2Application
from acs.version2_release_app import _build_version2_windows_file_runtime
from acs.version2_windows_library_export import (
    LibraryExportHostEvent,
    LibraryExportHostEventKind,
    build_version2_windows_library_file_runtime,
)


class Version2LibraryExportReleaseReachabilityTests(unittest.TestCase):
    def test_release_runtime_composes_canonical_library_export_service(self) -> None:
        library_service = object()
        file_events = Mock()
        import_ui_ready = Mock()
        export_selected = Mock()
        worker_factory_result = Mock()
        worker_factory = Mock(return_value=worker_factory_result)
        board_dispatch = Mock()
        dialog_language_provider = Mock(return_value="uk")
        session = object()

        application = SimpleNamespace(
            library_export=library_service,
            _file_event=file_events,
            session=session,
            worker_factory=worker_factory,
            pgn_commands=SimpleNamespace(export_selected=export_selected),
            import_ui_ready=import_ui_ready,
            _focus="library-results",
            confirm_document_replace=lambda: False,
            set_document=Mock(),
        )
        api = SimpleNamespace(v2_board_dispatch=board_dispatch)
        database_path = Path("library.acsdb")
        owner = object()
        runtime = object()

        with patch(
            "acs.version2_release_app.build_version2_windows_library_file_runtime",
            return_value=runtime,
        ) as builder:
            result = _build_version2_windows_file_runtime(
                application=application,
                api=api,
                database_path=database_path,
                owner_control=owner,
                dialog_language_provider=dialog_language_provider,
            )

        self.assertIs(result, runtime)
        builder.assert_called_once()
        kwargs = builder.call_args.kwargs
        self.assertIs(kwargs["owner_control"], owner)
        self.assertIs(kwargs["library_service"], library_service)
        self.assertIs(kwargs["library_export_event_sink"], file_events)
        self.assertIs(kwargs["pgn_export_event_sink"], file_events)
        self.assertIs(kwargs["export_selected"], export_selected)
        self.assertIs(kwargs["import_ui_ready"], import_ui_ready)
        self.assertIs(kwargs["next_delegate"], board_dispatch)
        self.assertIs(kwargs["dialog_language_provider"], dialog_language_provider)
        self.assertIs(kwargs["get_pgn_session"](), session)
        self.assertEqual(kwargs["current_focus_provider"](), "library-results")
        worker_factory.assert_called_once_with(database_path)
        self.assertIs(kwargs["import_services_factory"], worker_factory_result)

    def test_release_library_export_sink_stays_path_free_presentation_boundary(self) -> None:
        file_events = Mock()
        application = SimpleNamespace(
            library_export=object(),
            _file_event=file_events,
            session=None,
            worker_factory=Mock(return_value=Mock()),
            pgn_commands=SimpleNamespace(export_selected=Mock()),
            import_ui_ready=Mock(),
            _focus="library-results",
            confirm_document_replace=lambda: True,
            set_document=Mock(),
        )
        api = SimpleNamespace(v2_board_dispatch=Mock())

        with patch(
            "acs.version2_release_app.build_version2_windows_library_file_runtime",
            return_value=object(),
        ) as builder:
            _build_version2_windows_file_runtime(
                application=application,
                api=api,
                database_path=Path("library.acsdb"),
                owner_control=object(),
                dialog_language_provider=lambda: "en",
            )

        kwargs = builder.call_args.kwargs
        self.assertIs(kwargs["library_export_event_sink"], application._file_event)
        self.assertNotIn("destination", kwargs)
        self.assertNotIn("path", kwargs)


    def test_real_runtime_chain_rejects_browser_destination_before_native_dialog(self) -> None:
        class Owner:
            IsDisposed = False
            Disposing = False
            InvokeRequired = False

            def BeginInvoke(self, delegate):  # noqa: N802
                raise AssertionError("invalid Library export must not post UI work")

        database = AcsDatabase()
        try:
            application = SimpleNamespace(
                library_export=LibraryExportService(database),
                _file_event=Mock(),
                session=None,
                worker_factory=Mock(return_value=lambda: None),
                pgn_commands=SimpleNamespace(export_selected=Mock()),
                import_ui_ready=Mock(),
                _focus="library-results",
                confirm_document_replace=lambda: True,
                set_document=Mock(),
            )
            runtime = _build_version2_windows_file_runtime(
                application=application,
                api=SimpleNamespace(v2_board_dispatch=Mock()),
                database_path=Path("library.acsdb"),
                owner_control=Owner(),
                dialog_language_provider=lambda: "uk",
            )
            try:
                event = runtime(
                    "library.export",
                    {
                        "scope": "selected",
                        "game_ids": [1],
                        "path": r"C:\\Users\\Private\\stolen.pgn",
                    },
                )
                self.assertEqual(event.kind, LibraryExportHostEventKind.FAILED)
                self.assertEqual(event.error_code, "invalid_export_request")
                self.assertEqual(event.focus_target, "library-results")
                self.assertNotIn("stolen.pgn", repr(event))
                application._file_event.assert_called_once_with(event)
            finally:
                self.assertTrue(runtime.shutdown())
        finally:
            database.close()


    def test_production_helper_reaches_canonical_writer_through_trusted_delegate(self) -> None:
        pgn = """[Event "Release reachability"]
[Site "Bratislava"]
[Date "2026.09.27"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *
"""
        class Owner:
            IsDisposed = False
            Disposing = False
            InvokeRequired = False

            def BeginInvoke(self, delegate):  # noqa: N802
                raise AssertionError("synchronous export must not post UI work")

        class Dialogs:
            def __init__(self, destination: Path) -> None:
                self.destination = destination
                self.calls: list[str] = []

            def export_selection(self, suggested_filename: str = "selection.pgn") -> Path:
                self.calls.append(suggested_filename)
                return self.destination

        database = AcsDatabase()
        try:
            database.import_pgn_text(pgn, source_name="release-reachability.pgn")
            row = database.conn.execute("SELECT id FROM games").fetchone()
            self.assertIsNotNone(row)
            game_id = int(row[0])
            service = LibraryExportService(database)

            with tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / "Обрані партії.pgn"
                dialogs = Dialogs(destination)
                application = SimpleNamespace(
                    library_export=service,
                    _file_event=Mock(),
                    session=None,
                    worker_factory=Mock(return_value=lambda: None),
                    pgn_commands=SimpleNamespace(export_selected=Mock()),
                    import_ui_ready=Mock(),
                    _focus="library-results",
                    confirm_document_replace=lambda: True,
                    set_document=Mock(),
                )
                with patch(
                    "acs.version2_windows_library_export.Version2OwnedWindowsPgnExportDialogs",
                    return_value=dialogs,
                ):
                    runtime = _build_version2_windows_file_runtime(
                        application=application,
                        api=SimpleNamespace(v2_board_dispatch=Mock()),
                        database_path=Path("library.acsdb"),
                        owner_control=Owner(),
                        dialog_language_provider=lambda: "uk",
                    )
                try:
                    event = runtime(
                        "library.export",
                        LibraryExportRequest.selected([game_id]).browser_payload(),
                    )
                    reopened = open_pgn(destination)
                finally:
                    self.assertTrue(runtime.shutdown())

            self.assertEqual(event.kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(event.game_count, 1)
            self.assertEqual(event.focus_target, "library-results")
            self.assertEqual(dialogs.calls, ["library-export.pgn"])
            self.assertEqual(len(reopened.games), 1)
            self.assertEqual(reopened.games[0].tags["Event"], "Release reachability")
            self.assertNotIn(str(destination), repr(event))
            application._file_event.assert_called_once_with(event)
        finally:
            database.close()


    def test_library_export_events_use_existing_localized_path_free_status_projection(self) -> None:
        fake = SimpleNamespace(
            _events=[],
            shell=SimpleNamespace(language=UILanguage.UA),
            _error=lambda: {
                "kind": "error",
                "payload": {"message": "The action could not be completed."},
            },
        )
        exported = LibraryExportHostEvent(
            LibraryExportHostEventKind.EXPORTED,
            focus_target="library-results",
            game_count=2,
        )
        Version2Application._file_event(fake, exported)
        self.assertEqual(
            fake._events,
            [
                {
                    "kind": "status",
                    "payload": {
                        "announcement": "Експорт завершено.",
                        "focus_target": "library-results",
                    },
                }
            ],
        )

        fake._events.clear()
        fake.shell.language = UILanguage.EN
        cancelled = LibraryExportHostEvent(
            LibraryExportHostEventKind.DIALOG_CANCELLED,
            focus_target="library-results",
        )
        Version2Application._file_event(fake, cancelled)
        self.assertEqual(
            fake._events,
            [
                {
                    "kind": "status",
                    "payload": {
                        "announcement": "Cancelled.",
                        "focus_target": "library-results",
                    },
                }
            ],
        )

        fake._events.clear()
        failed = LibraryExportHostEvent(
            LibraryExportHostEventKind.FAILED,
            focus_target="library-export-filtered",
            error_code="library_export_failed",
        )
        Version2Application._file_event(fake, failed)
        self.assertEqual(fake._events[-1]["kind"], "error")
        self.assertEqual(
            fake._events[-1]["payload"]["focus_target"],
            "library-export-filtered",
        )
        self.assertNotIn("library_export_failed", repr(fake._events[-1]))

        fake._events.clear()
        invalid_focus = LibraryExportHostEvent(
            LibraryExportHostEventKind.DIALOG_CANCELLED,
            focus_target="not a valid dom id",
        )
        Version2Application._file_event(fake, invalid_focus)
        self.assertEqual(
            fake._events,
            [{"kind": "status", "payload": {"announcement": "Cancelled."}}],
        )

        fake._events.clear()
        pgn_saved = SimpleNamespace(
            kind=SimpleNamespace(value="pgn_saved"),
            action_id="pgn.save",
            focus_target="pgn-save-control",
        )
        Version2Application._file_event(fake, pgn_saved)
        self.assertEqual(
            fake._events,
            [{"kind": "status", "payload": {"announcement": "PGN saved."}}],
        )
        self.assertNotIn("focus_target", fake._events[-1]["payload"])


    def test_release_bootstrap_restores_library_status_focus_without_repaint(self) -> None:
        source = (
            Path(__file__).parents[1] / "web" / "version2_release_bootstrap.js"
        ).read_text(encoding="utf-8")
        candidate = source.index(
            'const candidate = typeof payload.focus_target === "string"'
        )
        dispatch = source.index(
            "const refreshRequired = applyQueuedEvent(event, orderedStage1Refreshes);"
        )
        self.assertLess(candidate, dispatch)
        self.assertIn(
            "} else if (queuedFocusTarget) {\n        focusById(queuedFocusTarget);",
            source,
        )
        self.assertIn(
            'actionId === "library.export";',
            source,
        )

    def test_production_helper_exports_full_filtered_result_through_same_native_chain(self) -> None:
        pgn = """[Event "Filtered Cup"]
[Site "Bratislava"]
[Date "2026.09.27"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *

[Event "Filtered Cup"]
[Site "Košice"]
[Date "2026.09.27"]
[Round "2"]
[White "Gamma"]
[Black "Delta"]
[Result "*"]

1. d4 d5 *

[Event "Other Event"]
[Site "Nitra"]
[Date "2026.09.27"]
[Round "3"]
[White "Epsilon"]
[Black "Zeta"]
[Result "*"]

1. c4 c5 *
"""

        class Owner:
            IsDisposed = False
            Disposing = False
            InvokeRequired = False

            def BeginInvoke(self, delegate):  # noqa: N802
                raise AssertionError("synchronous export must not post UI work")

        class Dialogs:
            def __init__(self, destination: Path) -> None:
                self.destination = destination
                self.calls: list[str] = []

            def export_selection(self, suggested_filename: str = "selection.pgn") -> Path:
                self.calls.append(suggested_filename)
                return self.destination

        database = AcsDatabase()
        try:
            database.import_pgn_text(pgn, source_name="filtered-release-reachability.pgn")
            service = LibraryExportService(database)
            request = LibraryExportRequest.filtered(GameSearchQuery(event="Filtered Cup"))
            with tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / "Відфільтровані партії.pgn"
                dialogs = Dialogs(destination)
                application = SimpleNamespace(
                    library_export=service,
                    _file_event=Mock(),
                    session=None,
                    worker_factory=Mock(return_value=lambda: None),
                    pgn_commands=SimpleNamespace(export_selected=Mock()),
                    import_ui_ready=Mock(),
                    _focus="library-search-player",
                    confirm_document_replace=lambda: True,
                    set_document=Mock(),
                )
                board_dispatch = Mock()
                with patch(
                    "acs.version2_windows_library_export.Version2OwnedWindowsPgnExportDialogs",
                    return_value=dialogs,
                ):
                    runtime = _build_version2_windows_file_runtime(
                        application=application,
                        api=SimpleNamespace(v2_board_dispatch=board_dispatch),
                        database_path=Path("library.acsdb"),
                        owner_control=Owner(),
                        dialog_language_provider=lambda: "uk",
                    )
                try:
                    event = runtime("library.export", request.browser_payload())
                    reopened = open_pgn(destination)
                finally:
                    self.assertTrue(runtime.shutdown())

            self.assertEqual(event.kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(event.game_count, 2)
            self.assertEqual(event.focus_target, "library-search-player")
            self.assertEqual(dialogs.calls, ["library-export.pgn"])
            self.assertEqual(len(reopened.games), 2)
            self.assertEqual(
                [game.tags["Event"] for game in reopened.games],
                ["Filtered Cup", "Filtered Cup"],
            )
            board_dispatch.assert_not_called()
            self.assertNotIn(str(destination), repr(event))
            application._file_event.assert_called_once_with(event)
        finally:
            database.close()


    def test_canonical_builder_uses_exact_owner_for_library_save_dialog(self) -> None:
        pgn = """[Event "Owner-bound export"]
[White "Олексій"]
[Black "Test"]
[Result "*"]

1. e4 e5 *
"""

        class DialogResult:
            OK = "ok"

        class OpenDialog:
            def __init__(self) -> None:
                self.FileName = ""

            def ShowDialog(self, owner):  # noqa: N802
                return DialogResult.OK

            def Dispose(self):  # noqa: N802
                return None

        class SaveDialog:
            destination: Path | None = None
            owners: list[object] = []

            def __init__(self) -> None:
                self.FileName = ""

            def ShowDialog(self, owner):  # noqa: N802
                type(self).owners.append(owner)
                if type(self).destination is not None:
                    self.FileName = str(type(self).destination)
                return DialogResult.OK

            def Dispose(self):  # noqa: N802
                return None

        def forms_loader():
            return DialogResult, OpenDialog, SaveDialog

        class Owner:
            IsDisposed = False
            Disposing = False
            InvokeRequired = False

            def BeginInvoke(self, delegate):  # noqa: N802
                raise AssertionError("synchronous export must not post UI work")

        database = AcsDatabase()
        try:
            report = database.import_pgn_text(pgn, source_name="owner-bound-export.pgn")
            game_id = report.game_ids[0]
            owner = Owner()
            events: list[object] = []
            fallbacks: list[object] = []

            with tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / "експорт ♞.pgn"
                SaveDialog.destination = destination
                SaveDialog.owners.clear()
                runtime = build_version2_windows_library_file_runtime(
                    owner_control=owner,
                    library_service=LibraryExportService(database),
                    library_export_event_sink=events.append,
                    get_pgn_session=lambda: None,
                    set_pgn_session=lambda _session: None,
                    import_services_factory=lambda: None,
                    export_selected=lambda _request, _destination: None,
                    import_ui_ready=lambda _mailbox: None,
                    pgn_export_event_sink=lambda _event: None,
                    next_delegate=lambda action_id, payload: fallbacks.append(
                        (action_id, dict(payload))
                    ),
                    current_focus_provider=lambda: "library-results",
                    ui_delegate_factory=lambda callback: callback,
                    file_forms_loader=forms_loader,
                    export_forms_loader=forms_loader,
                )
                try:
                    event = runtime(
                        "library.export",
                        LibraryExportRequest.selected([game_id]).browser_payload(),
                    )
                    reopened = open_pgn(destination)
                finally:
                    self.assertTrue(runtime.shutdown())

            self.assertEqual(event.kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(events, [event])
            self.assertEqual(fallbacks, [])
            self.assertEqual(SaveDialog.owners, [owner])
            self.assertEqual(reopened.games[0].tags["Event"], "Owner-bound export")
            self.assertNotIn(str(destination), repr(event))
        finally:
            database.close()


    def test_application_selected_export_reaches_bound_native_runtime(self) -> None:
        pgn = """[Event "Application route"]
[Site "Bratislava"]
[Date "2026.09.27"]
[Round "1"]
[White "Route"]
[Black "Runtime"]
[Result "*"]

1. Nf3 Nf6 *
"""

        class Owner:
            IsDisposed = False
            Disposing = False
            InvokeRequired = False

            def BeginInvoke(self, delegate):  # noqa: N802
                raise AssertionError("synchronous export must not post UI work")

        class Dialogs:
            def __init__(self, destination: Path) -> None:
                self.destination = destination
                self.calls: list[str] = []

            def export_selection(self, suggested_filename: str = "selection.pgn") -> Path:
                self.calls.append(suggested_filename)
                return self.destination

        database = AcsDatabase()
        runtime = None
        try:
            report = database.import_pgn_text(pgn, source_name="application-route.pgn")
            game_id = report.game_ids[0]
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                destination = root / "маршрут експорту.pgn"
                application = Version2Application(
                    database,
                    progress_store=SimpleNamespace(path=root / "book-progress.json"),
                    engine_assistance=object(),
                    board_dispatch=Mock(),
                    copy_text=lambda _value: None,
                    language=UILanguage.UA,
                )
                application.library.projection.toggle_export_selection(game_id)
                dialogs = Dialogs(destination)
                with patch(
                    "acs.version2_windows_library_export.Version2OwnedWindowsPgnExportDialogs",
                    return_value=dialogs,
                ):
                    runtime = _build_version2_windows_file_runtime(
                        application=application,
                        api=SimpleNamespace(v2_board_dispatch=Mock()),
                        database_path=root / "library.acsdb",
                        owner_control=Owner(),
                        dialog_language_provider=lambda: application.shell.language,
                    )
                application.bind_files(runtime)

                delegated = application._delegate("library.export", {})
                reopened = open_pgn(destination)
                events = application.drain_events()

            self.assertEqual(delegated.kind, "delegated")
            self.assertEqual(delegated.payload["action"], "library.export")
            self.assertEqual(delegated.payload["scope"], "selected")
            self.assertEqual(dialogs.calls, ["library-export.pgn"])
            self.assertEqual(len(reopened.games), 1)
            self.assertEqual(reopened.games[0].tags["Event"], "Application route")
            self.assertIn(
                {"kind": "status", "payload": {"announcement": "Експорт завершено."}},
                events,
            )
        finally:
            if runtime is not None:
                self.assertTrue(runtime.shutdown())
            database.close()


    def test_browser_filtered_export_reaches_native_runtime_and_restores_focus(self) -> None:
        pgn = """[Event "Browser Filter"]
[Site "Bratislava"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *

[Event "Browser Filter"]
[Site "Košice"]
[White "Gamma"]
[Black "Delta"]
[Result "*"]

1. d4 d5 *

[Event "Other"]
[Site "Nitra"]
[White "Epsilon"]
[Black "Zeta"]
[Result "*"]

1. c4 c5 *
"""

        class Owner:
            IsDisposed = False
            Disposing = False
            InvokeRequired = False

            def BeginInvoke(self, delegate):  # noqa: N802
                raise AssertionError("synchronous export must not post UI work")

        class Dialogs:
            def __init__(self, destination: Path) -> None:
                self.destination = destination

            def export_selection(self, suggested_filename: str = "selection.pgn") -> Path:
                return self.destination

        database = AcsDatabase()
        runtime = None
        try:
            database.import_pgn_text(pgn, source_name="browser-filter.pgn")
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                destination = root / "filtered browser export.pgn"
                application = Version2Application(
                    database,
                    progress_store=SimpleNamespace(path=root / "book-progress.json"),
                    engine_assistance=object(),
                    board_dispatch=Mock(),
                    copy_text=lambda _value: None,
                    language=UILanguage.EN,
                )
                application.library.projection.search(GameSearchQuery(event="Browser Filter"))
                application.record_focus("library-search-event")
                with patch(
                    "acs.version2_windows_library_export.Version2OwnedWindowsPgnExportDialogs",
                    return_value=Dialogs(destination),
                ):
                    runtime = _build_version2_windows_file_runtime(
                        application=application,
                        api=SimpleNamespace(v2_board_dispatch=Mock()),
                        database_path=root / "library.acsdb",
                        owner_control=Owner(),
                        dialog_language_provider=lambda: application.shell.language,
                    )
                application.bind_files(runtime)

                delegated = application.browser_command(
                    "library",
                    "library.export_filtered",
                    {},
                )
                reopened = open_pgn(destination)
                events = application.drain_events()

            self.assertEqual(delegated["kind"], "delegated")
            self.assertEqual(delegated["payload"]["scope"], "filtered")
            self.assertEqual(len(reopened.games), 2)
            self.assertEqual(
                [game.tags["Event"] for game in reopened.games],
                ["Browser Filter", "Browser Filter"],
            )
            self.assertIn(
                {
                    "kind": "status",
                    "payload": {
                        "announcement": "Export completed.",
                        "focus_target": "library-search-event",
                    },
                },
                events,
            )
            self.assertEqual(application._focus, "library-search-event")
            self.assertNotIn(str(destination), repr(events))
        finally:
            if runtime is not None:
                self.assertTrue(runtime.shutdown())
            database.close()


if __name__ == "__main__":
    unittest.main()
