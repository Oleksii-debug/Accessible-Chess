from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.version2_upgrade import UserDataLayout, Version2UpgradeCoordinator, Version2UpgradeError


class V2UpgradeCurrentAcsdbIdentityAuditTests(unittest.TestCase):
    def _make_current_library(self, root: Path) -> Path:
        library = root / "library.acsdb"
        with AcsDatabase(library) as database:
            source_id = database.add_source("identity-audit.pgn", "pgn")
            database.conn.execute(
                "INSERT INTO games(source_id,source_index,import_status,warnings_json,pgn_text) "
                "VALUES(?,0,'full','[]','1. e4 e5 *')",
                (source_id,),
            )
            database.conn.commit()
            self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
        return library

    def _assert_quick_check_still_ok(self, library: Path) -> None:
        conn = sqlite3.connect(library)
        try:
            self.assertEqual(str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower(), "ok")
            self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), ACSDB_SCHEMA_VERSION)
            with self.assertRaises(RuntimeError):
                AcsDatabase._check_sqlite_integrity(conn)
        finally:
            conn.close()

    def test_current_schema_missing_required_index_is_not_already_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = self._make_current_library(root)
            conn = sqlite3.connect(library)
            try:
                conn.execute("DROP INDEX idx_positions_key_game_ply")
                conn.commit()
            finally:
                conn.close()
            self._assert_quick_check_still_ok(library)
            with self.assertRaisesRegex(Version2UpgradeError, "library validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

    def test_current_schema_missing_required_table_is_not_already_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = self._make_current_library(root)
            conn = sqlite3.connect(library)
            try:
                conn.execute("DROP TABLE positions")
                conn.commit()
            finally:
                conn.close()
            self._assert_quick_check_still_ok(library)
            with self.assertRaisesRegex(Version2UpgradeError, "library validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

    def test_current_schema_foreign_key_violation_is_not_already_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = self._make_current_library(root)
            conn = sqlite3.connect(library)
            try:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute(
                    "UPDATE games SET source_id=999999 WHERE id=(SELECT id FROM games ORDER BY id LIMIT 1)"
                )
                conn.commit()
            finally:
                conn.close()
            self._assert_quick_check_still_ok(library)
            with self.assertRaisesRegex(Version2UpgradeError, "library validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()


if __name__ == "__main__":
    unittest.main()
