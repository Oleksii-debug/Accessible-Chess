"""Owner shareability policy: no paid/unimported Ivan or other store catalog masquerades as a book."""
from __future__ import annotations

import json
from pathlib import Path
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
