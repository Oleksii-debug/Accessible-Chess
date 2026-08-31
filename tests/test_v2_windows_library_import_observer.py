from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import (
    LibraryImportProgress,
    LibraryImportResult,
    LibraryImportService,
)
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)
from acs.version2_windows_library_import_observer import (
    Version2ObservedImportServicesFactory,
)


PGN_TWO = """[Event \"Observed 1\"]
[Site \"?\"]
[Date \"2026.08.31\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 *

[Event \"Observed 2\"]
[Site \"?\"]
[Date \"2026.08.31\"]
[Round \"2\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. d4 d5 *
"""


class _Dialogs:
    def __init__(self, import_path: Path) -> None:
        self.import_path = import_path

    def open_pgn(self):
        return None

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        return None

    def select_library_import(self):
        return self.import_path


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected PGN Library import")


class Version2WindowsLibraryImportObserverTests(unittest.TestCase):
    def _controller(self, path: Path, factory, events):
        return Version2WindowsFileActionDelegate(
            dialogs=_Dialogs(path),
            get_pgn_session=lambda: None,
            set_pgn_session=lambda value: None,
            import_services_factory=factory,
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
        )

    def test_real_pgn_import_preserves_exact_canonical_progress_and_result_off_browser_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "private-observer-source.pgn"
            database_path = root / "private-observer-library.acsdb"
            source.write_text(PGN_TWO, encoding="utf-8")
            progress_values = []
            results = []
            events = []

            def base_factory():
                database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(
                    LibraryImportService(database),
                    None,
                    database.close,
                )

            factory = Version2ObservedImportServicesFactory(
                base_factory,
                progress_sink=progress_values.append,
                result_sink=results.append,
            )
            controller = self._controller(source, factory, events)
            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(10.0))

            self.assertTrue(progress_values)
            self.assertEqual(len(results), 1)
            self.assertTrue(all(isinstance(value, LibraryImportProgress) for value in progress_values))
            result = results[0]
            self.assertIsInstance(result, LibraryImportResult)
            self.assertEqual(result.game_count, 2)
            self.assertEqual(progress_values[-1].attempt_id, result.attempt_id)
            self.assertEqual(progress_values[-1].processed_games, 2)
            self.assertEqual(progress_values[-1].total_games, 2)

            with AcsDatabase(database_path) as database:
                row = database.conn.execute(
                    "SELECT id, source_id, status, game_count FROM import_attempts ORDER BY id"
                ).fetchone()
            self.assertEqual(row[0], result.attempt_id)
            self.assertEqual(row[1], result.source_id)
            self.assertEqual(row[2], "full")
            self.assertEqual(row[3], result.game_count)

            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            for event in events:
                rendered = repr(event)
                self.assertNotIn(str(source), rendered)
                self.assertNotIn(str(database_path), rendered)
                self.assertNotIn("private-observer", rendered)
                # Canonical database identities remain on the internal observer
                # port; the bounded browser/native event contract is unchanged.
                self.assertNotIn("source_id", rendered)
                self.assertNotIn("attempt_id", rendered)

    def test_chessbase_port_observes_same_result_object_without_redecoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "database.cbh"
            source.write_bytes(b"host-port-fixture")
            progress_values = []
            results = []
            events = []
            canonical_result = LibraryImportResult(17, 23, 2, 1, 101, 102)

            class ChessBaseService:
                def import_database(self, path, **kwargs):
                    callback = kwargs["progress_callback"]
                    callback(LibraryImportProgress(17, 0, 2))
                    callback(LibraryImportProgress(17, 2, 2))
                    return SimpleNamespace(
                        library_result=canonical_result,
                        warning_count=1,
                    )

            base_bundle = Version2ImportWorkerServices(
                _UnusedLibrary(),
                ChessBaseService(),
                lambda: None,
            )
            factory = Version2ObservedImportServicesFactory(
                lambda: base_bundle,
                progress_sink=progress_values.append,
                result_sink=results.append,
            )
            controller = self._controller(source, factory, events)
            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual([value.attempt_id for value in progress_values], [17, 17])
            self.assertEqual(len(results), 1)
            self.assertIs(results[0], canonical_result)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(events[-1].game_count, 2)
            self.assertNotIn("attempt_id", repr(events[-1]))
            self.assertNotIn("source_id", repr(events[-1]))

    def test_observer_failure_does_not_rollback_canonical_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "observer-failure.pgn"
            database_path = root / "library.acsdb"
            source.write_text(PGN_TWO, encoding="utf-8")
            events = []

            def base_factory():
                database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(
                    LibraryImportService(database),
                    None,
                    database.close,
                )

            def fail_observer(value):
                raise RuntimeError("UI observer deliberately unavailable")

            factory = Version2ObservedImportServicesFactory(
                base_factory,
                progress_sink=fail_observer,
                result_sink=fail_observer,
            )
            controller = self._controller(source, factory, events)
            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(10.0))

            with AcsDatabase(database_path) as database:
                game_count = database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
                attempt = database.conn.execute(
                    "SELECT status, game_count FROM import_attempts ORDER BY id"
                ).fetchone()
            self.assertEqual(game_count, 2)
            self.assertEqual(tuple(attempt), ("full", 2))
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertNotEqual(events[-1].kind, FileWorkflowEventKind.FAILED)

    def test_factory_preserves_exact_cleanup_callback(self) -> None:
        closed = []
        bundle = Version2ImportWorkerServices(
            _UnusedLibrary(),
            None,
            lambda: closed.append(True),
        )
        factory = Version2ObservedImportServicesFactory(
            lambda: bundle,
            progress_sink=lambda value: None,
            result_sink=lambda value: None,
        )
        observed = factory()
        observed.close()
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
