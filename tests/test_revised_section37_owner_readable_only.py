"""Owner shareability policy: no paid/unimported Ivan or other store catalog masquerades as a book."""
from __future__ import annotations

import json
from pathlib import Path
import hashlib
import zipfile
import tempfile
import unittest
from unittest.mock import patch

from acs.version2_application import Version2Application
from acs.pgn_roundtrip import parse_pgn_text
from acs.lawful_corpus_registry import load_catalog
from tools.revised_section37_bilingual_workbook_pack import main as build_main


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/corpus/SECTION37_UK_EN_HIGH_LEVEL_REFERENCE_MATRIX.json"


class RealBookOnlyAcceptance(unittest.TestCase):
    def test_owner_library_never_lists_unavailable_paid_publications(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertFalse(matrix["external_publication_is_program_content"])
        self.assertFalse(matrix["ukrainian_external_book_status"]["imported_into_accessible_chess"])
        self.assertFalse(matrix["ukrainian_external_book_status"]["listed_as_owner_test_file"])
        self.assertTrue(matrix["ukrainian_external_book_status"]["owner_reading_policy"].startswith("NO_PAID"))
        for work in matrix["worktypes"]:
            self.assertEqual(work.get("ukrainian_external_verified_references"), [])
            self.assertEqual(work["usable_in_accessible_chess"]["paid_external_book"],
                             "NOT_IMPORTED_NOT_INCLUDED")
            self.assertFalse(work["english_external_advanced_bibliography"]["acquired_full_book"])
            self.assertEqual(work["english_external_advanced_bibliography"]["catalog_purpose"],
                             "REFERENCE_ONLY_NOT_DELIVERED_AND_NEVER_COUNTED_AS_PRODUCT_WORKBOOK")
        text = MATRIX.read_text(encoding="utf-8")
        self.assertNotIn("Хабінець", text)
        self.assertNotIn("Шахова тактика. Від a до h", text)

    def test_repeated_publish_refuses_to_overwrite_preexisting_book_or_zip(self):
        with tempfile.TemporaryDirectory(prefix="section37-repeat-") as temp:
            root = Path(temp)
            folder = root / "books"
            bundle = root / "bookpack.zip"
            with patch("sys.argv", ["packer", "--output-dir", str(folder),
                                    "--zip-output", str(bundle)]):
                build_main()
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            manifest = (folder / "section37-bilingual-manifest.json").read_bytes()
            with patch("sys.argv", ["packer", "--output-dir", str(folder),
                                    "--zip-output", str(bundle)]):
                with self.assertRaises(FileExistsError):
                    build_main()
            self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), digest)
            self.assertEqual((folder / "section37-bilingual-manifest.json").read_bytes(), manifest)

    def test_failed_mid_build_cleans_unique_partial_output_instead_of_publishing(self):
        with tempfile.TemporaryDirectory(prefix="section37-atomic-") as temp:
            root = Path(temp)
            folder = root / "books"
            bundle = root / "never-publish.zip"
            def abort_after_first_book(args):
                args.output_dir.mkdir()
                (args.output_dir / "partial.epub").write_bytes(b"not-qualified")
                raise ValueError("unit-injected invalid original book content")
            with patch("sys.argv", ["packer", "--output-dir", str(folder),
                                    "--zip-output", str(bundle)]), patch(
                    "tools.revised_section37_bilingual_workbook_pack._build_pack",
                    side_effect=abort_after_first_book):
                with self.assertRaisesRegex(ValueError, "invalid original"):
                    build_main()
            self.assertFalse(folder.exists())
            self.assertFalse(bundle.exists())
            self.assertFalse((root / "never-publish.zip.partial").exists())

    def test_shareable_release_zip_is_licensed_hash_checked_and_reopens_in_real_program(self):
        with tempfile.TemporaryDirectory(prefix="section37-final-uk-en-pack-") as root:
            original = Path(root) / "originals"
            ready_zip = Path(root) / "section37-advanced-uk-en-real-tests.zip"
            with patch("sys.argv", ["pack-builder", "--output-dir", str(original),
                                    "--zip-output", str(ready_zip)]):
                build_main()
            self.assertTrue(ready_zip.is_file())
            with zipfile.ZipFile(ready_zip) as archive:
                self.assertIsNone(archive.testzip())
                names = archive.namelist()
                self.assertEqual(len(names), 14)
                self.assertEqual(set(names), {p.name for p in original.iterdir() if p.is_file()})
                manifest = json.loads(archive.read("section37-bilingual-manifest.json"))
                self.assertEqual(len(manifest["generated_files"]), 13)
                for name, details in manifest["generated_files"].items():
                    with self.subTest(source=name):
                        raw = archive.read(name)
                        self.assertEqual(hashlib.sha256(raw).hexdigest(), details["sha256"])
                        self.assertEqual(len(raw), details["bytes"])
                        restored = Path(root) / "restored" / name
                        restored.parent.mkdir(exist_ok=True)
                        restored.write_bytes(raw)
                        if restored.suffix in (".txt", ".md", ".html", ".epub", ".docx"):
                            imported = Version2Application.prepare_book_open(restored)
                            self.assertGreater(len(imported.document.blocks), 20)

    def test_all_actual_shareable_book_content_is_opened_by_product_not_just_linked(self):
        with tempfile.TemporaryDirectory(prefix="acs-37-real-reader-only-") as root:
            directory = Path(root) / "out"
            with patch("sys.argv", ["builder", "--output-dir", str(directory)]):
                build_main()
            manifest = json.loads((directory / "section37-bilingual-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["generated_files"]), 13)
            for name in sorted(manifest["generated_files"]):
                path = directory / name
                self.assertTrue(path.is_file(), name)
                self.assertGreater(path.stat().st_size, 5)
                if path.suffix in (".md", ".txt", ".html", ".epub", ".docx"):
                    native = Version2Application.prepare_book_open(path)
                    self.assertTrue(native.book_key)
                    self.assertGreater(len(native.document.blocks), 20)
                elif path.suffix == ".pgn":
                    self.assertIn(len(parse_pgn_text(path.read_text(encoding="utf-8"), strict=False)), (1, 4))
                elif path.suffix == ".fen":
                    from acs.chesscore import Board
                    for fen in path.read_text(encoding="utf-8").splitlines():
                        Board(fen)
                else:
                    self.fail("unsupported book/test source smuggled into user pack: " + name)


if __name__ == "__main__":
    unittest.main()
