from __future__ import annotations

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
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "publication guard changed unexpectedly",
                ):
                    Version2UpgradeCoordinator(UserDataLayout(root)).run()

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
                info = real_require(guard)
                require_calls += 1
                if require_calls == 4:
                    guard.path.unlink()
                return info

            with mock.patch.object(
                upgrade_base_module,
                "_require_publication_guard",
                side_effect=race_require,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "publication guard changed unexpectedly",
                ):
                    Version2UpgradeCoordinator(UserDataLayout(root)).run()

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
