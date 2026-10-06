from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.full_product_actions import build_full_product_action_registry
from acs.full_product_ui_shell import UILanguage
from acs.keybindings import BindingContext
from acs.library_export_service import (
    LibraryExportCancelledError,
    LibraryExportControlError,
    LibraryExportError,
    LibraryExportRequest,
    LibraryExportResult,
    LibraryExportScope,
    LibraryExportService,
)
from acs.library_export_workspace import build_library_export_webview
from acs.pgn_service import open_pgn
from acs.search_service import (
    GameSearchPage,
    GameSearchQuery,
    GameSearchService,
    SearchCancelledError,
)
from acs.ui_keymap_adapter import build_web_keymap
from acs.version2_application import Version2Application
from acs.version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind
from acs.version2_windows_library_export import (
    LibraryExportHostEvent,
    LibraryExportHostEventKind,
    LibraryExportWorkerServices,
    Version2WindowsLibraryExportDelegate,
)


_PGN = '''[Event "Background Library Export"]
[Site "Uzhhorod UKR"]
[Date "2026.10.05"]
[Round "1"]
[White "Олексій"]
[Black "Worker"]
[Result "*"]

1. e4 {visible comment} e5 (1... c5 $5) *
'''


class _Dialogs:
    def __init__(self, destination: Path | None) -> None:
        self.destination = destination
        self.calls: list[str] = []

    def export_selection(self, suggested_filename: str = "selection.pgn") -> Path | None:
        self.calls.append(suggested_filename)
        return self.destination


class _BlockingLibraryExportService(LibraryExportService):
    def __init__(
        self,
        database: AcsDatabase,
        *,
        hashing_started: threading.Event,
        release_hash: threading.Event,
    ) -> None:
        super().__init__(database)
        self._hashing_started = hashing_started
        self._release_hash = release_hash

    def expected_destination_sha256(self, destination, *, cancel_check=None):
        self._hashing_started.set()
        self._release_hash.wait()
        if cancel_check is not None and cancel_check():
            raise LibraryExportCancelledError("Library export cancelled")
        return super().expected_destination_sha256(
            destination,
            cancel_check=cancel_check,
        )


class _ZeroCountLibraryExportService(LibraryExportService):
    def export_to(self, destination, request, *, expected_sha256=None, cancel_check=None):
        return LibraryExportResult(
            game_count=0,
            destination_fingerprint=SimpleNamespace(),
        )


class _RollbackFailingConnection:
    """Delegate SQLite work but fail the transaction cleanup boundary."""

    def __init__(self, connection) -> None:
        self._connection = connection

    @property
    def in_transaction(self):
        return self._connection.in_transaction

    def execute(self, *args, **kwargs):
        return self._connection.execute(*args, **kwargs)

    def rollback(self):
        raise RuntimeError("simulated snapshot rollback failure")

    def __getattr__(self, name):
        return getattr(self._connection, name)


class Version2WindowsLibraryExportBackgroundTests(unittest.TestCase):
    def _create_library(self, directory: str) -> tuple[Path, int]:
        database_path = Path(directory) / "library.acsdb"
        database = AcsDatabase(database_path)
        try:
            database.import_pgn_text(_PGN, source_name="worker-library.pgn")
            game_id = GameSearchQuery().normalized().limit
            # Obtain the canonical inserted id rather than assuming SQLite starts at 1.
            row = database.conn.execute("SELECT id FROM games ORDER BY id LIMIT 1").fetchone()
            assert row is not None
            game_id = int(row["id"])
            return database_path, game_id
        finally:
            database.close()

    @staticmethod
    def _worker_factory(database_path: Path):
        def create() -> LibraryExportWorkerServices:
            database = AcsDatabase(database_path)
            return LibraryExportWorkerServices(
                LibraryExportService(database),
                database.close,
            )

        return create

    @staticmethod
    def _delegate(
        destination: Path,
        worker_factory,
        events: list,
        posted: list,
    ) -> tuple[Version2WindowsLibraryExportDelegate, _Dialogs]:
        dialogs = _Dialogs(destination)
        delegate = Version2WindowsLibraryExportDelegate(
            dialogs=dialogs,
            worker_services_factory=worker_factory,
            post_to_ui=posted.append,
            event_sink=events.append,
            next_delegate=lambda action_id, payload: (action_id, dict(payload)),
            current_focus_provider=lambda: "library-results",
        )
        return delegate, dialogs

    def test_export_host_event_rejects_active_action_id_without_comparison(self) -> None:
        touched: list[str] = []

        class ActiveActionId(str):
            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active action-id equality executed")

            def __ne__(self, other):
                touched.append("ne")
                raise AssertionError("active action-id inequality executed")

        with self.assertRaisesRegex(ValueError, "event action is invalid"):
            LibraryExportHostEvent(
                LibraryExportHostEventKind.FAILED,
                action_id=ActiveActionId("library.export"),
                error_code="library_export_failed",
            )

        self.assertEqual([], touched)

    def test_export_delegate_rejects_active_action_id_without_comparison(self) -> None:
        touched: list[str] = []
        forwarded: list[tuple[object, object]] = []

        class ActiveActionId(str):
            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active action-id equality executed")

            def __ne__(self, other):
                touched.append("ne")
                raise AssertionError("active action-id inequality executed")

        delegate = Version2WindowsLibraryExportDelegate(
            dialogs=_Dialogs(None),
            worker_services_factory=lambda: (_ for _ in ()).throw(
                AssertionError("worker factory must not run")
            ),
            post_to_ui=lambda callback: (_ for _ in ()).throw(
                AssertionError("UI poster must not run")
            ),
            event_sink=lambda event: (_ for _ in ()).throw(
                AssertionError("event sink must not run")
            ),
            next_delegate=lambda action_id, payload: forwarded.append(
                (action_id, payload)
            ),
        )

        with self.assertRaisesRegex(TypeError, "action id must be text"):
            delegate(ActiveActionId("library.export"), {})

        self.assertEqual([], touched)
        self.assertEqual([], forwarded)

    def test_owner_action_base_exceptions_are_bounded_and_path_free(self) -> None:
        class HostAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "host-abort.pgn"
            database = AcsDatabase()
            try:
                service = LibraryExportService(database)

                focus_delegate = Version2WindowsLibraryExportDelegate(
                    dialogs=_Dialogs(None),
                    service=service,
                    event_sink=lambda event: None,
                    next_delegate=lambda action_id, payload: None,
                    current_focus_provider=lambda: (_ for _ in ()).throw(
                        HostAbort("focus provider aborted")
                    ),
                )
                focus_result = focus_delegate(
                    "library.export",
                    LibraryExportRequest.selected([1]).browser_payload(),
                )
                self.assertEqual(
                    focus_result.kind,
                    LibraryExportHostEventKind.DIALOG_CANCELLED,
                )
                self.assertEqual(focus_result.focus_target, "")

                request_events: list[LibraryExportHostEvent] = []
                request_delegate = Version2WindowsLibraryExportDelegate(
                    dialogs=_Dialogs(destination),
                    service=service,
                    event_sink=request_events.append,
                    next_delegate=lambda action_id, payload: None,
                    current_focus_provider=lambda: "library-results",
                )
                with patch(
                    "acs.version2_windows_library_export.LibraryExportRequest.from_payload",
                    side_effect=HostAbort("request parser aborted"),
                ):
                    request_result = request_delegate("library.export", {})
                self.assertEqual(
                    request_result.error_code,
                    "invalid_export_request",
                )
                self.assertEqual(request_result.focus_target, "library-results")
                self.assertIs(request_result, request_events[-1])

                class AbortDialogs(_Dialogs):
                    def export_selection(self, suggested_filename: str = "selection.pgn"):
                        raise HostAbort("native dialog aborted")

                dialog_events: list[LibraryExportHostEvent] = []
                dialog_delegate = Version2WindowsLibraryExportDelegate(
                    dialogs=AbortDialogs(destination),
                    service=service,
                    event_sink=dialog_events.append,
                    next_delegate=lambda action_id, payload: None,
                    current_focus_provider=lambda: "library-results",
                )
                dialog_result = dialog_delegate(
                    "library.export",
                    LibraryExportRequest.selected([1]).browser_payload(),
                )
                self.assertEqual(dialog_result.error_code, "file_dialog_failed")
                self.assertEqual(dialog_result.focus_target, "library-results")
                self.assertIs(dialog_result, dialog_events[-1])

                sync_events: list[LibraryExportHostEvent] = []
                sync_delegate = Version2WindowsLibraryExportDelegate(
                    dialogs=_Dialogs(destination),
                    service=service,
                    event_sink=sync_events.append,
                    next_delegate=lambda action_id, payload: None,
                    current_focus_provider=lambda: "library-results",
                )
                with patch.object(
                    LibraryExportService,
                    "expected_destination_sha256",
                    autospec=True,
                    side_effect=HostAbort("synchronous provider aborted"),
                ):
                    sync_result = sync_delegate(
                        "library.export",
                        LibraryExportRequest.selected([1]).browser_payload(),
                    )
                self.assertEqual(sync_result.error_code, "library_export_failed")
                self.assertEqual(sync_result.focus_target, "library-results")
                self.assertFalse(destination.exists())
                self.assertIs(sync_result, sync_events[-1])
            finally:
                database.close()

    def test_started_sink_base_exception_cannot_strand_reserved_export_worker(self) -> None:
        class SinkAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "started-sink-abort.pgn"
            events: list[LibraryExportHostEvent] = []
            posted: list[object] = []

            def sink(event: LibraryExportHostEvent) -> None:
                events.append(event)
                if event.kind is LibraryExportHostEventKind.STARTED:
                    raise SinkAbort("started event sink aborted")

            delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_Dialogs(destination),
                worker_services_factory=self._worker_factory(database_path),
                post_to_ui=posted.append,
                event_sink=sink,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "library-results",
            )

            started = delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertEqual(len(posted), 1)
            self.assertTrue(delegate.export_running)

            posted.pop()()

            self.assertFalse(delegate.export_running)
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.EXPORTED)
            self.assertTrue(destination.exists())
            self.assertEqual(len(open_pgn(destination)), 1)

    def test_worker_factory_rejects_derived_services_without_field_or_cleanup_hooks(self) -> None:
        touched: list[str] = []

        class HostileWorkerServices(LibraryExportWorkerServices):
            def __getattribute__(self, name):
                if name in {"library", "close"}:
                    touched.append(name)
                    raise AssertionError("rejected worker-services hook executed")
                return super().__getattribute__(name)

        with tempfile.TemporaryDirectory() as directory:
            database = AcsDatabase()
            hostile = HostileWorkerServices.__new__(HostileWorkerServices)
            object.__setattr__(hostile, "library", LibraryExportService(database))
            object.__setattr__(hostile, "close", database.close)
            events: list[LibraryExportHostEvent] = []
            posted: list[object] = []
            delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_Dialogs(Path(directory) / "hostile-services.pgn"),
                worker_services_factory=lambda: hostile,
                post_to_ui=posted.append,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                current_focus_provider=lambda: "library-results",
            )
            try:
                started = delegate(
                    "library.export",
                    LibraryExportRequest.selected([1]).browser_payload(),
                )
                self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
                self.assertTrue(delegate.wait_for_export(timeout=2.0))
                self.assertEqual(touched, [])
                self.assertEqual(len(posted), 1)

                posted.pop()()

                self.assertFalse(delegate.export_running)
                self.assertEqual(events[-1].kind, LibraryExportHostEventKind.FAILED)
                self.assertEqual(events[-1].error_code, "library_export_failed")
                self.assertEqual(touched, [])
            finally:
                database.close()

    def test_worker_cleanup_base_exception_cannot_strand_selected_terminal(self) -> None:
        class CleanupAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "cleanup-abort.pgn"
            events: list[LibraryExportHostEvent] = []
            posted: list[object] = []
            cleanup_calls: list[str] = []

            def worker_factory() -> LibraryExportWorkerServices:
                database = AcsDatabase(database_path)

                def close() -> None:
                    cleanup_calls.append("close")
                    database.close()
                    raise CleanupAbort("secondary cleanup abort")

                return LibraryExportWorkerServices(
                    LibraryExportService(database),
                    close,
                )

            delegate, _ = self._delegate(
                destination,
                worker_factory,
                events,
                posted,
            )
            started = delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertEqual(cleanup_calls, ["close"])
            self.assertEqual(len(posted), 1)
            self.assertTrue(delegate.export_running)

            posted.pop()()

            self.assertFalse(delegate.export_running)
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(events[-1].game_count, 1)
            self.assertTrue(destination.exists())
            self.assertEqual(len(open_pgn(destination)), 1)

    def test_refused_shutdown_resume_reuses_owner_and_fences_stale_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            first_destination = Path(directory) / "before-refused-close.pgn"
            second_destination = Path(directory) / "after-refused-close.pgn"
            events: list[LibraryExportHostEvent] = []
            posted: list[object] = []
            delegate, dialogs = self._delegate(
                first_destination,
                self._worker_factory(database_path),
                events,
                posted,
            )
            request = LibraryExportRequest.selected([game_id]).browser_payload()

            first_started = delegate("library.export", request)
            self.assertEqual(first_started.kind, LibraryExportHostEventKind.STARTED)
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertEqual(len(posted), 1)
            stale_finish = posted.pop()
            self.assertTrue(delegate.export_running)
            self.assertTrue(first_destination.exists())

            self.assertTrue(delegate.shutdown())
            self.assertFalse(delegate.export_running)
            unavailable = delegate("library.export", request)
            self.assertEqual(unavailable.kind, LibraryExportHostEventKind.FAILED)
            self.assertEqual(unavailable.error_code, "library_export_unavailable")

            self.assertTrue(delegate.resume_after_refused_shutdown())
            stale_finish()
            self.assertEqual(
                [event.kind for event in events],
                [
                    LibraryExportHostEventKind.STARTED,
                    LibraryExportHostEventKind.FAILED,
                ],
            )
            self.assertFalse(delegate.export_running)

            dialogs.destination = second_destination
            second_started = delegate("library.export", request)
            self.assertEqual(second_started.kind, LibraryExportHostEventKind.STARTED)
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertEqual(len(posted), 1)
            posted.pop()()

            self.assertFalse(delegate.export_running)
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(events[-1].game_count, 1)
            self.assertTrue(second_destination.exists())
            self.assertEqual(len(open_pgn(second_destination)), 1)
            self.assertTrue(delegate.shutdown())

    def test_export_scope_rejects_active_text_before_comparison_or_dialog(self) -> None:
        touched: list[str] = []

        class ActiveScope(str):
            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active scope equality executed")

            def __ne__(self, other):
                touched.append("ne")
                raise AssertionError("active scope inequality executed")

        payload = {
            "scope": ActiveScope(LibraryExportScope.SELECTED.value),
            "game_ids": [1],
        }
        with self.assertRaisesRegex(ValueError, "unsupported Library export scope"):
            LibraryExportRequest.from_payload(payload)
        self.assertEqual([], touched)

        dialogs = _Dialogs(Path("must-not-open.pgn"))
        events: list[LibraryExportHostEvent] = []
        delegate = Version2WindowsLibraryExportDelegate(
            dialogs=dialogs,
            worker_services_factory=lambda: (_ for _ in ()).throw(
                AssertionError("worker factory must not run")
            ),
            post_to_ui=lambda callback: (_ for _ in ()).throw(
                AssertionError("UI poster must not run")
            ),
            event_sink=events.append,
            next_delegate=lambda action_id, value: (_ for _ in ()).throw(
                AssertionError("next delegate must not run")
            ),
            current_focus_provider=lambda: "library-results",
        )

        terminal = delegate("library.export", payload)

        self.assertEqual([], touched)
        self.assertEqual(dialogs.calls, [])
        self.assertEqual(len(events), 1)
        self.assertIs(terminal, events[0])
        self.assertEqual(terminal.kind, LibraryExportHostEventKind.FAILED)
        self.assertEqual(terminal.error_code, "invalid_export_request")
        self.assertEqual(terminal.focus_target, "library-results")

    def test_export_delegate_still_forwards_unknown_exact_string_action(self) -> None:
        forwarded: list[tuple[str, object]] = []
        payload = {"opaque": object()}
        delegate = Version2WindowsLibraryExportDelegate(
            dialogs=_Dialogs(None),
            worker_services_factory=lambda: (_ for _ in ()).throw(
                AssertionError("worker factory must not run")
            ),
            post_to_ui=lambda callback: (_ for _ in ()).throw(
                AssertionError("UI poster must not run")
            ),
            event_sink=lambda event: (_ for _ in ()).throw(
                AssertionError("event sink must not run")
            ),
            next_delegate=lambda action_id, value: forwarded.append(
                (action_id, value)
            )
            or "next",
        )

        result = delegate("library.other", payload)

        self.assertEqual("next", result)
        self.assertEqual([("library.other", payload)], forwarded)

    def test_reentrant_shutdown_during_started_event_never_starts_reserved_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "must-not-start-after-shutdown.pgn"
            events: list[LibraryExportHostEvent] = []
            shutdown_results: list[bool] = []
            delegate_box: dict[str, Version2WindowsLibraryExportDelegate] = {}

            def event_sink(event: LibraryExportHostEvent) -> None:
                events.append(event)
                if event.kind is LibraryExportHostEventKind.STARTED:
                    shutdown_results.append(delegate_box["delegate"].shutdown(timeout=0.1))

            delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_Dialogs(destination),
                worker_services_factory=self._worker_factory(database_path),
                post_to_ui=lambda callback: None,
                event_sink=event_sink,
                next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                current_focus_provider=lambda: "library-results",
            )
            delegate_box["delegate"] = delegate
            starts: list[str] = []

            with patch(
                "acs.version2_windows_library_export.threading.Thread.start",
                autospec=True,
                side_effect=lambda thread: starts.append(thread.name),
            ):
                result = delegate(
                    "library.export",
                    LibraryExportRequest.selected([game_id]).browser_payload(),
                )

            self.assertEqual(shutdown_results, [True])
            self.assertEqual(starts, [])
            self.assertFalse(delegate.export_running)
            self.assertFalse(destination.exists())
            self.assertEqual(
                [event.kind for event in events],
                [
                    LibraryExportHostEventKind.STARTED,
                    LibraryExportHostEventKind.FAILED,
                ],
            )
            self.assertIs(result, events[-1])
            self.assertEqual(result.error_code, "library_export_unavailable")
            self.assertEqual(result.focus_target, "library-results")

    def test_reentrant_cancel_during_started_event_never_starts_reserved_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "must-not-start-after-cancel.pgn"
            events: list[LibraryExportHostEvent] = []
            cancel_results: list[LibraryExportHostEvent] = []
            delegate_box: dict[str, Version2WindowsLibraryExportDelegate] = {}

            def event_sink(event: LibraryExportHostEvent) -> None:
                events.append(event)
                if event.kind is LibraryExportHostEventKind.STARTED:
                    cancel_results.append(delegate_box["delegate"].cancel_export())

            delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_Dialogs(destination),
                worker_services_factory=self._worker_factory(database_path),
                post_to_ui=lambda callback: None,
                event_sink=event_sink,
                next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                current_focus_provider=lambda: "library-results",
            )
            delegate_box["delegate"] = delegate
            starts: list[str] = []

            with patch(
                "acs.version2_windows_library_export.threading.Thread.start",
                autospec=True,
                side_effect=lambda thread: starts.append(thread.name),
            ):
                result = delegate(
                    "library.export",
                    LibraryExportRequest.selected([game_id]).browser_payload(),
                )

            self.assertEqual(starts, [])
            self.assertFalse(delegate.export_running)
            self.assertFalse(destination.exists())
            self.assertEqual(len(cancel_results), 1)
            self.assertEqual(
                cancel_results[0].kind,
                LibraryExportHostEventKind.CANCELLING,
            )
            self.assertEqual(
                [event.kind for event in events],
                [
                    LibraryExportHostEventKind.STARTED,
                    LibraryExportHostEventKind.CANCELLING,
                    LibraryExportHostEventKind.DIALOG_CANCELLED,
                ],
            )
            self.assertIs(result, events[-1])
            self.assertEqual(result.focus_target, "library-results")

    def test_cancel_callback_base_exception_is_a_bounded_control_failure(self) -> None:
        class CancelAbort(BaseException):
            pass

        database = AcsDatabase()
        try:
            service = LibraryExportService(database)
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "cancel-control-abort.pgn"

                with self.assertRaises(LibraryExportControlError):
                    service.expected_destination_sha256(
                        destination,
                        cancel_check=lambda: (_ for _ in ()).throw(
                            CancelAbort("cancel provider aborted")
                        ),
                    )

                with self.assertRaises(LibraryExportControlError):
                    service.export_to(
                        destination,
                        LibraryExportRequest.selected([1]),
                        cancel_check=lambda: (_ for _ in ()).throw(
                            CancelAbort("cancel provider aborted")
                        ),
                    )

                self.assertFalse(destination.exists())
        finally:
            database.close()

    def test_destination_hashing_is_cooperatively_cancellable_between_chunks(self) -> None:
        database = AcsDatabase()
        try:
            service = LibraryExportService(database)
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "large-existing.pgn"
                original = b"x" * (3 * 1024 * 1024 + 17)
                destination.write_bytes(original)
                polls = 0

                def cancel_check() -> bool:
                    nonlocal polls
                    polls += 1
                    return polls >= 3

                with self.assertRaises(LibraryExportCancelledError):
                    service.expected_destination_sha256(
                        destination,
                        cancel_check=cancel_check,
                    )
                self.assertEqual(destination.read_bytes(), original)
                self.assertGreaterEqual(polls, 3)
        finally:
            database.close()

    def test_service_revalidates_directly_constructed_export_requests(self) -> None:
        database = AcsDatabase()
        try:
            service = LibraryExportService(database)
            invalid = (
                LibraryExportRequest(
                    scope=LibraryExportScope.SELECTED,
                    game_ids=(True,),
                ),
                LibraryExportRequest(
                    scope=LibraryExportScope.SELECTED,
                    game_ids=(1,),
                    query=GameSearchQuery(),
                ),
                LibraryExportRequest(
                    scope=LibraryExportScope.FILTERED,
                    game_ids=(1,),
                    query=GameSearchQuery(),
                ),
                LibraryExportRequest(
                    scope=LibraryExportScope.FILTERED,
                    query=GameSearchQuery(after_game_id=1),
                ),
            )
            with tempfile.TemporaryDirectory() as directory:
                for index, request in enumerate(invalid):
                    with self.subTest(index=index):
                        destination = Path(directory) / f"invalid-{index}.pgn"
                        with self.assertRaises(LibraryExportError):
                            service.export_to(destination, request)
                        self.assertFalse(destination.exists())
        finally:
            database.close()

    def test_filtered_export_cancel_reaches_search_progress_boundary(self) -> None:
        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="cancel-search.pgn")
            polls = 0

            def cancel_check() -> bool:
                nonlocal polls
                polls += 1
                return polls >= 3

            class CancelInsideSearch(GameSearchService):
                def search(self, query=None, *, cancel_check=None):
                    self_assert = cancel_check
                    if self_assert is None:
                        raise AssertionError("filtered export did not pass cancel_check")
                    if self_assert():
                        raise SearchCancelledError("cancelled inside SQLite search")
                    return super().search(query, cancel_check=cancel_check)

            service = LibraryExportService(
                database,
                search_service=CancelInsideSearch(database),
            )
            request = LibraryExportRequest.filtered(GameSearchQuery())
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "cancel-search.pgn"
                with self.assertRaises(LibraryExportCancelledError):
                    service.export_to(
                        destination,
                        request,
                        cancel_check=cancel_check,
                    )
                self.assertFalse(destination.exists())
                self.assertEqual(list(Path(directory).glob("*.tmp")), [])
            self.assertEqual(polls, 3)
        finally:
            database.close()

    def test_filtered_export_rejects_nonadvancing_or_inconsistent_search_pages(self) -> None:
        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="malformed-search-page.pgn")
            canonical_search = GameSearchService(database)
            canonical_page = canonical_search.search(GameSearchQuery(limit=200))
            self.assertTrue(canonical_page.items)
            first = canonical_page.items[0]

            class MalformedSearch(GameSearchService):
                def __init__(self, db, mode):
                    super().__init__(db)
                    self.mode = mode

                def search(self, query=None, **_kwargs):
                    if self.mode == "backward-id":
                        return GameSearchPage(
                            items=(first,),
                            next_after_game_id=first.game_id,
                            has_more=True,
                        )
                    if self.mode == "empty-more":
                        return GameSearchPage(
                            items=(),
                            next_after_game_id=first.game_id,
                            has_more=True,
                        )
                    if self.mode == "terminal-cursor":
                        return GameSearchPage(
                            items=(first,),
                            next_after_game_id=first.game_id,
                            has_more=False,
                        )
                    if self.mode == "oversized-page":
                        return GameSearchPage(
                            items=tuple(
                                replace(first, game_id=first.game_id + offset)
                                for offset in range(201)
                            ),
                            next_after_game_id=None,
                            has_more=False,
                        )
                    raise AssertionError("unexpected malformed-search mode")

            request = LibraryExportRequest.filtered(GameSearchQuery())
            for mode, message in (
                ("backward-id", "ids are not strictly increasing"),
                ("empty-more", "paging did not advance"),
                ("terminal-cursor", "terminal search page has a cursor"),
                ("oversized-page", "search page exceeds the page limit"),
            ):
                with self.subTest(mode=mode):
                    service = LibraryExportService(
                        database,
                        search_service=MalformedSearch(database, mode),
                    )
                    with tempfile.TemporaryDirectory() as directory:
                        destination = Path(directory) / f"{mode}.pgn"
                        with self.assertRaisesRegex(LibraryExportError, message):
                            service.export_to(destination, request)
                        self.assertFalse(destination.exists())
        finally:
            database.close()

    def test_export_rejects_active_database_row_before_mapping_hooks(self) -> None:
        touched: list[str] = []

        class HostileRow(dict):
            def get(self, *_args, **_kwargs):
                touched.append("get")
                raise AssertionError("rejected database row hook executed")

        class RowDatabase(AcsDatabase):
            def get_game(self, game_id):
                return HostileRow({"pgn_text": _PGN})

        database = RowDatabase()
        try:
            service = LibraryExportService(database)
            request = LibraryExportRequest.selected([1])
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "active-row.pgn"
                with self.assertRaisesRegex(
                    LibraryExportError,
                    "game record is invalid",
                ):
                    service.export_to(destination, request)
                self.assertFalse(destination.exists())
                self.assertEqual(touched, [])
        finally:
            database.close()

    def test_export_request_rejects_provider_containers_without_running_hooks(self) -> None:
        touched: list[str] = []

        class HostileDict(dict):
            def __len__(self):
                touched.append("dict-len")
                raise AssertionError("hostile dict hook executed")

            def __iter__(self):
                touched.append("dict-iter")
                raise AssertionError("hostile dict hook executed")

            def get(self, *_args, **_kwargs):
                touched.append("dict-get")
                raise AssertionError("hostile dict hook executed")

        class HostileList(list):
            def __len__(self):
                touched.append("list-len")
                raise AssertionError("hostile list hook executed")

            def __iter__(self):
                touched.append("list-iter")
                raise AssertionError("hostile list hook executed")

        with self.assertRaisesRegex(ValueError, "invalid Library export request"):
            LibraryExportRequest.from_payload(
                HostileDict({"scope": "selected", "game_ids": [1]})
            )
        with self.assertRaisesRegex(ValueError, "invalid Library export filters"):
            LibraryExportRequest.from_payload(
                {"scope": "filtered", "filters": HostileDict({"player": "A"})}
            )
        with self.assertRaisesRegex(TypeError, "selected game ids"):
            LibraryExportRequest.selected(HostileList([1]))

        self.assertEqual(touched, [])

    def test_direct_empty_selected_request_fails_before_any_file_write(self) -> None:
        database = AcsDatabase()
        try:
            service = LibraryExportService(database)
            request = LibraryExportRequest(
                scope=LibraryExportScope.SELECTED,
                game_ids=(),
            )
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "must-not-exist.pgn"
                with self.assertRaisesRegex(
                    LibraryExportError,
                    "selected Library export contains no games",
                ):
                    service.export_to(destination, request)
                self.assertFalse(destination.exists())
                self.assertEqual(list(Path(directory).glob("*.tmp")), [])
        finally:
            database.close()

    def test_synchronous_host_rejects_export_result_subclass(self) -> None:
        class DerivedResult(LibraryExportResult):
            pass

        class DerivedResultService(LibraryExportService):
            def export_to(
                self,
                destination,
                request,
                *,
                expected_sha256=None,
                cancel_check=None,
            ):
                return DerivedResult(
                    game_count=1,
                    destination_fingerprint=SimpleNamespace(),
                )

        database = AcsDatabase()
        try:
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "derived-result.pgn"
                events: list[LibraryExportHostEvent] = []
                delegate = Version2WindowsLibraryExportDelegate(
                    dialogs=_Dialogs(destination),
                    service=DerivedResultService(database),
                    event_sink=events.append,
                    next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                    current_focus_provider=lambda: "library-results",
                )

                result = delegate(
                    "library.export",
                    LibraryExportRequest.selected([1]).browser_payload(),
                )

                self.assertEqual(result.kind, LibraryExportHostEventKind.FAILED)
                self.assertEqual(result.error_code, "library_export_failed")
                self.assertIs(result, events[-1])
                self.assertFalse(destination.exists())
        finally:
            database.close()

    def test_invalid_zero_count_synchronous_result_is_bounded_failure(self) -> None:
        database = AcsDatabase()
        try:
            service = _ZeroCountLibraryExportService(database)
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "invalid-sync-zero-result.pgn"
                events: list[LibraryExportHostEvent] = []
                delegate = Version2WindowsLibraryExportDelegate(
                    dialogs=_Dialogs(destination),
                    service=service,
                    event_sink=events.append,
                    next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                    current_focus_provider=lambda: "library-results",
                )

                result = delegate(
                    "library.export",
                    LibraryExportRequest.selected([1]).browser_payload(),
                )

                self.assertIs(result, events[-1])
                self.assertEqual(result.kind, LibraryExportHostEventKind.FAILED)
                self.assertEqual(result.error_code, "library_export_failed")
                self.assertEqual(result.focus_target, "library-results")
                self.assertFalse(destination.exists())
        finally:
            database.close()

    def test_invalid_zero_count_worker_result_fails_without_stranding_busy_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "invalid-zero-result.pgn"
            events: list = []
            posted: list = []

            def worker_factory() -> LibraryExportWorkerServices:
                database = AcsDatabase(database_path)
                return LibraryExportWorkerServices(
                    _ZeroCountLibraryExportService(database),
                    database.close,
                )

            delegate, _ = self._delegate(
                destination,
                worker_factory,
                events,
                posted,
            )
            started = delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertTrue(delegate.export_running)
            self.assertEqual(len(posted), 1)

            posted.pop()()
            self.assertFalse(delegate.export_running)
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_export_failed")
            self.assertFalse(destination.exists())

    def test_post_publish_rollback_failure_keeps_durable_success_authoritative(self) -> None:
        database = AcsDatabase()
        real_connection = database.conn
        try:
            database.import_pgn_text(_PGN, source_name="cleanup-success.pgn")
            row = real_connection.execute(
                "SELECT id FROM games ORDER BY id LIMIT 1"
            ).fetchone()
            assert row is not None
            request = LibraryExportRequest.selected([int(row["id"])])
            service = LibraryExportService(database)
            database.conn = _RollbackFailingConnection(real_connection)

            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "published-before-cleanup-failure.pgn"
                result = service.export_to(destination, request)

                self.assertEqual(result.game_count, 1)
                self.assertTrue(destination.exists())
                self.assertEqual(len(open_pgn(destination).games), 1)
                with self.assertRaisesRegex(
                    LibraryExportError,
                    "snapshot cleanup previously failed",
                ):
                    service.resolve_games(request)
        finally:
            database.conn = real_connection
            database.close()

    def test_primary_export_error_is_not_masked_by_snapshot_cleanup_failure(self) -> None:
        database = AcsDatabase()
        real_connection = database.conn
        try:
            service = LibraryExportService(database)
            database.conn = _RollbackFailingConnection(real_connection)
            missing = LibraryExportRequest.selected([9223372036854775807])

            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "must-not-publish.pgn"
                with self.assertRaisesRegex(
                    LibraryExportError,
                    "Library export game is unavailable",
                ):
                    service.export_to(destination, missing)
                self.assertFalse(destination.exists())
        finally:
            database.conn = real_connection
            database.close()

    def test_cancel_at_prepublication_gate_leaves_no_output_or_temp_file(self) -> None:
        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="prepublish.pgn")
            row = database.conn.execute("SELECT id FROM games ORDER BY id LIMIT 1").fetchone()
            assert row is not None
            request = LibraryExportRequest.selected([int(row["id"])])
            service = LibraryExportService(database)
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "cancelled.pgn"
                polls = 0

                def cancel_check() -> bool:
                    nonlocal polls
                    polls += 1
                    # export_to polls once before work, before and after the one
                    # game, then at D06's pre-publication gate.
                    return polls >= 4

                with self.assertRaises(LibraryExportCancelledError):
                    service.export_to(
                        destination,
                        request,
                        cancel_check=cancel_check,
                    )
                self.assertFalse(destination.exists())
                self.assertEqual(list(Path(directory).glob("*.tmp")), [])
                self.assertEqual(list(Path(directory).glob("*.cas-*.bak")), [])
                self.assertEqual(polls, 4)
        finally:
            database.close()

    def test_export_runs_after_dialog_and_terminal_event_is_marshaled_to_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "background-export.pgn"
            events: list = []
            posted: list = []
            delegate, dialogs = self._delegate(
                destination,
                self._worker_factory(database_path),
                events,
                posted,
            )

            started = delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertEqual(started.kind, LibraryExportHostEventKind.STARTED)
            self.assertEqual(events, [started])
            self.assertEqual(dialogs.calls, ["library-export.pgn"])
            self.assertTrue(delegate.wait_for_export())
            self.assertTrue(delegate.export_running)
            self.assertEqual(len(posted), 1)
            self.assertEqual(len(events), 1)

            posted.pop()()
            self.assertFalse(delegate.export_running)
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(events[-1].game_count, 1)
            self.assertEqual(events[-1].focus_target, "library-results")
            self.assertNotIn(str(destination), repr(events[-1]))
            self.assertEqual(len(open_pgn(destination).games), 1)

    def test_single_flight_rejects_second_export_before_opening_second_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "one-flight.pgn"
            hashing_started = threading.Event()
            release_hash = threading.Event()
            events: list = []
            posted: list = []

            def worker_factory() -> LibraryExportWorkerServices:
                database = AcsDatabase(database_path)
                return LibraryExportWorkerServices(
                    _BlockingLibraryExportService(
                        database,
                        hashing_started=hashing_started,
                        release_hash=release_hash,
                    ),
                    database.close,
                )

            delegate, dialogs = self._delegate(
                destination,
                worker_factory,
                events,
                posted,
            )
            request = LibraryExportRequest.selected([game_id]).browser_payload()
            first = delegate("library.export", request)
            self.assertEqual(first.kind, LibraryExportHostEventKind.STARTED)
            self.assertTrue(hashing_started.wait(timeout=2.0))

            second = delegate("library.export", request)
            self.assertEqual(second.kind, LibraryExportHostEventKind.FAILED)
            self.assertEqual(second.error_code, "library_export_busy")
            self.assertEqual(dialogs.calls, ["library-export.pgn"])

            cancelling = delegate.cancel_export()
            self.assertEqual(cancelling.kind, LibraryExportHostEventKind.CANCELLING)
            release_hash.set()
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertEqual(len(posted), 1)
            posted.pop()()
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.DIALOG_CANCELLED)
            self.assertFalse(destination.exists())

    def test_late_cancel_consumes_already_chosen_durable_success_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "durable-winner.pgn"
            events: list = []
            posted: list = []
            delegate, _ = self._delegate(
                destination,
                self._worker_factory(database_path),
                events,
                posted,
            )
            delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertEqual(len(posted), 1)
            self.assertTrue(destination.exists())

            terminal = delegate.cancel_export()
            self.assertEqual(terminal.kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(events[-1], terminal)
            self.assertFalse(delegate.export_running)
            self.assertNotIn(
                LibraryExportHostEventKind.CANCELLING,
                [event.kind for event in events],
            )
            event_count = len(events)

            posted.pop()()
            self.assertEqual(len(events), event_count)
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.EXPORTED)

    def test_terminal_ui_post_failure_retries_without_losing_accessible_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "retry-terminal.pgn"
            events: list = []
            posted: list = []
            retry_posted = threading.Event()
            post_attempts = 0

            def flaky_post(callback) -> None:
                nonlocal post_attempts
                post_attempts += 1
                if post_attempts == 1:
                    raise RuntimeError("simulated BeginInvoke rejection")
                posted.append(callback)
                retry_posted.set()

            delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_Dialogs(destination),
                worker_services_factory=self._worker_factory(database_path),
                post_to_ui=flaky_post,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                current_focus_provider=lambda: "library-results",
            )
            delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertTrue(retry_posted.wait(timeout=2.0))
            self.assertEqual(post_attempts, 2)
            self.assertTrue(delegate.export_running)
            self.assertEqual(
                [event.kind for event in events],
                [LibraryExportHostEventKind.STARTED],
            )

            posted.pop()()
            self.assertFalse(delegate.export_running)
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(events[-1].focus_target, "library-results")
            self.assertEqual(len(open_pgn(destination).games), 1)

    def test_terminal_stays_recoverable_after_retry_post_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "manual-terminal-recovery.pgn"
            events: list = []
            retry_attempted = threading.Event()
            post_attempts = 0

            def broken_post(_callback) -> None:
                nonlocal post_attempts
                post_attempts += 1
                if post_attempts >= 2:
                    retry_attempted.set()
                raise RuntimeError("simulated persistent BeginInvoke rejection")

            delegate = Version2WindowsLibraryExportDelegate(
                dialogs=_Dialogs(destination),
                worker_services_factory=self._worker_factory(database_path),
                post_to_ui=broken_post,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: (action_id, dict(payload)),
                current_focus_provider=lambda: "library-results",
            )
            delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertTrue(retry_attempted.wait(timeout=2.0))
            self.assertTrue(delegate.export_running)

            self.assertTrue(delegate.recover_pending_terminal())
            terminal = events[-1]
            self.assertEqual(terminal.kind, LibraryExportHostEventKind.EXPORTED)
            self.assertFalse(delegate.export_running)
            self.assertFalse(delegate.recover_pending_terminal())
            self.assertEqual(post_attempts, 2)
            self.assertEqual(len(open_pgn(destination).games), 1)

    def test_export_activity_enables_one_shared_cancel_action_and_blocks_competing_ui_work(self) -> None:
        database = AcsDatabase()
        dispatched: list[tuple[str, dict[str, object]]] = []
        try:
            database.import_pgn_text(_PGN, source_name="projection.pgn")
            bridge = build_library_export_webview(
                database,
                lambda action, payload: dispatched.append((action, dict(payload))),
                language=UILanguage.EN,
            )
            bridge.dispatch("library.search", {})
            baseline = bridge.projection.snapshot()
            baseline_import = baseline["import"]
            self.assertTrue(baseline_import["actions"][0]["enabled"])
            self.assertFalse(baseline_import["actions"][1]["enabled"])

            started = bridge.projection.host_export_started()
            self.assertEqual(started.kind, "render-import")
            self.assertEqual(started.payload["focus_target"], "library-import-cancel")
            started_actions = started.payload["import"]["actions"]
            self.assertFalse(started_actions[0]["enabled"])
            self.assertTrue(started_actions[1]["enabled"])
            self.assertEqual(started_actions[1]["label"], "Cancel export")

            busy_snapshot = bridge.projection.snapshot()
            export_actions = {
                action["action"]: action
                for action in busy_snapshot["actions"]
                if action["action"].startswith("library.export_")
            }
            self.assertFalse(export_actions["library.export_selected"]["enabled"])
            self.assertFalse(export_actions["library.export_filtered"]["enabled"])

            cancelling = bridge.dispatch("library.cancel_import", {})
            self.assertEqual(dispatched[-1], ("library.cancel_import", {}))
            self.assertEqual(cancelling.kind, "render-import")
            self.assertFalse(cancelling.payload["import"]["actions"][1]["enabled"])

            finished = bridge.projection.host_export_finished()
            self.assertEqual(finished.kind, "render-import")
            finished_actions = finished.payload["import"]["actions"]
            self.assertTrue(finished_actions[0]["enabled"])
            self.assertFalse(finished_actions[1]["enabled"])
            self.assertFalse(bridge.projection.export_running)
        finally:
            database.close()

    def test_library_browser_bridge_bounds_projection_base_exception(self) -> None:
        class ProjectionAbort(BaseException):
            pass

        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="bridge-abort.pgn")
            bridge = build_library_export_webview(
                database,
                lambda action, payload: None,
                language=UILanguage.EN,
            )
            rendered = bridge.projection.search(GameSearchQuery())
            game_id = rendered.payload["snapshot"]["rows"][0]["game_id"]

            with patch.object(
                bridge.projection,
                "toggle_export_selection",
                side_effect=ProjectionAbort("projection command aborted"),
            ):
                event = bridge.dispatch(
                    "library.toggle_export_selection",
                    {"game_id": game_id},
                )

            self.assertEqual(event.kind, "error")
            self.assertEqual(bridge.projection.export_game_ids, ())
        finally:
            database.close()

    def test_export_projection_mutations_roll_back_on_base_exception(self) -> None:
        class ProjectionAbort(BaseException):
            pass

        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="selection-atomicity.pgn")
            bridge = build_library_export_webview(
                database,
                lambda action, payload: None,
                language=UILanguage.EN,
            )
            projection = bridge.projection
            rendered = projection.search(GameSearchQuery())
            game_id = rendered.payload["snapshot"]["rows"][0]["game_id"]

            with patch.object(
                projection,
                "_render_event",
                side_effect=ProjectionAbort("simulated malformed presenter render"),
            ):
                with self.assertRaises(ProjectionAbort):
                    projection.toggle_export_selection(game_id)
            self.assertEqual(projection.export_game_ids, ())

            projection.toggle_export_selection(game_id)
            self.assertEqual(projection.export_game_ids, (game_id,))
            with patch.object(
                projection,
                "_render_event",
                side_effect=ProjectionAbort("simulated malformed clear render"),
            ):
                with self.assertRaises(ProjectionAbort):
                    projection.clear_export_selection()
            self.assertEqual(projection.export_game_ids, (game_id,))

            with patch(
                "acs.library_export_webview_projection.LibraryWebViewProjection.search",
                side_effect=ProjectionAbort("canonical search aborted"),
            ):
                with self.assertRaises(ProjectionAbort):
                    projection.search(GameSearchQuery(player="Different"))
            self.assertEqual(projection.export_game_ids, (game_id,))

            projection.host_export_started()
            with patch.object(
                projection,
                "_dispatch",
                side_effect=ProjectionAbort("cancel dispatch aborted"),
            ):
                with self.assertRaises(ProjectionAbort):
                    projection.request_cancel_operation()
            cancel_action = next(
                action
                for action in projection.snapshot()["import"]["actions"]
                if action["action"] == "library.cancel_import"
            )
            self.assertTrue(cancel_action["enabled"])
            projection.host_export_finished()
        finally:
            database.close()

    def test_cancel_library_operation_hotkey_resolves_from_library_and_document_contexts(self) -> None:
        registry = build_full_product_action_registry()
        definition = registry.definition("library.cancel_import")
        self.assertEqual(definition.context, BindingContext.GLOBAL)
        self.assertEqual(registry.get_binding("library.cancel_import"), "Ctrl+Shift+X")
        for context in (
            BindingContext.DOCUMENT,
            BindingContext.DATABASE,
            BindingContext.LIBRARY_RESULTS,
        ):
            with self.subTest(context=context):
                resolved = registry.resolve_binding(context, "Ctrl+Shift+X")
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved.action_id, "library.cancel_import")

        keymap = build_web_keymap(registry)
        projected = next(
            item for item in keymap["actions"]
            if item["id"] == "library.cancel_import"
        )
        self.assertEqual(projected["registryContext"], "global")
        self.assertEqual(projected["context"], "document")
        self.assertEqual(projected["labelUk"], "Скасувати операцію бібліотеки")
        self.assertEqual(projected["labelEn"], "Cancel library operation")

    def test_application_publishes_export_cancel_availability_as_partial_library_event(self) -> None:
        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="app-projection.pgn")
            bridge = build_library_export_webview(
                database,
                lambda action, payload: None,
                language=UILanguage.EN,
            )
            fake = SimpleNamespace(
                shell=SimpleNamespace(language=UILanguage.EN),
                library=bridge,
                _events=[],
                _native_file_error_message=lambda event: "The action could not be completed.",
            )
            started = LibraryExportHostEvent(
                LibraryExportHostEventKind.STARTED,
                focus_target="library-export-selected",
            )
            Version2Application._file_event(fake, started)
            self.assertEqual(fake._events[0]["kind"], "render-import")
            self.assertEqual(
                fake._events[0]["payload"]["focus_target"],
                "library-import-cancel",
            )
            self.assertTrue(fake._events[0]["payload"]["import"]["actions"][1]["enabled"])
            self.assertEqual(fake._events[1]["kind"], "status")

            fake._events.clear()
            terminal = LibraryExportHostEvent(
                LibraryExportHostEventKind.EXPORTED,
                focus_target="library-export-selected",
                game_count=1,
            )
            Version2Application._file_event(fake, terminal)
            self.assertEqual(fake._events[0]["kind"], "render-import")
            self.assertFalse(fake._events[0]["payload"]["import"]["actions"][1]["enabled"])
            self.assertEqual(
                fake._events[1]["payload"]["focus_target"],
                "library-export-selected",
            )
            self.assertFalse(bridge.projection.export_running)
        finally:
            database.close()

    def test_busy_export_rejection_does_not_finish_active_export_presentation(self) -> None:
        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="busy-presentation.pgn")
            bridge = build_library_export_webview(
                database,
                lambda action, payload: None,
                language=UILanguage.EN,
            )
            fake = SimpleNamespace(
                shell=SimpleNamespace(language=UILanguage.EN),
                library=bridge,
                _events=[],
                _native_file_error_message=lambda event: "The action could not be completed.",
            )

            Version2Application._file_event(
                fake,
                LibraryExportHostEvent(
                    LibraryExportHostEventKind.STARTED,
                    focus_target="library-export-selected",
                ),
            )
            self.assertTrue(bridge.projection.export_running)

            fake._events.clear()
            Version2Application._file_event(
                fake,
                LibraryExportHostEvent(
                    LibraryExportHostEventKind.FAILED,
                    focus_target="library-export-selected",
                    error_code="library_export_busy",
                ),
            )

            self.assertTrue(bridge.projection.export_running)
            snapshot = bridge.projection.snapshot()
            import_actions = snapshot["import"]["actions"]
            self.assertFalse(import_actions[0]["enabled"])
            self.assertTrue(import_actions[1]["enabled"])
            self.assertEqual(import_actions[1]["label"], "Cancel export")
            self.assertEqual(
                fake._events,
                [
                    {
                        "kind": "error",
                        "payload": {
                            "message": "The action could not be completed.",
                        },
                    }
                ],
            )

            fake._events.clear()
            Version2Application._file_event(
                fake,
                LibraryExportHostEvent(
                    LibraryExportHostEventKind.EXPORTED,
                    focus_target="library-export-selected",
                    game_count=1,
                ),
            )
            self.assertFalse(bridge.projection.export_running)
            self.assertEqual(fake._events[0]["kind"], "render-import")
            self.assertFalse(
                fake._events[0]["payload"]["import"]["actions"][1]["enabled"]
            )
            self.assertEqual(
                fake._events[1]["payload"]["focus_target"],
                "library-export-selected",
            )
        finally:
            database.close()

    def test_no_import_running_recovers_stale_export_after_lost_terminal_event(self) -> None:
        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="lost-terminal-recovery.pgn")
            bridge = build_library_export_webview(
                database,
                lambda action, payload: None,
                language=UILanguage.EN,
            )
            bridge.projection.host_export_started()
            self.assertTrue(bridge.projection.export_running)
            fake = SimpleNamespace(
                shell=SimpleNamespace(language=UILanguage.EN),
                library=bridge,
                _events=[],
                _native_file_error_message=lambda event: "The action could not be completed.",
            )

            Version2Application._file_event(
                fake,
                FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.cancel_import",
                    focus_target="library-import-file",
                    error_code="no_import_running",
                ),
            )

            self.assertFalse(bridge.projection.export_running)
            self.assertEqual(fake._events[0]["kind"], "render-import")
            self.assertFalse(
                fake._events[0]["payload"]["import"]["actions"][1]["enabled"]
            )
            self.assertEqual(
                fake._events[1],
                {
                    "kind": "status",
                    "payload": {
                        "announcement": "The Library operation has already finished.",
                        "focus_target": "library-import-file",
                    },
                },
            )
        finally:
            database.close()

    def test_known_idle_export_failures_recover_stale_busy_projection_and_focus(self) -> None:
        database = AcsDatabase()
        try:
            database.import_pgn_text(_PGN, source_name="idle-recovery.pgn")
            for error_code in (
                "file_dialog_failed",
                "library_export_unavailable",
                "no_library_export_running",
            ):
                with self.subTest(error_code=error_code):
                    bridge = build_library_export_webview(
                        database,
                        lambda action, payload: None,
                        language=UILanguage.EN,
                    )
                    fake = SimpleNamespace(
                        shell=SimpleNamespace(language=UILanguage.EN),
                        library=bridge,
                        _events=[],
                        _native_file_error_message=lambda event: "The action could not be completed.",
                    )
                    Version2Application._file_event(
                        fake,
                        LibraryExportHostEvent(
                            LibraryExportHostEventKind.STARTED,
                            focus_target="library-export-filtered",
                        ),
                    )
                    self.assertTrue(bridge.projection.export_running)

                    fake._events.clear()
                    Version2Application._file_event(
                        fake,
                        LibraryExportHostEvent(
                            LibraryExportHostEventKind.FAILED,
                            focus_target="library-export-filtered",
                            error_code=error_code,
                        ),
                    )

                    self.assertFalse(bridge.projection.export_running)
                    self.assertEqual(fake._events[0]["kind"], "render-import")
                    self.assertFalse(
                        fake._events[0]["payload"]["import"]["actions"][1]["enabled"]
                    )
                    self.assertEqual(fake._events[1]["kind"], "error")
                    self.assertEqual(
                        fake._events[1]["payload"]["focus_target"],
                        "library-export-filtered",
                    )
        finally:
            database.close()

    def test_application_projects_worker_lifecycle_and_terminal_focus(self) -> None:
        fake = SimpleNamespace(
            _events=[],
            shell=SimpleNamespace(language=UILanguage.EN),
        )

        started = LibraryExportHostEvent(
            LibraryExportHostEventKind.STARTED,
            focus_target="library-export-selected",
        )
        Version2Application._file_event(fake, started)
        self.assertEqual(
            fake._events,
            [
                {
                    "kind": "status",
                    "payload": {
                        "announcement": "Export started. You can cancel the operation.",
                    },
                }
            ],
        )

        fake._events.clear()
        cancelling = LibraryExportHostEvent(
            LibraryExportHostEventKind.CANCELLING,
            focus_target="library-export-selected",
        )
        Version2Application._file_event(fake, cancelling)
        self.assertEqual(
            fake._events,
            [
                {
                    "kind": "status",
                    "payload": {"announcement": "Cancelling export."},
                }
            ],
        )

        fake._events.clear()
        exported = LibraryExportHostEvent(
            LibraryExportHostEventKind.EXPORTED,
            focus_target="library-export-selected",
            game_count=1,
        )
        Version2Application._file_event(fake, exported)
        self.assertEqual(
            fake._events,
            [
                {
                    "kind": "status",
                    "payload": {
                        "announcement": "Export completed.",
                        "focus_target": "library-export-selected",
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
        unicode_focus = LibraryExportHostEvent(
            LibraryExportHostEventKind.DIALOG_CANCELLED,
            focus_target="library-export-Олексій",
        )
        Version2Application._file_event(fake, unicode_focus)
        self.assertEqual(
            fake._events,
            [{"kind": "status", "payload": {"announcement": "Cancelled."}}],
        )

    def test_release_bootstrap_serializes_terminal_export_focus_without_repaint(self) -> None:
        source = (
            Path(__file__).parents[1] / "web" / "version2_release_bootstrap.js"
        ).read_text(encoding="utf-8")

        self.assertIn('actionId === "library.export";', source)
        self.assertIn("function restoreQueuedNativeFocus(id)", source)
        self.assertIn("workspace.contains(active)", source)
        self.assertIn('event.kind === "status" || event.kind === "error"', source)
        self.assertIn(
            "if (queuedTerminalFocus) restoreQueuedNativeFocus(queuedTerminalFocus);",
            source,
        )
        self.assertIn(
            "Raw terminal focus is used",
            source,
        )

    def test_shutdown_is_retryable_and_stale_queued_terminal_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "shutdown.pgn"
            hashing_started = threading.Event()
            release_hash = threading.Event()
            events: list = []
            posted: list = []

            def worker_factory() -> LibraryExportWorkerServices:
                database = AcsDatabase(database_path)
                return LibraryExportWorkerServices(
                    _BlockingLibraryExportService(
                        database,
                        hashing_started=hashing_started,
                        release_hash=release_hash,
                    ),
                    database.close,
                )

            delegate, _ = self._delegate(destination, worker_factory, events, posted)
            delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertTrue(hashing_started.wait(timeout=2.0))
            self.assertFalse(delegate.shutdown(timeout=0))
            release_hash.set()
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertEqual(len(posted), 1)
            event_count = len(events)

            self.assertTrue(delegate.shutdown(timeout=0))
            posted.pop()()
            self.assertEqual(len(events), event_count)
            self.assertFalse(delegate.export_running)
            self.assertFalse(destination.exists())


    def test_refused_shutdown_resume_republishes_cancelled_terminal_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path, game_id = self._create_library(directory)
            destination = Path(directory) / "cancelled-by-refused-close.pgn"
            hashing_started = threading.Event()
            release_hash = threading.Event()
            events: list[LibraryExportHostEvent] = []
            posted: list[object] = []

            def worker_factory() -> LibraryExportWorkerServices:
                database = AcsDatabase(database_path)
                return LibraryExportWorkerServices(
                    _BlockingLibraryExportService(
                        database,
                        hashing_started=hashing_started,
                        release_hash=release_hash,
                    ),
                    database.close,
                )

            delegate, _ = self._delegate(
                destination,
                worker_factory,
                events,
                posted,
            )
            delegate(
                "library.export",
                LibraryExportRequest.selected([game_id]).browser_payload(),
            )
            self.assertTrue(hashing_started.wait(timeout=2.0))
            self.assertFalse(delegate.shutdown(timeout=0.0))
            release_hash.set()
            self.assertTrue(delegate.wait_for_export(timeout=2.0))
            self.assertEqual(len(posted), 1)
            stale_finish = posted.pop()

            self.assertTrue(delegate.shutdown(timeout=0.0))
            self.assertEqual(
                [event.kind for event in events],
                [LibraryExportHostEventKind.STARTED],
            )
            self.assertTrue(delegate.resume_after_refused_shutdown())
            self.assertEqual(events[-1].kind, LibraryExportHostEventKind.DIALOG_CANCELLED)
            delivered = len(events)
            stale_finish()
            self.assertEqual(len(events), delivered)
            self.assertFalse(destination.exists())
            self.assertTrue(delegate.shutdown())

if __name__ == "__main__":
    unittest.main()
