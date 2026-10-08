from __future__ import annotations

import tempfile
import hashlib
import json
import zipfile
from pathlib import Path
import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.user_data_portability import BundleKind
from acs.version2_upgrade import UserDataLayout
from acs.version2_user_data_portability_host import (
    UserDataArchiveError,
    Version2UserDataPortabilityHost,
    begin_pending_user_data_operation,
    create_user_data_archive,
    schedule_user_data_backup,
    schedule_user_data_restore,
    validate_user_data_archive,
)


class Section37ProductionPortabilityTests(unittest.TestCase):
    def _layout(self, base: Path, name: str = "user") -> UserDataLayout:
        return UserDataLayout(base / name)

    def test_backup_runs_at_startup_and_preserves_live_root(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            layout = self._layout(base)
            layout.root.mkdir()
            (layout.root / "settings.json").write_text('{"v":1}', encoding="utf-8")
            destination = base / "backup.acdata"

            result = schedule_user_data_backup(layout, destination, kind=BundleKind.BACKUP)
            self.assertTrue(result["restart_required"])
            self.assertFalse(destination.exists())

            tx = begin_pending_user_data_operation(layout)
            self.assertIsNone(tx)
            self.assertTrue(destination.is_file())
            self.assertEqual((layout.root / "settings.json").read_text("utf-8"), '{"v":1}')
            manifest = validate_user_data_archive(destination, expected_kind=BundleKind.BACKUP)
            self.assertEqual([entry["path"] for entry in manifest["entries"]], ["settings.json"])

    def test_restore_publication_rolls_back_until_upgrade_commit(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source = base / "source"
            source.mkdir()
            (source / "settings.json").write_text("new", encoding="utf-8")
            archive = base / "backup.acdata"
            create_user_data_archive(source, archive, kind=BundleKind.BACKUP)

            layout = self._layout(base, "target")
            layout.root.mkdir()
            (layout.root / "settings.json").write_text("old", encoding="utf-8")
            schedule_user_data_restore(layout, archive, kind=BundleKind.BACKUP)

            tx = begin_pending_user_data_operation(layout)
            self.assertIsNotNone(tx)
            self.assertEqual((layout.root / "settings.json").read_text("utf-8"), "new")
            tx.rollback()
            self.assertEqual((layout.root / "settings.json").read_text("utf-8"), "old")

    def test_restore_commit_keeps_validated_root(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source = base / "source"
            source.mkdir()
            (source / "settings.json").write_text("new", encoding="utf-8")
            archive = base / "backup.acdata"
            create_user_data_archive(source, archive, kind=BundleKind.BACKUP)

            layout = self._layout(base, "target")
            layout.root.mkdir()
            (layout.root / "settings.json").write_text("old", encoding="utf-8")
            schedule_user_data_restore(layout, archive, kind=BundleKind.BACKUP)
            tx = begin_pending_user_data_operation(layout)
            self.assertIsNotNone(tx)
            tx.commit()

            self.assertEqual((layout.root / "settings.json").read_text("utf-8"), "new")
            self.assertIsNone(begin_pending_user_data_operation(layout))

    def test_portable_import_preserves_machine_local_private_state(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source = base / "source"
            source.mkdir()
            (source / "settings.json").write_text("portable-new", encoding="utf-8")
            (source / "credential-token.txt").write_text("must-not-export", encoding="utf-8")
            archive = base / "portable.acdata"
            create_user_data_archive(source, archive, kind=BundleKind.PORTABLE)
            manifest = validate_user_data_archive(archive, expected_kind=BundleKind.PORTABLE)
            self.assertEqual([entry["path"] for entry in manifest["entries"]], ["settings.json"])

            layout = self._layout(base, "target")
            layout.root.mkdir()
            (layout.root / "settings.json").write_text("portable-old", encoding="utf-8")
            (layout.root / "old-user-note.txt").write_text("remove-me", encoding="utf-8")
            (layout.root / "credential-token.txt").write_text("local-secret", encoding="utf-8")
            schedule_user_data_restore(layout, archive, kind=BundleKind.PORTABLE)
            tx = begin_pending_user_data_operation(layout)
            self.assertIsNotNone(tx)

            self.assertEqual((layout.root / "settings.json").read_text("utf-8"), "portable-new")
            self.assertEqual((layout.root / "credential-token.txt").read_text("utf-8"), "local-secret")
            self.assertFalse((layout.root / "old-user-note.txt").exists())
            tx.commit()


    def test_archive_rejects_windows_ambiguous_member_path(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            archive = base / "malicious.acdata"
            payload = b"x"
            relative = "folder\\\\..\\\\secret.txt"
            manifest = {
                "schema": 1,
                "kind": BundleKind.PORTABLE.value,
                "entries": [{
                    "path": relative,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }],
            }
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("manifest.json", (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\\n").encode())
                zf.writestr(f"data/{relative}", payload)
            with self.assertRaisesRegex(UserDataArchiveError, "unsafe|Windows-portable"):
                validate_user_data_archive(archive, expected_kind=BundleKind.PORTABLE)


    def test_host_uses_native_dialog_results_and_rejects_browser_paths(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            layout = self._layout(base)
            layout.root.mkdir()
            (layout.root / "settings.json").write_text("x", encoding="utf-8")
            destination = base / "chosen.acdata"
            host = Version2UserDataPortabilityHost(
                layout,
                save_dialog=lambda _kind: destination,
                open_dialog=lambda _kind: None,
            )
            result = host("data.backup", {})
            self.assertTrue(result["ok"])
            self.assertTrue(result["restart_required"])
            with self.assertRaisesRegex(UserDataArchiveError, "no browser payload"):
                host("data.backup", {"path": str(base / "attacker.acdata")})

    def test_canonical_action_registry_has_four_data_actions(self):
        ids = {item.action_id for item in build_full_product_action_registry().definitions()}
        self.assertTrue({"data.backup", "data.restore", "data.export", "data.import"}.issubset(ids))

    def test_release_composition_runs_pending_transaction_before_writers_and_binds_native_host(self):
        text = (Path(__file__).resolve().parents[1] / "acs" / "version2_release_app.py").read_text("utf-8")
        begin = text.index("portability_transaction = begin_pending_user_data_operation(layout)")
        settings = text.index("settings = Settings(layout.settings_path)")
        database = text.index("database = AcsDatabase(database_path)")
        self.assertLess(begin, settings)
        self.assertLess(begin, database)
        self.assertIn("portability_transaction.rollback()", text)
        self.assertIn("portability_transaction.commit()", text)
        self.assertIn("application.bind_user_data_portability(portability_host)", text)
        self.assertIn("_Version2OwnedUserDataArchiveDialogs", text)


if __name__ == "__main__":
    unittest.main()
