from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

import acs.v1_runtime_bridge as bridge_module
from acs.acsdb import AcsDatabase
from acs.settings import Settings
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


class _InjectedTermination(BaseException):
    """Model an abrupt process exit that Product exception handlers cannot clean up."""


class V1RuntimeBridgeWindowsCrashOracleTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, UserDataLayout]:
        install = root / "installed"
        legacy = install / "data"
        legacy.mkdir(parents=True)
        executable = install / "AccessibleChess.exe"
        executable.write_bytes(b"MZ-windows-crash-oracle")

        (legacy / "settings.json").write_text(
            json.dumps({"language": "en", "volume": 22}) + "\n",
            encoding="utf-8",
        )
        library = legacy / "library.acsdb"
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

        return (
            executable,
            legacy,
            UserDataLayout(root / "localappdata" / "AccessibleChess"),
        )

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _journal_phase(layout: UserDataLayout) -> str | None:
        path = layout.backup_root / ".v1-runtime-bridge-state.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data["phase"])

    @staticmethod
    def _completed_exists(layout: UserDataLayout) -> bool:
        return (layout.backup_root / ".v1-runtime-bridge-completed.json").exists()

    def _assert_sqlite_clean(self, path: Path) -> None:
        self.assertTrue(path.is_file(), f"SQLite file missing: {path}")
        connection = sqlite3.connect(path)
        try:
            quick = connection.execute("PRAGMA quick_check").fetchone()
            self.assertIsNotNone(quick)
            assert quick is not None
            self.assertEqual(str(quick[0]).lower(), "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def _assert_legacy_exact(
        self,
        legacy: Path,
        settings_bytes: bytes,
        library_bytes: bytes,
    ) -> None:
        self.assertEqual((legacy / "settings.json").read_bytes(), settings_bytes)
        self.assertEqual((legacy / "library.acsdb").read_bytes(), library_bytes)
        self._assert_sqlite_clean(legacy / "library.acsdb")

    def _assert_successful_restart_and_idempotence(
        self,
        layout: UserDataLayout,
        executable: Path,
        legacy: Path,
        settings_bytes: bytes,
        library_bytes: bytes,
    ) -> None:
        report = V1RuntimeBridgeCoordinator(layout, executable).run()
        self.assertEqual(report.status, "migrated")
        self.assertTrue(layout.settings_path.is_file())
        self.assertTrue(layout.library_path.is_file())
        self.assertIsNone(self._journal_phase(layout))
        self.assertTrue(self._completed_exists(layout))
        self._assert_sqlite_clean(layout.library_path)
        self._assert_legacy_exact(legacy, settings_bytes, library_bytes)

        first_settings = layout.settings_path.read_bytes()
        first_library_state = self._sha(layout.library_path)
        again = V1RuntimeBridgeCoordinator(layout, executable).run()
        self.assertEqual(again.status, "already_migrated")
        self.assertEqual(layout.settings_path.read_bytes(), first_settings)
        self.assertEqual(self._sha(layout.library_path), first_library_state)
        self._assert_sqlite_clean(layout.library_path)
        self._assert_legacy_exact(legacy, settings_bytes, library_bytes)

    def test_before_backup_completion_restart_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = (legacy / "settings.json").read_bytes()
            library_before = (legacy / "library.acsdb").read_bytes()

            def terminate_mid_copy(source: Path, destination: Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"partial-backup")
                raise _InjectedTermination("before backup completion")

            with mock.patch.object(
                bridge_module, "_stable_copy", side_effect=terminate_mid_copy
            ):
                with self.assertRaises(_InjectedTermination):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertIsNone(self._journal_phase(layout))
            self.assertFalse(self._completed_exists(layout))
            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())
            self._assert_legacy_exact(legacy, settings_before, library_before)

            self._assert_successful_restart_and_idempotence(
                layout, executable, legacy, settings_before, library_before
            )

    def test_after_backup_before_journal_publication_restart_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = (legacy / "settings.json").read_bytes()
            library_before = (legacy / "library.acsdb").read_bytes()
            real_atomic_json = bridge_module._atomic_json

            def terminate_after_manifest(path: Path, value):
                real_atomic_json(path, value)
                if Path(path).name == "manifest.json":
                    raise _InjectedTermination("after backup manifest")

            with mock.patch.object(
                bridge_module, "_atomic_json", side_effect=terminate_after_manifest
            ):
                with self.assertRaises(_InjectedTermination):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            backup_dirs = [item for item in layout.backup_root.iterdir() if item.is_dir()]
            self.assertEqual(len(backup_dirs), 1)
            self.assertTrue((backup_dirs[0] / "manifest.json").is_file())
            self.assertIsNone(self._journal_phase(layout))
            self.assertFalse(self._completed_exists(layout))
            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())
            self._assert_legacy_exact(legacy, settings_before, library_before)

            self._assert_successful_restart_and_idempotence(
                layout, executable, legacy, settings_before, library_before
            )

    def test_after_journal_publication_restart_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = (legacy / "settings.json").read_bytes()
            library_before = (legacy / "library.acsdb").read_bytes()

            def terminate(phase: str) -> None:
                if phase == "prepared":
                    raise _InjectedTermination("after journal publication")

            with self.assertRaises(_InjectedTermination):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=terminate
                ).run()

            self.assertEqual(self._journal_phase(layout), "prepared")
            self.assertFalse(self._completed_exists(layout))
            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())
            self._assert_legacy_exact(legacy, settings_before, library_before)

            self._assert_successful_restart_and_idempotence(
                layout, executable, legacy, settings_before, library_before
            )

    def test_after_settings_publication_newer_settings_writer_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = (legacy / "settings.json").read_bytes()
            library_before = (legacy / "library.acsdb").read_bytes()

            def terminate(phase: str) -> None:
                if phase == "settings-published":
                    raise _InjectedTermination("after settings publication")

            with self.assertRaises(_InjectedTermination):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=terminate
                ).run()

            self.assertEqual(self._journal_phase(layout), "settings_published")
            self.assertFalse(self._completed_exists(layout))
            self.assertTrue(layout.settings_path.is_file())
            self.assertFalse(layout.library_path.exists())

            Settings(layout.settings_path).set("volume", 91)
            external_bytes = layout.settings_path.read_bytes()
            self.assertEqual(
                json.loads(external_bytes.decode("utf-8"))["values"]["volume"], 91
            )

            for _ in range(2):
                with self.assertRaises(V1RuntimeBridgeError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()
                self.assertEqual(layout.settings_path.read_bytes(), external_bytes)
                self.assertFalse(layout.library_path.exists())
                self.assertEqual(self._journal_phase(layout), "settings_published")
                self.assertFalse(self._completed_exists(layout))
                self._assert_legacy_exact(legacy, settings_before, library_before)

    def test_after_library_publication_newer_library_writer_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = (legacy / "settings.json").read_bytes()
            library_before = (legacy / "library.acsdb").read_bytes()

            def terminate(phase: str) -> None:
                if phase == "library-published":
                    raise _InjectedTermination("after library publication")

            with self.assertRaises(_InjectedTermination):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=terminate
                ).run()

            self.assertEqual(self._journal_phase(layout), "library_published")
            self.assertFalse(self._completed_exists(layout))
            self.assertTrue(layout.settings_path.is_file())
            self.assertTrue(layout.library_path.is_file())

            with AcsDatabase(layout.library_path) as database:
                source_id = database.add_source(
                    "external-writer.pgn", "pgn", "f" * 64
                )
                self.assertGreater(source_id, 0)
            external_bytes = layout.library_path.read_bytes()
            settings_published_bytes = layout.settings_path.read_bytes()
            self._assert_sqlite_clean(layout.library_path)

            for _ in range(2):
                with self.assertRaises(V1RuntimeBridgeError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()
                self.assertEqual(layout.library_path.read_bytes(), external_bytes)
                self.assertEqual(
                    layout.settings_path.read_bytes(), settings_published_bytes
                )
                self.assertEqual(self._journal_phase(layout), "library_published")
                self.assertFalse(self._completed_exists(layout))
                self._assert_sqlite_clean(layout.library_path)
                self._assert_legacy_exact(legacy, settings_before, library_before)

    def test_failure_during_regular_file_fsync_restart_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = (legacy / "settings.json").read_bytes()
            library_before = (legacy / "library.acsdb").read_bytes()
            real_fsync = os.fsync
            injected = False

            def fail_regular_file_once(fd: int) -> None:
                nonlocal injected
                mode = os.fstat(fd).st_mode
                if not injected and stat.S_ISREG(mode):
                    injected = True
                    raise OSError("injected fsync failure")
                real_fsync(fd)

            with mock.patch.object(
                bridge_module.os, "fsync", side_effect=fail_regular_file_once
            ):
                with self.assertRaises(V1RuntimeBridgeError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertTrue(injected)
            self.assertIsNone(self._journal_phase(layout))
            self.assertFalse(self._completed_exists(layout))
            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())
            self._assert_legacy_exact(legacy, settings_before, library_before)

            self._assert_successful_restart_and_idempotence(
                layout, executable, legacy, settings_before, library_before
            )

    def test_failure_during_journal_replace_restart_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = (legacy / "settings.json").read_bytes()
            library_before = (legacy / "library.acsdb").read_bytes()
            journal_path = layout.backup_root / ".v1-runtime-bridge-state.json"
            real_replace = os.replace
            injected = False

            def fail_journal_replace_once(source, destination, *args, **kwargs):
                nonlocal injected
                if not injected and Path(destination) == journal_path:
                    injected = True
                    raise OSError("injected replace failure")
                return real_replace(source, destination, *args, **kwargs)

            with mock.patch.object(
                bridge_module.os, "replace", side_effect=fail_journal_replace_once
            ):
                with self.assertRaises(OSError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertTrue(injected)
            self.assertIsNone(self._journal_phase(layout))
            self.assertFalse(self._completed_exists(layout))
            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())
            self._assert_legacy_exact(legacy, settings_before, library_before)

            self._assert_successful_restart_and_idempotence(
                layout, executable, legacy, settings_before, library_before
            )

    def test_termination_while_starting_recovery_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, legacy, layout = self._fixture(root)
            settings_before = (legacy / "settings.json").read_bytes()
            library_before = (legacy / "library.acsdb").read_bytes()

            def terminate_after_prepare(phase: str) -> None:
                if phase == "prepared":
                    raise _InjectedTermination("seed interrupted recovery")

            with self.assertRaises(_InjectedTermination):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=terminate_after_prepare
                ).run()

            journal_path = layout.backup_root / ".v1-runtime-bridge-state.json"
            journal_bytes = journal_path.read_bytes()
            self.assertEqual(self._journal_phase(layout), "prepared")

            real_load_json = bridge_module._load_json

            def terminate_on_recovery_read(path: Path, label: str):
                if Path(path) == journal_path:
                    raise _InjectedTermination("while starting recovery")
                return real_load_json(path, label)

            with mock.patch.object(
                bridge_module, "_load_json", side_effect=terminate_on_recovery_read
            ):
                with self.assertRaises(_InjectedTermination):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertEqual(journal_path.read_bytes(), journal_bytes)
            self.assertEqual(self._journal_phase(layout), "prepared")
            self.assertFalse(self._completed_exists(layout))
            self.assertFalse(layout.settings_path.exists())
            self.assertFalse(layout.library_path.exists())
            self._assert_legacy_exact(legacy, settings_before, library_before)

            self._assert_successful_restart_and_idempotence(
                layout, executable, legacy, settings_before, library_before
            )


if __name__ == "__main__":
    unittest.main()
