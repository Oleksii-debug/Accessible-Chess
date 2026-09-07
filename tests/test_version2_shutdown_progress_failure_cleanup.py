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


class Version2ShutdownProgressFailureCleanupTests(unittest.TestCase):
    def test_progress_save_failure_propagates_after_database_close(self) -> None:
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
                # Keep this lifecycle oracle independent of Book parser/format work.
                application.reader = object()
                application.book_key = "shutdown-book"

                with self.assertRaisesRegex(OSError, "synthetic progress publication failure"):
                    application.shutdown()

                with self.assertRaises(sqlite3.ProgrammingError):
                    database.conn.execute("SELECT 1")
            finally:
                database.close()
                analysis.close()


if __name__ == "__main__":
    unittest.main()
