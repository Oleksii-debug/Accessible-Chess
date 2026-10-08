"""Section 40 no-owner-overwrite executable-package composition qualification.

Uses EXISTING Windows Version 2 prepared-package fixtures and the canonical
assembler: a structurally valid synthetic PE is not an actual installed EXE.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from acs.user_library_seed import BUNDLE_KIND, SCHEMA_VERSION
from tests.test_version2_package_preflight import _make_tree, _SHA
from tools.revised_section40_offline_test_library import (
    OfflineCollectionError, build_collection,
)
from tools.revised_section40_windows_qa_assembler import (
    build_section40_windows_test_package,
)

ROOT = Path(__file__).resolve().parents[1]


def _prepared_fixture(work: Path) -> tuple[Path, Path]:
    original = work / "prepared-original"
    original.mkdir()
    _make_tree(original)
    product = original / "AccessibleChess"
    # Do not use a fake unstyled HTML: exercise actual Section41 offline
    # assets together with the real Section40 Windows package contract.
    for relative in (
        "web/index.html",
        "web/assets/accessible_chess_design.css",
        "web/assets/tabler/chess-rook.svg",
        "web/assets/tabler/adjustments.svg",
        "web/assets/tabler/LICENSE",
        "web/assets/tabler/SECTION41_PROVENANCE.json",
        "web/assets/tabler-core/accessibility.css",
        "web/assets/tabler-core/LICENSE",
        "web/assets/tabler-core/SECTION41_CORE_PROVENANCE.json",
    ):
        destination = product / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    return product, original / "THIRD_PARTY_NOTICES"


class Section40RealWindowsQAPackageTests(unittest.TestCase):
    def test_actual_canonical_windows_package_assembles_and_reimports_516(self):
        with tempfile.TemporaryDirectory(prefix="section40-canonical-win-") as temp:
            root = Path(temp)
            product, notices = _prepared_fixture(root)
            collection = root / "licensed-corpus.zip"
            output = root / "owner-test.zip"
            build_collection("TEST_BUILD", collection)
            before = hashlib.sha256(
                (product / "web/index.html").read_bytes()
            ).hexdigest()
            report = build_section40_windows_test_package(
                product, notices, collection, output, exact_source_sha=_SHA)
            self.assertEqual(report["seed_sources"], 3)
            self.assertEqual(report["seed_games"], 517)
            self.assertEqual(report["restart_reused_sources"], 3)
            self.assertEqual(report["original_seed_files_untouched"], 0)
            self.assertTrue(report["canonical_version2_package_readback"])
            self.assertEqual(report["section37_native_bilingual_books_verified"], 10)
            self.assertEqual(report["section37_authentic_advanced_lessons"], 12)
            self.assertEqual(len(report["section37_workbook_source_sha256"]), 64)
            self.assertFalse(report["compiled_real_exe_attested"])
            self.assertFalse(report["section40_done"])
            self.assertEqual(before, hashlib.sha256(
                (product / "web/index.html").read_bytes()).hexdigest())
            with zipfile.ZipFile(output) as archive:
                members = set(archive.namelist())
                self.assertIn("AccessibleChess/web/assets/tabler-core/LICENSE", members)
                self.assertIn("AccessibleChess/web/assets/accessible_chess_design.css", members)
                self.assertIn(
                    "AccessibleChess/release-content/user-library-seed/manifest.json",
                    members,
                )
                manifest = json.loads(archive.read(
                    "AccessibleChess/release-content/user-library-seed/manifest.json"))
                self.assertEqual(len(manifest["files"]), 3)
                self.assertIn("section40-original-reti-1921-uk-en-study.pgn",
                              [item["file"] for item in manifest["files"]])
                self.assertEqual(manifest["bundle_kind"], BUNDLE_KIND)
                self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
                # The actual reviewed offline library ships IN the Windows QA
                # package, not merely as a separate builder artifact.
                archive_path = "AccessibleChess/release-content/section40/"
                self.assertIn(archive_path + "TEST_COLLECTION.zip", members)
                self.assertIn(archive_path + "READ_FIRST_UK.txt", members)
                self.assertIn(archive_path + "READ_FIRST_EN.txt", members)
                self.assertIn(b"517", archive.read(archive_path + "READ_FIRST_UK.txt"))
                self.assertIn(b"517", archive.read(archive_path + "READ_FIRST_EN.txt"))
                corpus_zip = archive.read(archive_path + "TEST_COLLECTION.zip")
                self.assertEqual(
                    hashlib.sha256(corpus_zip).hexdigest(),
                    report["bundled_offline_collection_sha256"],
                )
                with zipfile.ZipFile(BytesIO(corpus_zip)) as corpus:
                    self.assertIn("catalog/materials.json", corpus.namelist())
                    self.assertIn("books/advanced-lichess-16-en.json", corpus.namelist())
                    self.assertIn("training/extreme-lichess-4-original-puzzles.json", corpus.namelist())
                    self.assertIn("library/original-reti-1921-uk-en-study.pgn", corpus.namelist())
                    metadata = json.loads(corpus.read("catalog/materials.json"))
                    self.assertEqual(metadata["profile"], "TEST_BUILD")
                    bilingual = [
                        entry for entry in metadata["materials"]
                        if entry["id"].startswith("section37_bilingual_original_workbook_")
                    ]
                    self.assertEqual(len(bilingual), 10)
                    self.assertEqual(
                        {(item["language"], item["format"]) for item in bilingual},
                        {(lang, extension) for lang in ("uk", "en")
                         for extension in ("txt", "md", "html", "docx", "epub")},
                    )
                    for entry in bilingual:
                        source = corpus.read(entry["source_path"])
                        self.assertEqual(entry["sha256"], hashlib.sha256(source).hexdigest())
                        self.assertEqual(entry["size_bytes"], len(source))
                        self.assertEqual(entry["original_lesson_count"], 12)
                    self.assertIn(
                        "books/section37-advanced-workbook-uk.epub", corpus.namelist()
                    )
                    self.assertIn(
                        "books/section37-advanced-workbook-en.docx", corpus.namelist()
                    )


    def test_existing_private_seed_is_preserved_and_extended_only_in_disposable_qa(self):
        with tempfile.TemporaryDirectory(prefix="acs-section40-existing-seed-") as temp:
            root = Path(temp)
            product, notices = _prepared_fixture(root)
            seed = product / "release-content" / "user-library-seed"
            seed.mkdir(parents=True)
            original_pgn = b'[Event "Owner"]\n[Result "*"]\n\n1. e4 e5 *\n'
            (seed / "original-owner.pgn").write_bytes(original_pgn)
            old = {
                "schema_version": SCHEMA_VERSION,
                "bundle_kind": BUNDLE_KIND,
                "runtime_network_required": False,
                "ai_required": False,
                "files": [{
                    "file": "original-owner.pgn",
                    "display_name": "Owner existing private PGN",
                    "bytes": len(original_pgn),
                    "sha256": hashlib.sha256(original_pgn).hexdigest(),
                }],
            }
            manifest = seed / "manifest.json"
            manifest.write_text(json.dumps(old) + "\n", encoding="utf-8")
            old_manifest = manifest.read_bytes()
            collection = root / "collection.zip"
            build_collection("TEST_BUILD", collection)
            output = root / "preserved-test-build.zip"
            report = build_section40_windows_test_package(
                product, notices, collection, output, exact_source_sha=_SHA)
            self.assertEqual(report["seed_sources"], 4)
            self.assertEqual(report["seed_games"], 518)
            self.assertEqual(report["original_seed_files_untouched"], 1)
            self.assertEqual(manifest.read_bytes(), old_manifest)
            self.assertEqual((seed / "original-owner.pgn").read_bytes(), original_pgn)
            with zipfile.ZipFile(output) as archived:
                payload = json.loads(archived.read(
                    "AccessibleChess/release-content/user-library-seed/manifest.json"))
                self.assertEqual(len(payload["files"]), 4)
                self.assertEqual(payload["files"][0], old["files"][0])

    def test_public_only_archive_must_not_become_rich_windows_test_build(self):
        with tempfile.TemporaryDirectory(prefix="section40-public-win-refuse-") as temp:
            root = Path(temp)
            product, notices = _prepared_fixture(root)
            collection = root / "public-corpus.zip"
            build_collection("PUBLIC_RELEASE", collection)
            target = root / "must-not-exist.zip"
            with self.assertRaises(OfflineCollectionError):
                build_section40_windows_test_package(
                    product, notices, collection, target, exact_source_sha=_SHA)
            self.assertFalse(target.exists())

    def test_owner_zip_no_overwrite_even_if_data_not_yet_checked(self):
        with tempfile.TemporaryDirectory(prefix="section40-output-guard-") as temp:
            root = Path(temp)
            target = root / "owner-test.zip"
            target.write_bytes(b"existing user archive")
            with self.assertRaises(OfflineCollectionError):
                build_section40_windows_test_package(
                    root / "missing-product", root / "missing-notices",
                    root / "missing-corpus", target, exact_source_sha=_SHA)
            self.assertEqual(target.read_bytes(), b"existing user archive")


if __name__ == "__main__":
    unittest.main()
