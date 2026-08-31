from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.version2_upgrade import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
)


class V2UpgradeV6SuccessorTests(unittest.TestCase):
    def _make_real_v1_library(self, path: Path) -> None:
        """Create the actual canonical D07 v1 schema, not a v6 DB with a lowered version."""
        database = object.__new__(AcsDatabase)
        database.path = str(path)
        database.conn = sqlite3.connect(path)
        try:
            database.conn.row_factory = sqlite3.Row
            database.conn.execute("PRAGMA foreign_keys = ON")
            database._migrate_to_v1()
            self.assertTrue(database.conn.in_transaction)
            database.conn.execute("PRAGMA user_version = 1")
            database.conn.commit()
            database.conn.execute(
                "INSERT INTO sources(source_name,source_format,sha256,imported_at) "
                "VALUES(?,?,?,?)",
                ("version1-library.pgn", "pgn", "1" * 64, "2026-01-02T03:04:05+00:00"),
            )
            database.conn.commit()
        finally:
            database.conn.close()

    def _make_current_library_with_game(self, path: Path) -> None:
        with AcsDatabase(path) as database:
            source_id = database.add_source("current.pgn", "pgn", "2" * 64)
            database.conn.execute(
                "INSERT INTO games(source_id,source_index,import_status,warnings_json,"
                "event,white,black,result,pgn_text) VALUES(?,0,'full','[]',?,?,?,?,?)",
                (source_id, "Integrity", "White", "Black", "1-0", "1. e4 e5 2. Nf3 1-0"),
            )
            database.conn.commit()
            self.assertEqual(database.verify_integrity(), ACSDB_SCHEMA_VERSION)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_real_v1_user_tree_upgrades_to_v6_without_losing_books_or_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 37}), encoding="utf-8"
            )
            (root / "books").mkdir()
            book = root / "books" / "course.bin"
            book.write_bytes(b"book\x00version-one\xff")
            (root / "progress").mkdir()
            progress = root / "progress" / "training.json"
            progress.write_text(
                json.dumps({"exercise": "mate-1", "attempts": 7}, ensure_ascii=False),
                encoding="utf-8",
            )
            library = root / "library.acsdb"
            self._make_real_v1_library(library)

            book_before = book.read_bytes()
            progress_before = progress.read_bytes()
            report = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertEqual(report.status, "upgraded")
            self.assertTrue(report.settings_migrated)
            self.assertTrue(report.library_migrated)
            self.assertEqual(report.target_acsdb_schema, 6)
            self.assertEqual(book.read_bytes(), book_before)
            self.assertEqual(progress.read_bytes(), progress_before)

            with AcsDatabase(library) as reopened:
                self.assertEqual(reopened.verify_integrity(), 6)
                self.assertEqual(reopened.get_source(1)["source_name"], "version1-library.pgn")

            backup = root.parent / "AccessibleChess.upgrade-backups" / report.backup_name
            manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
            by_path = {item["path"]: item for item in manifest["entries"]}
            for relative in (
                "settings.json",
                "library.acsdb",
                "books/course.bin",
                "progress/training.json",
            ):
                with self.subTest(relative=relative):
                    saved = backup / "data" / Path(*relative.split("/"))
                    self.assertTrue(saved.is_file())
                    self.assertEqual(by_path[relative]["size"], saved.stat().st_size)
                    self.assertEqual(by_path[relative]["sha256"], self._sha256(saved))

    def test_current_v6_with_missing_required_index_is_rejected_not_already_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_current_library_with_game(library)
            conn = sqlite3.connect(library)
            try:
                conn.execute("DROP INDEX idx_positions_key_game_ply")
                conn.commit()
                self.assertEqual(str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower(), "ok")
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 6)
            finally:
                conn.close()

            with self.assertRaisesRegex(Version2UpgradeError, "library validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_current_v6_with_dirty_search_projection_is_rejected_not_already_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_current_library_with_game(library)
            conn = sqlite3.connect(library)
            try:
                game_id = conn.execute("SELECT id FROM games LIMIT 1").fetchone()[0]
                conn.execute("DELETE FROM game_search_fold WHERE game_id=?", (game_id,))
                conn.commit()
                self.assertEqual(str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower(), "ok")
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 6)
            finally:
                conn.close()

            with self.assertRaisesRegex(Version2UpgradeError, "library validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_current_v6_with_foreign_key_violation_is_rejected_not_already_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_current_library_with_game(library)
            conn = sqlite3.connect(library)
            try:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("UPDATE games SET source_id=999999")
                conn.commit()
                self.assertEqual(str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower(), "ok")
                self.assertIsNotNone(conn.execute("PRAGMA foreign_key_check").fetchone())
            finally:
                conn.close()

            with self.assertRaisesRegex(Version2UpgradeError, "library validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_corrupt_old_v1_is_rejected_before_backup_or_journal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)
            conn = sqlite3.connect(library)
            try:
                conn.execute("DROP TABLE positions")
                conn.commit()
                self.assertEqual(str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower(), "ok")
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            finally:
                conn.close()

            with self.assertRaisesRegex(Version2UpgradeError, "library validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertFalse((root / ".v2-upgrade-state.json").exists())
            backup_root = root.parent / "AccessibleChess.upgrade-backups"
            self.assertFalse(backup_root.exists() and any(backup_root.iterdir()))

    def test_future_schema_is_rejected_before_backup_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_current_library_with_game(library)
            conn = sqlite3.connect(library)
            try:
                conn.execute(f"PRAGMA user_version={ACSDB_SCHEMA_VERSION + 1}")
                conn.commit()
            finally:
                conn.close()
            marked_future_bytes = library.read_bytes()

            with self.assertRaisesRegex(Version2UpgradeError, "newer than"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertEqual(library.read_bytes(), marked_future_bytes)
            conn = sqlite3.connect(library)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 7)
            finally:
                conn.close()
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_upgrade_module_delegates_d07_and_contains_no_schema_object_names(self) -> None:
        source = (Path(__file__).parents[1] / "acs" / "version2_upgrade.py").read_text(encoding="utf-8")
        self.assertIn("AcsDatabase._check_sqlite_integrity", source)
        for token in (
            "idx_positions_key_game_ply",
            "game_search_fold",
            "game_search_fold_dirty",
            "idx_games_search_date_key",
            "CREATE TABLE sources",
            "CREATE TABLE games",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
