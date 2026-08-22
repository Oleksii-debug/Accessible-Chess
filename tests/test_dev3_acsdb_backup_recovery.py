import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase


PGN = '''[Event "Backup"]
[Site "Uzhhorod"]
[Date "2026.08.22"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]
[ECO "C20"]
[Opening "King's Pawn Game"]

1. e4 e5 2. Nf3 Nc6 1-0
'''

FEN = "8/8/8/8/8/8/8/8 w - - 0 1"


class Dev3AcsdbBackupRecoveryTests(unittest.TestCase):
    def _populate(self, path: Path) -> tuple[int, int]:
        with AcsDatabase(path) as db:
            report = db.import_pgn_text(PGN, "backup-source.pgn")
            db.record_position(report.game_ids[0], 4, FEN)
            return report.source_id, report.game_ids[0]

    def test_consistent_backup_from_wal_database_preserves_data_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            backup = root / "backup.acsdb"
            source_id, game_id = self._populate(live)

            with AcsDatabase(live) as db:
                created = db.backup_to(backup)
                self.assertEqual(created, backup)
                self.assertTrue(backup.is_file())

            with AcsDatabase(backup) as restored:
                self.assertEqual(restored.schema_version, ACSDB_SCHEMA_VERSION)
                game = restored.get_game(game_id)
                source = restored.get_source(source_id)
                self.assertIsNotNone(game)
                self.assertIsNotNone(source)
                self.assertEqual(source["source_name"], "backup-source.pgn")
                self.assertEqual(restored.search_position(FEN)[0]["id"], game_id)
                attempts = restored.list_import_attempts(limit=10)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0]["source_id"], source_id)

    def test_backup_refuses_live_path_and_protects_existing_destination_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            backup = root / "backup.acsdb"
            self._populate(live)
            backup.write_bytes(b"sentinel")

            with AcsDatabase(live) as db:
                with self.assertRaises(ValueError):
                    db.backup_to(live)
                with self.assertRaises(FileExistsError):
                    db.backup_to(backup)
                self.assertEqual(backup.read_bytes(), b"sentinel")
                db.backup_to(backup, overwrite=True)

            with AcsDatabase(backup) as reopened:
                self.assertEqual(len(reopened.search_games(limit=10)), 1)

    def test_overwrite_flags_reject_coercive_scalars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            backup = root / "backup.acsdb"
            self._populate(live)

            with AcsDatabase(live) as db:
                for bad in (1, 0, "yes", None):
                    with self.subTest(api="backup", value=bad):
                        with self.assertRaises(TypeError):
                            db.backup_to(backup, overwrite=bad)

            for bad in (1, 0, "yes", None):
                with self.subTest(api="restore", value=bad):
                    with self.assertRaises(TypeError):
                        AcsDatabase.restore_backup(backup, root / "restored.acsdb", overwrite=bad)

    def test_restore_valid_backup_is_atomic_and_preserves_source_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            backup = root / "backup.acsdb"
            restored_path = root / "restored.acsdb"
            _source_id, game_id = self._populate(live)

            with AcsDatabase(live) as db:
                db.backup_to(backup)

            live_before = live.read_bytes()
            result = AcsDatabase.restore_backup(backup, restored_path)
            self.assertEqual(result, restored_path)
            self.assertEqual(live.read_bytes(), live_before)

            with AcsDatabase(restored_path) as restored:
                self.assertEqual(restored.get_game(game_id)["event"], "Backup")
                self.assertEqual(restored.search_position(FEN)[0]["matched_ply"], 4)

    def test_corrupt_backup_fails_closed_without_overwriting_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "corrupt.acsdb"
            destination = root / "destination.acsdb"
            backup.write_bytes(b"not a sqlite database")
            destination.write_bytes(b"keep-me")

            with self.assertRaises(RuntimeError):
                AcsDatabase.restore_backup(backup, destination, overwrite=True)
            self.assertEqual(destination.read_bytes(), b"keep-me")
            leftovers = [
                path for path in root.iterdir()
                if path.name.startswith(f".{destination.name}.") and path.suffix == ".tmp"
            ]
            self.assertEqual(leftovers, [])

    def test_future_schema_backup_is_rejected_before_destination_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "future.acsdb"
            destination = root / "destination.acsdb"
            destination.write_bytes(b"keep-me")

            conn = sqlite3.connect(backup)
            try:
                conn.execute(f"PRAGMA user_version = {ACSDB_SCHEMA_VERSION + 1}")
                conn.commit()
            finally:
                conn.close()

            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                AcsDatabase.restore_backup(backup, destination, overwrite=True)
            self.assertEqual(destination.read_bytes(), b"keep-me")

    def test_restore_guards_missing_same_path_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            backup = root / "backup.acsdb"
            destination = root / "destination.acsdb"
            self._populate(live)
            with AcsDatabase(live) as db:
                db.backup_to(backup)

            with self.assertRaises(FileNotFoundError):
                AcsDatabase.restore_backup(root / "missing.acsdb", destination)
            with self.assertRaises(ValueError):
                AcsDatabase.restore_backup(backup, backup)

            destination.write_bytes(b"sentinel")
            with self.assertRaises(FileExistsError):
                AcsDatabase.restore_backup(backup, destination)
            self.assertEqual(destination.read_bytes(), b"sentinel")

    def test_empty_sqlite_database_is_not_accepted_as_acsdb_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "foreign.sqlite"
            destination = root / "destination.acsdb"
            sqlite3.connect(backup).close()
            destination.write_bytes(b"keep-me")

            with self.assertRaisesRegex(RuntimeError, "supported ACSDB"):
                AcsDatabase.restore_backup(backup, destination, overwrite=True)
            self.assertEqual(destination.read_bytes(), b"keep-me")

    def test_foreign_sqlite_with_forged_supported_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "foreign.sqlite"
            destination = root / "destination.acsdb"
            destination.write_bytes(b"keep-me")

            conn = sqlite3.connect(backup)
            try:
                conn.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY, payload TEXT)")
                conn.execute(f"PRAGMA user_version = {ACSDB_SCHEMA_VERSION}")
                conn.commit()
            finally:
                conn.close()

            with self.assertRaisesRegex(RuntimeError, "schema identity"):
                AcsDatabase.restore_backup(backup, destination, overwrite=True)
            self.assertEqual(destination.read_bytes(), b"keep-me")

    def test_current_schema_missing_required_position_index_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            backup = root / "backup.acsdb"
            destination = root / "destination.acsdb"
            self._populate(live)
            with AcsDatabase(live) as db:
                db.backup_to(backup)

            conn = sqlite3.connect(backup)
            try:
                conn.execute("DROP INDEX idx_positions_key_game_ply")
                conn.commit()
            finally:
                conn.close()
            destination.write_bytes(b"keep-me")

            with self.assertRaisesRegex(RuntimeError, "schema identity"):
                AcsDatabase.restore_backup(backup, destination, overwrite=True)
            self.assertEqual(destination.read_bytes(), b"keep-me")

    def test_foreign_key_corruption_is_rejected_even_when_quick_check_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            backup = root / "backup.acsdb"
            destination = root / "destination.acsdb"
            source_id, _game_id = self._populate(live)
            with AcsDatabase(live) as db:
                db.backup_to(backup)

            conn = sqlite3.connect(backup)
            try:
                self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
                conn.commit()
                self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertIsNotNone(conn.execute("PRAGMA foreign_key_check").fetchone())
            finally:
                conn.close()
            destination.write_bytes(b"keep-me")

            with self.assertRaisesRegex(RuntimeError, "foreign-key integrity"):
                AcsDatabase.restore_backup(backup, destination, overwrite=True)
            self.assertEqual(destination.read_bytes(), b"keep-me")

    def test_supported_legacy_v1_and_v2_backups_restore_and_migrate_forward(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.acsdb"
            _source_id, game_id = self._populate(live)

            for version in (1, 2):
                with self.subTest(version=version):
                    backup = root / f"legacy-v{version}.acsdb"
                    restored_path = root / f"restored-v{version}.acsdb"
                    with AcsDatabase(live) as db:
                        db.backup_to(backup)

                    conn = sqlite3.connect(backup)
                    try:
                        conn.execute("DROP INDEX idx_positions_key_game_ply")
                        if version == 1:
                            conn.execute("DROP TABLE import_attempts")
                        conn.execute(f"PRAGMA user_version = {version}")
                        conn.commit()
                    finally:
                        conn.close()

                    AcsDatabase.restore_backup(backup, restored_path)
                    with AcsDatabase(restored_path) as restored:
                        self.assertEqual(restored.schema_version, ACSDB_SCHEMA_VERSION)
                        self.assertEqual(restored.get_game(game_id)["event"], "Backup")
                        self.assertEqual(restored.search_position(FEN)[0]["matched_ply"], 4)


if __name__ == "__main__":
    unittest.main()
