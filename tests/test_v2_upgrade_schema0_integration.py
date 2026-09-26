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


class Version2Schema0IntegrationTests(unittest.TestCase):
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
