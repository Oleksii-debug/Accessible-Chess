"""Section 37 complete advanced-training work-type, language, legal/format evidence matrix."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/corpus/SECTION37_UK_EN_HIGH_LEVEL_REFERENCE_MATRIX.json"
UK = ROOT / "tests/real_corpus/advanced_training/section37-advanced-workbook-uk.md"
EN = ROOT / "tests/real_corpus/advanced_training/section37-advanced-workbook-en.md"


class Section37BothLanguageWorktypeMatrix(unittest.TestCase):
    def test_all_advanced_work_types_have_separate_uk_en_literature_and_no_beginners(self):
        source = json.loads(MATRIX.read_text(encoding="utf-8"))
        wanted = {
            "calculation", "tactics", "composed_studies", "openings",
            "middlegame", "endgame", "annotated_games", "databases",
        }
        self.assertEqual({x["work_type"] for x in source["worktypes"]}, wanted)
        self.assertEqual(len(source["worktypes"]), 8)
        self.assertFalse(source["full_foreign_paid_books_included"])
        self.assertFalse(source["translations_of_protected_books_included"])
        for part in source["worktypes"]:
            with self.subTest(work_type=part["work_type"]):
                self.assertEqual(set(part["languages"]), {"uk", "en"})
                self.assertEqual(part["min_required_level"], "first category or higher")
                self.assertTrue(all(part["languages"][lang]["language_verified"] for lang in ("uk", "en")))
                self.assertTrue(all(
                    part["languages"][lang]["available_advanced_material"] ==
                    "original_project_authored_bilingual_workbook"
                    for lang in ("uk", "en")
                ))
                self.assertFalse(part["english_external_advanced_bibliography"]["acquired_full_book"])
                self.assertEqual(
                    part["english_external_advanced_bibliography"]["public_distribution"],
                    "NOT_AUTHORIZED",
                )
                self.assertTrue(
                    part["english_external_advanced_bibliography"]["verified_primary_source_page"].startswith("https://")
                )

    def test_all_program_format_families_have_separate_truthed_read_status(self):
        d = json.loads(MATRIX.read_text(encoding="utf-8"))
        status = d["workbook_format_status"]
        self.assertEqual(set(status), {
            "txt", "md", "html", "epub", "docx", "pdf", "pgn", "epd",
            "fen", "cbh", "cbv", "cbf", "two_cbh", "cbone",
        })
        self.assertIn("independently qualified", status["pdf"])
        for key in ("cbv", "cbf", "two_cbh", "cbone"):
            self.assertIn("No legally full authentic source qualified", status[key])
        self.assertIn("no implicit chess", status["txt"].lower())
        self.assertIn("BookEpubImport", status["epub"])
        self.assertIn("BookDocxImport", status["docx"])
        paid = d["ukrainian_external_book_status"]
        self.assertFalse(paid["imported_into_accessible_chess"])
        self.assertFalse(paid["listed_as_owner_test_file"])
        self.assertFalse(paid["full_original_rights_to_redistribute"])
        self.assertTrue(paid["owner_reading_policy"].startswith("NO_PAID"))
        self.assertFalse(d["external_publication_is_program_content"])
        for track in d["worktypes"]:
            self.assertEqual(track["ukrainian_external_verified_references"], [])
            self.assertEqual(
                track["usable_in_accessible_chess"]["paid_external_book"],
                "NOT_IMPORTED_NOT_INCLUDED",
            )

    def test_actual_both_language_shareable_markdown_is_full_source_not_only_index(self):
        a = UK.read_text(encoding="utf-8")
        b = EN.read_text(encoding="utf-8")
        self.assertIn("Майстерська шахова лабораторія", a)
        self.assertIn("Advanced Chess Laboratory", b)
        self.assertEqual(a.count("```fen"), 12)
        self.assertEqual(b.count("```fen"), 12)
        self.assertIn("Складність задачі Lichess", a)
        self.assertIn("Lichess puzzle difficulty", b)
        self.assertIn("Відповіді після", a)
        self.assertIn("Solutions", b)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
