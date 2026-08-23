import os
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase


class _FailAfterV1(AcsDatabase):
    def _migrate_to_v1(self) -> None:
        super()._migrate_to_v1()
        self.conn.execute("CREATE TABLE d07_partial_v1(value TEXT NOT NULL)")
        self.conn.execute("INSERT INTO d07_partial_v1(value) VALUES('must-rollback')")
        raise RuntimeError("synthetic v1 migration failure")


class _FailAfterV2(AcsDatabase):
    def _migrate_to_v2(self) -> None:
        super()._migrate_to_v2()
        self.conn.execute("CREATE TABLE d07_partial_v2(value TEXT NOT NULL)")
        self.conn.execute("INSERT INTO d07_partial_v2(value) VALUES('must-rollback')")
        raise RuntimeError("synthetic v2 migration failure")


def _table_names(path: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        }
    finally:
        conn.close()


def _user_version(path: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


class D07AcsdbMigrationAtomicityTests(unittest.TestCase):
    def test_failed_fresh_v1_migration_rolls_back_all_schema_changes(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with self.assertRaisesRegex(RuntimeError, "synthetic v1 migration failure"):
                _FailAfterV1(path)

            self.assertEqual(_user_version(path), 0)
            self.assertEqual(_table_names(path), set())

            with AcsDatabase(path) as recovered:
                self.assertEqual(recovered.schema_version, ACSDB_SCHEMA_VERSION)
                recovered.add_source("recovered.pgn", "pgn")
            with AcsDatabase(path) as reopened:
                self.assertEqual(reopened.get_source(1)["source_name"], "recovered.pgn")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_failed_v2_migration_preserves_exact_v1_schema_and_rows(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as current:
                current.add_source("legacy-v1.pgn", "pgn")
                current.conn.execute("DROP INDEX idx_positions_key_game_ply")
                current.conn.execute("DROP TABLE import_attempts")
                current.conn.execute("PRAGMA user_version = 1")
                current.conn.commit()

            before_tables = _table_names(path)
            self.assertNotIn("import_attempts", before_tables)

            with self.assertRaisesRegex(RuntimeError, "synthetic v2 migration failure"):
                _FailAfterV2(path)

            self.assertEqual(_user_version(path), 1)
            self.assertEqual(_table_names(path), before_tables)
            conn = sqlite3.connect(path)
            try:
                self.assertEqual(
                    conn.execute("SELECT source_name FROM sources WHERE id=1").fetchone()[0],
                    "legacy-v1.pgn",
                )
            finally:
                conn.close()

            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(migrated.get_source(1)["source_name"], "legacy-v1.pgn")
                self.assertIn(
                    "import_attempts",
                    {
                        str(row[0])
                        for row in migrated.conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    },
                )
            with AcsDatabase(path) as reopened:
                self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(reopened.get_source(1)["source_name"], "legacy-v1.pgn")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_v2_database_upgrades_to_v3_and_reopens_without_data_loss(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as current:
                current.add_source("legacy-v2.pgn", "pgn")
                current.conn.execute("DROP INDEX idx_positions_key_game_ply")
                current.conn.execute("PRAGMA user_version = 2")
                current.conn.commit()

            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(migrated.get_source(1)["source_name"], "legacy-v2.pgn")
                index_columns = [
                    str(row[2])
                    for row in migrated.conn.execute(
                        'PRAGMA index_info("idx_positions_key_game_ply")'
                    ).fetchall()
                ]
                self.assertEqual(index_columns, ["position_key", "game_id", "ply"])

            with AcsDatabase(path) as reopened:
                self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(reopened.get_source(1)["source_name"], "legacy-v2.pgn")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_successful_migration_leaves_no_open_transaction(self):
        with AcsDatabase(":memory:") as database:
            self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
            self.assertFalse(database.conn.in_transaction)


if __name__ == "__main__":
    unittest.main()
