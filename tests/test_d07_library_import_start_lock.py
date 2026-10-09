import os
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportService,
    LibraryImportStorageError,
)


DIGEST = "a" * 64


def game(index: int = 0) -> PgnGame:
    return PgnGame(
        tags={"White": "White", "Black": "Black", "Result": "*"},
        line=VariationLine(result="*"),
        source_index=index,
        warnings=[],
    )


class D07LibraryImportStartLockTests(unittest.TestCase):
    def _locked_database(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        database = AcsDatabase(path)
        database.conn.execute("PRAGMA busy_timeout = 1")
        blocker = sqlite3.connect(path)
        blocker.execute("PRAGMA busy_timeout = 1")
        blocker.execute("BEGIN IMMEDIATE")
        return path, database, blocker

    def test_cancel_repolls_after_busy_start_lock_without_raw_sqlite_error(self) -> None:
        path, database, blocker = self._locked_database()
        polls = 0

        def cancel() -> bool:
            nonlocal polls
            polls += 1
            return polls >= 2

        try:
            service = LibraryImportService(database)
            with self.assertRaisesRegex(
                LibraryImportCancelledError,
                "Library import cancelled",
            ):
                service.import_games(
                    (game(),),
                    source_name="locked-cancel.pgn",
                    source_format="pgn",
                    source_sha256=DIGEST,
                    cancel_check=cancel,
                )
            self.assertGreaterEqual(polls, 2)
        finally:
            blocker.rollback()
            blocker.close()

        try:
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0],
                0,
            )
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
            self.assertEqual(database.conn.execute("PRAGMA busy_timeout").fetchone()[0], 1)
        finally:
            database.close()
            if os.path.exists(path):
                os.unlink(path)

    def test_busy_start_timeout_is_sanitized_storage_error_and_zero_mutation(self) -> None:
        path, database, blocker = self._locked_database()
        try:
            service = LibraryImportService(database)
            with self.assertRaisesRegex(
                LibraryImportStorageError,
                "Library import failed",
            ) as caught:
                service.import_games(
                    (game(),),
                    source_name="locked-timeout.pgn",
                    source_format="pgn",
                    source_sha256=DIGEST,
                )
            self.assertNotIsInstance(caught.exception, sqlite3.OperationalError)
            self.assertNotIn("locked", str(caught.exception).lower())
            self.assertNotIn(path, str(caught.exception))
        finally:
            blocker.rollback()
            blocker.close()

        try:
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0],
                0,
            )
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
            self.assertEqual(database.conn.execute("PRAGMA busy_timeout").fetchone()[0], 1)
        finally:
            database.close()
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
