"""25 professional UA/EN chess genres: provenance and status QA.

This is a metadata-level integrity test, not a claim that a protected English
book or all real proprietary format bytes have been acquired.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit

from acs.lawful_corpus_registry import load_catalog
from acs.section40_advanced_licensed_dataset import bundled_advanced_puzzles
from acs.section40_extreme_licensed_dataset import bundled_extreme_puzzles
from tools.revised_section37_bilingual_workbook_pack import load_advanced_workbook


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/corpus/SECTION38_39_MASTER_GENRES_UA_EN_SOURCE_MATRIX.json"
APPROVED_RIGHTS_BOUNDARIES = {
    "SOURCE_CANDIDATE_REQUIRES_REAL_FORMAT_QUALIFICATION",
    "VENDORED_DERIVED_SOURCE_PINNED",
    "VENDORED_ORIGINAL_PGN_PINNED",
    "VENDORED_ORIGINAL_BYTES_HASH_PINNED",
    "VENDORED_HISTORICAL_BILINGUAL_PGN_PINNED",
    "SOURCE_PAGE_ONLY_RIGHTS_UNCLEARED",
    "SOURCE_PAGE_ONLY_SA_LICENSE",
    "SOURCE_PAGE_ONLY_NOT_DOWNLOADED",
    "PINNED_NOT_DOWNLOADED_IN_THIS_PASS",
    "BLOCKED_NO_LAWFUL_COMPLETE_SAMPLE",
}


class MasterGenresProofTests(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads(SOURCE.read_text(encoding="utf-8"))

    def test_twenty_five_professional_genres_bilingual_with_strict_origin_labels(self):
        data = self.matrix
        self.assertEqual(data["plan"], "SECTION38_AND_39_OF_CANONICAL_0_53")
        self.assertEqual(data["languages"], ["uk", "en"])
        self.assertEqual(data["genre_count"], 25)
        self.assertFalse(data["contains_book_binary"])
        self.assertFalse(data["section38_terminal_done"])
        self.assertFalse(data["section39_terminal_done"])
        genres = data["genres"]
        self.assertEqual(len(genres), 25)
        self.assertEqual(len({g["id"] for g in genres}), 25)
        for item in genres:
            with self.subTest(genre=item["id"]):
                self.assertEqual(item["available_languages_for_self_authored_test_briefs"], ["uk", "en"])
                self.assertGreater(len(item["uk"]), 6)
                self.assertGreater(len(item["en"]), 6)
                self.assertTrue(item["no_beginners"])
                self.assertFalse(item["full_genre_qualification_obtained"])
                self.assertTrue(item["original_or_derived_source_candidates"])
                self.assertTrue(item["tested_material_scope"])
                for row in item["original_or_derived_source_candidates"]:
                    self.assertIn(row["qualification_status"], APPROVED_RIGHTS_BOUNDARIES)
                    # ``PINNED_NOT_DOWNLOADED_IN_THIS_PASS`` records that the
                    # source was deliberately *not* acquired in this run; the
                    # substring must not be mistaken for a PASS verdict.
                    self.assertNotEqual("PASS", row["qualification_status"])

    def test_legal_original_sources_are_registered_and_unsupported_chessbase_stays_blocked(self):
        catalog = {r["id"]: r for r in load_catalog()}
        self.assertGreaterEqual(len(catalog), 50)
        for genre in self.matrix["genres"]:
            for row in genre["original_or_derived_source_candidates"]:
                with self.subTest(genre=genre["id"],id=row["catalog_source_id"]):
                    ident = row["catalog_source_id"]
                    self.assertIn(ident, catalog)
                    source = catalog[ident]
                    status = row["qualification_status"]
                    if status == "VENDORED_ORIGINAL_PGN_PINNED":
                        self.assertEqual(source["acquisition"], "VENDORED_SOURCE_VERIFIED")
                        self.assertEqual(source["format"], "pgn")
                    if status == "SOURCE_PAGE_ONLY_SA_LICENSE":
                        self.assertEqual(source["acquisition"], "SOURCE_PAGE_ONLY")
                    if status == "BLOCKED_NO_LAWFUL_COMPLETE_SAMPLE":
                        self.assertEqual(source["acquisition"], status)
                        self.assertEqual(source["redistribution"], "NOT_CLEARED")
        names = {s["catalog_source_id"] for g in self.matrix["genres"]
                 for s in g["original_or_derived_source_candidates"]}
        self.assertIn("historical_reti_1921_original_bilingual_study_pgn", names)
        self.assertIn("lichess_cc0_high_level_4_original_annotated_games", names)
        self.assertIn("stockfish_frc_openings_epd_zip", names)

    def test_every_external_protected_book_is_only_a_bibliographic_reference(self):
        seen = set()
        for genre in self.matrix["genres"]:
            for book in genre["professional_book_references"]:
                with self.subTest(genre=genre["id"],title=book["title"]):
                    self.assertEqual(book["availability"], "BIBLIOGRAPHY_ONLY_NOT_IMPORTED")
                    self.assertIs(book["book_binary_in_repo"], False)
                    self.assertIs(book["licensed_copy_proven"], False)
                    self.assertNotIn("sha256", book)
                    self.assertGreater(len(book["author"]), 6)
                    self.assertIn(book["language"], {"en", "uk-publisher-page-edition-language-to-verify"})
                    u = urlsplit(book["provider_url"])
                    self.assertEqual(u.scheme, "https")
                    self.assertTrue(u.hostname)
                    self.assertIsNone(u.username)
                    self.assertIsNone(u.password)
                    seen.add(book["title"])
        self.assertGreaterEqual(len(seen), 9)
        self.assertIn("Тактика для всіх — вибірково 200 задач КМС/МС/ММ", seen)
        self.assertIn("Grandmaster Preparation: Calculation", seen)
        self.assertIn("Методика розрахунку в шахах на 5-10 ходів та більше", seen)
        ukrainian = [
            book for genre in self.matrix["genres"]
            for book in genre["professional_book_references"]
            if book.get("isbn") == "978-966-8906-80-0"
        ]
        self.assertEqual(len(ukrainian), 2)
        for book in ukrainian:
            self.assertEqual(book["bibliography_year"], 2025)
            self.assertEqual(book["bibliography_pages"], 135)
            self.assertIn("Вернадського", book["bibliography_provider"])
            self.assertIs(book["edition_language_verified"], False)
            self.assertFalse(book["licensed_copy_proven"])
            self.assertFalse(book["book_binary_in_repo"])

    def test_uk_en_source_authored_workbook_and_all_twenty_licensed_puzzles_survive(self):
        workbook = load_advanced_workbook()
        self.assertEqual(workbook["language_codes"], ["uk", "en"])
        self.assertEqual(len(workbook["lessons"]), 12)
        self.assertTrue(all(len(lesson["uk"]["prompt"]) >= 10
                            and len(lesson["en"]["prompt"]) >= 10
                            for lesson in workbook["lessons"]))
        self.assertEqual(len(bundled_advanced_puzzles()), 16)
        self.assertEqual(len(bundled_extreme_puzzles()), 4)
        self.assertTrue(all(x["rating"] >= 2200 for x in bundled_advanced_puzzles()))
        self.assertTrue(all(x["puzzle_rating"] >= 3000 for x in bundled_extreme_puzzles()))


if __name__ == "__main__":
    unittest.main()
