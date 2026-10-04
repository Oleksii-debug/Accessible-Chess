from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportCancelledError, LibraryImportService
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)
from acs.version2_windows_pgn_streaming_host import (
    Version2WindowsStreamingFileActionDelegate,
)


VALID_PGN = '''[Event "First"]
[Result "*"]

1. e4 e5 *

[Event "Second"]
[Result "*"]

1. d4 d5 *
'''

VALID_PREFIX_THEN_TRUNCATED = '''[Event "Accepted"]
[Result "*"]

1. e4 e5 *

[Event "Broken"]
[Result "*"]

1. d4 {unterminated
'''


class _Dialogs:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.select_calls = 0

    def open_pgn(self):
        raise AssertionError("ordinary PGN open is not part of Library import")

    def save_pgn_as(self, suggested_filename="game.pgn"):
        raise AssertionError("ordinary PGN save is not part of Library import")

    def select_library_import(self):
        self.select_calls += 1
        return self.source


class _ObservedLibrary:
    def __init__(self, service: LibraryImportService, calls: list[int]) -> None:
        self._service = service
        self._calls = calls

    def import_games(self, games, **kwargs):
        self._calls.append(len(games))
        return self._service.import_games(games, **kwargs)


class _BlockingCancellableLibrary:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self.saw_cancel = False

    def import_games(self, games, **kwargs):
        self.calls += 1
        cancel_check = kwargs["cancel_check"]
        self.entered.set()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if cancel_check():
                self.saw_cancel = True
                raise LibraryImportCancelledError("Library import cancelled")
            threading.Event().wait(0.002)
        raise AssertionError("streaming import did not receive cancellation")


class _NoopLibrary:
    def import_games(self, games, **kwargs):
        raise AssertionError("PGN Library service must not handle ChessBase sources")


class _ChessBase:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def import_database(self, path, **kwargs):
        self.paths.append(Path(path))
        return SimpleNamespace(library_result=None, warning_count=0)


class Version2WindowsPgnStreamingLifecycleTests(unittest.TestCase):
    def _controller(self, dialogs: _Dialogs, factory):
        events = []
        controller = Version2WindowsStreamingFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: None,
            set_pgn_session=lambda session: None,
            import_services_factory=factory,
            event_sink=events.append,
            next_delegate=lambda action, payload: None,
            current_focus_provider=lambda: "library-search-player",
        )
        return controller, events

    def _assert_path_free(self, events, *sources: Path) -> None:
        for event in events:
            rendered = repr(event)
            for source in sources:
                self.assertNotIn(str(source), rendered)
                self.assertNotIn(source.name, rendered)
            self.assertFalse(
                any("path" in name.lower() for name in event.__dataclass_fields__),
                msg=f"path-bearing public event field: {event!r}",
            )

    def test_browser_payload_cannot_supply_library_filesystem_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "private-browser-path.pgn"
            source.write_text(VALID_PGN, encoding="utf-8", newline="")
            dialogs = _Dialogs(source)
            factory_calls = []

            def factory():
                factory_calls.append(True)
                return Version2ImportWorkerServices(_NoopLibrary(), None, lambda: None)

            controller, events = self._controller(dialogs, factory)
            with self.assertRaisesRegex(ValueError, "no browser path payload"):
                controller("library.import", {"path": str(source)})

            self.assertEqual(dialogs.select_calls, 0)
            self.assertEqual(factory_calls, [])
            self.assertEqual(events, [])

    def test_cancel_action_stops_streaming_worker_without_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "private-cancel.pgn"
            source.write_text(VALID_PGN, encoding="utf-8", newline="")
            dialogs = _Dialogs(source)
            library = _BlockingCancellableLibrary()
            closed = []

            def factory():
                return Version2ImportWorkerServices(
                    library,
                    None,
                    lambda: closed.append(True),
                )

            controller, events = self._controller(dialogs, factory)
            started = controller("library.import", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(library.entered.wait(3.0))

            cancelling = controller("library.cancel_import", {})
            self.assertEqual(cancelling.kind, FileWorkflowEventKind.IMPORT_CANCELLING)
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertTrue(library.saw_cancel)
            self.assertEqual(closed, [True])
            self.assertFalse(controller.import_running)
            kinds = [event.kind for event in events]
            self.assertEqual(kinds[-1], FileWorkflowEventKind.IMPORT_CANCELLED)
            self.assertNotIn(FileWorkflowEventKind.IMPORT_COMPLETED, kinds)
            self._assert_path_free(events, source)

    def test_shutdown_cancels_and_joins_streaming_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "private-shutdown.pgn"
            source.write_text(VALID_PGN, encoding="utf-8", newline="")
            dialogs = _Dialogs(source)
            library = _BlockingCancellableLibrary()
            closed = []

            def factory():
                return Version2ImportWorkerServices(
                    library,
                    None,
                    lambda: closed.append(True),
                )

            controller, events = self._controller(dialogs, factory)
            controller("library.import", {})
            self.assertTrue(library.entered.wait(3.0))
            self.assertTrue(controller.import_running)

            self.assertTrue(controller.shutdown(5.0))
            self.assertTrue(library.saw_cancel)
            self.assertFalse(controller.import_running)
            self.assertEqual(closed, [True])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_CANCELLED)
            self.assertNotIn(
                FileWorkflowEventKind.IMPORT_COMPLETED,
                [event.kind for event in events],
            )
            self._assert_path_free(events, source)

    def test_retry_after_late_invalid_source_publishes_only_valid_retry_to_d07(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / "private-truncated.pgn"
            valid = root / "private-retry.pgn"
            database_path = root / "library.acsdb"
            broken.write_text(
                VALID_PREFIX_THEN_TRUNCATED,
                encoding="utf-8",
                newline="",
            )
            valid.write_text(VALID_PGN, encoding="utf-8", newline="")
            dialogs = _Dialogs(broken)
            publish_calls: list[int] = []
            closed = []

            def factory():
                database = AcsDatabase(database_path)
                observed = _ObservedLibrary(
                    LibraryImportService(database),
                    publish_calls,
                )

                def close() -> None:
                    database.close()
                    closed.append(True)

                return Version2ImportWorkerServices(observed, None, close)

            controller, events = self._controller(dialogs, factory)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_import_failed")
            self.assertEqual(publish_calls, [])
            with AcsDatabase(database_path) as database:
                self.assertEqual(database.search_games(limit=100), [])

            dialogs.source = valid
            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(events[-1].game_count, 2)
            self.assertEqual(publish_calls, [2])
            self.assertEqual(closed, [True, True])
            with AcsDatabase(database_path) as database:
                self.assertEqual(len(database.search_games(limit=100)), 2)

            self._assert_path_free(events, broken, valid)

    def test_cbh_and_cbv_stay_on_existing_chessbase_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix in (".cbh", ".cbv"):
                with self.subTest(suffix=suffix):
                    source = root / f"private-source{suffix}"
                    source.write_bytes(b"backend-owned fixture")
                    dialogs = _Dialogs(source)
                    chessbase = _ChessBase()
                    closed = []

                    def factory():
                        return Version2ImportWorkerServices(
                            _NoopLibrary(),
                            chessbase,
                            lambda: closed.append(True),
                        )

                    controller, events = self._controller(dialogs, factory)
                    controller("library.import", {})
                    self.assertTrue(controller.wait_for_import(5.0))

                    self.assertEqual(chessbase.paths, [source])
                    self.assertEqual(closed, [True])
                    self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_EMPTY)
                    self._assert_path_free(events, source)

    def test_normal_pgn_open_and_save_ownership_is_inherited_unchanged(self) -> None:
        self.assertIs(
            Version2WindowsStreamingFileActionDelegate._open_pgn,
            Version2WindowsFileActionDelegate._open_pgn,
        )
        self.assertIs(
            Version2WindowsStreamingFileActionDelegate._save_pgn,
            Version2WindowsFileActionDelegate._save_pgn,
        )
        self.assertIs(
            Version2WindowsStreamingFileActionDelegate._save_pgn_as,
            Version2WindowsFileActionDelegate._save_pgn_as,
        )


if __name__ == "__main__":
    unittest.main()
