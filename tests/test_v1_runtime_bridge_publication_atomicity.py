from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import acs.v1_runtime_bridge as bridge_module
from acs.v1_runtime_bridge import V1RuntimeBridgeCoordinator, V1RuntimeBridgeError
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


class V1RuntimeBridgePublicationAtomicityTests(unittest.TestCase):
    @staticmethod
    def _settings_fixture(root: Path) -> tuple[Path, Path, UserDataLayout]:
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
        layout = UserDataLayout(root / "localappdata" / "AccessibleChess")
        return executable, settings, layout

    @staticmethod
    def _library_fixture(root: Path) -> tuple[Path, Path, UserDataLayout]:
        install = root / "installed"
        data = install / "data"
        data.mkdir(parents=True)
        executable = install / "AccessibleChess.exe"
        executable.write_bytes(b"MZ-test-fixture")
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
        return executable, library, layout

    def test_candidate_change_during_settings_publish_leaves_no_v2_target(self) -> None:
        """A failed settings publication must roll back only its own hard-link."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, _settings, layout = self._settings_fixture(root)

            real_link = os.link
            mutated = False

            def mutate_then_link(source: os.PathLike[str] | str, destination: os.PathLike[str] | str, *args, **kwargs) -> None:
                nonlocal mutated
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    not mutated
                    and destination_path == layout.settings_path
                    and source_path.name == layout.settings_name
                ):
                    source_path.write_bytes(b'{"language":"en","volume":99}\n')
                    mutated = True
                real_link(source, destination, *args, **kwargs)

            with mock.patch.object(bridge_module.os, "link", side_effect=mutate_then_link):
                with self.assertRaises(V1RuntimeBridgeError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertTrue(mutated)
            self.assertFalse(
                layout.settings_path.exists(),
                "failed migration must not leave a canonical V2 settings file",
            )
            self.assertFalse(layout.library_path.exists())

    def test_candidate_change_during_library_publish_leaves_no_v2_target(self) -> None:
        """The same rollback contract applies to schema-0 ACSDB publication."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, _library, layout = self._library_fixture(root)

            real_link = os.link
            mutated = False

            def mutate_then_link(source: os.PathLike[str] | str, destination: os.PathLike[str] | str, *args, **kwargs) -> None:
                nonlocal mutated
                source_path = Path(source)
                destination_path = Path(destination)
                if not mutated and destination_path == layout.library_path:
                    source_path.write_bytes(b"not-a-valid-sqlite-database")
                    mutated = True
                real_link(source, destination, *args, **kwargs)

            with mock.patch.object(bridge_module.os, "link", side_effect=mutate_then_link):
                with self.assertRaises(V1RuntimeBridgeError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertTrue(mutated)
            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(
                layout.library_path.exists(),
                "failed migration must not leave a canonical V2 library file",
            )

    def test_settings_rollback_never_deletes_newer_external_replacement(self) -> None:
        """Rollback owns the bridge hard-link, never a later external pathname."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, settings, layout = self._settings_fixture(root)
            source_before = settings.read_bytes()
            external_bytes = b'{"schema_version":2,"values":{"language":"uk","volume":77}}\n'
            real_hash = bridge_module._hash
            replaced = False

            def replace_before_verification(path: Path) -> str:
                nonlocal replaced
                target = Path(path)
                if not replaced and target == layout.settings_path and target.exists():
                    target.unlink()
                    target.write_bytes(external_bytes)
                    replaced = True
                return real_hash(target)

            with mock.patch.object(bridge_module, "_hash", side_effect=replace_before_verification):
                with self.assertRaisesRegex(
                    V1RuntimeBridgeError,
                    "publication changed before rollback",
                ):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertTrue(replaced)
            self.assertEqual(layout.settings_path.read_bytes(), external_bytes)
            self.assertEqual(settings.read_bytes(), source_before)
            self.assertFalse(layout.library_path.exists())

    def test_restart_after_prepared_checkpoint_finishes_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, settings, layout = self._settings_fixture(root)
            source_before = settings.read_bytes()

            def crash(phase: str) -> None:
                if phase == "prepared":
                    raise RuntimeError("simulated crash after prepared checkpoint")

            with self.assertRaises(RuntimeError):
                V1RuntimeBridgeCoordinator(layout, executable, phase_hook=crash).run()

            self.assertFalse(layout.settings_path.exists())
            self.assertTrue(
                (layout.backup_root / ".v1-runtime-bridge-state.json").is_file()
            )

            report = V1RuntimeBridgeCoordinator(layout, executable).run()
            self.assertEqual(report.status, "migrated")
            self.assertTrue(layout.settings_path.is_file())
            self.assertEqual(settings.read_bytes(), source_before)

            again = V1RuntimeBridgeCoordinator(layout, executable).run()
            self.assertEqual(again.status, "already_migrated")
            self.assertEqual(again.bridge_id, report.bridge_id)

    def test_restart_after_committed_checkpoint_finishes_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, settings, layout = self._settings_fixture(root)
            source_before = settings.read_bytes()

            def crash(phase: str) -> None:
                if phase == "committed":
                    raise RuntimeError("simulated crash after committed checkpoint")

            with self.assertRaises(RuntimeError):
                V1RuntimeBridgeCoordinator(layout, executable, phase_hook=crash).run()

            self.assertTrue(layout.settings_path.is_file())
            self.assertTrue(
                (layout.backup_root / ".v1-runtime-bridge-state.json").is_file()
            )
            self.assertTrue(
                (layout.backup_root / ".v1-runtime-bridge-completed.json").is_file()
            )

            report = V1RuntimeBridgeCoordinator(layout, executable).run()
            self.assertEqual(report.status, "migrated")
            self.assertTrue(report.recovered)
            self.assertEqual(settings.read_bytes(), source_before)
            self.assertFalse(
                (layout.backup_root / ".v1-runtime-bridge-state.json").exists()
            )

            again = V1RuntimeBridgeCoordinator(layout, executable).run()
            self.assertEqual(again.status, "already_migrated")
            self.assertEqual(again.bridge_id, report.bridge_id)

    def test_completed_marker_rejects_missing_legacy_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, settings, layout = self._settings_fixture(root)
            V1RuntimeBridgeCoordinator(layout, executable).run()
            canonical_before = layout.settings_path.read_bytes()

            settings.unlink()

            with self.assertRaisesRegex(V1RuntimeBridgeError, "settings disappeared"):
                V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertEqual(layout.settings_path.read_bytes(), canonical_before)

    def test_completed_marker_rejects_missing_legacy_library(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, library, layout = self._library_fixture(root)
            V1RuntimeBridgeCoordinator(layout, executable).run()
            canonical_before = layout.library_path.read_bytes()

            library.unlink()

            with self.assertRaisesRegex(V1RuntimeBridgeError, "library disappeared"):
                V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertEqual(layout.library_path.read_bytes(), canonical_before)


if __name__ == "__main__":
    unittest.main()
