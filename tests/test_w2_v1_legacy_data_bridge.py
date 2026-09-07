from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase, ACSDB_SCHEMA_VERSION
from acs.legacy_v1_data_bridge import LegacyV1BridgeError, bridge_legacy_v1_data
from acs.version2_upgrade import UserDataLayout, Version2UpgradeCoordinator


class LegacyV1DataBridgeTests(unittest.TestCase):
    def _make_legacy_library(self, path: Path) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)"
            )
            connection.execute(
                "INSERT INTO games(title,pgn,created_at) VALUES(?,?,?)",
                (
                    "legacy-game",
                    '[Event "Legacy"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n',
                    "2026-08-20T10:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def test_exact_exe_data_topology_materializes_without_mutating_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "installed"
            legacy_data = exe / "data"
            legacy_data.mkdir(parents=True)
            settings = legacy_data / "settings.json"
            settings.write_text(json.dumps({"language": "en", "volume": 25}), encoding="utf-8")
            library = legacy_data / "library.acsdb"
            self._make_legacy_library(library)
            settings_before = settings.read_bytes()
            library_before = library.read_bytes()

            layout = UserDataLayout(root / "localappdata" / "AccessibleChess")
            report = bridge_legacy_v1_data(exe, layout)

            self.assertEqual(report.status, "materialized")
            self.assertTrue(report.settings_copied)
            self.assertTrue(report.library_converted)
            self.assertEqual(report.library_games, 1)
            self.assertEqual(settings.read_bytes(), settings_before)
            self.assertEqual(library.read_bytes(), library_before)
            self.assertEqual(layout.settings_path.read_bytes(), settings_before)
            database = AcsDatabase(layout.library_path)
            try:
                self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)
            finally:
                database.close()

    def test_bridge_is_idempotent_after_materialized_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "installed"
            legacy_data = exe / "data"
            legacy_data.mkdir(parents=True)
            (legacy_data / "settings.json").write_text(json.dumps({"volume": 30}), encoding="utf-8")
            self._make_legacy_library(legacy_data / "library.acsdb")
            layout = UserDataLayout(root / "canonical")

            first = bridge_legacy_v1_data(exe, layout)
            second = bridge_legacy_v1_data(exe, layout)

            self.assertEqual(first.status, "materialized")
            self.assertEqual(second.status, "already_materialized")
            self.assertFalse(second.settings_copied)
            self.assertFalse(second.library_converted)
            self.assertEqual(second.library_games, 1)

    def test_existing_different_canonical_settings_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "installed"
            legacy_data = exe / "data"
            legacy_data.mkdir(parents=True)
            (legacy_data / "settings.json").write_text(json.dumps({"volume": 30}), encoding="utf-8")
            layout = UserDataLayout(root / "canonical")
            layout.root.mkdir(parents=True)
            layout.settings_path.write_text(json.dumps({"volume": 90}), encoding="utf-8")

            with self.assertRaises(LegacyV1BridgeError):
                bridge_legacy_v1_data(exe, layout)
            self.assertIn("90", layout.settings_path.read_text(encoding="utf-8"))

    def test_existing_canonical_library_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "installed"
            legacy_data = exe / "data"
            legacy_data.mkdir(parents=True)
            legacy = legacy_data / "library.acsdb"
            self._make_legacy_library(legacy)
            layout = UserDataLayout(root / "canonical")
            layout.root.mkdir(parents=True)
            existing = AcsDatabase(layout.library_path)
            existing.close()
            before = layout.library_path.read_bytes()

            with self.assertRaises(LegacyV1BridgeError):
                bridge_legacy_v1_data(exe, layout)
            self.assertEqual(layout.library_path.read_bytes(), before)

    def test_library_conflict_is_detected_before_settings_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "installed"
            legacy_data = exe / "data"
            legacy_data.mkdir(parents=True)
            (legacy_data / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 42}), encoding="utf-8"
            )
            self._make_legacy_library(legacy_data / "library.acsdb")
            layout = UserDataLayout(root / "canonical")
            layout.root.mkdir(parents=True)
            existing = AcsDatabase(layout.library_path)
            existing.close()
            before_library = layout.library_path.read_bytes()

            with self.assertRaises(LegacyV1BridgeError):
                bridge_legacy_v1_data(exe, layout)

            self.assertFalse(
                layout.settings_path.exists(),
                "a Library conflict must be detected before settings are materialized",
            )
            self.assertEqual(layout.library_path.read_bytes(), before_library)
            self.assertFalse((layout.root / ".v1-legacy-bridge.json").exists())

    def test_bridge_then_existing_upgrade_coordinator_migrates_legacy_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "installed"
            legacy_data = exe / "data"
            legacy_data.mkdir(parents=True)
            (legacy_data / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 31}), encoding="utf-8"
            )
            layout = UserDataLayout(root / "canonical")

            bridge_legacy_v1_data(exe, layout)
            result = Version2UpgradeCoordinator(layout).run()

            self.assertIn(result.status, {"upgraded", "already_current"})
            raw = json.loads(layout.settings_path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], 2)
            self.assertEqual(raw["values"]["volume"], 31)
            self.assertTrue((layout.root / ".v1-legacy-bridge.json").exists())

    def test_no_legacy_files_is_clean_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = bridge_legacy_v1_data(root / "installed", UserDataLayout(root / "canonical"))
            self.assertEqual(report.status, "no_legacy_data")
            self.assertFalse((root / "canonical").exists())


if __name__ == "__main__":
    unittest.main()
