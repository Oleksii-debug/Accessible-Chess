from __future__ import annotations

"""Narrow Section-51 owner-data export/import behavioral acceptance tests."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
import acs.user_data_transfer as transfer_module
from acs.version2_package_assembler import Version2PackageAssemblyError
from acs.user_data_transfer import (
    UserDataTransferError,
    export_owner_profile,
    import_owner_profile,
)
from acs.version2_upgrade import UserDataLayout


class OwnerDataTransferTests(unittest.TestCase):
    def _source(self, parent: Path) -> Path:
        root = parent / "AccessibleChess"
        root.mkdir()
        (root / "settings.json").write_text(
            json.dumps({"language": "uk", "volume": 36}), encoding="utf-8"
        )
        (root / "books").mkdir()
        (root / "books" / "мої-уроки.txt").write_text(
            "Варіант: 1. e4 e5\n", encoding="utf-8"
        )
        for folder, name, payload in (
            ("media", "timeline.json", b'{"timeline":42}\n'),
            ("agent-jobs", "draft.txt", b"private user question\n"),
            ("training-progress", "lesson.json", b'{"level":3}\n'),
            ("accounts", "profile.json", b'{"user":"owner"}\n'),
        ):
            target = root / folder
            target.mkdir()
            (target / name).write_bytes(payload)
        with AcsDatabase(root / "library.acsdb") as database:
            database.add_source("Особисті партії.pgn", "pgn")
        return root

    def test_export_import_fresh_root_preserves_all_owner_bytes_and_migrates(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            parent = base / "original"
            parent.mkdir()
            source = self._source(parent)
            source_files = {
                str(p.relative_to(source)): p.read_bytes()
                for p in source.rglob("*")
                if p.is_file() and p.name != "library.acsdb"
            }
            exported = export_owner_profile(UserDataLayout(source))
            self.assertTrue((exported / "manifest.json").is_file())
            self.assertTrue((exported / "data" / "library.acsdb").is_file())
            self.assertEqual(exported.parent.name, "AccessibleChess.upgrade-backups")

            destination = base / "another-pc" / "AccessibleChess"
            destination.parent.mkdir()
            self.assertEqual(import_owner_profile(exported, destination), "upgraded")
            for name, expected in source_files.items():
                # The settings V1->V2 migration changes its serialization.
                if name == "settings.json":
                    continue
                with self.subTest(name=name):
                    self.assertEqual((destination / name).read_bytes(), expected)
                    self.assertEqual((source / name).read_bytes(), expected)
            settings = json.loads((destination / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["schema_version"], 2)
            self.assertEqual(settings["values"]["language"], "uk")
            self.assertEqual(settings["values"]["volume"], 36)
            with AcsDatabase(destination / "library.acsdb") as db:
                self.assertEqual(db.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(db.get_source(1)["source_name"], "Особисті партії.pgn")
            self.assertTrue((destination.parent / "AccessibleChess.upgrade-backups").is_dir())

    def test_backup_byte_tamper_refuses_without_creating_destination(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = self._source(parent)
            exported = export_owner_profile(UserDataLayout(source))
            book = exported / "data" / "books" / "мої-уроки.txt"
            before = book.read_bytes()
            book.write_bytes(before[:-1] + b"X")
            destination = parent / "new-user"
            with self.assertRaisesRegex(UserDataTransferError, "manifest|digest"):
                import_owner_profile(exported, destination)
            self.assertFalse(destination.exists())
            self.assertEqual((source / "books" / "мої-уроки.txt").read_text(
                encoding="utf-8"
            ), "Варіант: 1. e4 e5\n")

    def test_manifest_path_traversal_refused_before_any_target_write(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = self._source(parent)
            exported = export_owner_profile(UserDataLayout(source))
            path = exported / "manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["entries"][0]["path"] = "../outside.txt"
            path.write_text(json.dumps(data), encoding="utf-8")
            destination = parent / "fresh"
            with self.assertRaises(UserDataTransferError):
                import_owner_profile(exported, destination)
            self.assertFalse(destination.exists())
            self.assertFalse((parent / "outside.txt").exists())

    def test_existing_destination_never_replaced_even_with_valid_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = self._source(parent)
            exported = export_owner_profile(UserDataLayout(source))
            target = parent / "existing"
            target.mkdir()
            (target / "owner.txt").write_bytes(b"preserve")
            with self.assertRaisesRegex(UserDataTransferError, "already exists"):
                import_owner_profile(exported, target)
            self.assertEqual((target / "owner.txt").read_bytes(), b"preserve")

    def test_publication_race_never_overwrites_foreign_new_profile(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = self._source(parent)
            exported = export_owner_profile(UserDataLayout(source))
            destination = parent / "new-owner"
            real_publish = transfer_module._publish_directory_no_replace

            def foreign_profile_appears(stage: Path, output: Path) -> None:
                if output == destination:
                    destination.mkdir()
                    (destination / "foreign.txt").write_bytes(b"never overwrite")
                    raise Version2PackageAssemblyError("destination appeared")
                return real_publish(stage, output)

            with mock.patch.object(
                transfer_module,
                "_publish_directory_no_replace",
                side_effect=foreign_profile_appears,
            ):
                with self.assertRaises(UserDataTransferError):
                    import_owner_profile(exported, destination)
            self.assertEqual(
                (destination / "foreign.txt").read_bytes(), b"never overwrite"
            )

    def test_future_schema_blocks_staged_import_without_touching_target(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = self._source(parent)
            (source / "settings.json").write_text(
                json.dumps({"schema_version": 999, "values": {"language": "uk"}}),
                encoding="utf-8",
            )
            exported = export_owner_profile(UserDataLayout(source))
            destination = parent / "fresh"
            with self.assertRaises(UserDataTransferError):
                import_owner_profile(exported, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(
                json.loads((source / "settings.json").read_text(encoding="utf-8"))[
                    "schema_version"
                ],
                999,
            )

    def test_preexisting_target_backup_history_is_never_merged_or_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = self._source(parent)
            exported = export_owner_profile(UserDataLayout(source))
            destination = parent / "new-user"
            existing = parent / "new-user.upgrade-backups"
            existing.mkdir()
            (existing / "receipt.txt").write_bytes(b"historical state")
            with self.assertRaisesRegex(UserDataTransferError, "already exists"):
                import_owner_profile(exported, destination)
            self.assertEqual((existing / "receipt.txt").read_bytes(), b"historical state")
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
