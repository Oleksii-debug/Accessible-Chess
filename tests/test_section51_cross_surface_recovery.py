from __future__ import annotations

"""Section 51 cross-surface user-data preservation and recovery contracts.

These tests exercise the single shipped Version2UpgradeCoordinator authority.
They intentionally do not claim a user-facing multi-device import UI, packaged
Windows validation, or owner/NVDA acceptance.
"""

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase, ACSDB_SCHEMA_VERSION
from acs.version2_upgrade import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    Version2UpgradeRecoveryError,
)


class _AbruptExit(BaseException):
    """Model process loss without invoking the upgrader's exception rollback."""


class Section51CrossSurfaceRecoveryTests(unittest.TestCase):
    def _fixture(
        self, parent: Path, *, legacy_library: bool = False
    ) -> tuple[Path, dict[str, bytes]]:
        root = parent / "AccessibleChess"
        root.mkdir()
        # A legacy Settings file forces the actual transaction, while the
        # Library is a real canonical SQLite database with user-owned rows.
        (root / "settings.json").write_text(
            json.dumps({"language": "uk", "volume": 37}), encoding="utf-8"
        )
        with AcsDatabase(root / "library.acsdb") as database:
            database.add_source("Особиста бібліотека.pgn", "pgn")
        if legacy_library:
            # Preserve a genuine older upgrade entrypoint with the precise
            # schema-v1 test geometry used by existing D07 migration tests.
            with sqlite3.connect(root / "library.acsdb") as connection:
                connection.execute("DROP INDEX IF EXISTS idx_positions_key_game_ply")
                connection.execute("DROP TABLE IF EXISTS import_attempts")
                connection.execute("PRAGMA user_version=1")


        durable = {
            "book-progress.json": b'{"completed":["lesson-1"]}\n',
            "training-progress/" + "a" * 64 + ".json": b'{"owner":"training"}\n',
            "education-workspace.json": b'{"teacher":"notes"}\n',
            "media/sessions.json": b'{"timeline":"user-prepared"}\n',
            "agent-jobs/drafts.json": b'{"pending":"user-draft"}\n',
            "accounts/profile.json": b'{"display_name":"owner"}\n',
            "books/Мої шахи.md": "Моя книжка: 1. e4 e5\n".encode("utf-8"),
        }
        for relative, payload in durable.items():
            destination = root.joinpath(*relative.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        return root, durable

    def _assert_durable(self, root: Path, durable: dict[str, bytes]) -> None:
        for relative, payload in durable.items():
            with self.subTest(relative=relative):
                self.assertEqual(
                    root.joinpath(*relative.split("/")).read_bytes(), payload
                )

    def test_backup_manifest_covers_each_stateful_surface_and_fresh_profile_reopens(self):
        """A real backup copy can be migrated in a fresh, empty data root."""
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            root, durable = self._fixture(parent)
            report = Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertEqual(report.status, "upgraded")
            self._assert_durable(root, durable)
            backup = root.parent / "AccessibleChess.upgrade-backups" / report.backup_name
            manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
            listed = {row["path"]: row for row in manifest["entries"]}
            expected = {"settings.json", "library.acsdb", *durable}
            self.assertEqual(set(listed), expected)

            for relative in expected:
                with self.subTest(backup=relative):
                    stored = backup / "data" / Path(*relative.split("/"))
                    payload = stored.read_bytes()
                    self.assertEqual(len(payload), listed[relative]["size"])
                    self.assertEqual(
                        hashlib.sha256(payload).hexdigest(), listed[relative]["sha256"]
                    )
                    if relative in durable:
                        self.assertEqual(payload, durable[relative])

            # A fresh-profile data transplant is intentionally host-side only.
            # It proves canonical migration/readback, not accessible UI import.
            fresh = parent / "AnotherMachine" / "AccessibleChess"
            fresh.parent.mkdir()
            shutil.copytree(backup / "data", fresh)
            migrated = Version2UpgradeCoordinator(UserDataLayout(fresh)).run()
            self.assertEqual(migrated.status, "upgraded")
            self._assert_durable(fresh, durable)
            with AcsDatabase(fresh / "library.acsdb") as database:
                self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(
                    database.get_source(1)["source_name"],
                    "Особиста бібліотека.pgn",
                )
            profile = json.loads((fresh / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["values"]["volume"], 37)

    def test_failure_after_settings_migration_rolls_back_tracked_state_and_keeps_all_user_files(self):
        with tempfile.TemporaryDirectory() as td:
            root, durable = self._fixture(Path(td))
            settings_before = (root / "settings.json").read_bytes()

            def fail(phase: str) -> None:
                if phase == "settings-migrated":
                    raise RuntimeError("injected migration failure")

            with self.assertRaisesRegex(
                Version2UpgradeError, "original user data was restored"
            ):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=fail
                ).run()

            self.assertEqual((root / "settings.json").read_bytes(), settings_before)
            self._assert_durable(root, durable)
            with AcsDatabase(root / "library.acsdb") as database:
                self.assertEqual(
                    database.get_source(1)["source_name"],
                    "Особиста бібліотека.pgn",
                )
            journal = json.loads(
                (root / ".v2-upgrade-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(journal["phase"], "rolled_back")
            self.assertNotIn("injected migration failure", json.dumps(journal))

    def test_process_loss_recovers_and_retries_without_dropping_other_domains(self):
        with tempfile.TemporaryDirectory() as td:
            root, durable = self._fixture(Path(td))

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _AbruptExit()

            with self.assertRaises(_AbruptExit):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash
                ).run()

            self._assert_durable(root, durable)
            recovered = Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertTrue(recovered.recovered_interrupted_upgrade)
            self.assertEqual(recovered.status, "upgraded")
            self._assert_durable(root, durable)
            current = Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertEqual(current.status, "already_current")
            self._assert_durable(root, durable)

    def test_tampered_backup_blocks_restore_and_preserves_live_state(self):
        with tempfile.TemporaryDirectory() as td:
            root, durable = self._fixture(Path(td))

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _AbruptExit()

            with self.assertRaises(_AbruptExit):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash
                ).run()
            journal_path = root / ".v2-upgrade-state.json"
            journal_before = journal_path.read_bytes()
            journal = json.loads(journal_before)
            backup_file = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / journal["backup_name"]
                / "data"
                / "agent-jobs"
                / "drafts.json"
            )
            backup_file.write_bytes(b"tampered data")
            settings_before = (root / "settings.json").read_bytes()
            with self.assertRaises(Version2UpgradeRecoveryError):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertEqual((root / "settings.json").read_bytes(), settings_before)
            self.assertEqual(journal_path.read_bytes(), journal_before)
            self._assert_durable(root, durable)

    def test_legacy_library_schema_migrates_with_all_independent_user_domains(self):
        with tempfile.TemporaryDirectory() as td:
            root, durable = self._fixture(Path(td), legacy_library=True)
            before = sqlite3.connect(root / "library.acsdb")
            try:
                self.assertEqual(before.execute("PRAGMA user_version").fetchone()[0], 1)
            finally:
                before.close()

            report = Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertEqual(report.status, "upgraded")
            self.assertTrue(report.library_migrated)
            self.assertTrue(report.settings_migrated)
            self._assert_durable(root, durable)
            with AcsDatabase(root / "library.acsdb") as database:
                self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(
                    database.get_source(1)["source_name"],
                    "Особиста бібліотека.pgn",
                )

    def test_future_library_schema_blocks_downgrade_and_preserves_all_user_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root, durable = self._fixture(Path(td))
            connection = sqlite3.connect(root / "library.acsdb")
            try:
                connection.execute("PRAGMA user_version=999")
                connection.commit()
            finally:
                connection.close()
            settings_before = (root / "settings.json").read_bytes()
            with self.assertRaises(Version2UpgradeError):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()
            self.assertEqual((root / "settings.json").read_bytes(), settings_before)
            self._assert_durable(root, durable)
            connection = sqlite3.connect(root / "library.acsdb")
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 999)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
            finally:
                connection.close()

    def test_future_settings_schema_blocks_downgrade_without_touching_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            root, durable = self._fixture(Path(td))
            future = json.dumps(
                {"schema_version": 999, "values": {"language": "uk"}},
                sort_keys=True,
            ).encode("utf-8")
            (root / "settings.json").write_bytes(future)

            with self.assertRaises(Version2UpgradeError):
                Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertEqual((root / "settings.json").read_bytes(), future)
            self._assert_durable(root, durable)
            with AcsDatabase(root / "library.acsdb") as database:
                self.assertEqual(
                    database.get_source(1)["source_name"],
                    "Особиста бібліотека.pgn",
                )


if __name__ == "__main__":
    unittest.main()
