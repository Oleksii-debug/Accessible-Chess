from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.settings import Settings
import acs.version2_upgrade_base as upgrade_base_module
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

    def test_recovery_settings_rejects_same_state_inode_swap_before_guard(self) -> None:
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

            authorized_identity = upgrade_base_module._stat_identity(
                settings.lstat()
            )
            migrated_bytes = settings.read_bytes()
            replacement = root / "same-state-settings.json"
            replacement.write_bytes(migrated_bytes)
            replacement_identity = upgrade_base_module._stat_identity(
                replacement.lstat()
            )
            self.assertNotEqual(authorized_identity, replacement_identity)

            real_guard = upgrade_base_module._publication_guard
            injected = False

            def swap_before_guard(path):
                nonlocal injected
                if Path(path) == settings and not injected:
                    injected = True
                    replacement.replace(settings)
                return real_guard(path)

            with mock.patch.object(
                upgrade_base_module,
                "_publication_guard",
                side_effect=swap_before_guard,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError,
                    "identity changed before recovery publication",
                ):
                    Version2UpgradeCoordinator(
                        UserDataLayout(root)
                    ).recover_interrupted()

            self.assertTrue(injected)
            self.assertEqual(
                replacement_identity,
                upgrade_base_module._stat_identity(settings.lstat()),
            )
            self.assertEqual(migrated_bytes, settings.read_bytes())

    def test_recovery_library_rejects_same_state_inode_swap_before_prepare(self) -> None:
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

            authorized_identity = upgrade_base_module._stat_identity(
                library.lstat()
            )
            replacement = root / "same-state-library.acsdb"
            source_connection = sqlite3.connect(library)
            replacement_connection = sqlite3.connect(replacement)
            try:
                source_connection.backup(replacement_connection)
                replacement_connection.commit()
            finally:
                replacement_connection.close()
                source_connection.close()
            replacement_identity = upgrade_base_module._stat_identity(
                replacement.lstat()
            )
            self.assertNotEqual(authorized_identity, replacement_identity)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            expected_state = upgrade_base_module._library_state_sha256(
                library,
                schema_validator=coordinator._validate_library_schema,
            )
            replacement_state = upgrade_base_module._library_state_sha256(
                replacement,
                schema_validator=coordinator._validate_library_schema,
            )
            self.assertEqual(expected_state, replacement_state)

            real_prepare = Version2UpgradeCoordinator._prepare_library_publication
            injected = False

            def swap_before_prepare(instance, expected_original, **kwargs):
                nonlocal injected
                if not injected:
                    injected = True
                    replacement.replace(library)
                return real_prepare(
                    instance,
                    expected_original,
                    **kwargs,
                )

            with mock.patch.object(
                Version2UpgradeCoordinator,
                "_prepare_library_publication",
                new=swap_before_prepare,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError,
                    "tracked Library changed before recovery publication",
                ):
                    coordinator.recover_interrupted()

            self.assertTrue(injected)
            self.assertEqual(
                replacement_identity,
                upgrade_base_module._stat_identity(library.lstat()),
            )
            self.assertEqual(
                expected_state,
                upgrade_base_module._library_state_sha256(
                    library,
                    schema_validator=coordinator._validate_library_schema,
                ),
            )

    def test_recovery_settings_writer_in_final_replace_window_is_restored_from_guard(self) -> None:
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
                json.dumps({"language": "uk", "volume": 94}, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
            real_stable_copy = upgrade_base_module._stable_copy
            injected = False

            def race_restore_copy(source, destination, **kwargs):
                nonlocal injected
                if Path(destination) == settings and not injected:
                    injected = True
                    settings.write_bytes(external_bytes)
                return real_stable_copy(source, destination, **kwargs)

            with mock.patch.object(
                upgrade_base_module,
                "_stable_copy",
                side_effect=race_restore_copy,
            ):
                with self.assertRaises(Version2UpgradeRecoveryError):
                    Version2UpgradeCoordinator(
                        UserDataLayout(root)
                    ).recover_interrupted()

            self.assertTrue(injected)
            self.assertEqual(
                settings.read_bytes(),
                external_bytes,
                "recovery silently overwrote the final-window Settings writer",
            )

    def test_recovery_library_writer_in_final_replace_window_is_restored_from_guard(self) -> None:
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

            real_stable_copy = upgrade_base_module._stable_copy
            injected = False

            def race_restore_copy(source, destination, **kwargs):
                nonlocal injected
                if Path(destination) == library and not injected:
                    injected = True
                    connection = sqlite3.connect(library)
                    try:
                        connection.execute(
                            "INSERT INTO sources(source_name,source_format,sha256,imported_at) "
                            "VALUES(?,?,?,?)",
                            (
                                "external-recovery-window-v6.pgn",
                                "pgn",
                                "7" * 64,
                                "2026-10-04T00:20:00+02:00",
                            ),
                        )
                        connection.commit()
                    finally:
                        connection.close()
                return real_stable_copy(source, destination, **kwargs)

            with mock.patch.object(
                upgrade_base_module,
                "_stable_copy",
                side_effect=race_restore_copy,
            ):
                with self.assertRaises(Version2UpgradeRecoveryError):
                    Version2UpgradeCoordinator(
                        UserDataLayout(root)
                    ).recover_interrupted()

            self.assertTrue(injected)
            with AcsDatabase(library) as reopened:
                self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
                names = [
                    str(row["source_name"])
                    for row in reopened.conn.execute(
                        "SELECT source_name FROM sources ORDER BY id"
                    ).fetchall()
                ]
            self.assertIn(
                "external-recovery-window-v6.pgn",
                names,
                "recovery silently overwrote the final-window Library writer",
            )

    def test_lock_path_split_defers_rollback_and_preserves_new_settings_writer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings_path = root / "settings.json"
            original_bytes = json.dumps(
                {"language": "en", "volume": 20}
            ).encode("utf-8")
            settings_path.write_bytes(original_bytes)
            lock_path = root / ".v2-upgrade.lock"
            displaced_lock = root / ".v2-upgrade.lock.displaced"
            replacement_lock = root / "replacement-upgrade.lock"
            external_volume = 96
            injected = False

            def split_lock_and_write(phase: str) -> None:
                nonlocal injected
                if phase != "settings-migrated" or injected:
                    return
                os.replace(lock_path, displaced_lock)
                replacement_lock.write_bytes(b"\0")
                os.replace(replacement_lock, lock_path)

                external = Settings(settings_path)
                external.set("volume", external_volume)
                injected = True

            with self.assertRaisesRegex(
                Version2UpgradeRecoveryError,
                "upgrade lock identity was lost",
            ):
                Version2UpgradeCoordinator(
                    UserDataLayout(root),
                    phase_hook=split_lock_and_write,
                ).run()

            self.assertTrue(injected)
            current = Settings(settings_path)
            self.assertEqual(external_volume, current.get("volume"))

            journal = json.loads(
                (root / ".v2-upgrade-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "migrating",
                journal["phase"],
                "lock loss must leave a nonterminal journal for later recovery",
            )

            # The old locked inode is no longer canonical and the coordinator
            # has exited, so removing this test-only displaced pathname does not
            # change the canonical lock used by the next recovery attempt.
            displaced_lock.unlink()

            with self.assertRaises(Version2UpgradeRecoveryError):
                Version2UpgradeCoordinator(
                    UserDataLayout(root)
                ).recover_interrupted()

            current = Settings(settings_path)
            self.assertEqual(
                external_volume,
                current.get("volume"),
                "later recovery overwrote a writer that used the new canonical lock",
            )

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
