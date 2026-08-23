import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportControlError,
    LibraryImportService,
)


DIGEST = "d" * 64


def game(index: int) -> PgnGame:
    return PgnGame(
        tags={
            "Event": f"Owner {index}",
            "White": f"White {index}",
            "Black": f"Black {index}",
            "Result": "*",
        },
        line=VariationLine(result="*"),
        source_index=index,
        warnings=[],
    )


class D07LibraryImportTransactionOwnershipTests(unittest.TestCase):
    def test_progress_callback_cannot_commit_through_public_acsdb_write_api(self) -> None:
        db = AcsDatabase(":memory:")
        service = LibraryImportService(db)
        cancel_polls = 0
        callback_write_outcomes: list[str] = []

        def cancel() -> bool:
            nonlocal cancel_polls
            cancel_polls += 1
            # Poll 4 is reached immediately before the second game. By then
            # game 0 has been staged and the progress callback has run once.
            return cancel_polls == 4

        def progress(item) -> None:
            if item.processed_games != 1:
                return
            try:
                db.add_source("reentrant-source", "callback", "e" * 64)
            except RuntimeError:
                callback_write_outcomes.append("blocked")
            else:
                callback_write_outcomes.append("committed")

        try:
            with self.assertRaisesRegex(LibraryImportCancelledError, "Library import cancelled"):
                service.import_games(
                    (game(0), game(1)),
                    source_name="atomic-owner.pgn",
                    source_format="pgn",
                    source_sha256=DIGEST,
                    cancel_check=cancel,
                    progress_callback=progress,
                )

            # A progress observer must not be able to end the importer's SQLite
            # transaction through an official mutating AcsDatabase API.
            self.assertEqual(callback_write_outcomes, ["blocked"])
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
            self.assertEqual(
                db.conn.execute(
                    "SELECT COUNT(*) FROM sources WHERE source_name=?",
                    ("atomic-owner.pgn",),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.conn.execute(
                    "SELECT COUNT(*) FROM sources WHERE source_name=?",
                    ("reentrant-source",),
                ).fetchone()[0],
                0,
            )
            attempt = db.list_import_attempts(limit=1)[0]
            self.assertEqual(attempt["status"], "failed")
            self.assertIsNone(attempt["source_id"])
            self.assertEqual(attempt["game_count"], 0)
        finally:
            db.close()

    def test_unhandled_progress_connection_reentry_is_sanitized_and_rolls_back(self) -> None:
        db = AcsDatabase(":memory:")
        service = LibraryImportService(db)

        def progress(item) -> None:
            if item.processed_games == 1:
                db.conn.commit()

        try:
            with self.assertRaisesRegex(
                LibraryImportControlError,
                "Library import progress callback failed",
            ):
                service.import_games(
                    (game(0), game(1)),
                    source_name="raw-commit.pgn",
                    source_format="pgn",
                    source_sha256=DIGEST,
                    progress_callback=progress,
                )

            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
            self.assertEqual(
                db.conn.execute(
                    "SELECT COUNT(*) FROM sources WHERE source_name=?",
                    ("raw-commit.pgn",),
                ).fetchone()[0],
                0,
            )
            attempt = db.list_import_attempts(limit=1)[0]
            self.assertEqual(attempt["status"], "failed")
            self.assertEqual(attempt["error_message"], "Library import progress callback failed")
        finally:
            db.close()

    def test_cancel_callback_reentry_is_blocked_without_partial_publication(self) -> None:
        db = AcsDatabase(":memory:")
        service = LibraryImportService(db)
        polls = 0

        def cancel() -> bool:
            nonlocal polls
            polls += 1
            if polls == 3:
                db.add_source("cancel-reentrant", "callback", "f" * 64)
            return False

        try:
            with self.assertRaisesRegex(
                LibraryImportControlError,
                "Library import cancellation check failed",
            ):
                service.import_games(
                    (game(0), game(1)),
                    source_name="cancel-owner.pgn",
                    source_format="pgn",
                    source_sha256=DIGEST,
                    cancel_check=cancel,
                )

            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
            attempt = db.list_import_attempts(limit=1)[0]
            self.assertEqual(attempt["status"], "failed")
            self.assertEqual(
                attempt["error_message"],
                "Library import cancellation check failed",
            )
        finally:
            db.close()

    def test_connection_is_restored_after_callback_isolation_and_successful_import(self) -> None:
        db = AcsDatabase(":memory:")
        service = LibraryImportService(db)
        original_connection = db.conn
        blocked = 0

        def progress(item) -> None:
            nonlocal blocked
            try:
                db.conn.execute("SELECT 1")
            except RuntimeError:
                blocked += 1

        try:
            result = service.import_games(
                (game(0), game(1)),
                source_name="restore-owner.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
                progress_callback=progress,
            )
            self.assertEqual(blocked, 3)
            self.assertIs(db.conn, original_connection)
            self.assertEqual(db.get_source(result.source_id)["source_name"], "restore-owner.pgn")
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 2)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
