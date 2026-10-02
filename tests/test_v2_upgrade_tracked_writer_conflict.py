from __future__ import annotations

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
    Version2UpgradeRecoveryError,
)


class _Crash(BaseException):
    pass


class V2UpgradeTrackedWriterConflictTests(unittest.TestCase):
    def _make_real_v1_library(self, path: Path) -> None:
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
                ("initial-v1.pgn", "pgn", "1" * 64, "2026-01-02T03:04:05+00:00"),
            )
            database.conn.commit()
        finally:
            database.conn.close()

    @staticmethod
    def _source_names(path: Path) -> list[str]:
        connection = sqlite3.connect(path)
        try:
            return [
                str(row[0])
                for row in connection.execute(
                    "SELECT source_name FROM sources ORDER BY id"
                ).fetchall()
            ]
        finally:
            connection.close()

    def test_post_snapshot_external_settings_write_survives_late_upgrade_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 10}), encoding="utf-8"
            )
            self._make_real_v1_library(root / "library.acsdb")
            external_bytes = (
                json.dumps({"language": "uk", "volume": 91}, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")

            def external_writer_and_late_failure(phase: str) -> None:
                if phase == "prepared":
                    settings.write_bytes(external_bytes)
                elif phase == "library-migrated":
                    raise RuntimeError("forced late failure")

            with self.assertRaises(Version2UpgradeError):
                Version2UpgradeCoordinator(
                    UserDataLayout(root),
                    phase_hook=external_writer_and_late_failure,
                ).run()

            self.assertEqual(settings.read_bytes(), external_bytes)

    def test_post_snapshot_external_library_write_survives_late_upgrade_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)

            def external_writer_and_late_failure(phase: str) -> None:
                if phase == "prepared":
                    connection = sqlite3.connect(library)
                    try:
                        connection.execute(
                            "INSERT INTO sources(source_name,source_format,sha256,imported_at) "
                            "VALUES(?,?,?,?)",
                            (
                                "external-v1.pgn",
                                "pgn",
                                "2" * 64,
                                "2026-08-31T11:45:00+00:00",
                            ),
                        )
                        connection.commit()
                    finally:
                        connection.close()
                elif phase == "library-migrated":
                    raise RuntimeError("forced late failure")

            with self.assertRaises(Version2UpgradeError):
                Version2UpgradeCoordinator(
                    UserDataLayout(root),
                    phase_hook=external_writer_and_late_failure,
                ).run()

            self.assertIn("external-v1.pgn", self._source_names(library))

    def test_interrupted_recovery_preserves_newer_external_tracked_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 20}), encoding="utf-8"
            )

            def crash_after_settings(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with self.assertRaises(_Crash):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash_after_settings
                ).run()

            external_bytes = (
                json.dumps({"language": "uk", "volume": 92}, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
            settings.write_bytes(external_bytes)

            with self.assertRaises(Version2UpgradeRecoveryError):
                Version2UpgradeCoordinator(UserDataLayout(root)).recover_interrupted()

            self.assertEqual(settings.read_bytes(), external_bytes)

    def test_interrupted_recovery_preserves_newer_external_tracked_library(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)

            def crash_after_library(phase: str) -> None:
                if phase == "library-migrated":
                    raise _Crash()

            with self.assertRaises(_Crash):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash_after_library
                ).run()

            with AcsDatabase(library) as database:
                self.assertEqual(database.verify_integrity(), ACSDB_SCHEMA_VERSION)
                database.add_source("external-v6.pgn", "pgn", "3" * 64)

            with self.assertRaises(Version2UpgradeRecoveryError):
                Version2UpgradeCoordinator(UserDataLayout(root)).recover_interrupted()

            with AcsDatabase(library) as reopened:
                self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
                names = [
                    str(row["source_name"])
                    for row in reopened.conn.execute(
                        "SELECT source_name FROM sources ORDER BY id"
                    ).fetchall()
                ]
            self.assertIn("external-v6.pgn", names)


if __name__ == "__main__":
    unittest.main()
