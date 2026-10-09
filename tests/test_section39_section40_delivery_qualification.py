"""Source-bound Section 39 to 40 offline product acceptance tests."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from acs.lawful_corpus_registry import LawfulCorpusError
from tools.revised_section40_offline_test_library import build_collection
from tools.revised_section40_user_library_seed_bridge import build_owner_test_seed
from tools.section39_section40_delivery_qualification import (
    _inspect_zip, _catalog_data, qualify_built_delivery,
)

class Section39Section40PackagedAcceptanceTests(unittest.TestCase):
    def test_actual_test_public_seed_packages_reopen_and_separate_rights(self):
        with tempfile.TemporaryDirectory(prefix="acs-real-package-qualification-") as temp:
            root = Path(temp)
            trial, release, seed = (root / "trial.zip", root / "release.zip", root / "seed.zip")
            build_collection("TEST_BUILD", trial)
            build_owner_test_seed(trial, seed)
            build_collection("PUBLIC_RELEASE", release)
            evidence = qualify_built_delivery(trial, release, seed)
            self.assertEqual(len(evidence["product_source_commit_sha"]), 40)
            self.assertEqual(evidence["real_library_games"], 516)
            self.assertEqual(evidence["real_516_game_acsdb_backup_restore"], "PASS")
            self.assertEqual(evidence["original_annotated_games"], 4)
            self.assertEqual(evidence["advanced_training_original_tasks"], 16)
            self.assertEqual(evidence["extreme_training_original_tasks"], 4)
            self.assertEqual(evidence["book_document_reopen"], "PASS")
            self.assertEqual(evidence["bilingual_advanced_chess_positions"], "PASS")
            self.assertEqual(evidence["section37_bilingual_native_original_derived_book_files"], 10)
            self.assertEqual(evidence["section37_bilingual_original_lessons"], 12)
            self.assertEqual(evidence["integrated_product_books_menu_12_lessons_uk_en"], "PASS")
            self.assertEqual(len(evidence["product_menu_source_git_blob_sha1"]), 40)
            self.assertEqual(evidence["runtime_user_library_restart"], "PASS")
            self.assertEqual(evidence["public_rights_separation"], "PASS")
            self.assertEqual(len(set(evidence["archive_sha256"].values())), 3)
            self.assertFalse(evidence["section39_terminal_done"])
            self.assertFalse(evidence["section40_terminal_done"])
            self.assertFalse(evidence["windows_exe_packaged_verified"])

    def test_invalid_receipts_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp) / "fake.zip"
            with zipfile.ZipFile(original, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("catalog/materials.json", "{}")
            files, _ = _inspect_zip(original)
            with self.assertRaisesRegex(LawfulCorpusError, "checksum"):
                _catalog_data(files, "PUBLIC_RELEASE")
            with self.assertRaises(LawfulCorpusError):
                qualify_built_delivery(original, original, original)

    def test_public_archive_different_source_commit_fails_even_with_valid_recomputed_hashes(self):
        with tempfile.TemporaryDirectory(prefix="acs-stale-original-build-") as tmp:
            root = Path(tmp)
            trial, public, seed = (
                root / "trial.zip", root / "public.zip", root / "seed.zip"
            )
            build_collection("TEST_BUILD", trial)
            build_owner_test_seed(trial, seed)
            build_collection("PUBLIC_RELEASE", public)
            with zipfile.ZipFile(public) as existing:
                members = {name: existing.read(name) for name in existing.namelist()}
            public_meta = json.loads(members["catalog/materials.json"])
            self.assertEqual(len(public_meta["source_commit_sha"]), 40)
            bogus_sha = ("a" if public_meta["source_commit_sha"][0] != "a" else "b") * 40
            public_meta["source_commit_sha"] = bogus_sha
            metadata_wire = (
                json.dumps(public_meta, sort_keys=True, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            members["catalog/materials.json"] = metadata_wire
            checksum_ledger = json.loads(members["catalog/checksums.json"])
            import hashlib
            for receipt in checksum_ledger:
                if receipt["path"] == "catalog/materials.json":
                    receipt.update(
                        sha256=hashlib.sha256(metadata_wire).hexdigest(),
                        bytes=len(metadata_wire),
                    )
            members["catalog/checksums.json"] = (
                json.dumps(checksum_ledger, sort_keys=True) + "\n"
            ).encode("utf-8")
            mismatched = root / "public-source-rewritten-with-valid-checksums.zip"
            with zipfile.ZipFile(mismatched, "w", zipfile.ZIP_DEFLATED) as rebuilt:
                for member, content in sorted(members.items()):
                    rebuilt.writestr(member, content)
            files, _ = _inspect_zip(mismatched)
            self.assertEqual(
                _catalog_data(files, "PUBLIC_RELEASE")["source_commit_sha"], bogus_sha
            )
            with self.assertRaisesRegex(LawfulCorpusError, "mixed-version"):
                qualify_built_delivery(trial, mismatched, seed)

    def test_public_archive_rejects_original_cbv_even_with_all_its_checksums_regenerated(self):
        with tempfile.TemporaryDirectory(prefix="acs-unlicensed-original-injection-") as tmp:
            root = Path(tmp)
            trial, release, seed = root / "trial.zip", root / "public.zip", root / "seed.zip"
            build_collection("TEST_BUILD", trial)
            build_owner_test_seed(trial, seed)
            build_collection("PUBLIC_RELEASE", release)
            with zipfile.ZipFile(release) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            foreign = "books/publisher-uncleared-original.cbv"
            payload = b"not-a-licensed-chessbase-original"
            members[foreign] = payload
            receipt = json.loads(members["catalog/checksums.json"])
            import hashlib
            receipt.append({
                "path": foreign, "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            })
            members["catalog/checksums.json"] = (
                json.dumps(receipt, sort_keys=True) + "\n"
            ).encode("utf-8")
            tampered = root / "public-with-forged-consistent-source-ledger.zip"
            with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as zip_out:
                for name, content in sorted(members.items()):
                    zip_out.writestr(name, content)
            files, _ = _inspect_zip(tampered)
            self.assertEqual(
                _catalog_data(files, "PUBLIC_RELEASE")["profile"], "PUBLIC_RELEASE",
                "a forged self-consistent checksum ledger should reach the rights denylist",
            )
            with self.assertRaisesRegex(LawfulCorpusError, "unauthorized unregistered file"):
                qualify_built_delivery(trial, tampered, seed)

    def test_zip_traversal_refused_before_extract(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../stolen.pgn", "1. e4 e5 *")
            with self.assertRaisesRegex(LawfulCorpusError, "unsafe packaged"):
                _inspect_zip(path)
            self.assertFalse((Path(temp) / "stolen.pgn").exists())

if __name__ == "__main__":
    unittest.main()
