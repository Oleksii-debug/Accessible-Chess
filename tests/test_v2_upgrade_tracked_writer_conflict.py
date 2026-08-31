from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase
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
                (
                    "version1-library.pgn",
                    "pgn",
                    "1" * 64,
                    "2026-01-02T03:04:05+00:00",
                ),
            )
            database.conn.commit()
        finally:
            database.conn.close()

    def test_post_snapshot_settings_writer_aborts_without_rewriting_writer_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 10}),
                encoding="utf-8",
            )
            external = b'{"language":"uk","volume":91}'

            def writer(phase: str) -> None:
                if phase == "prepared":
                    settings.write_bytes(external)

            with self.assertRaises(Version2UpgradeError):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=writer
                ).run()

            self.assertEqual(settings.read_bytes(), external)

    def test_post_publication_settings_writer_survives_failed_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 20}),
                encoding="utf-8",
            )
            external = b'{"language":"uk","volume":92}'

            def writer(phase: str) -> None:
                if phase == "settings-migrated":
                    settings.write_bytes(external)

            with self.assertRaises(Version2UpgradeError):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=writer
                ).run()

            self.assertEqual(settings.read_bytes(), external)

    def test_post_snapshot_library_writer_aborts_without_rewriting_writer_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)

            def writer(phase: str) -> None:
                if phase != "prepared":
                    return
                connection = sqlite3.connect(library)
                try:
                    connection.execute(
                        "INSERT INTO sources(source_name,source_format,sha256,imported_at) "
                        "VALUES(?,?,?,?)",
                        (
                            "external-after-backup.pgn",
                            "pgn",
                            "2" * 64,
                            "2026-08-31T11:44:00+00:00",
                        ),
                    )
                    connection.commit()
                finally:
                    connection.close()

            with self.assertRaises(Version2UpgradeError):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=writer
                ).run()

            connection = sqlite3.connect(library)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0], 1
                )
                names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT source_name FROM sources"
                    ).fetchall()
                }
            finally:
                connection.close()
            self.assertIn("external-after-backup.pgn", names)

    def test_post_publication_library_writer_is_not_silently_committed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)

            def writer(phase: str) -> None:
                if phase != "library-migrated":
                    return
                connection = sqlite3.connect(library)
                try:
                    connection.execute(
                        "INSERT INTO sources(source_name,source_format,sha256,imported_at) "
                        "VALUES(?,?,?,?)",
                        (
                            "external-after-migration.pgn",
                            "pgn",
                            "3" * 64,
                            "2026-08-31T11:44:30+00:00",
                        ),
                    )
                    connection.commit()
                finally:
                    connection.close()

            with self.assertRaises(Version2UpgradeError):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=writer
                ).run()

            connection = sqlite3.connect(library)
            try:
                names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT source_name FROM sources"
                    ).fetchall()
                }
            finally:
                connection.close()
            self.assertIn("external-after-migration.pgn", names)

    def test_interrupted_recovery_preserves_post_crash_settings_writer_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 30}),
                encoding="utf-8",
            )

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with self.assertRaises(_Crash):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash
                ).run()

            external = b'{"language":"uk","volume":93}'
            settings.write_bytes(external)

            with self.assertRaises(Version2UpgradeRecoveryError):
                Version2UpgradeCoordinator(UserDataLayout(root)).recover_interrupted()

            self.assertEqual(settings.read_bytes(), external)


if __name__ == "__main__":
    unittest.main()
