from __future__ import annotations

import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase


_INITIAL = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


class V2FinalFormatsD07RegressionAuditTests(unittest.TestCase):
    def test_final_formats_retains_accepted_schema_v6_authority(self) -> None:
        self.assertEqual(
            ACSDB_SCHEMA_VERSION,
            6,
            "final-formats staging dropped the accepted D07 schema-v6 authority",
        )

    def test_final_formats_retains_strict_non_destructive_position_identity(self) -> None:
        with AcsDatabase() as database:
            report = database.import_pgn_text(
                '[Event "Integrity"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 *',
                "integrity.pgn",
            )
            game_id = report.game_ids[0]
            database.record_position(game_id, 1, _INITIAL)

            for ambiguous in ("1", True, 1.0):
                with self.subTest(value=repr(ambiguous)):
                    with self.assertRaises(TypeError):
                        database.record_position(game_id, ambiguous, _AFTER_E4)  # type: ignore[arg-type]
                    row = database.conn.execute(
                        "SELECT ply, fen FROM positions WHERE game_id=? AND ply=1",
                        (game_id,),
                    ).fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(int(row[0]), 1)
                    self.assertEqual(str(row[1]), _INITIAL)


if __name__ == "__main__":
    unittest.main()
