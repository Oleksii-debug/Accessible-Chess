from __future__ import annotations

import tempfile
import threading
from pathlib import Path
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_library_import import (
    ChessBaseLibraryImportReport,
    ChessBaseLibraryImportStatus,
)
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

    def test_chessbase_port_observes_detached_result_without_redecoding(self) -> None:
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
                    return ChessBaseLibraryImportReport(
                        status=ChessBaseLibraryImportStatus.IMPORTED_WITH_WARNINGS,
                        source_name="database.cbh",
                        source_sha256="a" * 64,
                        backend_name="test-backend",
                        backend_commit="b" * 40,
                        decoded_game_count=2,
                        warnings=(),
                        library_result=canonical_result,
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
            self.assertIsNot(results[0], canonical_result)
            self.assertEqual(results[0], canonical_result)
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
            canonical_result_seen = threading.Event()

            def base_factory():
                database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(
                    LibraryImportService(database),
                    None,
                    database.close,
                )

            class ObserverAbort(BaseException):
                pass

            def fail_observer(value):
                if type(value) is LibraryImportResult:
                    canonical_result_seen.set()
                raise ObserverAbort("UI observer deliberately aborted")

            factory = Version2ObservedImportServicesFactory(
                base_factory,
                progress_sink=fail_observer,
                result_sink=fail_observer,
            )
            controller = self._controller(source, factory, events)
            controller("library.import", {})
            # The import itself is not a timing contract. Synchronize on the
            # canonical result boundary, then bound only the worker cleanup that
            # follows observer failure. This keeps Windows CI load from turning a
            # slow but valid import into a false lifecycle failure.
            self.assertTrue(
                canonical_result_seen.wait(30.0),
                "canonical Library import did not reach result publication",
            )
            self.assertTrue(
                controller.wait_for_import(5.0),
                "import worker did not close promptly after canonical result publication",
            )
            self.assertFalse(controller.import_running)

            with AcsDatabase(database_path) as database:
                game_count = database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
                attempt = database.conn.execute(
                    "SELECT status, game_count FROM import_attempts ORDER BY id"
                ).fetchone()
            self.assertEqual(game_count, 2)
            self.assertEqual(tuple(attempt), ("full", 2))
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertNotEqual(events[-1].kind, FileWorkflowEventKind.FAILED)

    def test_observer_mutation_cannot_change_worker_progress_or_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "observer-mutation.pgn"
            source.write_text(PGN_TWO, encoding="utf-8")
            events = []
            canonical_progress = LibraryImportProgress(41, 2, 2)
            canonical_result = LibraryImportResult(41, 7, 2, 0, 101, 102)
            observed_progress = []
            observed_results = []

            class SnapshotLibrary:
                def import_games(self, *_args, **kwargs):
                    callback = kwargs["progress_callback"]
                    callback(canonical_progress)
                    self_progress_after_callback = (
                        canonical_progress.attempt_id,
                        canonical_progress.processed_games,
                        canonical_progress.total_games,
                    )
                    self.assertEqual(self_progress_after_callback, (41, 2, 2))
                    return canonical_result

            # Bind the test case explicitly so the synthetic service can assert
            # that observer mutation never reaches the canonical DTO.
            test_case = self

            class SnapshotLibrary:
                def import_games(self, *_args, **kwargs):
                    callback = kwargs["progress_callback"]
                    callback(canonical_progress)
                    test_case.assertEqual(
                        (
                            canonical_progress.attempt_id,
                            canonical_progress.processed_games,
                            canonical_progress.total_games,
                        ),
                        (41, 2, 2),
                    )
                    return canonical_result

            def mutate_progress(value):
                observed_progress.append(value)
                object.__setattr__(value, "processed_games", 0)
                object.__setattr__(value, "total_games", 999)

            def mutate_result(value):
                observed_results.append(value)
                object.__setattr__(value, "game_count", 999)
                object.__setattr__(value, "warning_count", 999)

            bundle = Version2ImportWorkerServices(
                SnapshotLibrary(),
                None,
                lambda: None,
            )
            factory = Version2ObservedImportServicesFactory(
                lambda: bundle,
                progress_sink=mutate_progress,
                result_sink=mutate_result,
            )
            controller = self._controller(source, factory, events)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(len(observed_progress), 1)
            self.assertEqual(len(observed_results), 1)
            self.assertIsNot(observed_progress[0], canonical_progress)
            self.assertIsNot(observed_results[0], canonical_result)
            self.assertEqual(
                (
                    canonical_progress.attempt_id,
                    canonical_progress.processed_games,
                    canonical_progress.total_games,
                ),
                (41, 2, 2),
            )
            self.assertEqual(
                (
                    canonical_result.game_count,
                    canonical_result.warning_count,
                ),
                (2, 0),
            )
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(events[-1].game_count, 2)
            self.assertEqual(events[-1].warning_count, 0)

    def test_observer_exception_string_hook_is_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "observer-error-string.pgn"
            source.write_text(PGN_TWO, encoding="utf-8")
            events = []
            touched = []

            class ActiveObserverError(BaseException):
                def __str__(self):
                    touched.append("str")
                    raise AssertionError("observer exception string hook executed")

            class SnapshotLibrary:
                def import_games(self, *_args, **kwargs):
                    kwargs["progress_callback"](LibraryImportProgress(51, 2, 2))
                    return LibraryImportResult(51, 8, 2, 0, 201, 202)

            def abort_observer(_value):
                raise ActiveObserverError()

            bundle = Version2ImportWorkerServices(
                SnapshotLibrary(),
                None,
                lambda: None,
            )
            factory = Version2ObservedImportServicesFactory(
                lambda: bundle,
                progress_sink=abort_observer,
                result_sink=abort_observer,
            )
            controller = self._controller(source, factory, events)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(touched, [])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(events[-1].game_count, 2)

    def test_exact_progress_with_active_scalar_is_rejected_before_observer(self) -> None:
        touched = []
        observed = []

        class ActiveInt(int):
            def __lt__(self, other):
                touched.append("lt")
                raise AssertionError("active integer ordering hook executed")

            def __gt__(self, other):
                touched.append("gt")
                raise AssertionError("active integer ordering hook executed")

        hostile = LibraryImportProgress(61, 0, 2)
        object.__setattr__(hostile, "processed_games", ActiveInt(0))

        class ActiveScalarLibrary:
            def import_games(self, *_args, **kwargs):
                kwargs["progress_callback"](hostile)
                return LibraryImportResult(61, 9, 2, 0, 301, 302)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "active-progress-scalar.pgn"
            source.write_text(PGN_TWO, encoding="utf-8")
            events = []
            bundle = Version2ImportWorkerServices(
                ActiveScalarLibrary(),
                None,
                lambda: None,
            )
            factory = Version2ObservedImportServicesFactory(
                lambda: bundle,
                progress_sink=observed.append,
                result_sink=observed.append,
            )
            controller = self._controller(source, factory, events)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(touched, [])
            self.assertEqual(observed, [])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_exact_result_with_active_scalar_is_rejected_before_observer(self) -> None:
        touched = []
        observed = []

        class ActiveInt(int):
            def __lt__(self, other):
                touched.append("lt")
                raise AssertionError("active integer ordering hook executed")

            def __gt__(self, other):
                touched.append("gt")
                raise AssertionError("active integer ordering hook executed")

        hostile = LibraryImportResult(71, 10, 2, 0, 401, 402)
        object.__setattr__(hostile, "game_count", ActiveInt(2))

        class ActiveScalarLibrary:
            def import_games(self, *_args, **_kwargs):
                return hostile

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "active-result-scalar.pgn"
            source.write_text(PGN_TWO, encoding="utf-8")
            events = []
            bundle = Version2ImportWorkerServices(
                ActiveScalarLibrary(),
                None,
                lambda: None,
            )
            factory = Version2ObservedImportServicesFactory(
                lambda: bundle,
                progress_sink=observed.append,
                result_sink=observed.append,
            )
            controller = self._controller(source, factory, events)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(touched, [])
            self.assertEqual(observed, [])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_derived_progress_is_rejected_before_observer_field_hooks(self) -> None:
        touched: list[str] = []
        observed: list[object] = []

        class ActiveProgress(LibraryImportProgress):
            def __getattribute__(self, name: str):
                if name in {"attempt_id", "processed_games", "total_games"}:
                    touched.append(name)
                    raise AssertionError("derived progress field hook executed")
                return super().__getattribute__(name)

        hostile = ActiveProgress.__new__(ActiveProgress)
        object.__setattr__(hostile, "attempt_id", 1)
        object.__setattr__(hostile, "processed_games", 0)
        object.__setattr__(hostile, "total_games", 2)

        class ActiveProgressLibrary:
            def import_games(self, *_args, **kwargs):
                kwargs["progress_callback"](hostile)
                return LibraryImportResult(1, 1, 2, 0, 1, 2)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "active-progress.pgn"
            source.write_text(PGN_TWO, encoding="utf-8")
            events = []
            bundle = Version2ImportWorkerServices(
                ActiveProgressLibrary(),
                None,
                lambda: None,
            )
            factory = Version2ObservedImportServicesFactory(
                lambda: bundle,
                progress_sink=observed.append,
                result_sink=observed.append,
            )
            controller = self._controller(source, factory, events)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(touched, [])
            self.assertEqual(observed, [])
            self.assertFalse(controller.import_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_derived_result_is_rejected_before_observer_field_hooks(self) -> None:
        touched: list[str] = []
        observed: list[object] = []

        class ActiveResult(LibraryImportResult):
            def __getattribute__(self, name: str):
                if name in {"attempt_id", "source_id", "game_count", "warning_count"}:
                    touched.append(name)
                    raise AssertionError("derived result field hook executed")
                return super().__getattribute__(name)

        hostile = ActiveResult.__new__(ActiveResult)
        for name, value in (
            ("attempt_id", 1),
            ("source_id", 1),
            ("game_count", 2),
            ("warning_count", 0),
            ("first_game_id", 1),
            ("last_game_id", 2),
            ("reused", False),
        ):
            object.__setattr__(hostile, name, value)

        class ActiveResultLibrary:
            def import_games(self, *_args, **_kwargs):
                return hostile

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "active-result.pgn"
            source.write_text(PGN_TWO, encoding="utf-8")
            events = []
            bundle = Version2ImportWorkerServices(
                ActiveResultLibrary(),
                None,
                lambda: None,
            )
            factory = Version2ObservedImportServicesFactory(
                lambda: bundle,
                progress_sink=observed.append,
                result_sink=observed.append,
            )
            controller = self._controller(source, factory, events)

            controller("library.import", {})
            self.assertTrue(controller.wait_for_import(5.0))

            self.assertEqual(touched, [])
            self.assertEqual(observed, [])
            self.assertFalse(controller.import_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_factory_rejects_derived_bundle_before_service_field_hooks(self) -> None:
        touched: list[str] = []

        class ActiveBundle(Version2ImportWorkerServices):
            def __getattribute__(self, name: str):
                if name in {"library", "chessbase", "close"}:
                    touched.append(name)
                    raise AssertionError("derived bundle field hook executed")
                return super().__getattribute__(name)

        hostile = ActiveBundle.__new__(ActiveBundle)
        object.__setattr__(hostile, "library", _UnusedLibrary())
        object.__setattr__(hostile, "chessbase", None)
        object.__setattr__(hostile, "close", lambda: None)
        factory = Version2ObservedImportServicesFactory(
            lambda: hostile,
            progress_sink=lambda value: None,
            result_sink=lambda value: None,
        )

        with self.assertRaisesRegex(TypeError, "invalid bundle"):
            factory()

        self.assertEqual(touched, [])

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
