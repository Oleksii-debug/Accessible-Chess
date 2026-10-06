from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application
from acs.version2_windows_book_open_worker import Version2BookOpenWorker


class _FailingProgressStore:
    def __init__(self, path: Path, error: BaseException | None = None) -> None:
        self.path = path
        self.error = error or OSError("synthetic progress publication failure")

    def save(self, _book_key, _reader) -> None:
        raise self.error


class Version2ShutdownProgressFailureCleanupEvidenceTests(unittest.TestCase):
    def _application(self, database: AcsDatabase, analysis: AnalysisService, store) -> Version2Application:
        application = Version2Application(
            database,
            progress_store=store,
            engine_assistance=EngineAssistedWorkflowService(analysis),
            board_dispatch=lambda *_args: None,
        )
        # Keep these oracles independent of Book parsing/format ownership.
        # save_book_progress() only requires that a current reader exists.
        application.reader = object()
        application.book_key = "shutdown-evidence-book"
        return application

    def test_book_worker_refusal_still_retires_file_worker_and_keeps_shared_state_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                book_worker = mock.Mock()
                book_worker.shutdown.return_value = False
                file_worker = mock.Mock()
                file_worker.shutdown.return_value = True
                application._book_open_worker = book_worker
                application._files = file_worker

                with mock.patch.object(application, "save_training_progress") as training, \
                     mock.patch.object(application, "save_book_progress") as book, \
                     mock.patch.object(database, "close", wraps=database.close) as close:
                    self.assertFalse(application.shutdown(timeout=0.25))

                book_worker.shutdown.assert_called_once_with(timeout=0.25)
                file_worker.shutdown.assert_called_once_with(timeout=0.25)
                training.assert_not_called()
                book.assert_not_called()
                close.assert_not_called()
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_real_draining_book_refusal_restores_other_native_owner(self) -> None:
        class RecoverableFiles:
            def __init__(self) -> None:
                self.shutdown_calls = []
                self.resume_calls = 0
                self.closed = False

            def shutdown(self, timeout=None):
                self.shutdown_calls.append(timeout)
                self.closed = True
                return True

            def resume_after_refused_shutdown(self):
                self.resume_calls += 1
                if not self.closed:
                    return False
                self.closed = False
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            callbacks = []
            entered = threading.Event()
            release = threading.Event()
            book_worker = None

            def prepare(_source, *, cancel_check):
                entered.set()
                release.wait(2)
                return object()

            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                book_worker = Version2BookOpenWorker(
                    prepare=prepare,
                    commit=lambda _prepared: None,
                    post_to_ui=callbacks.append,
                    event_sink=lambda _event: None,
                )
                files = RecoverableFiles()
                application._book_open_worker = book_worker
                application._files = files

                self.assertTrue(book_worker.start(root / "book.md"))
                self.assertTrue(entered.wait(2))
                self.assertFalse(application.shutdown(timeout=0))

                self.assertFalse(book_worker.closed)
                self.assertTrue(book_worker.active)
                self.assertFalse(files.closed)
                self.assertEqual(files.shutdown_calls, [0])
                self.assertEqual(files.resume_calls, 1)
                self.assertIsNone(
                    getattr(application, "_native_shutdown_recovery_error", None)
                )
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))

                release.set()
                # The worker posts exactly one stale terminal back to this UI
                # owner. Wait without consuming it from the worker thread.
                for _ in range(400):
                    if callbacks:
                        break
                    threading.Event().wait(0.005)
                self.assertTrue(callbacks)
                callbacks.pop(0)()
                self.assertFalse(book_worker.active)
            finally:
                release.set()
                if book_worker is not None:
                    book_worker.shutdown(timeout=2)
                database.close()
                analysis.close()
    def test_progress_failure_reconciles_retired_book_busy_status_without_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            callbacks = []
            commits = []
            prepared = threading.Event()
            book_worker = None

            def prepare(_source, *, cancel_check):
                prepared.set()
                return object()

            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                book_worker = Version2BookOpenWorker(
                    prepare=prepare,
                    commit=commits.append,
                    post_to_ui=callbacks.append,
                    event_sink=application._book_open_event,
                )
                application._book_open_worker = book_worker

                self.assertTrue(
                    book_worker.start(root / "book.md", focus_target="book-open")
                )
                self.assertTrue(prepared.wait(2.0))
                for _ in range(400):
                    if callbacks:
                        break
                    threading.Event().wait(0.005)
                self.assertTrue(callbacks)
                self.assertTrue(application._events[-1]["payload"]["book_open_busy"])

                with self.assertRaises(OSError):
                    application.shutdown()

                self.assertFalse(book_worker.closed)
                self.assertFalse(book_worker.active)
                self.assertEqual(commits, [])
                recovered = application._events[-1]
                self.assertEqual(recovered["kind"], "status")
                self.assertEqual(recovered["payload"]["focus_target"], "book-open")
                self.assertFalse(recovered["payload"]["book_open_busy"])

                event_count = len(application._events)
                callbacks.pop(0)()
                self.assertEqual(commits, [])
                self.assertEqual(len(application._events), event_count)
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                if book_worker is not None:
                    book_worker.shutdown(timeout=2)
                database.close()
                analysis.close()
    def test_partial_worker_retirement_refusal_reopens_each_recoverable_owner(self) -> None:
        class Worker:
            def __init__(self, shutdown_result, resume_result) -> None:
                self.shutdown_result = shutdown_result
                self.resume_result = resume_result
                self.shutdown_calls = 0
                self.resume_calls = 0

            def shutdown(self, timeout=None):
                self.shutdown_calls += 1
                return self.shutdown_result

            def resume_after_refused_shutdown(self):
                self.resume_calls += 1
                return self.resume_result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                still_busy = Worker(False, False)
                already_retired = Worker(True, True)
                application._book_open_worker = still_busy
                application._files = already_retired

                self.assertFalse(application.shutdown(timeout=0.1))

                self.assertEqual(still_busy.shutdown_calls, 1)
                self.assertEqual(already_retired.shutdown_calls, 1)
                self.assertEqual(still_busy.resume_calls, 1)
                self.assertEqual(already_retired.resume_calls, 1)
                self.assertIsInstance(
                    application._native_shutdown_recovery_error,
                    RuntimeError,
                )
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_worker_retirement_abort_reopens_other_owner_without_replacing_primary(self) -> None:
        class RetirementAbort(BaseException):
            pass

        class Worker:
            def __init__(self, *, error=None) -> None:
                self.error = error
                self.resume_calls = 0

            def shutdown(self, timeout=None):
                if self.error is not None:
                    raise self.error
                return True

            def resume_after_refused_shutdown(self):
                self.resume_calls += 1
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = RetirementAbort("PRIMARY_RETIREMENT_ABORT")
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                failed = Worker(error=primary)
                retired = Worker()
                application._book_open_worker = failed
                application._files = retired

                with self.assertRaises(RetirementAbort) as caught:
                    application.shutdown()

                self.assertIs(caught.exception, primary)
                self.assertEqual(failed.resume_calls, 1)
                self.assertEqual(retired.resume_calls, 1)
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_bounded_shutdown_retry_finishes_after_prior_worker_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            store = mock.Mock()
            store.path = root / "book-progress.json"
            try:
                application = self._application(database, analysis, store)
                book_worker = mock.Mock()
                book_worker.shutdown.side_effect = [False, True]
                file_worker = mock.Mock()
                file_worker.shutdown.return_value = True
                application._book_open_worker = book_worker
                application._files = file_worker

                self.assertFalse(application.shutdown(timeout=0.01))
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))

                self.assertTrue(application.shutdown(timeout=0.5))
                with self.assertRaises(sqlite3.ProgrammingError):
                    database.conn.execute("SELECT 1")

                self.assertEqual(
                    book_worker.shutdown.call_args_list,
                    [mock.call(timeout=0.01), mock.call(timeout=0.5)],
                )
                self.assertEqual(
                    file_worker.shutdown.call_args_list,
                    [mock.call(timeout=0.01), mock.call(timeout=0.5)],
                )
                store.save.assert_called_once_with(
                    application.book_key,
                    application.reader,
                )
            finally:
                database.close()
                analysis.close()

    def test_worker_abort_still_retires_other_worker_and_preserves_first_abort(self) -> None:
        class BookAbort(BaseException):
            pass

        class FileAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = BookAbort("PRIMARY_BOOK_WORKER")
            secondary = FileAbort("SECONDARY_FILE_WORKER")
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                book_worker = mock.Mock()
                book_worker.shutdown.side_effect = primary
                file_worker = mock.Mock()
                file_worker.shutdown.side_effect = secondary
                application._book_open_worker = book_worker
                application._files = file_worker

                with mock.patch.object(application, "save_training_progress") as training, \
                     mock.patch.object(application, "save_book_progress") as book, \
                     mock.patch.object(database, "close", wraps=database.close) as close:
                    with self.assertRaises(BookAbort) as caught:
                        application.shutdown(timeout=0.5)

                self.assertIs(caught.exception, primary)
                book_worker.shutdown.assert_called_once_with(timeout=0.5)
                file_worker.shutdown.assert_called_once_with(timeout=0.5)
                training.assert_not_called()
                book.assert_not_called()
                close.assert_not_called()
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_non_boolean_worker_success_fails_closed_before_shared_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                book_worker = mock.Mock()
                book_worker.shutdown.return_value = 1
                file_worker = mock.Mock()
                file_worker.shutdown.return_value = True
                application._book_open_worker = book_worker
                application._files = file_worker

                with mock.patch.object(application, "save_training_progress") as training, \
                     mock.patch.object(application, "save_book_progress") as book, \
                     mock.patch.object(database, "close", wraps=database.close) as close:
                    self.assertFalse(application.shutdown())

                book_worker.shutdown.assert_called_once_with(timeout=None)
                file_worker.shutdown.assert_called_once_with(timeout=None)
                training.assert_not_called()
                book.assert_not_called()
                close.assert_not_called()
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_shell_publication_rollback_abort_keeps_shared_state_retryable(self) -> None:
        class RollbackAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = RollbackAbort("PRIMARY_SHELL_ROLLBACK")
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                application._pending_shell_publication = (17,)

                with mock.patch.object(
                    application,
                    "_finish_shell_publication",
                    side_effect=primary,
                ) as rollback, mock.patch.object(
                    application,
                    "save_training_progress",
                ) as training, mock.patch.object(
                    application,
                    "save_book_progress",
                ) as book, mock.patch.object(
                    database,
                    "close",
                    wraps=database.close,
                ) as close:
                    with self.assertRaises(RollbackAbort) as caught:
                        application.shutdown()

                self.assertIs(caught.exception, primary)
                rollback.assert_called_once_with(17, commit=False)
                training.assert_not_called()
                book.assert_not_called()
                close.assert_not_called()
                self.assertEqual(application._pending_shell_publication, (17,))
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_shell_rollback_abort_reopens_retired_workers_and_preserves_primary(self) -> None:
        class RollbackAbort(BaseException):
            pass

        class Worker:
            def __init__(self) -> None:
                self.resume_calls = 0

            def shutdown(self, timeout=None):
                return True

            def resume_after_refused_shutdown(self):
                self.resume_calls += 1
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = RollbackAbort("PRIMARY_SHELL_ROLLBACK")
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                book_worker = Worker()
                file_worker = Worker()
                application._book_open_worker = book_worker
                application._files = file_worker
                application._pending_shell_publication = (29,)

                with mock.patch.object(
                    application,
                    "_finish_shell_publication",
                    side_effect=primary,
                ):
                    with self.assertRaises(RollbackAbort) as caught:
                        application.shutdown()

                self.assertIs(caught.exception, primary)
                self.assertEqual(book_worker.resume_calls, 1)
                self.assertEqual(file_worker.resume_calls, 1)
                self.assertEqual(application._pending_shell_publication, (29,))
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_progress_save_failure_keeps_database_open_for_close_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )

                with self.assertRaisesRegex(OSError, "synthetic progress publication failure"):
                    application.shutdown()

                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_progress_save_failure_can_retry_and_then_close_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            progress_failure = OSError("FIRST_PROGRESS_FAILURE")
            store = mock.Mock()
            store.path = root / "book-progress.json"
            store.save.side_effect = [progress_failure, None]
            try:
                application = self._application(database, analysis, store)

                with self.assertRaises(OSError) as caught:
                    application.shutdown()

                self.assertIs(caught.exception, progress_failure)
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))

                self.assertTrue(application.shutdown())
                with self.assertRaises(sqlite3.ProgrammingError):
                    database.conn.execute("SELECT 1")
                self.assertEqual(store.save.call_count, 2)
            finally:
                database.close()
                analysis.close()

    def test_training_progress_failure_still_attempts_book_progress_and_keeps_database_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = OSError("PRIMARY_TRAINING_PROGRESS")
            calls: list[str] = []
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )

                def fail_training() -> None:
                    calls.append("training")
                    raise primary

                def fail_book() -> None:
                    calls.append("book")
                    raise RuntimeError("SECONDARY_BOOK_PROGRESS")

                with mock.patch.object(
                    application,
                    "save_training_progress",
                    side_effect=fail_training,
                ), mock.patch.object(
                    application,
                    "save_book_progress",
                    side_effect=fail_book,
                ):
                    with self.assertRaises(OSError) as caught:
                        application.shutdown()

                self.assertIs(caught.exception, primary)
                self.assertEqual(calls, ["training", "book"])
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_progress_failure_skips_database_close_even_if_close_would_abort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = OSError("PRIMARY_TRAINING_PROGRESS")
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                with mock.patch.object(
                    application,
                    "save_training_progress",
                    side_effect=primary,
                ), mock.patch.object(
                    application,
                    "save_book_progress",
                    return_value=None,
                ), mock.patch.object(
                    database,
                    "close",
                    side_effect=RuntimeError("SHOULD_NOT_CLOSE"),
                ) as close:
                    with self.assertRaises(OSError) as caught:
                        application.shutdown()

                self.assertIs(caught.exception, primary)
                close.assert_not_called()
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_database_close_failure_recovers_workers_and_retry_can_finish(self) -> None:
        class RecoverableWorker:
            def __init__(self) -> None:
                self.shutdown_calls = []
                self.resume_calls = 0

            def shutdown(self, timeout=None):
                self.shutdown_calls.append(timeout)
                return True

            def resume_after_refused_shutdown(self):
                self.resume_calls += 1
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            database_failure = RuntimeError("DATABASE_CLOSE_FAILED")
            store = mock.Mock()
            store.path = root / "book-progress.json"
            close_calls = 0
            real_close = database.close

            def flaky_close() -> None:
                nonlocal close_calls
                close_calls += 1
                if close_calls == 1:
                    raise database_failure
                real_close()

            try:
                application = self._application(database, analysis, store)
                book_worker = RecoverableWorker()
                file_worker = RecoverableWorker()
                application._book_open_worker = book_worker
                application._files = file_worker

                with mock.patch.object(database, "close", side_effect=flaky_close):
                    with self.assertRaises(RuntimeError) as caught:
                        application.shutdown()

                    self.assertIs(caught.exception, database_failure)
                    self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
                    self.assertEqual(book_worker.resume_calls, 1)
                    self.assertEqual(file_worker.resume_calls, 1)
                    self.assertEqual(book_worker.shutdown_calls, [None])
                    self.assertEqual(file_worker.shutdown_calls, [None])

                    self.assertTrue(application.shutdown())

                with self.assertRaises(sqlite3.ProgrammingError):
                    database.conn.execute("SELECT 1")
                self.assertEqual(close_calls, 2)
                self.assertEqual(book_worker.shutdown_calls, [None, None])
                self.assertEqual(file_worker.shutdown_calls, [None, None])
                self.assertEqual(book_worker.resume_calls, 1)
                self.assertEqual(file_worker.resume_calls, 1)
                self.assertEqual(store.save.call_count, 2)
            finally:
                database.close()
                analysis.close()

    def test_progress_failure_reopens_retired_native_workers(self) -> None:
        class RecoverableWorker:
            def __init__(self) -> None:
                self.shutdown_calls = []
                self.resume_calls = 0

            def shutdown(self, timeout=None):
                self.shutdown_calls.append(timeout)
                return True

            def resume_after_refused_shutdown(self):
                self.resume_calls += 1
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = OSError("PRIMARY_PROGRESS_FAILURE")
            store = mock.Mock()
            store.path = root / "book-progress.json"
            store.save.side_effect = primary
            try:
                application = self._application(database, analysis, store)
                book_worker = RecoverableWorker()
                file_worker = RecoverableWorker()
                application._book_open_worker = book_worker
                application._files = file_worker

                with self.assertRaises(OSError) as caught:
                    application.shutdown(timeout=0.25)

                self.assertIs(caught.exception, primary)
                self.assertEqual(book_worker.shutdown_calls, [0.25])
                self.assertEqual(file_worker.shutdown_calls, [0.25])
                self.assertEqual(book_worker.resume_calls, 1)
                self.assertEqual(file_worker.resume_calls, 1)
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_worker_recovery_failure_never_replaces_progress_failure(self) -> None:
        class RecoveryAbort(BaseException):
            pass

        class RecoverableWorker:
            def __init__(self, *, fail_resume=False) -> None:
                self.fail_resume = fail_resume
                self.shutdown_calls = []
                self.resume_calls = 0

            def shutdown(self, timeout=None):
                self.shutdown_calls.append(timeout)
                return True

            def resume_after_refused_shutdown(self):
                self.resume_calls += 1
                if self.fail_resume:
                    raise RecoveryAbort("SECONDARY_RECOVERY_FAILURE")
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = OSError("PRIMARY_PROGRESS_FAILURE")
            store = mock.Mock()
            store.path = root / "book-progress.json"
            store.save.side_effect = primary
            try:
                application = self._application(database, analysis, store)
                book_worker = RecoverableWorker()
                file_worker = RecoverableWorker(fail_resume=True)
                application._book_open_worker = book_worker
                application._files = file_worker

                with self.assertRaises(OSError) as caught:
                    application.shutdown()

                self.assertIs(caught.exception, primary)
                self.assertEqual(book_worker.resume_calls, 1)
                self.assertEqual(file_worker.resume_calls, 1)
                self.assertEqual(book_worker.shutdown_calls, [None, 0.0])
                self.assertEqual(file_worker.shutdown_calls, [None, 0.0])
                self.assertIsInstance(
                    application._native_shutdown_recovery_error,
                    RecoveryAbort,
                )
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_missing_worker_recovery_contract_fails_closed_and_retires_all_owners(self) -> None:
        class NonRecoverableWorker:
            def __init__(self) -> None:
                self.shutdown_calls = []

            def shutdown(self, timeout=None):
                self.shutdown_calls.append(timeout)
                return True

        class RecoverableWorker:
            def __init__(self) -> None:
                self.shutdown_calls = []
                self.resume_calls = 0

            def shutdown(self, timeout=None):
                self.shutdown_calls.append(timeout)
                return True

            def resume_after_refused_shutdown(self):
                self.resume_calls += 1
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            primary = OSError("PRIMARY_PROGRESS_FAILURE")
            store = mock.Mock()
            store.path = root / "book-progress.json"
            store.save.side_effect = primary
            try:
                application = self._application(database, analysis, store)
                book_worker = NonRecoverableWorker()
                file_worker = RecoverableWorker()
                application._book_open_worker = book_worker
                application._files = file_worker

                with self.assertRaises(OSError) as caught:
                    application.shutdown()

                self.assertIs(caught.exception, primary)
                self.assertEqual(file_worker.resume_calls, 1)
                self.assertEqual(book_worker.shutdown_calls, [None, 0.0])
                self.assertEqual(file_worker.shutdown_calls, [None, 0.0])
                self.assertIsInstance(
                    application._native_shutdown_recovery_error,
                    RuntimeError,
                )
                self.assertIn(
                    "recovery contract",
                    str(application._native_shutdown_recovery_error),
                )
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()

    def test_successful_worker_recovery_clears_stale_recovery_diagnostic(self) -> None:
        class RecoverableWorker:
            def shutdown(self, timeout=None):
                return True

            def resume_after_refused_shutdown(self):
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            store = mock.Mock()
            store.path = root / "book-progress.json"
            store.save.side_effect = OSError("PRIMARY_PROGRESS_FAILURE")
            try:
                application = self._application(database, analysis, store)
                application._book_open_worker = RecoverableWorker()
                application._files = RecoverableWorker()
                application._native_shutdown_recovery_error = RuntimeError("STALE")

                with self.assertRaises(OSError):
                    application.shutdown()

                self.assertIsNone(application._native_shutdown_recovery_error)
                self.assertEqual(tuple(database.conn.execute("SELECT 1").fetchone()), (1,))
            finally:
                database.close()
                analysis.close()


if __name__ == "__main__":
    unittest.main()
