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
    def __init__(self, error: BaseException | None = None) -> None:
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

    def test_progress_save_failure_does_not_skip_database_close(self) -> None:
        """Shutdown must release ACSDB even when durable Book progress fails."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                application = self._application(database, analysis, _FailingProgressStore())

                with self.assertRaisesRegex(OSError, "synthetic progress publication failure"):
                    application.shutdown()

                with self.assertRaises(sqlite3.ProgrammingError):
                    database.conn.execute("SELECT 1")
            finally:
                # Idempotent if Product already did the required cleanup; needed
                # only to keep an expected-RED baseline from leaking a test DB.
                database.close()
                analysis.close()

    def test_database_close_failure_does_not_replace_progress_failure(self) -> None:
        """The first cleanup failure remains primary while later cleanup is attempted."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            progress_failure = OSError("PRIMARY_PROGRESS_PUBLICATION")
            database_failure = RuntimeError("SECONDARY_DATABASE_CLOSE")
            try:
                application = self._application(
                    database,
                    analysis,
                    _FailingProgressStore(progress_failure),
                )
                with mock.patch.object(database, "close", side_effect=database_failure) as close:
                    with self.assertRaises(OSError) as caught:
                        application.shutdown()

                self.assertIs(caught.exception, progress_failure)
                close.assert_called_once_with()
            finally:
                database.close()
                analysis.close()


if __name__ == "__main__":
    unittest.main()
