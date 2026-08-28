import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.version2_upgrade import (
    UPGRADE_JOURNAL_SCHEMA_VERSION,
    UpgradeLimits,
    UserDataLayout,
    Version2UpgradeBusy,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    _UpgradeLock,
)


class _Crash(BaseException):
    pass


def _make_versioned_db(path: Path, version: int = 1) -> None:
    # Start from the real current schema, add durable user data, then reduce the
    # visible schema/version exactly the same way the D07 migration tests do.
    with AcsDatabase(path) as database:
        source_id = database.add_source("keep-source.pgn", "pgn")
        if version < ACSDB_SCHEMA_VERSION:
            if version < 3:
                database.conn.execute("DROP INDEX IF EXISTS idx_positions_key_game_ply")
            if version < 2:
                database.conn.execute("DROP TABLE IF EXISTS import_attempts")
            database.conn.execute(f"PRAGMA user_version={version}")
            database.conn.commit()
        assert source_id == 1


class Version2UpgradeTests(unittest.TestCase):
    def test_v1_like_settings_library_and_books_upgrade_and_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 55}),
                encoding="utf-8",
            )
            books = root / "books"
            books.mkdir()
            book = books / "lesson-one.txt"
            book.write_text("e4 e5\n", encoding="utf-8")
            library = root / "library.acsdb"
            _make_versioned_db(library, version=1)

            report = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertEqual(report.status, "upgraded")
            self.assertTrue(report.settings_migrated)
            self.assertTrue(report.library_migrated)
            self.assertEqual(book.read_text(encoding="utf-8"), "e4 e5\n")
            settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["schema_version"], 2)
            self.assertEqual(settings["values"]["language"], "en")
            self.assertEqual(settings["values"]["volume"], 55)
            with AcsDatabase(library) as reopened:
                self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(reopened.get_source(1)["source_name"], "keep-source.pgn")
            journal = json.loads((root / ".v2-upgrade-state.json").read_text(encoding="utf-8"))
            self.assertEqual(journal["schema_version"], UPGRADE_JOURNAL_SCHEMA_VERSION)
            self.assertEqual(journal["phase"], "committed")
            self.assertNotIn(str(root), json.dumps(journal))
            backup = root.parent / "AccessibleChess.upgrade-backups" / report.backup_name
            self.assertTrue((backup / "manifest.json").is_file())
            self.assertTrue((backup / "data" / "settings.json").is_file())
            self.assertTrue((backup / "data" / "library.acsdb").is_file())
            self.assertTrue((backup / "data" / "books" / "lesson-one.txt").is_file())

            second = Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertEqual(second.status, "already_current")
            self.assertEqual(second.backup_name, report.backup_name)
            self.assertEqual(
                len([p for p in (root.parent / "AccessibleChess.upgrade-backups").iterdir() if p.is_dir()]),
                1,
            )

    def test_interrupted_after_settings_write_recovers_then_retries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            original = json.dumps({"language": "en", "volume": 34})
            (root / "settings.json").write_text(original, encoding="utf-8")
            (root / "books").mkdir()
            book = root / "books" / "keep.txt"
            book.write_bytes(b"keep")

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with self.assertRaises(_Crash):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash
                ).run()

            changed = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(changed["schema_version"], 2)
            journal = json.loads((root / ".v2-upgrade-state.json").read_text(encoding="utf-8"))
            self.assertEqual(journal["phase"], "migrating")

            recovered = Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertTrue(recovered.recovered_interrupted_upgrade)
            self.assertEqual(recovered.status, "upgraded")
            self.assertEqual(book.read_bytes(), b"keep")
            migrated = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated["values"]["volume"], 34)

    def test_failed_library_migration_restores_original_settings_and_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings_path = root / "settings.json"
            settings_raw = json.dumps({"language": "en", "volume": 66})
            settings_path.write_text(settings_raw, encoding="utf-8")
            library = root / "library.acsdb"
            _make_versioned_db(library, version=1)

            class FailingDatabase:
                def __init__(self, path):
                    conn = sqlite3.connect(path)
                    conn.execute("PRAGMA user_version=2")
                    conn.execute(
                        "INSERT INTO sources(source_name,source_format,sha256,imported_at) "
                        "VALUES('partial','pgn',NULL,'2026-08-28T00:00:00+00:00')"
                    )
                    conn.commit()
                    conn.close()
                    raise RuntimeError("synthetic migration failure")

            with self.assertRaisesRegex(
                Version2UpgradeError, "original user data was restored"
            ):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), database_factory=FailingDatabase
                ).run()

            self.assertEqual(settings_path.read_text(encoding="utf-8"), settings_raw)
            conn = sqlite3.connect(library)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(
                    conn.execute("SELECT source_name FROM sources ORDER BY id").fetchall(),
                    [("keep-source.pgn",)],
                )
            finally:
                conn.close()
            journal = json.loads((root / ".v2-upgrade-state.json").read_text(encoding="utf-8"))
            self.assertEqual(journal["phase"], "rolled_back")
            self.assertNotIn("synthetic migration failure", json.dumps(journal))

    def test_unversioned_legacy_library_is_blocked_without_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            conn = sqlite3.connect(library)
            conn.execute(
                "CREATE TABLE games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)"
            )
            conn.execute(
                "INSERT INTO games(title,pgn,created_at) "
                "VALUES('legacy','1. e4 e5 *','2026-08-28T00:00:00')"
            )
            conn.commit()
            conn.close()

            with self.assertRaisesRegex(
                Version2UpgradeError, "explicit D07 migration"
            ):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

            conn = sqlite3.connect(library)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertEqual(
                    conn.execute("SELECT title,pgn FROM games").fetchone(),
                    ("legacy", "1. e4 e5 *"),
                )
            finally:
                conn.close()
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_corrupt_settings_fail_closed_without_default_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text("{bad-json", encoding="utf-8")
            with self.assertRaisesRegex(Version2UpgradeError, "settings validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertEqual(settings.read_text(encoding="utf-8"), "{bad-json")

    def test_backup_rejects_symlink_and_windows_case_collision(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink support unavailable")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
            target = root / "target.txt"
            target.write_text("private", encoding="utf-8")
            link = root / "book-link.txt"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(Version2UpgradeError, "symlink or reparse"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
            (root / "Books").mkdir()
            try:
                (root / "books").mkdir()
            except FileExistsError:
                self.skipTest("case-insensitive filesystem")
            (root / "Books" / "a.txt").write_text("A", encoding="utf-8")
            (root / "books" / "a.txt").write_text("B", encoding="utf-8")
            with self.assertRaisesRegex(Version2UpgradeError, "case-folding"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

    def test_backup_limits_fail_before_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            raw = json.dumps({"language": "en"})
            settings.write_text(raw, encoding="utf-8")
            (root / "large.bin").write_bytes(b"x" * 20)
            with self.assertRaisesRegex(Version2UpgradeError, "byte limit"):
                Version2UpgradeCoordinator(
                    UserDataLayout(root),
                    limits=UpgradeLimits(max_files=10, max_bytes=10),
                ).run()
            self.assertEqual(settings.read_text(encoding="utf-8"), raw)
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_future_library_schema_fails_closed_without_backup_or_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            _make_versioned_db(library, version=ACSDB_SCHEMA_VERSION + 1)
            with self.assertRaisesRegex(Version2UpgradeError, "newer than"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()
            conn = sqlite3.connect(library)
            try:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    ACSDB_SCHEMA_VERSION + 1,
                )
                self.assertEqual(
                    conn.execute("SELECT source_name FROM sources").fetchone()[0],
                    "keep-source.pgn",
                )
            finally:
                conn.close()
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_active_sqlite_writer_blocks_pre_migration_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
            library = root / "library.acsdb"
            _make_versioned_db(library, version=1)
            writer = sqlite3.connect(library, timeout=0.0)
            writer.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaisesRegex(
                    Version2UpgradeError, "library backup could not be validated"
                ):
                    Version2UpgradeCoordinator(UserDataLayout(root)).run()
            finally:
                writer.rollback()
                writer.close()
            self.assertEqual(
                json.loads((root / "settings.json").read_text(encoding="utf-8")),
                {"language": "en"},
            )
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_os_lock_rejects_parallel_upgrade_and_stale_file_is_reusable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            lock = root / ".v2-upgrade.lock"
            with _UpgradeLock(lock):
                with self.assertRaises(Version2UpgradeBusy):
                    with _UpgradeLock(lock):
                        pass
            with _UpgradeLock(lock):
                pass

    def test_environment_layout_matches_existing_stage1_user_root(self):
        layout = UserDataLayout.from_environment(
            environ={"LOCALAPPDATA": r"C:\Users\Blind\AppData\Local"},
            home=Path("/unused"),
        )
        self.assertEqual(layout.root.name, "AccessibleChess")
        self.assertEqual(layout.settings_path.name, "settings.json")
        self.assertEqual(layout.library_path.name, "library.acsdb")


if __name__ == "__main__":
    unittest.main()
