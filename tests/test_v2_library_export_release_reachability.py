from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from acs.acsdb import AcsDatabase
from acs.library_export_service import LibraryExportRequest, LibraryExportService
from acs.pgn_service import open_pgn
from acs.version2_release_app import _build_version2_windows_file_runtime
from acs.version2_windows_library_export import LibraryExportHostEventKind


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


if __name__ == "__main__":
    unittest.main()
