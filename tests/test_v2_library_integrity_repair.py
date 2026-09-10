from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.search_policy import search_fold


_INITIAL = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
_AFTER_D4 = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 1"


_V5_INSERT_TRIGGER = """
CREATE TRIGGER trg_games_search_fold_insert
AFTER INSERT ON games
BEGIN
    INSERT OR REPLACE INTO game_search_fold(
        game_id, white_fold, black_fold, event_fold, eco_fold, opening_fold
    ) VALUES(
        NEW.id,
        ACS_SEARCH_FOLD(NEW.white),
        ACS_SEARCH_FOLD(NEW.black),
        ACS_SEARCH_FOLD(NEW.event),
        ACS_SEARCH_FOLD(NEW.eco),
        ACS_SEARCH_FOLD(NEW.opening)
    );
END;
"""

_V5_UPDATE_TRIGGER = """
CREATE TRIGGER trg_games_search_fold_update
AFTER UPDATE OF white, black, event, eco, opening ON games
BEGIN
    INSERT OR REPLACE INTO game_search_fold(
        game_id, white_fold, black_fold, event_fold, eco_fold, opening_fold
    ) VALUES(
        NEW.id,
        ACS_SEARCH_FOLD(NEW.white),
        ACS_SEARCH_FOLD(NEW.black),
        ACS_SEARCH_FOLD(NEW.event),
        ACS_SEARCH_FOLD(NEW.eco),
        ACS_SEARCH_FOLD(NEW.opening)
    );
END;
"""


def _downgrade_to_v5(database: AcsDatabase) -> None:
    database.conn.executescript(
        """
        DROP TRIGGER IF EXISTS trg_game_search_fold_dirty_insert;
        DROP TRIGGER IF EXISTS trg_game_search_fold_dirty_update;
        DROP TRIGGER IF EXISTS trg_game_search_fold_dirty_delete;
        DROP TRIGGER IF EXISTS trg_games_search_fold_delete_cleanup;
        DROP TRIGGER IF EXISTS trg_games_search_fold_insert;
        DROP TRIGGER IF EXISTS trg_games_search_fold_update;
        DROP TABLE IF EXISTS game_search_fold_dirty;
        """
        + _V5_INSERT_TRIGGER
        + _V5_UPDATE_TRIGGER
        + "PRAGMA user_version = 5;\n"
    )
    database.conn.commit()


class _FailAfterV6(AcsDatabase):
    def _migrate_to_v6(self) -> None:
        super()._migrate_to_v6()
        self.conn.execute("CREATE TABLE v6_partial_marker(value TEXT NOT NULL)")
        self.conn.execute("INSERT INTO v6_partial_marker(value) VALUES('must-rollback')")
        raise RuntimeError("synthetic v6 migration failure")


class V2LibraryIntegrityRepairTests(unittest.TestCase):
    def test_schema_v6_tracks_projection_mutation_and_canonical_write_clears_own_id(self) -> None:
        with AcsDatabase() as database:
            self.assertEqual(ACSDB_SCHEMA_VERSION, 6)
            self.assertEqual(database.schema_version, 6)
            columns = {
                str(row[1])
                for row in database.conn.execute(
                    "PRAGMA table_info(game_search_fold_dirty)"
                ).fetchall()
            }
            self.assertEqual(columns, {"game_id"})

            report = database.import_pgn_text(
                '[Event "Projection"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 *',
                "projection.pgn",
            )
            game_id = report.game_ids[0]
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM game_search_fold_dirty").fetchone()[0],
                0,
            )

            with database.conn:
                database.conn.execute("UPDATE games SET white=? WHERE id=?", ("Gamma", game_id))
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM game_search_fold_dirty").fetchone()[0],
                0,
            )
            self.assertEqual(
                database.conn.execute(
                    "SELECT white_fold FROM game_search_fold WHERE game_id=?", (game_id,)
                ).fetchone()[0],
                search_fold("Gamma"),
            )
            self.assertEqual([row["id"] for row in database.search_games(player="gamma")], [game_id])

    def test_v5_migration_rebuilds_preexisting_missing_projection_before_v6_publication(self) -> None:
        fd, raw = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        path = Path(raw)
        try:
            with AcsDatabase(path) as database:
                report = database.import_pgn_text(
                    '[Event "Repair"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 *',
                    "repair.pgn",
                )
                game_id = report.game_ids[0]
                _downgrade_to_v5(database)
                database.conn.execute("DELETE FROM game_search_fold WHERE game_id=?", (game_id,))
                database.conn.commit()
                self.assertEqual(database.conn.execute("PRAGMA user_version").fetchone()[0], 5)

            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, 6)
                self.assertEqual([row["id"] for row in migrated.search_games(player="alpha")], [game_id])
                self.assertEqual(
                    migrated.conn.execute("SELECT COUNT(*) FROM game_search_fold_dirty").fetchone()[0],
                    0,
                )
                self.assertEqual(migrated.verify_integrity(), 6)
        finally:
            if path.exists():
                path.unlink()

    def test_failed_v6_migration_rolls_back_projection_rebuild_triggers_and_user_version(self) -> None:
        fd, raw = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        path = Path(raw)
        try:
            with AcsDatabase(path) as database:
                report = database.import_pgn_text(
                    '[Event "Rollback"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 *',
                    "rollback.pgn",
                )
                game_id = report.game_ids[0]
                _downgrade_to_v5(database)
                database.conn.execute(
                    "UPDATE game_search_fold SET white_fold='stale-v5' WHERE game_id=?",
                    (game_id,),
                )
                database.conn.commit()

            with self.assertRaisesRegex(RuntimeError, "synthetic v6 migration failure"):
                _FailAfterV6(path)

            raw_connection = sqlite3.connect(path)
            try:
                self.assertEqual(raw_connection.execute("PRAGMA user_version").fetchone()[0], 5)
                tables = {
                    str(row[0])
                    for row in raw_connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertNotIn("game_search_fold_dirty", tables)
                self.assertNotIn("v6_partial_marker", tables)
                self.assertEqual(
                    raw_connection.execute(
                        "SELECT white_fold FROM game_search_fold WHERE game_id=?", (game_id,)
                    ).fetchone()[0],
                    "stale-v5",
                )
            finally:
                raw_connection.close()

            with AcsDatabase(path) as recovered:
                self.assertEqual(recovered.schema_version, 6)
                self.assertEqual([row["id"] for row in recovered.search_games(player="alpha")], [game_id])
                self.assertEqual(recovered.verify_integrity(), 6)
        finally:
            if path.exists():
                path.unlink()

    def test_raw_projection_delete_fails_ordinary_search_closed_and_explicit_rebuild_recovers(self) -> None:
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

            external = sqlite3.connect(path)
            try:
                external.execute("DELETE FROM game_search_fold WHERE game_id=?", (game_id,))
                external.commit()
                self.assertEqual(
                    external.execute(
                        "SELECT COUNT(*) FROM game_search_fold_dirty WHERE game_id=?", (game_id,)
                    ).fetchone()[0],
                    1,
                )
            finally:
                external.close()

            with AcsDatabase(path) as reopened:
                with self.assertRaisesRegex(RuntimeError, "search projection integrity"):
                    reopened.search_games(player="alpha")
                with self.assertRaisesRegex(RuntimeError, "search projection integrity"):
                    reopened.verify_integrity()
                reopened.rebuild_search_projection()
                self.assertEqual([row["id"] for row in reopened.search_games(player="alpha")], [game_id])
                self.assertEqual(reopened.verify_integrity(), 6)

            with AcsDatabase(path) as reopened_again:
                self.assertEqual(
                    [row["id"] for row in reopened_again.search_games(player="alpha")],
                    [game_id],
                )
        finally:
            if path.exists():
                path.unlink()

    def test_raw_stale_projection_and_missing_guard_trigger_both_fail_closed(self) -> None:
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
                database.conn.execute(
                    "UPDATE game_search_fold SET white_fold='beta-only' WHERE game_id=?",
                    (game_id,),
                )
                database.conn.commit()
                with self.assertRaisesRegex(RuntimeError, "search projection integrity"):
                    database.search_games(player="alpha")
                database.rebuild_search_projection()
                self.assertEqual([row["id"] for row in database.search_games(player="alpha")], [game_id])

                database.conn.execute("DROP TRIGGER trg_game_search_fold_dirty_delete")
                database.conn.commit()
                with self.assertRaisesRegex(RuntimeError, "search projection integrity"):
                    database.search_games(player="alpha")
        finally:
            if path.exists():
                path.unlink()

    def test_position_ply_identity_rejects_coercion_without_mutation(self) -> None:
        with AcsDatabase() as database:
            report = database.import_pgn_text('[Result "*"]\n\n1. e4 *', "positions.pgn")
            game_id = report.game_ids[0]
            database.record_position(game_id, 1, _INITIAL)
            for ambiguous in ("1", True, 1.0, 1.9, None):
                with self.subTest(value=repr(ambiguous)):
                    with self.assertRaises(TypeError):
                        database.record_position(game_id, ambiguous, _AFTER_E4)  # type: ignore[arg-type]
                    self.assertEqual(
                        database.conn.execute(
                            "SELECT fen FROM positions WHERE game_id=? AND ply=1", (game_id,)
                        ).fetchone()[0],
                        _INITIAL,
                    )
            for invalid in (-1, 1 << 63):
                with self.subTest(value=invalid):
                    with self.assertRaises(ValueError):
                        database.record_position(game_id, invalid, _AFTER_E4)
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 1)

    def test_position_duplicate_rejects_by_default_and_explicit_overwrite_is_exact(self) -> None:
        with AcsDatabase() as database:
            report = database.import_pgn_text('[Result "*"]\n\n1. e4 *', "positions.pgn")
            game_id = report.game_ids[0]
            database.record_position(game_id, 1, _INITIAL)
            with self.assertRaises(sqlite3.IntegrityError):
                database.record_position(game_id, 1, _AFTER_E4)
            self.assertEqual(
                database.conn.execute(
                    "SELECT fen FROM positions WHERE game_id=? AND ply=1", (game_id,)
                ).fetchone()[0],
                _INITIAL,
            )
            database.record_position(game_id, 1, _AFTER_E4, overwrite=True)
            self.assertEqual(
                database.conn.execute(
                    "SELECT fen FROM positions WHERE game_id=? AND ply=1", (game_id,)
                ).fetchone()[0],
                _AFTER_E4,
            )
            with self.assertRaises(TypeError):
                database.record_position(game_id, 2, _AFTER_D4, overwrite=1)  # type: ignore[arg-type]
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 1)

    def test_position_batch_prevalidates_duplicate_and_invalid_rows_before_mutation(self) -> None:
        with AcsDatabase() as database:
            report = database.import_pgn_text('[Result "*"]\n\n1. e4 *', "positions.pgn")
            game_id = report.game_ids[0]
            with self.assertRaisesRegex(ValueError, "duplicate ply"):
                database.record_positions(
                    game_id,
                    [(1, _INITIAL), (1, _AFTER_E4)],
                )
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)

            with self.assertRaises(ValueError):
                database.record_positions(
                    game_id,
                    [(1, _INITIAL), (2, "not a fen")],
                )
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)

            database.record_positions(game_id, [(1, _INITIAL), (2, _AFTER_D4)])
            with self.assertRaises(sqlite3.IntegrityError):
                database.record_positions(game_id, [(3, _AFTER_E4), (2, _AFTER_E4)])
            self.assertEqual(
                [
                    (int(row[0]), str(row[1]))
                    for row in database.conn.execute(
                        "SELECT ply, fen FROM positions WHERE game_id=? ORDER BY ply", (game_id,)
                    ).fetchall()
                ],
                [(1, _INITIAL), (2, _AFTER_D4)],
            )

            database.record_positions(
                game_id,
                [(1, _AFTER_E4), (2, _INITIAL)],
                overwrite=True,
            )
            self.assertEqual(
                [str(row[0]) for row in database.conn.execute(
                    "SELECT fen FROM positions WHERE game_id=? ORDER BY ply", (game_id,)
                ).fetchall()],
                [_AFTER_E4, _INITIAL],
            )


if __name__ == "__main__":
    unittest.main()
