from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase


_INITIAL = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


class V2LibraryIntegrityAuditTests(unittest.TestCase):
    def test_position_ply_scalar_cannot_coerce_and_overwrite_existing_row(self) -> None:
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

    def test_corrupt_search_projection_cannot_silently_hide_canonical_game_after_reopen(self) -> None:
        fd, raw = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        path = Path(raw)
        try:
            with AcsDatabase(path) as database:
                report = database.import_pgn_text(
                    '[Event "Projection"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 *',
                    "projection.pgn",
                )
                game_id = report.game_ids[0]
                self.assertEqual(
                    [row["id"] for row in database.search_games(player="alpha")],
                    [game_id],
                )

            raw_connection = sqlite3.connect(path)
            try:
                raw_connection.execute(
                    "DELETE FROM game_search_fold WHERE game_id=?",
                    (game_id,),
                )
                raw_connection.commit()
                self.assertEqual(
                    raw_connection.execute(
                        "SELECT COUNT(*) FROM games WHERE id=?", (game_id,)
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    raw_connection.execute(
                        "SELECT COUNT(*) FROM game_search_fold WHERE game_id=?", (game_id,)
                    ).fetchone()[0],
                    0,
                )
            finally:
                raw_connection.close()

            with AcsDatabase(path) as reopened:
                try:
                    rows = reopened.search_games(player="alpha")
                except RuntimeError:
                    # Explicit fail-closed detection is acceptable.
                    return
                self.assertEqual(
                    [row["id"] for row in rows],
                    [game_id],
                    "search returned a false empty result because a derivative sidecar row was missing",
                )
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
