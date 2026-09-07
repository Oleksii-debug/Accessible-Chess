from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.settings import Settings, SettingsError
import acs.version2_upgrade as upgrade_module
from acs.version2_upgrade import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
)


class V2UpgradePublishRaceAuditTests(unittest.TestCase):
    """Evidence-only oracle for writes racing after the owner's final re-auth."""

    def _make_real_v1_library(self, path: Path) -> None:
        database = object.__new__(AcsDatabase)
        database.path = str(path)
        database.conn = sqlite3.connect(path)
        try:
            database.conn.row_factory = sqlite3.Row
            database.conn.execute("PRAGMA foreign_keys = ON")
            database._migrate_to_v1()
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

    def test_settings_writer_after_final_reauth_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 10}), encoding="utf-8"
            )
            external_bytes = (
                json.dumps({"language": "uk", "volume": 97}, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")

            real_atomic_bytes = upgrade_module._atomic_bytes
            injected = False

            def race_atomic_bytes(path: Path, payload: bytes) -> None:
                nonlocal injected
                if Path(path) == settings and not injected:
                    injected = True
                    settings.write_bytes(external_bytes)
                real_atomic_bytes(path, payload)

            def fail_after_owner_publication(phase: str) -> None:
                if phase == "settings-migrated":
                    raise RuntimeError("forced late failure after publication")

            with mock.patch.object(
                upgrade_module, "_atomic_bytes", side_effect=race_atomic_bytes
            ):
                with self.assertRaises(Version2UpgradeError):
                    Version2UpgradeCoordinator(
                        UserDataLayout(root), phase_hook=fail_after_owner_publication
                    ).run()

            self.assertTrue(injected, "race injection did not reach settings publication")
            self.assertEqual(
                settings.read_bytes(),
                external_bytes,
                "external settings writer was silently overwritten after final re-auth",
            )

    def test_canonical_settings_save_cannot_replace_during_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 10}), encoding="utf-8"
            )

            real_atomic_bytes = upgrade_module._atomic_bytes
            attempted = False
            blocked = False

            def race_atomic_bytes(path: Path, payload: bytes) -> None:
                nonlocal attempted, blocked
                if Path(path) == settings and not attempted:
                    attempted = True
                    external = Settings(settings)
                    try:
                        # Settings.set() exercises the real canonical save path:
                        # write settings.json.tmp then atomically replace pathname.
                        external.set("volume", 97)
                    except SettingsError:
                        blocked = True
                    else:
                        self.fail(
                            "canonical Settings.save replaced settings during active upgrade"
                        )
                real_atomic_bytes(path, payload)

            with mock.patch.object(
                upgrade_module, "_atomic_bytes", side_effect=race_atomic_bytes
            ):
                report = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertTrue(
                attempted,
                "canonical writer injection did not reach final settings publication",
            )
            self.assertTrue(
                blocked,
                "canonical Settings.save did not fail closed on the active upgrade lock",
            )
            self.assertEqual(report.status, "upgraded")
            persisted = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(persisted["schema_version"], 2)
            self.assertEqual(persisted["values"]["volume"], 10)

            # The lock is only a serialization boundary. Once the upgrade is
            # complete, the same canonical writer can retry and persist normally.
            retry = Settings(settings)
            retry.set("volume", 97)
            self.assertEqual(Settings(settings).get("volume"), 97)

    def test_library_writer_after_final_reauth_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)

            real_replace = upgrade_module.os.replace
            injected = False

            def race_replace(source: object, destination: object) -> None:
                nonlocal injected
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    destination_path == library
                    and ".library-publish-" in source_path.name
                    and not injected
                ):
                    injected = True
                    connection = sqlite3.connect(library)
                    try:
                        connection.execute(
                            "INSERT INTO sources(source_name,source_format,sha256,imported_at) "
                            "VALUES(?,?,?,?)",
                            (
                                "external-race-v1.pgn",
                                "pgn",
                                "9" * 64,
                                "2026-09-01T13:00:00+00:00",
                            ),
                        )
                        connection.commit()
                    finally:
                        connection.close()
                real_replace(source, destination)

            def fail_after_owner_publication(phase: str) -> None:
                if phase == "library-migrated":
                    raise RuntimeError("forced late failure after publication")

            with mock.patch.object(
                upgrade_module.os, "replace", side_effect=race_replace
            ):
                with self.assertRaises(Version2UpgradeError):
                    Version2UpgradeCoordinator(
                        UserDataLayout(root), phase_hook=fail_after_owner_publication
                    ).run()

            self.assertTrue(injected, "race injection did not reach library publication")
            self.assertIn(
                "external-race-v1.pgn",
                self._source_names(library),
                "external SQLite writer was silently overwritten after final re-auth",
            )


if __name__ == "__main__":
    unittest.main()
