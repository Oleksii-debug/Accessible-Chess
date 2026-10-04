from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.settings import Settings, SettingsError
import acs.version2_upgrade as upgrade_module
import acs.version2_upgrade_base as upgrade_base_module
from acs.version2_upgrade import (
    UserDataLayout,
    Version2UpgradeBusy,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    Version2UpgradeRecoveryError,
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

    def test_backup_staging_substitution_is_not_published_or_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "notes.txt").write_bytes(b"canonical-user-data")
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()

            real_atomic_json = upgrade_base_module._atomic_json
            substituted: Path | None = None
            moved_owned: Path | None = None

            def substitute_after_manifest(path: Path, value) -> None:
                nonlocal substituted, moved_owned
                real_atomic_json(path, value)
                staging = Path(path).parent
                moved_owned = staging.with_name(staging.name + ".owned-original")
                os.replace(staging, moved_owned)
                staging.mkdir()
                (staging / "foreign.txt").write_bytes(b"foreign-staging-directory")
                substituted = staging

            with mock.patch.object(
                upgrade_base_module,
                "_atomic_json",
                side_effect=substitute_after_manifest,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "upgrade backup staging directory changed unexpectedly",
                ):
                    coordinator._create_backup("staging-substitution")

            self.assertIsNotNone(substituted)
            self.assertIsNotNone(moved_owned)
            assert substituted is not None
            assert moved_owned is not None
            self.assertEqual(
                (substituted / "foreign.txt").read_bytes(),
                b"foreign-staging-directory",
                "cleanup deleted a directory substituted at the staging pathname",
            )
            self.assertTrue(moved_owned.is_dir())
            self.assertFalse(
                (coordinator.layout.backup_root / "staging-substitution").exists()
            )
            self.assertIsNone(coordinator._last_backup)

    def test_backup_publication_rejects_published_directory_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "notes.txt").write_bytes(b"canonical-user-data")
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            final = coordinator.layout.backup_root / "publication-substitution"

            real_atomic_json = upgrade_base_module._atomic_json
            real_replace = os.replace
            staging: Path | None = None
            displaced_owned: Path | None = None
            injected = False

            def capture_staging(path: Path, value) -> None:
                nonlocal staging
                staging = Path(path).parent
                real_atomic_json(path, value)

            def substitute_after_publish(source: object, destination: object) -> None:
                nonlocal injected, displaced_owned
                source_path = Path(source)
                destination_path = Path(destination)
                real_replace(source, destination)
                if (
                    staging is not None
                    and source_path == staging
                    and destination_path == final
                    and not injected
                ):
                    displaced_owned = final.with_name(final.name + ".owned-original")
                    real_replace(final, displaced_owned)
                    final.mkdir()
                    (final / "foreign.txt").write_bytes(
                        b"foreign-published-directory"
                    )
                    injected = True

            with mock.patch.object(
                upgrade_base_module,
                "_atomic_json",
                side_effect=capture_staging,
            ), mock.patch.object(
                upgrade_base_module.os,
                "replace",
                side_effect=substitute_after_publish,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "upgrade backup publication changed unexpectedly",
                ):
                    coordinator._create_backup("publication-substitution")

            self.assertTrue(injected)
            self.assertIsNotNone(displaced_owned)
            assert displaced_owned is not None
            self.assertEqual(
                (final / "foreign.txt").read_bytes(),
                b"foreign-published-directory",
            )
            self.assertTrue(displaced_owned.is_dir())
            self.assertIsNone(coordinator._last_backup)

    def test_recovery_json_rejects_same_bytes_inode_swap_on_open(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = root / "manifest.json"
            payload = b'{"schema_version": 2}\n'
            target.write_bytes(payload)
            substitute = root / "same-bytes-manifest.json"
            substitute.write_bytes(payload)
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            real_open = upgrade_base_module.os.open
            injected = False

            def swap_before_open(path, flags, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if candidate == target and not injected:
                    os.replace(substitute, target)
                    injected = True
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                upgrade_base_module.os,
                "open",
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError,
                    "is unreadable",
                ):
                    coordinator._read_json(target, "upgrade backup manifest")

            self.assertTrue(injected)
            self.assertEqual(payload, target.read_bytes())

    def test_descriptor_hash_rejects_same_bytes_inode_swap_on_open(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "backup.bin"
            payload = b"same-bytes-but-different-inode"
            target.write_bytes(payload)
            substitute = root / "substitute.bin"
            substitute.write_bytes(payload)
            real_open = upgrade_base_module.os.open
            injected = False

            def swap_before_open(path, flags, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if candidate == target and not injected:
                    os.replace(substitute, target)
                    injected = True
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                upgrade_base_module.os,
                "open",
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "changed while opening",
                ):
                    upgrade_base_module._hash(
                        target,
                        label="upgrade backup file",
                    )

            self.assertTrue(injected)
            self.assertEqual(payload, target.read_bytes())

    def test_recovery_json_raw_limit_precedes_descriptor_open(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = root / "oversized.json"
            target.write_bytes(
                b"x" * (upgrade_base_module._MAX_RECOVERY_JSON_BYTES + 1)
            )
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))

            with mock.patch.object(
                upgrade_base_module.os,
                "open",
                side_effect=AssertionError(
                    "over-budget recovery JSON must fail before descriptor open"
                ),
            ) as opened:
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError,
                    "is unreadable",
                ):
                    coordinator._read_json(target, "upgrade journal")
            opened.assert_not_called()

    def test_restore_rejects_changed_backup_before_live_publication(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            original = b'{"language":"en","volume":10}\n'
            settings.write_bytes(original)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            upgrade_id = "restore-source-race"
            backup, _manifest = coordinator._create_backup(upgrade_id)

            owned = b'{"schema_version":2,"values":{"volume":97}}\n'
            settings.write_bytes(owned)
            coordinator._owned_states = {
                coordinator.layout.settings_name: hashlib.sha256(owned).hexdigest()
            }
            coordinator._write_phase(
                upgrade_id,
                "migrating",
                recovered=False,
                notify=False,
            )

            real_manifest = coordinator._manifest
            injected = False
            corrupted = b"X" * len(original)

            def validate_then_corrupt(identifier: str):
                nonlocal injected
                validated_backup, validated_manifest = real_manifest(identifier)
                source = (
                    validated_backup
                    / "data"
                    / coordinator.layout.settings_name
                )
                source.write_bytes(corrupted)
                injected = True
                return validated_backup, validated_manifest

            with mock.patch.object(
                coordinator,
                "_manifest",
                side_effect=validate_then_corrupt,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "source digest does not match expected copy",
                ):
                    coordinator._restore(upgrade_id)

            self.assertTrue(injected)
            self.assertEqual(
                owned,
                settings.read_bytes(),
                "changed backup source was published to live Settings before checksum rejection",
            )
            self.assertEqual(
                corrupted,
                (backup / "data" / coordinator.layout.settings_name).read_bytes(),
            )

    def test_manifest_rejects_whole_backup_directory_swap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "notes.txt").write_bytes(b"preserved-user-data")
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            upgrade_id = "backup-directory-swap"
            backup, _manifest = coordinator._create_backup(upgrade_id)

            replacement = coordinator.layout.backup_root / "replacement-backup-tree"
            shutil.copytree(backup, replacement)
            displaced = coordinator.layout.backup_root / "displaced-backup-tree"
            real_read_json = coordinator._read_json
            injected = False

            def swap_then_read(path: Path, label: str):
                nonlocal injected
                if not injected:
                    os.replace(backup, displaced)
                    os.replace(replacement, backup)
                    injected = True
                return real_read_json(path, label)

            with mock.patch.object(
                coordinator,
                "_read_json",
                side_effect=swap_then_read,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError,
                    "backup directory changed during recovery",
                ):
                    coordinator._manifest(upgrade_id)

            self.assertTrue(injected)
            self.assertTrue(displaced.is_dir())
            self.assertTrue(backup.is_dir())

    def test_manifest_rejects_backup_data_directory_swap_during_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "notes.txt").write_bytes(b"preserved-user-data")
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            upgrade_id = "backup-data-directory-swap"
            backup, _manifest = coordinator._create_backup(upgrade_id)
            data = backup / "data"

            replacement = backup / "replacement-data-tree"
            shutil.copytree(data, replacement)
            displaced = backup / "displaced-data-tree"
            real_hash = upgrade_base_module._hash
            injected = False

            def swap_then_hash(path: Path, *, label: str = "hashed file"):
                nonlocal injected
                candidate = Path(path)
                if data in candidate.parents and not injected:
                    os.replace(data, displaced)
                    os.replace(replacement, data)
                    injected = True
                return real_hash(path, label=label)

            with mock.patch.object(
                upgrade_base_module,
                "_hash",
                side_effect=swap_then_hash,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError,
                    "backup directory changed during recovery",
                ):
                    coordinator._manifest(upgrade_id)

            self.assertTrue(injected)
            self.assertTrue(displaced.is_dir())
            self.assertTrue(data.is_dir())

    def test_library_state_digest_rejects_same_state_inode_swap_on_connect(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "library.acsdb"
            replacement = root / "replacement.acsdb"

            for path in (source, replacement):
                connection = sqlite3.connect(path)
                try:
                    connection.execute("PRAGMA user_version=31")
                    connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
                    connection.execute(
                        "INSERT INTO sample(value) VALUES ('same-logical-state')"
                    )
                    connection.commit()
                finally:
                    connection.close()

            real_connect = upgrade_base_module.sqlite3.connect
            injected = False

            def swap_before_connect(database, *args, **kwargs):
                nonlocal injected
                raw = os.fspath(database)
                if raw.startswith("file:") and not injected:
                    os.replace(replacement, source)
                    injected = True
                return real_connect(database, *args, **kwargs)

            def validate(connection):
                row = connection.execute("PRAGMA user_version").fetchone()
                return int(row[0])

            with mock.patch.object(
                upgrade_base_module.sqlite3,
                "connect",
                side_effect=swap_before_connect,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "library state source changed during validation",
                ):
                    upgrade_base_module._library_state_sha256(
                        source,
                        schema_validator=validate,
                    )

            self.assertTrue(injected)
            visible = sqlite3.connect(source)
            try:
                self.assertEqual(
                    [("same-logical-state",)],
                    visible.execute("SELECT value FROM sample").fetchall(),
                )
            finally:
                visible.close()

    def test_upgrade_decision_rejects_settings_inode_swap_on_open(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            payload = b'{"language":"en","volume":10}\n'
            settings.write_bytes(payload)
            replacement = root / "replacement-settings.json"
            replacement.write_bytes(payload)
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            real_open = upgrade_base_module.os.open
            injected = False

            def swap_before_open(path, flags, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if candidate == settings and not injected:
                    os.replace(replacement, settings)
                    injected = True
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                upgrade_base_module.os,
                "open",
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "settings validation failed",
                ):
                    coordinator._settings_need()

            self.assertTrue(injected)
            self.assertEqual(payload, settings.read_bytes())

    def test_upgrade_decision_rejects_library_inode_swap_on_connect(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            replacement = root / "replacement.acsdb"
            for path in (library, replacement):
                connection = sqlite3.connect(path)
                try:
                    connection.execute("PRAGMA user_version=1")
                    connection.commit()
                finally:
                    connection.close()

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._validate_library_schema = lambda connection: int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            real_connect = upgrade_base_module.sqlite3.connect
            injected = False

            def swap_before_connect(database, *args, **kwargs):
                nonlocal injected
                raw = os.fspath(database)
                if raw.startswith("file:") and not injected:
                    os.replace(replacement, library)
                    injected = True
                return real_connect(database, *args, **kwargs)

            with mock.patch.object(
                upgrade_base_module.sqlite3,
                "connect",
                side_effect=swap_before_connect,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "library file changed during validation",
                ):
                    coordinator._library_schema()

            self.assertTrue(injected)

    def test_settings_verify_rejects_same_bytes_inode_swap_on_open(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            current = Settings(settings)
            current.set("volume", 10)
            payload = settings.read_bytes()
            replacement = root / "replacement-current-settings.json"
            replacement.write_bytes(payload)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            real_open = upgrade_base_module.os.open
            injected = False

            def swap_before_open(path, flags, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if candidate == settings and not injected:
                    os.replace(replacement, settings)
                    injected = True
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                upgrade_base_module.os,
                "open",
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "migrated settings readback validation failed",
                ):
                    coordinator._verify(
                        coordinator.layout.backup_root / "unused",
                        {"entries": []},
                    )

            self.assertTrue(injected)
            self.assertEqual(payload, settings.read_bytes())

    def test_library_prepare_rejects_same_state_inode_swap_during_connect(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)
            replacement = root / "replacement-library.acsdb"
            shutil.copyfile(library, replacement)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            expected = upgrade_base_module._library_state_sha256(
                library,
                schema_validator=coordinator._validate_library_schema,
            )
            real_connect = upgrade_base_module.sqlite3.connect
            injected = False

            def swap_before_connect(database, *args, **kwargs):
                nonlocal injected
                raw = os.fspath(database)
                if raw == str(library) and not injected:
                    os.replace(replacement, library)
                    injected = True
                return real_connect(database, *args, **kwargs)

            with mock.patch.object(
                upgrade_base_module.sqlite3,
                "connect",
                side_effect=swap_before_connect,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "library publication target changed during preparation",
                ):
                    coordinator._prepare_library_publication(expected)

            self.assertTrue(injected)
            self.assertEqual(
                expected,
                upgrade_base_module._library_state_sha256(
                    library,
                    schema_validator=coordinator._validate_library_schema,
                ),
            )

    def test_sidecar_cleanup_rejects_library_owner_swap_before_removal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)
            original_identity = upgrade_base_module._stat_identity(
                library.lstat()
            )
            replacement = root / "replacement-library.acsdb"
            shutil.copyfile(library, replacement)
            wal = Path(str(library) + "-wal")
            wal_bytes = b"preserve-sidecar-on-owner-swap"
            wal.write_bytes(wal_bytes)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            real_safe_stat = upgrade_base_module._safe_stat
            owner_checks = 0
            injected = False

            def swap_on_second_owner_check(path, label):
                nonlocal owner_checks, injected
                if (
                    Path(path) == library
                    and label == "library sidecar owner"
                ):
                    owner_checks += 1
                    if owner_checks == 2 and not injected:
                        os.replace(replacement, library)
                        injected = True
                return real_safe_stat(path, label)

            with mock.patch.object(
                upgrade_base_module,
                "_safe_stat",
                side_effect=swap_on_second_owner_check,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError,
                    "library changed during sidecar cleanup",
                ):
                    coordinator._clear_library_sidecars(
                        expected_library_identity=original_identity,
                    )

            self.assertTrue(injected)
            self.assertEqual(wal_bytes, wal.read_bytes())

    def test_guard_creation_rejects_target_inode_swap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b"original-settings")
            real_link = upgrade_base_module.os.link
            injected = False

            def racing_link(source: object, destination: object) -> None:
                nonlocal injected
                real_link(source, destination)
                if not injected:
                    injected = True
                    replacement = root / "replacement-settings.json"
                    replacement.write_bytes(b"original-settings")
                    os.replace(replacement, settings)

            with mock.patch.object(
                upgrade_base_module.os, "link", side_effect=racing_link
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeBusy,
                    "changed while guard was created",
                ):
                    upgrade_base_module._publication_guard(settings)

            self.assertTrue(injected)
            self.assertEqual(settings.read_bytes(), b"original-settings")
            self.assertFalse(
                any(root.glob(".settings.json.publish-guard-*")),
                "failed guard creation left coordination residue",
            )

    def test_guard_creation_does_not_unlink_substituted_guard_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b"original-settings")
            real_link = upgrade_base_module.os.link
            substituted_guard: Path | None = None

            def racing_link(source: object, destination: object) -> None:
                nonlocal substituted_guard
                real_link(source, destination)
                substituted_guard = Path(destination)
                replacement = root / "guard-user-bytes.bin"
                replacement.write_bytes(b"user-owned-guard-path")
                os.replace(replacement, substituted_guard)

            with mock.patch.object(
                upgrade_base_module.os, "link", side_effect=racing_link
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeBusy,
                    "changed while guard was created",
                ):
                    upgrade_base_module._publication_guard(settings)

            self.assertIsNotNone(substituted_guard)
            assert substituted_guard is not None
            self.assertEqual(
                substituted_guard.read_bytes(),
                b"user-owned-guard-path",
                "creation cleanup deleted a substituted pathname",
            )
            self.assertEqual(settings.read_bytes(), b"original-settings")

    def test_guard_hash_does_not_cross_compare_windows_ctime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            payload = b"original-settings"
            settings.write_bytes(payload)
            guard = upgrade_base_module._publication_guard(settings)
            real_fstat = upgrade_base_module.os.fstat

            class ShiftedCtime:
                def __init__(self, info: os.stat_result) -> None:
                    self._info = info

                def __getattr__(self, name: str):
                    if name == "st_ctime_ns":
                        return int(getattr(self._info, name, 0)) + 1_000_000_000
                    return getattr(self._info, name)

            try:
                with mock.patch.object(
                    upgrade_base_module.os,
                    "fstat",
                    side_effect=lambda descriptor: ShiftedCtime(
                        real_fstat(descriptor)
                    ),
                ):
                    self.assertEqual(
                        upgrade_base_module._publication_guard_hash(guard),
                        hashlib.sha256(payload).hexdigest(),
                    )
            finally:
                upgrade_base_module._remove_publication_guard(guard)

    def test_guard_hash_rejects_same_bytes_path_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b"original-settings")
            guard = upgrade_base_module._publication_guard(settings)
            substitute = root / "substitute.bin"
            substitute.write_bytes(b"original-settings")
            os.replace(substitute, guard.path)

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "publication guard changed unexpectedly",
            ):
                upgrade_base_module._publication_guard_hash(guard)

            self.assertEqual(guard.path.read_bytes(), b"original-settings")

    def test_guard_cleanup_quarantines_last_moment_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b"original-settings")
            guard = upgrade_base_module._publication_guard(settings)
            foreign = root / "foreign-guard-bytes.bin"
            foreign.write_bytes(b"foreign-last-moment-guard-bytes")
            real_replace = upgrade_base_module.os.replace
            injected = False

            def substitute_before_quarantine(source: object, destination: object) -> None:
                nonlocal injected
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    source_path == guard.path
                    and ".remove-quarantine-" in destination_path.name
                    and not injected
                ):
                    real_replace(foreign, guard.path)
                    injected = True
                real_replace(source, destination)

            with mock.patch.object(
                upgrade_base_module.os,
                "replace",
                side_effect=substitute_before_quarantine,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "publication guard could not be removed safely",
                ):
                    upgrade_base_module._remove_publication_guard(guard)

            self.assertTrue(injected)
            quarantined = list(
                root.glob(".settings.json.publish-guard-*.remove-quarantine-*")
            )
            self.assertEqual(1, len(quarantined))
            self.assertEqual(
                b"foreign-last-moment-guard-bytes",
                quarantined[0].read_bytes(),
                "last-moment foreign guard pathname was deleted instead of preserved",
            )
            self.assertEqual(b"original-settings", settings.read_bytes())

    def test_sidecar_cleanup_quarantines_last_moment_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            library.write_bytes(b"library-main")
            wal = Path(str(library) + "-wal")
            wal.write_bytes(b"owned-derived-wal")
            foreign = root / "foreign-wal-bytes.bin"
            foreign.write_bytes(b"foreign-last-moment-wal")
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            real_replace = upgrade_base_module.os.replace
            injected = False

            def substitute_before_quarantine(source: object, destination: object) -> None:
                nonlocal injected
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    source_path == wal
                    and ".remove-quarantine-" in destination_path.name
                    and not injected
                ):
                    real_replace(foreign, wal)
                    injected = True
                real_replace(source, destination)

            with mock.patch.object(
                upgrade_base_module.os,
                "replace",
                side_effect=substitute_before_quarantine,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError,
                    "library sidecar changed during removal",
                ):
                    coordinator._clear_library_sidecars()

            self.assertTrue(injected)
            quarantined = list(
                root.glob(".library.acsdb-wal.remove-quarantine-*")
            )
            self.assertEqual(1, len(quarantined))
            self.assertEqual(
                b"foreign-last-moment-wal",
                quarantined[0].read_bytes(),
                "foreign WAL pathname was deleted instead of quarantined",
            )

    def test_guard_cleanup_does_not_delete_substituted_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b"original-settings")
            guard = upgrade_base_module._publication_guard(settings)
            substitute = root / "substitute.bin"
            substitute.write_bytes(b"user-owned-substitute")
            os.replace(substitute, guard.path)

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "publication guard changed unexpectedly",
            ):
                upgrade_base_module._remove_publication_guard(guard)

            self.assertEqual(
                guard.path.read_bytes(),
                b"user-owned-substitute",
            )

    def test_guard_cleanup_rejects_missing_owned_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b"original-settings")
            guard = upgrade_base_module._publication_guard(settings)
            guard.path.unlink()

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "publication guard changed unexpectedly",
            ):
                upgrade_base_module._remove_publication_guard(guard)

    def test_settings_same_bytes_candidate_inode_swap_preserves_old_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 10}),
                encoding="utf-8",
            )
            original_bytes = settings.read_bytes()

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            _backup, manifest = coordinator._create_backup(
                "settings-candidate-inode-swap"
            )

            real_replace = upgrade_base_module.os.replace
            injected = False

            def swap_candidate_at_replace(source: object, destination: object) -> None:
                nonlocal injected
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    destination_path == settings
                    and source_path.name.startswith(".settings.json.")
                    and source_path.name.endswith(".tmp")
                    and not injected
                ):
                    substitute = root / "same-bytes-settings-substitute.tmp"
                    shutil.copyfile(source_path, substitute)
                    real_replace(substitute, source_path)
                    injected = True
                real_replace(source, destination)

            with mock.patch.object(
                upgrade_base_module.os,
                "replace",
                side_effect=swap_candidate_at_replace,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "atomic write publication changed before durability confirmation",
                ):
                    coordinator._migrate_settings(manifest)

            self.assertTrue(injected)
            guards = list(root.glob(".settings.json.publish-guard-*"))
            self.assertEqual(
                1,
                len(guards),
                "ambiguous Settings publication discarded the authenticated old inode",
            )
            self.assertEqual(
                original_bytes,
                guards[0].read_bytes(),
                "preserved Settings guard no longer contains the pre-migration bytes",
            )

    def test_settings_publication_fails_if_guard_disappears_after_final_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 10}),
                encoding="utf-8",
            )
            original_bytes = settings.read_bytes()
            real_hash = upgrade_base_module._publication_guard_hash
            hash_calls = 0

            def race_hash(
                guard: upgrade_base_module._PublicationGuard,
            ) -> str:
                nonlocal hash_calls
                digest = real_hash(guard)
                hash_calls += 1
                if hash_calls == 2:
                    guard.path.unlink()
                return digest

            with mock.patch.object(
                upgrade_base_module,
                "_publication_guard_hash",
                side_effect=race_hash,
            ):
                with self.assertRaises(Version2UpgradeError) as caught:
                    Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertIsNotNone(caught.exception.__cause__)
            self.assertIn(
                "publication guard changed unexpectedly",
                str(caught.exception.__cause__),
            )
            self.assertEqual(hash_calls, 2)
            self.assertEqual(
                settings.read_bytes(),
                original_bytes,
                "missing post-publication guard was accepted as a committed migration",
            )

    def test_settings_publication_rejects_guard_path_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_text(
                json.dumps({"language": "en", "volume": 10}),
                encoding="utf-8",
            )
            original_bytes = settings.read_bytes()
            real_atomic_bytes = upgrade_module._atomic_bytes
            injected = False

            def race_atomic_bytes(path: Path, payload: bytes) -> None:
                nonlocal injected
                if Path(path) == settings and not injected:
                    guards = list(root.glob(".settings.json.publish-guard-*"))
                    self.assertEqual(len(guards), 1)
                    replacement = root / "guard-substitute.bin"
                    replacement.write_bytes(guards[0].read_bytes())
                    os.replace(replacement, guards[0])
                    injected = True
                real_atomic_bytes(path, payload)

            with mock.patch.object(
                upgrade_base_module,
                "_atomic_bytes",
                side_effect=race_atomic_bytes,
            ):
                with self.assertRaises(Version2UpgradeError):
                    Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertTrue(injected)
            self.assertEqual(
                settings.read_bytes(),
                original_bytes,
                "guard substitution allowed migration to commit silently",
            )

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
                upgrade_base_module, "_atomic_bytes", side_effect=race_atomic_bytes
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
                upgrade_base_module, "_atomic_bytes", side_effect=race_atomic_bytes
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

    def test_library_publish_same_bytes_inode_swap_preserves_old_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)
            original_sources = self._source_names(library)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            backup, manifest = coordinator._create_backup("candidate-inode-swap")

            real_replace = upgrade_base_module.os.replace
            injected = False

            def swap_candidate_at_replace(source: object, destination: object) -> None:
                nonlocal injected
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    destination_path == library
                    and ".library-publish-" in source_path.name
                    and not injected
                ):
                    substitute = coordinator.layout.backup_root / (
                        "same-bytes-publish-substitute.acsdb"
                    )
                    shutil.copyfile(source_path, substitute)
                    real_replace(substitute, source_path)
                    injected = True
                real_replace(source, destination)

            with mock.patch.object(
                upgrade_base_module.os,
                "replace",
                side_effect=swap_candidate_at_replace,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "library migration publication changed before durability confirmation",
                ):
                    coordinator._migrate_library(backup, manifest)

            self.assertTrue(injected)
            guards = list(root.glob(".library.acsdb.publish-guard-*"))
            self.assertEqual(
                1,
                len(guards),
                "ambiguous post-replace failure discarded the authenticated old Library inode",
            )
            self.assertEqual(self._source_names(guards[0]), original_sources)
            guard_connection = sqlite3.connect(guards[0])
            try:
                self.assertEqual(
                    1,
                    guard_connection.execute("PRAGMA user_version").fetchone()[0],
                )
            finally:
                guard_connection.close()

    def test_library_publish_cleanup_preserves_substituted_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            backup, manifest = coordinator._create_backup("candidate-cleanup")
            real_prepare = coordinator._prepare_library_publication
            substituted: Path | None = None
            injected = False
            foreign_bytes = b"foreign-publish-path-bytes"

            def substitute_candidate(original_state: str) -> None:
                nonlocal substituted, injected
                real_prepare(original_state)
                if injected:
                    return
                candidates = list(
                    coordinator.layout.backup_root.glob(
                        ".None.library-publish-*.acsdb"
                    )
                )
                self.assertEqual(1, len(candidates))
                candidate = candidates[0]
                displaced = candidate.with_name(candidate.name + ".owned-original")
                os.replace(candidate, displaced)
                candidate.write_bytes(foreign_bytes)
                substituted = candidate
                injected = True

            with mock.patch.object(
                coordinator,
                "_prepare_library_publication",
                side_effect=substitute_candidate,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "publication candidate changed before durability confirmation",
                ):
                    coordinator._migrate_library(backup, manifest)

            self.assertTrue(injected)
            self.assertIsNotNone(substituted)
            assert substituted is not None
            self.assertEqual(
                foreign_bytes,
                substituted.read_bytes(),
                "migration cleanup deleted a substituted publish pathname",
            )

    def test_library_publication_rejects_guard_path_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)
            original_sources = self._source_names(library)
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
                    guards = list(root.glob(".library.acsdb.publish-guard-*"))
                    self.assertEqual(len(guards), 1)
                    substitute = root / "library-guard-substitute.acsdb"
                    shutil.copyfile(guards[0], substitute)
                    real_replace(substitute, guards[0])
                    injected = True
                real_replace(source, destination)

            with mock.patch.object(
                upgrade_module.os,
                "replace",
                side_effect=race_replace,
            ):
                with self.assertRaises(Version2UpgradeError):
                    Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertTrue(injected)
            self.assertEqual(
                self._source_names(library),
                original_sources,
                "guard substitution allowed migrated Library state to commit silently",
            )

    def test_library_publication_fails_if_guard_disappears_after_final_state_check(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            self._make_real_v1_library(library)
            original_sources = self._source_names(library)
            real_require = upgrade_base_module._require_publication_guard
            require_calls = 0

            def race_require(
                guard: upgrade_base_module._PublicationGuard,
            ) -> os.stat_result:
                nonlocal require_calls
                require_calls += 1
                info = real_require(guard)
                if require_calls == 4:
                    guard.path.unlink()
                return info

            with mock.patch.object(
                upgrade_base_module,
                "_require_publication_guard",
                side_effect=race_require,
            ):
                with self.assertRaises(Version2UpgradeError) as caught:
                    Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertIsNotNone(caught.exception.__cause__)
            self.assertIn(
                "publication guard changed unexpectedly",
                str(caught.exception.__cause__),
            )
            self.assertGreaterEqual(require_calls, 5)
            self.assertEqual(
                self._source_names(library),
                original_sources,
                "missing Library guard was accepted as a committed migration",
            )

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
