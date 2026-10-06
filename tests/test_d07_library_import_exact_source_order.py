from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import LibraryImportService


DIGEST = "d" * 64


def game(index: int) -> PgnGame:
    return PgnGame(
        tags={
            "Event": f"Order {index}",
            "White": f"White {index}",
            "Black": f"Black {index}",
            "Result": "*",
        },
        line=VariationLine(result="*"),
        source_index=index,
        warnings=[],
    )


class ExactSourceOrderingIdempotencyTests(unittest.TestCase):
    def test_non_monotonic_exact_retry_reuses_without_duplicate_publication(self) -> None:
        with AcsDatabase(":memory:") as database:
            importer = LibraryImportService(database)
            games = (game(1), game(0))

            first = importer.import_games(
                games,
                source_name="original.pgn",
                source_format="PGN",
                source_sha256=DIGEST,
            )
            before_rows = [
                tuple(row)
                for row in database.conn.execute(
                    "SELECT id, source_id, source_index, import_status, warnings_json, pgn_text "
                    "FROM games ORDER BY id"
                ).fetchall()
            ]
            self.assertEqual([row[2] for row in before_rows], [1, 0])

            repeated = importer.import_games(
                games,
                source_name="renamed-copy.pgn",
                source_format="pgn",
                source_sha256=DIGEST.upper(),
            )
            after_rows = [
                tuple(row)
                for row in database.conn.execute(
                    "SELECT id, source_id, source_index, import_status, warnings_json, pgn_text "
                    "FROM games ORDER BY id"
                ).fetchall()
            ]

            self.assertFalse(first.reused)
            self.assertTrue(repeated.reused)
            self.assertNotEqual(repeated.attempt_id, first.attempt_id)
            self.assertEqual(repeated.source_id, first.source_id)
            self.assertEqual(repeated.first_game_id, first.first_game_id)
            self.assertEqual(repeated.last_game_id, first.last_game_id)
            self.assertEqual(after_rows, before_rows)
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                1,
            )
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                2,
            )
            attempts = database.list_import_attempts(limit=10)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(
                [row["source_name"] for row in attempts],
                ["renamed-copy.pgn", "original.pgn"],
            )


if __name__ == "__main__":
    unittest.main()
