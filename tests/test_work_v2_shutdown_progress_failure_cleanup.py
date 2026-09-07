from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


class _FailingProgressStore:
    def save(self, _book_key, _reader) -> None:
        raise OSError("synthetic progress publication failure")


class Version2ShutdownProgressFailureCleanupEvidenceTests(unittest.TestCase):
    def test_progress_save_failure_does_not_skip_database_close(self) -> None:
        """Shutdown must release ACSDB even when durable Book progress fails.

        Losing the progress exception would be dishonest, but allowing it to skip
        the database close leaves the V2 application with an owned SQLite
        connection/lock after the close path has already started.  The correct
        lifecycle is therefore: propagate the progress failure *after* cleanup,
        not instead of cleanup.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                application = Version2Application(
                    database,
                    progress_store=_FailingProgressStore(),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args: None,
                )
                # Keep this oracle independent of Book parsing/format ownership.
                # save_book_progress() only requires that a current reader exists.
                application.reader = object()
                application.book_key = "shutdown-evidence-book"

                with self.assertRaisesRegex(OSError, "synthetic progress publication failure"):
                    application.shutdown()

                with self.assertRaises(sqlite3.ProgrammingError):
                    database.conn.execute("SELECT 1")
            finally:
                # Idempotent if Product already did the required cleanup; needed
                # only to keep the expected-RED baseline from leaking a test DB.
                database.close()
                analysis.close()


if __name__ == "__main__":
    unittest.main()