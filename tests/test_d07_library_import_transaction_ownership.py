import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import LibraryImportCancelledError, LibraryImportService


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
            # Poll 4 is reached immediately before the second game.  By then
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


if __name__ == "__main__":
    unittest.main()
