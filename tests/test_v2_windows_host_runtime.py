from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.library_export_service import (
    LibraryExportRequest,
    LibraryExportService,
)
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportProgress,
    LibraryImportResult,
)
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
)
from acs.pgn_service import open_pgn
from acs.version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime
from acs.version2_windows_library_export import (
    LibraryExportHostEventKind,
    LibraryExportWorkerServices,
)
from acs.version2_windows_pgn_export import PgnSelectionExportEventKind


_PGN = """[Event "Runtime"]
[Site "?"]
[Date "2026.08.28"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
"""


class _DialogResult:
    OK = "ok"


class _OpenDialog:
    selected_paths: list[str] = []
    owners: list[object] = []

    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        type(self).owners.append(owner)
        if type(self).selected_paths:
            self.FileName = type(self).selected_paths.pop(0)
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


class _SaveDialog:
    owners: list[object] = []
    selected_paths: list[str] = []

    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        type(self).owners.append(owner)
        if type(self).selected_paths:
            self.FileName = type(self).selected_paths.pop(0)
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


def _forms_loader():
    return _DialogResult, _OpenDialog, _SaveDialog


class _Owner:
    def __init__(self) -> None:
        self.IsDisposed = False
        self.Disposing = False
        self.InvokeRequired = False
        self.posted: list[object] = []

    def BeginInvoke(self, delegate):  # noqa: N802
        self.posted.append(delegate)
        return len(self.posted)


class _FlakyOwner(_Owner):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.begin_invoke_calls = 0

    def BeginInvoke(self, delegate):  # noqa: N802
        self.begin_invoke_calls += 1
        if self.failures:
            self.failures -= 1
            raise RuntimeError("simulated BeginInvoke rejection")
        return super().BeginInvoke(delegate)


class _Library:
    def __init__(self) -> None:
        self.calls = 0

    def import_games(
        self,
        games,
        *,
        source_name,
        source_format,
        source_sha256,
        source_warning_count=0,
        cancel_check=None,
        progress_callback=None,
    ) -> LibraryImportResult:
        self.calls += 1
        total = len(games)
        if progress_callback is not None:
            progress_callback(LibraryImportProgress(1, 0, total))
            progress_callback(LibraryImportProgress(1, total, total))
        return LibraryImportResult(1, 1, total, source_warning_count, 1, total)


class _CancellableLibrary(_Library):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()

    def import_games(self, games, **kwargs) -> LibraryImportResult:
        self.calls += 1
        cancel_check = kwargs["cancel_check"]
        self.entered.set()
        if not self.entered.wait(1.0):
            raise AssertionError("cancellable import did not enter")
        for _ in range(10000):
            if cancel_check():
                raise LibraryImportCancelledError("cancelled")
            threading.Event().wait(0.001)
        raise AssertionError("runtime shutdown did not request cancellation")


class _ImportCapableLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("import service must not run")


class Version2WindowsFileWorkflowRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        _OpenDialog.selected_paths.clear()
        _OpenDialog.owners.clear()
        _SaveDialog.owners.clear()
        _SaveDialog.selected_paths.clear()

    def _runtime(
        self,
        owner: _Owner,
        *,
        library: object | None = None,
        imported_events: list[object] | None = None,
        export_calls: list[tuple[object, Path]] | None = None,
        export_events: list[object] | None = None,
        fallback_calls: list[tuple[str, dict[str, object]]] | None = None,
        closed_services: list[bool] | None = None,
        library_export_worker_services_factory=None,
    ) -> Version2WindowsFileWorkflowRuntime:
        imported_events = imported_events if imported_events is not None else []
        export_calls = export_calls if export_calls is not None else []
        export_events = export_events if export_events is not None else []
        fallback_calls = fallback_calls if fallback_calls is not None else []
        closed_services = closed_services if closed_services is not None else []
        library = library or _Library()

        def import_services_factory() -> Version2ImportWorkerServices:
            return Version2ImportWorkerServices(
                library,
                None,
                lambda: closed_services.append(True),
            )

        def export_selected(request, destination: Path) -> None:
            export_calls.append((request, destination))

        def import_ui_ready(mailbox) -> None:
            imported_events.extend(mailbox.drain())

        def fallback(action_id: str, payload) -> object:
            fallback_calls.append((action_id, dict(payload)))
            return ("fallback", action_id)

        return Version2WindowsFileWorkflowRuntime(
            owner_control=owner,
            get_pgn_session=lambda: None,
            set_pgn_session=lambda session: None,
            import_services_factory=import_services_factory,
            export_selected=export_selected,
            import_ui_ready=import_ui_ready,
            pgn_export_event_sink=export_events.append,
            next_delegate=fallback,
            library_export_worker_services_factory=library_export_worker_services_factory,
            current_focus_provider=lambda: "stable-focus",
            ui_delegate_factory=lambda callback: callback,
            file_forms_loader=_forms_loader,
            export_forms_loader=_forms_loader,
        )

    def test_runtime_rejects_active_action_id_before_any_comparison(self) -> None:
        owner = _Owner()
        fallback_calls: list[tuple[str, dict[str, object]]] = []
        runtime = self._runtime(owner, fallback_calls=fallback_calls)
        touched: list[str] = []

        class ActiveActionId(str):
            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active action-id equality executed")

            def __ne__(self, other):
                touched.append("ne")
                raise AssertionError("active action-id inequality executed")

            def __hash__(self):
                touched.append("hash")
                raise AssertionError("active action-id hash executed")

        with self.assertRaisesRegex(TypeError, "action id must be text"):
            runtime(ActiveActionId("library.export"), {})

        self.assertEqual([], touched)
        self.assertEqual([], fallback_calls)
        self.assertEqual([], _SaveDialog.owners)
        self.assertEqual([], owner.posted)

    def test_non_host_action_chains_exactly_once_to_canonical_delegate(self) -> None:
        owner = _Owner()
        fallback_calls: list[tuple[str, dict[str, object]]] = []
        runtime = self._runtime(owner, fallback_calls=fallback_calls)

        result = runtime("analysis.restart", {"source": "board"})

        self.assertEqual(result, ("fallback", "analysis.restart"))
        self.assertEqual(fallback_calls, [("analysis.restart", {"source": "board"})])
        self.assertEqual(owner.posted, [])
        self.assertTrue(runtime.shutdown())

    def test_export_routes_through_owned_dialog_then_injected_canonical_exporter(self) -> None:
        owner = _Owner()
        export_calls: list[tuple[object, Path]] = []
        export_events: list[object] = []
        fallback_calls: list[tuple[str, dict[str, object]]] = []
        runtime = self._runtime(
            owner,
            export_calls=export_calls,
            export_events=export_events,
            fallback_calls=fallback_calls,
        )
        payload = {
            "game_index": 0,
            "line_path": ((0, 0),),
            "move_index": 0,
            "expected_record_digest": "a" * 64,
            "content_revision": 1,
        }

        result = runtime("pgn.export_selection", payload)

        self.assertEqual(result.kind, PgnSelectionExportEventKind.EXPORTED)
        self.assertEqual(result.focus_target, "stable-focus")
        self.assertEqual(len(export_calls), 1)
        self.assertEqual(export_calls[0][1], Path("selection.pgn"))
        self.assertEqual(export_calls[0][0].game_index, 0)
        self.assertEqual(export_calls[0][0].line_path, ((0, 0),))
        self.assertEqual(_SaveDialog.owners, [owner])
        self.assertEqual(export_events, [result])
        self.assertEqual(fallback_calls, [])
        self.assertTrue(runtime.shutdown())

    def test_export_save_dialog_rejects_reentrant_import_before_open_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "outer-export.pgn"
            source = Path(directory) / "nested-import.pgn"
            source.write_text(_PGN, encoding="utf-8")
            _SaveDialog.selected_paths.append(str(destination))
            _OpenDialog.selected_paths.append(str(source))
            owner = _Owner()
            runtime = self._runtime(owner)
            nested_errors: list[BaseException] = []
            original_show = _SaveDialog.ShowDialog

            def reentrant_show(dialog, dialog_owner):
                try:
                    runtime("library.import", {})
                except BaseException as exc:
                    nested_errors.append(exc)
                return original_show(dialog, dialog_owner)

            try:
                with patch.object(_SaveDialog, "ShowDialog", new=reentrant_show):
                    started = runtime(
                        "library.export",
                        LibraryExportRequest.selected([1]).browser_payload(),
                    )
                self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
                self.assertEqual(len(nested_errors), 1)
                self.assertIsInstance(nested_errors[0], RuntimeError)
                self.assertIn("export is already active", str(nested_errors[0]))
                self.assertEqual(_OpenDialog.owners, [])
                self.assertEqual(_SaveDialog.owners, [owner])
                self.assertTrue(runtime.wait_for_export(5.0))
                for callback in list(owner.posted):
                    callback()
            finally:
                self.assertTrue(runtime.shutdown())

    def test_import_open_dialog_rejects_reentrant_export_before_save_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "outer-import.pgn"
            source.write_text(_PGN, encoding="utf-8")
            destination = Path(directory) / "nested-export.pgn"
            _OpenDialog.selected_paths.append(str(source))
            _SaveDialog.selected_paths.append(str(destination))
            owner = _Owner()
            runtime = self._runtime(owner)
            nested_errors: list[BaseException] = []
            original_show = _OpenDialog.ShowDialog

            def reentrant_show(dialog, dialog_owner):
                try:
                    runtime(
                        "library.export",
                        LibraryExportRequest.selected([1]).browser_payload(),
                    )
                except BaseException as exc:
                    nested_errors.append(exc)
                return original_show(dialog, dialog_owner)

            try:
                with patch.object(_OpenDialog, "ShowDialog", new=reentrant_show):
                    started = runtime("library.import", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
                self.assertEqual(len(nested_errors), 1)
                self.assertIsInstance(nested_errors[0], RuntimeError)
                self.assertIn("import is already active", str(nested_errors[0]))
                self.assertEqual(_SaveDialog.owners, [])
                self.assertEqual(_OpenDialog.owners, [owner])
                self.assertTrue(runtime.wait_for_import(5.0))
                for callback in list(owner.posted):
                    callback()
            finally:
                self.assertTrue(runtime.shutdown())

    def test_reentrant_shutdown_during_import_dialog_is_retryable_not_false_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "modal-shutdown-import.pgn"
            source.write_text(_PGN, encoding="utf-8")
            _OpenDialog.selected_paths.append(str(source))
            owner = _Owner()
            runtime = self._runtime(owner)
            shutdown_results: list[bool] = []
            closed_during_dialog: list[bool] = []
            original_show = _OpenDialog.ShowDialog

            def reentrant_show(dialog, dialog_owner):
                shutdown_results.append(runtime.shutdown(timeout=0.1))
                closed_during_dialog.append(runtime.closed)
                return original_show(dialog, dialog_owner)

            with patch.object(_OpenDialog, "ShowDialog", new=reentrant_show):
                started = runtime("library.import", {})

            self.assertEqual(shutdown_results, [False])
            self.assertEqual(closed_during_dialog, [False])
            self.assertFalse(runtime.closed)
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(runtime.wait_for_import(5.0))
            for callback in list(owner.posted):
                callback()
            self.assertTrue(runtime.shutdown(5.0))
            self.assertTrue(runtime.closed)

    def test_reentrant_shutdown_during_export_dialog_is_retryable_not_false_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "modal-shutdown-export.pgn"
            _SaveDialog.selected_paths.append(str(destination))
            owner = _Owner()
            runtime = self._runtime(owner)
            shutdown_results: list[bool] = []
            closed_during_dialog: list[bool] = []
            original_show = _SaveDialog.ShowDialog

            def reentrant_show(dialog, dialog_owner):
                shutdown_results.append(runtime.shutdown(timeout=0.1))
                closed_during_dialog.append(runtime.closed)
                return original_show(dialog, dialog_owner)

            with patch.object(_SaveDialog, "ShowDialog", new=reentrant_show):
                started = runtime(
                    "library.export",
                    LibraryExportRequest.selected([1]).browser_payload(),
                )

            self.assertEqual(shutdown_results, [False])
            self.assertEqual(closed_during_dialog, [False])
            self.assertFalse(runtime.closed)
            self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
            self.assertTrue(runtime.wait_for_export(5.0))
            for callback in list(owner.posted):
                callback()
            self.assertTrue(runtime.shutdown(5.0))
            self.assertTrue(runtime.closed)

    def test_library_export_worker_factory_rejects_active_service_containers_passively(self) -> None:
        touched: list[str] = []

        class HostileServices(Version2ImportWorkerServices):
            def __getattribute__(self, name):
                if name in {"close", "library", "chessbase"}:
                    touched.append(name)
                    raise AssertionError("rejected services hook executed")
                return super().__getattribute__(name)

        hostile = HostileServices.__new__(HostileServices)
        object.__setattr__(hostile, "library", _ImportCapableLibrary())
        object.__setattr__(hostile, "chessbase", None)
        object.__setattr__(hostile, "close", lambda: touched.append("close-call"))

        create = Version2WindowsFileWorkflowRuntime._library_export_worker_factory(
            lambda: hostile
        )

        with self.assertRaisesRegex(TypeError, "invalid bundle"):
            create()
        self.assertEqual(touched, [])

    def test_library_export_worker_factory_rejects_active_cleanup_before_owner_lookup(self) -> None:
        touched: list[str] = []

        class ActiveClose:
            def __call__(self):
                touched.append("call")

            def __getattribute__(self, name):
                if name == "__self__":
                    touched.append("owner")
                    raise AssertionError("active cleanup owner hook executed")
                return super().__getattribute__(name)

        services = Version2ImportWorkerServices(
            _ImportCapableLibrary(),
            None,
            ActiveClose(),
        )
        create = Version2WindowsFileWorkflowRuntime._library_export_worker_factory(
            lambda: services
        )

        with self.assertRaisesRegex(TypeError, "canonical AcsDatabase owner"):
            create()
        self.assertEqual(touched, [])

    def test_library_export_worker_factory_preserves_constructor_abort_and_closes_database(self) -> None:
        class ConstructionAbort(BaseException):
            pass

        database = AcsDatabase()
        services = Version2ImportWorkerServices(
            _ImportCapableLibrary(),
            None,
            database.close,
        )
        create = Version2WindowsFileWorkflowRuntime._library_export_worker_factory(
            lambda: services
        )

        with patch(
            "acs.version2_windows_host_runtime.LibraryExportService",
            side_effect=ConstructionAbort("Library export service construction aborted"),
        ):
            with self.assertRaises(ConstructionAbort):
                create()

        with self.assertRaises(Exception):
            database.conn.execute("SELECT 1")

    def test_next_library_start_recovers_export_terminal_after_both_ui_posts_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "library.acsdb"
            database = AcsDatabase(database_path)
            try:
                database.import_pgn_text(_PGN, source_name="export-source.pgn")
                row = database.conn.execute(
                    "SELECT id FROM games ORDER BY id LIMIT 1"
                ).fetchone()
                assert row is not None
                game_id = int(row["id"])
            finally:
                database.close()

            destination = Path(directory) / "recovered-export.pgn"
            import_source = Path(directory) / "next-import.pgn"
            import_source.write_text(_PGN, encoding="utf-8")
            _SaveDialog.selected_paths.append(str(destination))
            _OpenDialog.selected_paths.append(str(import_source))
            owner = _FlakyOwner(2)
            export_events: list[object] = []

            def export_worker_factory() -> LibraryExportWorkerServices:
                worker_db = AcsDatabase(database_path)
                return LibraryExportWorkerServices(
                    LibraryExportService(worker_db),
                    worker_db.close,
                )

            runtime = self._runtime(
                owner,
                export_events=export_events,
                library_export_worker_services_factory=export_worker_factory,
            )
            try:
                started = runtime(
                    "library.export",
                    LibraryExportRequest.selected([game_id]).browser_payload(),
                )
                self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
                self.assertTrue(runtime.wait_for_export(5.0))

                deadline = threading.Event()
                for _ in range(200):
                    if owner.begin_invoke_calls >= 2:
                        break
                    deadline.wait(0.01)
                self.assertEqual(owner.begin_invoke_calls, 2)
                self.assertEqual(owner.posted, [])
                self.assertTrue(runtime.export_running)
                self.assertEqual(
                    [event.kind for event in export_events],
                    [LibraryExportHostEventKind.STARTED],
                )

                import_started = runtime("library.import", {})

                self.assertEqual(
                    import_started.kind,
                    FileWorkflowEventKind.IMPORT_STARTED,
                )
                self.assertFalse(runtime.export_running)
                self.assertEqual(
                    [event.kind for event in export_events],
                    [
                        LibraryExportHostEventKind.STARTED,
                        LibraryExportHostEventKind.EXPORTED,
                    ],
                )
                self.assertTrue(destination.exists())
                self.assertTrue(runtime.wait_for_import(5.0))
                for callback in list(owner.posted):
                    callback()
            finally:
                self.assertTrue(runtime.shutdown(5.0))

    def test_import_running_rejects_export_before_save_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "busy-import.pgn"
            source.write_text(_PGN, encoding="utf-8")
            _OpenDialog.selected_paths.append(str(source))
            owner = _Owner()
            library = _CancellableLibrary()
            runtime = self._runtime(owner, library=library)
            try:
                started = runtime("library.import", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
                self.assertTrue(library.entered.wait(2.0))
                self.assertTrue(runtime.import_running)

                with self.assertRaisesRegex(RuntimeError, "import is already active"):
                    runtime(
                        "library.export",
                        LibraryExportRequest.selected([1]).browser_payload(),
                    )
                self.assertEqual(_SaveDialog.owners, [])

                runtime("library.cancel_import", {})
                self.assertTrue(runtime.wait_for_import(5.0))
            finally:
                self.assertTrue(runtime.shutdown())

    def test_export_running_rejects_import_before_open_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "busy-export.pgn"
            _SaveDialog.selected_paths.append(str(destination))
            owner = _Owner()
            export_events: list[object] = []
            runtime = Version2WindowsFileWorkflowRuntime(
                owner_control=owner,
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _Library(),
                    None,
                    lambda: None,
                ),
                export_selected=lambda request, path: None,
                import_ui_ready=lambda mailbox: None,
                pgn_export_event_sink=export_events.append,
                next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                library_export_worker_services_factory=lambda: object(),
                current_focus_provider=lambda: "library-export-selected",
                ui_delegate_factory=lambda callback: callback,
                file_forms_loader=_forms_loader,
                export_forms_loader=_forms_loader,
            )
            try:
                started = runtime(
                    "library.export",
                    LibraryExportRequest.selected([1]).browser_payload(),
                )
                self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
                self.assertTrue(runtime.wait_for_export(5.0))
                # The worker has selected a terminal event, but until the owner
                # callback consumes it the operation still owns cancellation.
                self.assertTrue(runtime.export_running)

                with self.assertRaisesRegex(RuntimeError, "export is already active"):
                    runtime("library.import", {})
                self.assertEqual(_OpenDialog.owners, [])

                class HostileCancelPayload(dict):
                    def __bool__(self):
                        raise AssertionError("payload truthiness must not run")

                with self.assertRaisesRegex(
                    ValueError,
                    "Library cancellation accepts no payload",
                ):
                    runtime(
                        "library.cancel_import",
                        HostileCancelPayload(unexpected=True),
                    )
                self.assertTrue(runtime.export_running)

                self.assertEqual(len(owner.posted), 1)
                owner.posted.pop(0)()
                self.assertFalse(runtime.export_running)
            finally:
                self.assertTrue(runtime.shutdown())

    def test_real_library_export_uses_worker_local_acsdb_and_owner_terminal_post(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "library.acsdb"
            database = AcsDatabase(database_path)
            try:
                report = database.import_pgn_text(
                    _PGN,
                    source_name="runtime-library-export.pgn",
                )
                game_id = report.game_ids[0]
            finally:
                database.close()

            destination = root / "library-export.pgn"
            _SaveDialog.selected_paths.append(str(destination))
            owner = _Owner()
            export_events: list[object] = []

            def import_services_factory() -> Version2ImportWorkerServices:
                worker_database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(
                    _Library(),
                    None,
                    worker_database.close,
                )

            runtime = Version2WindowsFileWorkflowRuntime(
                owner_control=owner,
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=import_services_factory,
                export_selected=lambda request, path: None,
                import_ui_ready=lambda mailbox: None,
                pgn_export_event_sink=export_events.append,
                next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                current_focus_provider=lambda: "library-export-selected",
                ui_delegate_factory=lambda callback: callback,
                file_forms_loader=_forms_loader,
                export_forms_loader=_forms_loader,
            )
            try:
                started = runtime(
                    "library.export",
                    LibraryExportRequest.selected([game_id]).browser_payload(),
                )

                self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
                self.assertEqual(started.focus_target, "library-export-selected")
                self.assertTrue(runtime.export_running)
                self.assertEqual(_SaveDialog.owners, [owner])
                self.assertEqual(export_events, [started])

                self.assertTrue(runtime.wait_for_export(5.0))
                self.assertTrue(runtime.export_running)
                self.assertEqual(len(owner.posted), 1)
                self.assertFalse(destination.name in repr(export_events))

                owner.posted.pop(0)()

                self.assertFalse(runtime.export_running)
                self.assertEqual(
                    [event.kind for event in export_events],
                    [
                        LibraryExportHostEventKind.STARTED,
                        LibraryExportHostEventKind.EXPORTED,
                    ],
                )
                terminal = export_events[-1]
                self.assertEqual(terminal.focus_target, "library-export-selected")
                self.assertEqual(terminal.game_count, 1)
                self.assertNotIn(str(destination), repr(terminal))

                reopened = open_pgn(destination)
                self.assertEqual(len(reopened.games), 1)
                self.assertEqual(reopened.games[0].tags["Event"], "Runtime")
            finally:
                self.assertTrue(runtime.shutdown())

    def test_real_pgn_import_posts_one_ui_wakeup_and_owner_drains_on_ui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(_PGN, encoding="utf-8")
            _OpenDialog.selected_paths.append(str(source))
            owner = _Owner()
            library = _Library()
            imported_events: list[object] = []
            closed_services: list[bool] = []
            runtime = self._runtime(
                owner,
                library=library,
                imported_events=imported_events,
                closed_services=closed_services,
            )

            started = runtime("library.import", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(runtime.wait_for_import(5.0))
            self.assertEqual(library.calls, 1)
            self.assertEqual(closed_services, [True])
            self.assertEqual(len(owner.posted), 1)
            self.assertGreaterEqual(runtime.import_mailbox.pending_count, 2)

            callback = owner.posted.pop(0)
            callback()

            self.assertEqual(runtime.import_mailbox.pending_count, 0)
            self.assertEqual(
                [event.kind for event in imported_events],
                [
                    FileWorkflowEventKind.IMPORT_STARTED,
                    FileWorkflowEventKind.IMPORT_PROGRESS,
                    FileWorkflowEventKind.IMPORT_COMPLETED,
                ],
            )
            self.assertEqual(imported_events[-1].game_count, 1)
            self.assertEqual(_OpenDialog.owners, [owner])
            self.assertTrue(runtime.shutdown())

    def test_refused_import_shutdown_does_not_retire_library_export_delegate(self) -> None:
        owner = _Owner()
        runtime = self._runtime(owner)

        with patch.object(
            runtime._file_delegate,
            "shutdown",
            return_value=False,
        ) as import_shutdown, patch.object(
            runtime._library_export_delegate,
            "shutdown",
            wraps=runtime._library_export_delegate.shutdown,
        ) as export_shutdown:
            self.assertFalse(runtime.shutdown(0.0))
            import_shutdown.assert_called_once_with(0.0)
            export_shutdown.assert_not_called()

        self.assertFalse(runtime.closed)
        still_live = runtime._library_export_delegate.cancel_export()
        self.assertEqual(still_live.kind, LibraryExportHostEventKind.FAILED)
        self.assertEqual(still_live.error_code, "no_library_export_running")
        self.assertTrue(runtime.shutdown())
        self.assertTrue(runtime.closed)

    def test_shutdown_cancels_and_joins_worker_before_runtime_closes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cancel.pgn"
            source.write_text(_PGN, encoding="utf-8")
            _OpenDialog.selected_paths.append(str(source))
            owner = _Owner()
            library = _CancellableLibrary()
            closed_services: list[bool] = []
            runtime = self._runtime(
                owner,
                library=library,
                closed_services=closed_services,
            )

            runtime("library.import", {})
            self.assertTrue(library.entered.wait(2.0))
            self.assertTrue(runtime.import_running)

            self.assertTrue(runtime.shutdown(5.0))
            self.assertTrue(runtime.closed)
            self.assertFalse(runtime.import_running)
            self.assertEqual(closed_services, [True])
            with self.assertRaisesRegex(RuntimeError, "runtime is closed"):
                runtime("analysis.restart", {})

            # A wakeup posted before close is safe to execute after close; the
            # closed pump performs no projection callback.
            for callback in list(owner.posted):
                callback()

    def test_shutdown_is_ui_thread_affine_and_retryable_from_owner_thread(self) -> None:
        owner = _Owner()
        runtime = self._runtime(owner)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                runtime.shutdown()
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, name="runtime-shutdown-wrong-thread")
        thread.start()
        thread.join(5.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("UI thread", str(errors[0]))
        self.assertFalse(runtime.closed)
        self.assertTrue(runtime.shutdown())
        self.assertTrue(runtime.closed)


if __name__ == "__main__":
    unittest.main()
