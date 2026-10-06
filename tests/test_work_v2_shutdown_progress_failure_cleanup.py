from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


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
                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))
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
                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))

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
                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))
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
                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))
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
                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))
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

                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))
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
                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))
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
                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))
            finally:
                database.close()
                analysis.close()

    def test_database_close_failure_propagates_after_progress_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            database_failure = RuntimeError("DATABASE_CLOSE_FAILED")
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(root / "book-progress.json"),
                )
                with mock.patch.object(
                    application,
                    "save_training_progress",
                    return_value=None,
                ), mock.patch.object(
                    application,
                    "save_book_progress",
                    return_value=None,
                ), mock.patch.object(
                    database,
                    "close",
                    side_effect=database_failure,
                ) as close:
                    with self.assertRaises(RuntimeError) as caught:
                        application.shutdown()

                self.assertIs(caught.exception, database_failure)
                close.assert_called_once_with()
                self.assertEqual(database.conn.execute("SELECT 1").fetchone(), (1,))
            finally:
                database.close()
                analysis.close()


if __name__ == "__main__":
    unittest.main()
