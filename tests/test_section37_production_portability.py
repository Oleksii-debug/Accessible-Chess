from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from acs.acsdb import AcsDatabase
from acs.full_product_actions import build_full_product_action_registry
from acs.full_product_native_menu import build_full_product_menu_spec
from acs.full_product_ui_shell import UILanguage
from acs.settings import Settings
from acs.version2_upgrade import UserDataLayout
from acs.version2_user_data_archive import (
    Version2UserDataArchiveError,
    Version2UserDataArchiveService,
    Version2UserDataHost,
    begin_pending_user_data_transaction,
    validate_user_data_archive,
)


class _Dialogs:
    def __init__(self, *, save: Path | None = None, open_: Path | None = None):
        self.save = save
        self.open = open_
        self.saved_kind = None
        self.opened_kind = None

    def save_user_data_archive(self, kind: str):
        self.saved_kind = kind
        return self.save

    def open_user_data_archive(self, kind: str):
        self.opened_kind = kind
        return self.open


def _write_settings(root: Path, language: str) -> None:
    settings = Settings(root / "settings.json")
    settings.set("language", language)


class Section37ProductionPortabilityTests(unittest.TestCase):
    def test_portable_export_excludes_credentials_but_backup_preserves_them(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data"
            root.mkdir()
            _write_settings(root, "en")
            (root / "profile.json").write_text('{"name":"Owner"}\n', encoding="utf-8")
            (root / "account-token.json").write_text("secret\n", encoding="utf-8")
            database = AcsDatabase(root / "library.acsdb")
            try:
                service = Version2UserDataArchiveService(
                    UserDataLayout(root),
                    live_database=database,
                )
                portable = Path(td) / "user.acsdata"
                backup = Path(td) / "user.acsbackup"
                portable_receipt = service.create_archive(portable, kind="portable")
                backup_receipt = service.create_archive(backup, kind="backup")
            finally:
                database.close()

            self.assertEqual(portable_receipt.kind, "portable")
            self.assertEqual(backup_receipt.kind, "backup")
            portable_manifest = validate_user_data_archive(
                portable,
                expected_kind="portable",
                settings_name="settings.json",
                library_name="library.acsdb",
            )
            backup_manifest = validate_user_data_archive(
                backup,
                expected_kind="backup",
                settings_name="settings.json",
                library_name="library.acsdb",
            )
            self.assertNotIn(
                "account-token.json",
                {entry.path for entry in portable_manifest.entries},
            )
            self.assertIn(
                "account-token.json",
                {entry.path for entry in backup_manifest.entries},
            )
            self.assertIn(
                "library.acsdb",
                {entry.path for entry in portable_manifest.entries},
            )

    def test_portable_import_is_published_on_startup_and_preserves_local_secret(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            _write_settings(source, "en")
            _write_settings(target, "uk")
            (source / "profile.json").write_text("source-profile\n", encoding="utf-8")
            (target / "profile.json").write_text("target-profile\n", encoding="utf-8")
            (target / "account-token.json").write_text("local-secret\n", encoding="utf-8")

            archive = base / "portable.acsdata"
            Version2UserDataArchiveService(UserDataLayout(source)).create_archive(
                archive,
                kind="portable",
            )
            service = Version2UserDataArchiveService(UserDataLayout(target))
            service.stage_import(archive, expected_kind="portable")

            tx = begin_pending_user_data_transaction(UserDataLayout(target))
            self.assertIsNotNone(tx)
            assert tx is not None
            self.assertEqual(
                (target / "profile.json").read_text(encoding="utf-8"),
                "source-profile\n",
            )
            self.assertEqual(
                (target / "account-token.json").read_text(encoding="utf-8"),
                "local-secret\n",
            )
            self.assertEqual(Settings(target / "settings.json").get("language"), "en")
            tx.commit()

            self.assertTrue(target.is_dir())
            self.assertFalse(
                (target.parent / f".{target.name}.section37-pending.acsdata").exists()
            )

    def test_pending_import_can_rollback_exact_old_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            (source / "profile.json").write_text("new\n", encoding="utf-8")
            (target / "profile.json").write_text("old\n", encoding="utf-8")
            archive = base / "portable.acsdata"
            Version2UserDataArchiveService(UserDataLayout(source)).create_archive(
                archive,
                kind="portable",
            )
            Version2UserDataArchiveService(UserDataLayout(target)).stage_import(
                archive,
                expected_kind="portable",
            )

            tx = begin_pending_user_data_transaction(UserDataLayout(target))
            self.assertIsNotNone(tx)
            assert tx is not None
            self.assertEqual((target / "profile.json").read_text(), "new\n")
            tx.rollback()
            self.assertEqual((target / "profile.json").read_text(), "old\n")

    def test_archive_rejects_path_traversal_and_undeclared_payload(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "bad.acsdata"
            manifest = {
                "schema_version": 1,
                "kind": "portable",
                "settings_name": "settings.json",
                "library_name": "library.acsdb",
                "entries": [
                    {
                        "path": "../outside.txt",
                        "size": 1,
                        "sha256": "0" * 64,
                    }
                ],
            }
            with zipfile.ZipFile(
                archive,
                "w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as zf:
                zf.writestr(
                    "manifest.json",
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                )
                zf.writestr("data/../outside.txt", b"x")
            with self.assertRaisesRegex(Version2UserDataArchiveError, "path"):
                validate_user_data_archive(archive, expected_kind="portable")

    def test_host_uses_native_dialogs_and_stages_restore_instead_of_live_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "data"
            root.mkdir()
            (root / "profile.json").write_text("original\n", encoding="utf-8")
            database = AcsDatabase(root / "library.acsdb")
            try:
                archive = base / "backup.acsbackup"
                export_dialogs = _Dialogs(save=archive)
                host = Version2UserDataHost(
                    UserDataLayout(root),
                    database,
                    export_dialogs,
                    language_provider=lambda: UILanguage.EN,
                )
                result = host("data.backup", {})
                self.assertTrue(result["ok"])
                self.assertEqual(export_dialogs.saved_kind, "backup")
                self.assertTrue(archive.is_file())

                (root / "profile.json").write_text("changed-after-backup\n", encoding="utf-8")
                restore_dialogs = _Dialogs(open_=archive)
                host = Version2UserDataHost(
                    UserDataLayout(root),
                    database,
                    restore_dialogs,
                    language_provider=lambda: UILanguage.EN,
                )
                restore = host("data.restore", {})
                self.assertTrue(restore["ok"])
                self.assertTrue(restore["restart_required"])
                self.assertEqual(
                    (root / "profile.json").read_text(encoding="utf-8"),
                    "changed-after-backup\n",
                )
                self.assertTrue(
                    (root.parent / f".{root.name}.section37-pending.acsdata").is_file()
                )
            finally:
                database.close()

    def test_native_menu_exposes_all_four_user_data_actions(self):
        registry = build_full_product_action_registry()
        menus = build_full_product_menu_spec(registry, language=UILanguage.EN)
        action_ids = {
            item.action_id
            for menu in menus
            for item in menu.items
            if item.action_id
        }
        self.assertTrue(
            {"data.backup", "data.restore", "data.export", "data.import"}.issubset(
                action_ids
            )
        )


if __name__ == "__main__":
    unittest.main()
