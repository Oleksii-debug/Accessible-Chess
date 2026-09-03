from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.search_policy import search_fold


TRIGGERS = ("trg_games_search_fold_insert", "trg_games_search_fold_update")


def _drop_v4(database: AcsDatabase) -> None:
    for trigger in TRIGGERS:
        database.conn.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
    database.conn.execute("DROP TABLE IF EXISTS game_search_fold")
    database.conn.execute("PRAGMA user_version = 3")
    database.conn.commit()


def _game_row(source_id: int, source_index: int, *, white: str = "Straße") -> tuple[object, ...]:
    return (
        source_id,
        source_index,
        "full",
        "[]",
        "Ｃａｆｅ\u0301 Cup",
        "Kyiv",
        "2026.08.28",
        str(source_index),
        white,
        "Олексій",
        "1-0",
        "C42",
        "Французький \\ Варіант",
        None,
        "*",
    )


INSERT_GAME = """INSERT INTO games(
    source_id, source_index, import_status, warnings_json,
    event, site, game_date, round, white, black, result,
    eco, opening, start_fen, pgn_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


class _FailAfterV4(AcsDatabase):
    def _migrate_to_v4(self) -> None:
        super()._migrate_to_v4()
        self.conn.execute("CREATE TABLE v4_partial_marker(value TEXT NOT NULL)")
        self.conn.execute("INSERT INTO v4_partial_marker(value) VALUES('must-rollback')")
        raise RuntimeError("synthetic v4 migration failure")


class V2LibraryAcsdbSearchV4Tests(unittest.TestCase):
    def test_schema_v4_projection_remains_explicit_in_current_schema(self) -> None:
        with AcsDatabase() as database:
            self.assertEqual(ACSDB_SCHEMA_VERSION, 6)
            self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
            columns = {
                str(row[1])
                for row in database.conn.execute("PRAGMA table_info(game_search_fold)").fetchall()
            }
            self.assertEqual(
                columns,
                {"game_id", "white_fold", "black_fold", "event_fold", "eco_fold", "opening_fold"},
            )
            trigger_names = {
                str(row[0])
                for row in database.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                ).fetchall()
            }
            self.assertTrue(set(TRIGGERS).issubset(trigger_names))

    def test_v3_migration_backfills_unicode_projection_then_advances_to_current_schema(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as database:
                source_id = database.add_source("legacy.pgn", "pgn")
                with database.conn:
                    database.conn.execute(INSERT_GAME, _game_row(source_id, 1))
                _drop_v4(database)

            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                row = migrated.conn.execute(
                    "SELECT white_fold, black_fold, event_fold, eco_fold, opening_fold "
                    "FROM game_search_fold WHERE game_id=1"
                ).fetchone()
                self.assertEqual(row[0], search_fold("Straße"))
                self.assertEqual(row[1], search_fold("Олексій"))
                self.assertEqual(row[2], search_fold("Ｃａｆｅ\u0301 Cup"))
                self.assertEqual(row[3], search_fold("C42"))
                self.assertEqual(row[4], search_fold("Французький \\ Варіант"))
                self.assertEqual(migrated.verify_integrity(), ACSDB_SCHEMA_VERSION)

            with AcsDatabase(path) as reopened:
                self.assertEqual([row["id"] for row in reopened.search_games(player="STRASSE")], [1])
                self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_failed_v4_migration_rolls_back_schema_backfill_and_user_version(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as database:
                source_id = database.add_source("rollback.pgn", "pgn")
                with database.conn:
                    database.conn.execute(INSERT_GAME, _game_row(source_id, 1))
                _drop_v4(database)

            with self.assertRaisesRegex(RuntimeError, "synthetic v4 migration failure"):
                _FailAfterV4(path)

            raw = sqlite3.connect(path)
            try:
                self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 3)
                tables = {
                    str(row[0])
                    for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                self.assertNotIn("game_search_fold", tables)
                self.assertNotIn("v4_partial_marker", tables)
                self.assertEqual(raw.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)
            finally:
                raw.close()

            with AcsDatabase(path) as recovered:
                self.assertEqual(recovered.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual([row["id"] for row in recovered.search_games(player="strasse")], [1])
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_database_triggers_write_through_update_and_rollback_atomically(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("owned.pgn", "pgn")
            with database.conn:
                database.conn.execute(INSERT_GAME, _game_row(source_id, 1))
            self.assertEqual(
                database.conn.execute(
                    "SELECT white_fold FROM game_search_fold WHERE game_id=1"
                ).fetchone()[0],
                search_fold("Straße"),
            )

            with database.conn:
                database.conn.execute("UPDATE games SET white=? WHERE id=1", ("İstanbul",))
            self.assertEqual(
                database.conn.execute(
                    "SELECT white_fold FROM game_search_fold WHERE game_id=1"
                ).fetchone()[0],
                search_fold("İstanbul"),
            )

            try:
                with database.conn:
                    database.conn.execute(INSERT_GAME, _game_row(source_id, 2, white="Rollback"))
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM game_search_fold").fetchone()[0],
                1,
            )

    def test_external_writer_without_canonical_search_functions_fails_closed(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as database:
                source_id = database.add_source("external.pgn", "pgn")

            external = sqlite3.connect(path)
            try:
                external.execute("PRAGMA foreign_keys = ON")
                with self.assertRaisesRegex(sqlite3.OperationalError, "(?:no such|unknown) function"):
                    external.execute(INSERT_GAME, _game_row(source_id, 1))
                external.rollback()
            finally:
                external.close()

            with AcsDatabase(path) as reopened:
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM game_search_fold").fetchone()[0], 0)
                self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_integrity_gate_detects_missing_and_stale_projection(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("corrupt.pgn", "pgn")
            with database.conn:
                database.conn.execute(INSERT_GAME, _game_row(source_id, 1))
            database.conn.execute(
                "UPDATE game_search_fold SET white_fold='definitely-wrong' WHERE game_id=1"
            )
            database.conn.commit()
            with self.assertRaisesRegex(RuntimeError, "search projection integrity"):
                database.verify_integrity()

            database.rebuild_search_projection()
            self.assertEqual(database.verify_integrity(), ACSDB_SCHEMA_VERSION)

            database.conn.execute("DELETE FROM game_search_fold WHERE game_id=1")
            database.conn.commit()
            with self.assertRaisesRegex(RuntimeError, "search projection integrity"):
                database.verify_integrity()

    def test_corrupt_projection_blocks_backup_publication(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        os.unlink(path)
        try:
            with AcsDatabase() as database:
                source_id = database.add_source("backup.pgn", "pgn")
                with database.conn:
                    database.conn.execute(INSERT_GAME, _game_row(source_id, 1))
                database.conn.execute("DELETE FROM game_search_fold WHERE game_id=1")
                database.conn.commit()
                with self.assertRaisesRegex(RuntimeError, "search projection integrity"):
                    database.backup_to(path)
            self.assertFalse(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_source_delete_cascades_through_games_and_search_projection(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("cascade.pgn", "pgn")
            with database.conn:
                database.conn.execute(INSERT_GAME, _game_row(source_id, 1))
                database.conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
            self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM game_search_fold").fetchone()[0], 0)
            self.assertEqual(database.verify_integrity(), ACSDB_SCHEMA_VERSION)

    def test_search_preserves_nfkc_casefold_literal_filters_keyset_and_public_shape(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("КОЛЕКЦІЯ%_\\.pgn", "pgn")
            rows = [
                _game_row(source_id, 1, white="Straße"),
                _game_row(source_id, 2, white="Literal%Name"),
                _game_row(source_id, 3, white="Under_score"),
                _game_row(source_id, 4, white="Back\\slash"),
            ]
            with database.conn:
                database.conn.executemany(INSERT_GAME, rows)

            traced: list[str] = []
            database.conn.set_trace_callback(traced.append)
            try:
                first = database.search_games(player="STRASSE", limit=1)
                literal_percent = database.search_games(player="%")
                literal_underscore = database.search_games(player="_")
                literal_slash = database.search_games(player="\\")
                source = database.search_games(source_name="колекція%_\\")
                eco = database.search_games(eco="c4")
                opening = database.search_games(opening="французький \\ варіант")
                page2 = database.search_games(after_id=2, limit=2)
            finally:
                database.conn.set_trace_callback(None)

            self.assertEqual([row["id"] for row in first], [1])
            self.assertEqual([row["id"] for row in literal_percent], [2])
            self.assertEqual([row["id"] for row in literal_underscore], [3])
            self.assertEqual([row["id"] for row in literal_slash], [4])
            self.assertEqual([row["id"] for row in source], [1, 2, 3, 4])
            self.assertEqual([row["id"] for row in eco], [1, 2, 3, 4])
            self.assertEqual([row["id"] for row in opening], [1, 2, 3, 4])
            self.assertEqual([row["id"] for row in page2], [3, 4])
            self.assertIn("source_sha256", first[0])
            search_sql = "\n".join(statement for statement in traced if "SELECT g.*" in statement)
            self.assertIn("game_search_fold", search_sql)
            self.assertNotIn("ACS_SEARCH_FOLD(g.white)", search_sql)


if __name__ == "__main__":
    unittest.main()