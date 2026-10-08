"""Source-bound Section 39 to 40 offline product acceptance tests."""
from __future__ import annotations
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
            self.assertEqual(evidence["real_library_games"], 516)
            self.assertEqual(evidence["original_annotated_games"], 4)
            self.assertEqual(evidence["advanced_training_original_tasks"], 16)
            self.assertEqual(evidence["extreme_training_original_tasks"], 4)
            self.assertEqual(evidence["book_document_reopen"], "PASS")
            self.assertEqual(evidence["bilingual_advanced_chess_positions"], "PASS")
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
