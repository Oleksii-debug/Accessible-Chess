from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest

from acs.acsdb import AcsDatabase
from acs.full_product_ui_shell import UILanguage
from acs.library_export_service import (
    LibraryExportCancelledError,
    LibraryExportRequest,
    LibraryExportService,
)
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery
from acs.version2_application import Version2Application
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

            terminal = delegate.cancel_export()
            self.assertEqual(terminal.kind, LibraryExportHostEventKind.EXPORTED)
            self.assertEqual(events[-1], terminal)
            self.assertFalse(delegate.export_running)
            self.assertEqual(post_attempts, 2)
            self.assertEqual(len(open_pgn(destination).games), 1)

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


if __name__ == "__main__":
    unittest.main()
