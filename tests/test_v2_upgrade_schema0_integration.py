import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from acs import version2_upgrade as upgrade_module
from acs import version2_upgrade_base as upgrade_base
from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.version2_upgrade import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
)


def _make_legacy(path: Path, *, pgn: str = "1. e4 e5 *") -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)"
        )
        connection.execute(
            "INSERT INTO games(title,pgn,created_at) VALUES(?,?,?)",
            ("legacy-source.pgn", pgn, "2026-08-28T00:00:00"),
        )
        connection.commit()
    finally:
        connection.close()


def _legacy_row(path: Path):
    connection = sqlite3.connect(path)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        row = connection.execute(
            "SELECT id,title,pgn,created_at FROM games ORDER BY id"
        ).fetchone()
        return version, row
    finally:
        connection.close()


def _legacy_rows(path: Path):
    connection = sqlite3.connect(path)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        rows = connection.execute(
            "SELECT id,title,pgn,created_at FROM games ORDER BY id"
        ).fetchall()
        return version, rows
    finally:
        connection.close()


def _leave_committed_wal_after_crash(path: Path) -> None:
    script = r'''
import os
import sqlite3
import sys

path = sys.argv[1]
connection = sqlite3.connect(path)
mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).casefold()
if mode != "wal":
    raise SystemExit("WAL mode unavailable")
connection.execute("PRAGMA wal_autocheckpoint=0")
connection.execute(
    "INSERT INTO games(title,pgn,created_at) VALUES(?,?,?)",
    ("wal-only-source.pgn", "1. d4 d5 2. c4 *", "2026-09-26T00:00:00"),
)
connection.commit()
# Model a process crash: do not close/checkpoint the SQLite connection.
os._exit(0)
'''
    subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=True,
        timeout=15,
    )


class Version2Schema0IntegrationTests(unittest.TestCase):
    def test_import_does_not_persistently_mutate_base_schema_authority(self):
        self.assertIsNot(
            upgrade_base._canonical_library_schema,
            upgrade_module._canonical_library_schema,
        )

    def test_schema_authority_is_restored_after_upgrade_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            _make_legacy(library)
            original_base_authority = upgrade_base._canonical_library_schema

            Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertIs(
                upgrade_base._canonical_library_schema,
                original_base_authority,
            )

    def test_exact_shipped_schema0_upgrades_through_d07_and_existing_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            _make_legacy(library)
            original = _legacy_row(library)

            report = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertEqual(report.status, "upgraded")
            self.assertTrue(report.library_migrated)
            with AcsDatabase(library) as reopened:
                self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                source = reopened.get_source(1)
                self.assertEqual(source["source_name"], "legacy-source.pgn")
                self.assertEqual(source["source_format"], "pgn")

            backup = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / report.backup_name
            )
            manifest = json.loads(
                (backup / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["library_schema_before"], 0)
            self.assertEqual(_legacy_row(backup / "data" / "library.acsdb"), original)
            journal = json.loads(
                (root / ".v2-upgrade-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(journal["phase"], "committed")

    def test_committed_schema0_wal_rows_survive_backup_and_upgrade(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            _make_legacy(library)
            _leave_committed_wal_after_crash(library)

            wal = Path(str(library) + "-wal")
            self.assertTrue(wal.is_file())
            before = _legacy_rows(library)
            self.assertEqual(len(before[1]), 2)

            report = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertEqual(report.status, "upgraded")
            self.assertTrue(report.library_migrated)
            with AcsDatabase(library) as reopened:
                self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                names = [
                    str(row[0])
                    for row in reopened.conn.execute(
                        "SELECT source_name FROM sources ORDER BY id"
                    ).fetchall()
                ]
                self.assertEqual(names, ["legacy-source.pgn", "wal-only-source.pgn"])
                self.assertEqual(
                    int(reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                    2,
                )

            backup = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / report.backup_name
            )
            manifest = json.loads(
                (backup / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["library_schema_before"], 0)
            self.assertEqual(_legacy_rows(backup / "data" / "library.acsdb"), before)

    def test_arbitrary_unversioned_sqlite_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            connection = sqlite3.connect(library)
            try:
                connection.execute("CREATE TABLE not_accessible_chess(value TEXT)")
                connection.execute(
                    "INSERT INTO not_accessible_chess(value) VALUES('keep-me')"
                )
                connection.commit()
            finally:
                connection.close()
            before = library.read_bytes()

            with self.assertRaisesRegex(Version2UpgradeError, "library validation failed"):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertEqual(library.read_bytes(), before)
            connection = sqlite3.connect(library)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT value FROM not_accessible_chess"
                    ).fetchone()[0],
                    "keep-me",
                )
            finally:
                connection.close()
            self.assertFalse((root / ".v2-upgrade-state.json").exists())

    def test_legacy_pgn_conversion_failure_rolls_back_exact_schema0_library(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            _make_legacy(library, pgn="1. e9 *")
            before = _legacy_row(library)

            with self.assertRaisesRegex(
                Version2UpgradeError, "original user data was restored"
            ):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertEqual(_legacy_row(library), before)
            journal = json.loads(
                (root / ".v2-upgrade-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(journal["phase"], "rolled_back")
            self.assertNotIn("e9", json.dumps(journal))


if __name__ == "__main__":
    unittest.main()
