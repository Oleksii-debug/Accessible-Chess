from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION
from acs.settings import Settings
from acs.v1_runtime_bridge import (
    V1RuntimeBridgeCoordinator,
    V1RuntimeBridgeError,
)
from acs.version2_upgrade import UserDataLayout


_VALID_PGN = """[Event "Legacy"]
[Site "?"]
[Date "2026.01.01"]
[Round "?"]
[White "White"]
[Black "Black"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
"""


class V1RuntimeBridgeTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, UserDataLayout]:
        install = root / "installed"
        data = install / "data"
        data.mkdir(parents=True)
        executable = install / "AccessibleChess.exe"
        executable.write_bytes(b"MZ-test-fixture")

        settings = data / "settings.json"
        settings.write_text(
            json.dumps({"language": "en", "volume": 22}) + "\n",
            encoding="utf-8",
        )

        library = data / "library.acsdb"
        connection = sqlite3.connect(library)
        try:
            connection.execute(
                """CREATE TABLE games(
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    pgn TEXT,
                    created_at TEXT
                )"""
            )
            connection.execute(
                "INSERT INTO games(title,pgn,created_at) VALUES(?,?,?)",
                ("legacy-one.pgn", _VALID_PGN, "2026-01-02T03:04:05+00:00"),
            )
            connection.commit()
        finally:
            connection.close()

        layout = UserDataLayout(root / "localappdata" / "AccessibleChess")
        return executable, data, layout

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_exact_shipped_runtime_topology_migrates_without_touching_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = self._sha(legacy / "settings.json")
            library_before = self._sha(legacy / "library.acsdb")

            report = V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertEqual(report.status, "migrated")
            self.assertTrue(report.settings_imported)
            self.assertTrue(report.library_imported)
            self.assertFalse(report.recovered)
            self.assertIsNotNone(report.library_result)
            assert report.library_result is not None
            self.assertEqual(report.library_result.legacy_rows, 1)
            self.assertEqual(report.library_result.games, 1)

            current_settings = json.loads(
                layout.settings_path.read_text(encoding="utf-8")
            )
            self.assertEqual(current_settings["schema_version"], 2)
            self.assertEqual(current_settings["values"]["language"], "en")
            self.assertEqual(current_settings["values"]["volume"], 22)

            connection = sqlite3.connect(layout.library_path)
            try:
                self.assertEqual(
                    int(connection.execute("PRAGMA user_version").fetchone()[0]),
                    ACSDB_SCHEMA_VERSION,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                    1,
                )
            finally:
                connection.close()

            self.assertEqual(self._sha(legacy / "settings.json"), settings_before)
            self.assertEqual(self._sha(legacy / "library.acsdb"), library_before)
            backup = layout.backup_root / report.backup_name / "legacy"
            self.assertTrue((backup / "settings.json").is_file())
            self.assertTrue((backup / "library.acsdb").is_file())

            again = V1RuntimeBridgeCoordinator(layout, executable).run()
            self.assertEqual(again.status, "already_migrated")
            self.assertEqual(again.bridge_id, report.bridge_id)

    def test_no_legacy_data_is_a_clean_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install = root / "installed"
            install.mkdir()
            executable = install / "AccessibleChess.exe"
            executable.write_bytes(b"MZ-test")
            layout = UserDataLayout(root / "localappdata" / "AccessibleChess")

            report = V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertEqual(report.status, "no_legacy_data")
            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())

    def test_existing_v2_target_fails_closed_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, _legacy, layout = self._fixture(root)
            layout.root.mkdir(parents=True)
            layout.settings_path.write_text("current-v2-user-data\n", encoding="utf-8")
            before = layout.settings_path.read_bytes()

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertEqual(layout.settings_path.read_bytes(), before)
            self.assertFalse(layout.library_path.exists())

    def test_library_collision_is_detected_before_settings_publication(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, _legacy, layout = self._fixture(root)
            layout.root.mkdir(parents=True)
            connection = sqlite3.connect(layout.library_path)
            try:
                connection.execute("CREATE TABLE keep_me(value TEXT)")
                connection.execute("INSERT INTO keep_me(value) VALUES('v2-user-data')")
                connection.commit()
            finally:
                connection.close()
            before_library = layout.library_path.read_bytes()

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertFalse(
                layout.settings_path.exists(),
                "a V2 Library collision must be rejected before settings publication",
            )
            self.assertEqual(layout.library_path.read_bytes(), before_library)
            self.assertFalse(
                (layout.backup_root / ".v1-runtime-bridge-state.json").exists()
            )

    def test_invalid_legacy_library_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            library = legacy / "library.acsdb"
            library.unlink()
            connection = sqlite3.connect(library)
            try:
                connection.execute("CREATE TABLE unrelated(value TEXT)")
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())
            self.assertFalse(
                (layout.backup_root / ".v1-runtime-bridge-state.json").exists()
            )

    def test_interruption_after_settings_publication_resumes_library(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            source_settings_sha = self._sha(legacy / "settings.json")
            source_library_sha = self._sha(legacy / "library.acsdb")

            def crash(phase: str) -> None:
                if phase == "settings-published":
                    raise RuntimeError("simulated process interruption")

            with self.assertRaises(RuntimeError):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=crash
                ).run()

            self.assertTrue(layout.settings_path.is_file())
            self.assertFalse(layout.library_path.exists())
            self.assertTrue(
                (layout.backup_root / ".v1-runtime-bridge-state.json").is_file()
            )

            report = V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertEqual(report.status, "migrated")
            self.assertTrue(report.recovered)
            self.assertTrue(layout.library_path.is_file())
            self.assertFalse(
                (layout.backup_root / ".v1-runtime-bridge-state.json").exists()
            )
            self.assertEqual(self._sha(legacy / "settings.json"), source_settings_sha)
            self.assertEqual(self._sha(legacy / "library.acsdb"), source_library_sha)

    def test_interruption_after_library_publication_resumes_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            source_settings_sha = self._sha(legacy / "settings.json")
            source_library_sha = self._sha(legacy / "library.acsdb")

            def crash(phase: str) -> None:
                if phase == "library-published":
                    raise RuntimeError("simulated process interruption after library")

            with self.assertRaises(RuntimeError):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=crash
                ).run()

            self.assertTrue(layout.settings_path.is_file())
            self.assertTrue(layout.library_path.is_file())
            self.assertTrue(
                (layout.backup_root / ".v1-runtime-bridge-state.json").is_file()
            )

            report = V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertEqual(report.status, "migrated")
            self.assertTrue(report.recovered)
            self.assertFalse(
                (layout.backup_root / ".v1-runtime-bridge-state.json").exists()
            )
            self.assertTrue(
                (layout.backup_root / ".v1-runtime-bridge-completed.json").is_file()
            )
            self.assertEqual(self._sha(legacy / "settings.json"), source_settings_sha)
            self.assertEqual(self._sha(legacy / "library.acsdb"), source_library_sha)

    def test_source_change_after_backup_fails_closed_before_library_publish(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)

            def change_source(phase: str) -> None:
                if phase == "settings-published":
                    legacy_settings = legacy / "settings.json"
                    legacy_settings.write_text(
                        json.dumps({"language": "uk", "volume": 91}) + "\n",
                        encoding="utf-8",
                    )
                    raise RuntimeError("source changed after publication checkpoint")

            with self.assertRaises(RuntimeError):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=change_source
                ).run()

            self.assertTrue(layout.settings_path.is_file())
            self.assertFalse(layout.library_path.exists())
            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()
            self.assertFalse(layout.library_path.exists())
            self.assertEqual(
                json.loads((legacy / "settings.json").read_text(encoding="utf-8"))[
                    "volume"
                ],
                91,
            )

    def test_valid_json_journal_cannot_drop_library_declared_by_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, _legacy, layout = self._fixture(root)

            def crash(phase: str) -> None:
                if phase == "prepared":
                    raise RuntimeError("simulated interruption after durable prepare")

            with self.assertRaises(RuntimeError):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=crash
                ).run()

            journal_path = layout.backup_root / ".v1-runtime-bridge-state.json"
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertTrue(journal["has_library"])
            journal["has_library"] = False
            journal_path.write_text(
                json.dumps(journal, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())

    def test_completed_marker_must_match_immutable_backup_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, _legacy, layout = self._fixture(root)
            V1RuntimeBridgeCoordinator(layout, executable).run()

            marker_path = layout.backup_root / ".v1-runtime-bridge-completed.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertTrue(marker["has_library"])
            marker["has_library"] = False
            marker_path.write_text(
                json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()

    def test_completed_marker_rejects_legacy_source_changed_later(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            V1RuntimeBridgeCoordinator(layout, executable).run()

            legacy_settings = Settings(legacy / "settings.json")
            legacy_settings.set("volume", 33)

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()

    def test_corrupt_duplicate_key_journal_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, _legacy, layout = self._fixture(root)
            layout.backup_root.mkdir(parents=True)
            journal = layout.backup_root / ".v1-runtime-bridge-state.json"
            journal.write_text(
                '{"schema_version":1,"schema_version":1,"phase":"prepared"}\n',
                encoding="utf-8",
            )

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())


if __name__ == "__main__":
    unittest.main()
