import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.acsdb import ACSDB_SCHEMA_VERSION
from acs.settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
import acs.version2_upgrade as upgrade_module
from acs.version2_upgrade import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeRecoveryError,
)


class Version2UpgradeRecoveryIntegrityTests(unittest.TestCase):
    def _prepare_interrupted(self, root: Path):
        root.mkdir()
        settings = root / "settings.json"
        settings.write_text(
            json.dumps({"language": "en", "volume": 37}),
            encoding="utf-8",
        )
        coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
        coordinator._ensure_roots()
        backup, manifest = coordinator._create_backup("recovery-integrity")
        coordinator._write_phase(
            "recovery-integrity", "migrating", recovered=False
        )
        return coordinator, backup, manifest

    def test_duplicate_json_keys_in_journal_and_manifest_fail_closed(self):
        for target in ("journal", "manifest"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "AccessibleChess"
                coordinator, backup, _ = self._prepare_interrupted(root)
                if target == "journal":
                    path = root / ".v2-upgrade-state.json"
                    raw = path.read_text(encoding="utf-8")
                    raw = raw.replace(
                        '"phase": "migrating"',
                        '"phase": "migrating",\n  "phase": "migrating"',
                        1,
                    )
                else:
                    path = backup / "manifest.json"
                    raw = path.read_text(encoding="utf-8")
                    raw = raw.replace(
                        '"upgrade_id": "recovery-integrity"',
                        '"upgrade_id": "recovery-integrity",\n  "upgrade_id": "recovery-integrity"',
                        1,
                    )
                path.write_text(raw, encoding="utf-8")

                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError, "duplicate JSON"
                ):
                    coordinator.recover_interrupted()
                self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_missing_recovery_metadata_fails_with_typed_recovery_error(self):
        for target in ("journal", "manifest"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "AccessibleChess"
                coordinator, backup, _ = self._prepare_interrupted(root)
                path = (
                    root / ".v2-upgrade-state.json"
                    if target == "journal"
                    else backup / "manifest.json"
                )
                path.unlink()
                if target == "journal":
                    path.mkdir()

                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError, "file|unreadable"
                ):
                    coordinator.recover_interrupted()

    def test_manifest_path_and_library_schema_before_types_are_strict(self):
        for field in ("path", "library_schema_before"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "AccessibleChess"
                coordinator, backup, _ = self._prepare_interrupted(root)
                manifest_path = backup / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if field == "path":
                    manifest["entries"][0]["path"] = 123
                else:
                    manifest["library_schema_before"] = "none"
                manifest_path.write_text(
                    json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError, "manifest|metadata|schema"
                ):
                    coordinator.recover_interrupted()

    def test_journal_target_schema_identity_is_not_ignored(self):
        for field, current in (
            ("target_settings_schema", SETTINGS_SCHEMA_VERSION),
            ("target_acsdb_schema", ACSDB_SCHEMA_VERSION),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "AccessibleChess"
                coordinator, _, _ = self._prepare_interrupted(root)
                journal_path = root / ".v2-upgrade-state.json"
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
                journal[field] = current + 1
                journal_path.write_text(
                    json.dumps(journal, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError, "target schema"
                ):
                    coordinator.recover_interrupted()
                self.assertEqual(
                    json.loads(journal_path.read_text(encoding="utf-8"))[field],
                    current + 1,
                )

    def test_restore_verifies_tracked_destination_before_claiming_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            coordinator, _, _ = self._prepare_interrupted(root)
            journal_path = root / ".v2-upgrade-state.json"
            original_copy = upgrade_module._stable_copy

            def corrupt_after_copy(source: Path, destination: Path):
                result = original_copy(source, destination)
                if destination == root / "settings.json":
                    destination.write_bytes(b'{"corrupt":')
                return result

            with mock.patch(
                "acs.version2_upgrade._stable_copy",
                side_effect=corrupt_after_copy,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeRecoveryError, "readback"
                ):
                    coordinator.recover_interrupted()

            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(journal["phase"], "migrating")


if __name__ == "__main__":
    unittest.main()
