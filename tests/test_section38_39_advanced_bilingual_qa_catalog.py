"""Truthful CM–GM aspiration, bilingual author rights and format-QA policy.

Pure policy/metadata tests: this is deliberately NOT an original book download
or a full Section 38 / 39 pass. Actual corpus readers and product-level QA
remain responsible for source-byte and user-journey evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit

from acs.format_capabilities import CapabilityStatus, capability_by_id
from acs.lawful_corpus_registry import load_catalog
from acs.section40_advanced_licensed_dataset import bundled_advanced_puzzles
from acs.section40_extreme_licensed_dataset import bundled_extreme_puzzles


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/corpus/SECTION38_39_ADVANCED_BILINGUAL_QA_CATALOG.json"
EXPECTED_FORMATS = frozenset({
    "FEN", "SAN", "EPD", "PGN", "ACSDB", "EPUB", "HTML", "TXT",
    "Markdown", "DOCX", "PDF", "CBH", "CBV", "CBF", "2CBH", "CBONE",
})
PUBLISHER_KINDS = frozenset({
    "PUBLISHER_REFERENCE_NOT_IMPORTED",
    "UKRAINIAN_PUBLISHER_PAGE_ADVANCED_SUBSET_ONLY",
})


class AdvancedBilingualCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def test_expert_only_tracks_have_real_ukrainian_and_english_readable_metadata(self):
        catalog = self.catalog
        self.assertEqual(catalog["official_plan_section_numbers"], [38, 39])
        self.assertEqual(catalog["languages"], ["uk", "en"])
        self.assertEqual(catalog["owner_floor"]["exclude_training_below_lichess_puzzle_rating"], 2200)
        self.assertEqual(catalog["owner_floor"]["rating_scale"],
                         "Lichess puzzle difficulty NOT FIDE Elo")
        self.assertTrue(catalog["distribution_policy"]["all_tracks_have_uk_en_accessible_briefs"])
        tracks = catalog["tracks"]
        self.assertGreaterEqual(len(tracks), 8)
        self.assertEqual(len({track["id"] for track in tracks}), len(tracks))
        for track in tracks:
            with self.subTest(track=track["id"]):
                self.assertIs(track["lower_level_material_permitted"], False)
                self.assertIn("CM_MASTER_IM_GM", track["professional_level"])
                for key in ("title_uk", "title_en", "testing_brief_uk",
                            "testing_brief_en"):
                    self.assertGreater(len(track[key]), 25 if "brief" in key else 8)
                    self.assertLess(len(track[key]), 1024)
                self.assertTrue(track["bibliography"])
                self.assertTrue(track["original_source_candidates"])
        self.assertIn("tactical_sacrifices", {t["id"] for t in tracks})
        self.assertIn("composed_studies", {t["id"] for t in tracks})
        self.assertIn("advanced_endgames", {t["id"] for t in tracks})

    def test_all_external_books_are_references_not_staged_bytes_or_falsely_translated(self):
        self.assertTrue(self.catalog["distribution_policy"]["publisher_links_only"])
        self.assertFalse(self.catalog["distribution_policy"]["protected_full_book_bytes_in_repository"])
        for track in self.catalog["tracks"]:
            for book in track["bibliography"]:
                with self.subTest(track=track["id"],book=book["title"]):
                    self.assertIn(book["kind"], PUBLISHER_KINDS)
                    self.assertEqual(book["rights"],
                                     "COPYRIGHT_OR_EDITIONS_UNVERIFIED_NO_BYTES_INCLUDED")
                    self.assertNotIn("source_sha256", book)
                    self.assertNotIn("local_source", book)
                    self.assertGreater(len(book["title"]), 8)
                    self.assertGreater(len(book["author"]), 6)
                    url = urlsplit(book["url"])
                    self.assertEqual(url.scheme, "https")
                    self.assertTrue(url.netloc)
                    self.assertIsNone(url.username)
                    self.assertIsNone(url.password)
        uk_selective = [
            book for track in self.catalog["tracks"] for book in track["bibliography"]
            if book["kind"] == "UKRAINIAN_PUBLISHER_PAGE_ADVANCED_SUBSET_ONLY"
        ]
        self.assertEqual(len(uk_selective), 1)
        self.assertIn("КМС/МС/ММ", uk_selective[0]["title"])
        self.assertEqual(
            next(t for t in self.catalog["tracks"] if t["id"] == "tactical_sacrifices")
            ["ua_book_language_status"],
            "PUBLISHER_PAGE_IN_UKRAINIAN_BOOK_PRINT_LANGUAGE_NOT_INDEPENDENTLY_VERIFIED",
        )

    def test_all_chess_source_ids_are_registered_and_none_claims_fake_import(self):
        known = {record["id"]: record for record in load_catalog()}
        for track in self.catalog["tracks"]:
            for source in track["original_source_candidates"]:
                with self.subTest(track=track["id"], id=source["catalog_source_id"]):
                    self.assertIn(source["catalog_source_id"], known)
                    self.assertIs(source["origin_bytes_in_this_catalog"], False)
                    self.assertTrue(source["rights"].endswith("VERIFY_BEFORE_RELEASE"))
        self.assertNotIn("downloaded", self.catalog["artifact_kind"].lower())

    def test_all_sixteen_real_format_targets_keep_unsupported_true(self):
        rows = self.catalog["format_qa"]
        self.assertEqual({r["format"] for r in rows}, EXPECTED_FORMATS)
        self.assertEqual(len(rows), 16)
        self.assertEqual(len(set(r["format"] for r in rows)), len(rows))
        for row in rows:
            with self.subTest(format=row["format"]):
                self.assertGreater(len(row["required_real_object"]), 20)
                self.assertGreater(len(row["semantic_readback"]), 20)
                self.assertNotIn("PASS", row["outcome"])
        self.assertEqual(next(r for r in rows if r["format"] == "DOCX")["outcome"],
                         "CURRENTLY_DERIVED_ONLY_NOT_GENUINE_SOURCE")
        self.assertIs(capability_by_id("book-docx").read, CapabilityStatus.PARTIAL)
        self.assertIs(capability_by_id("book-pdf").read, CapabilityStatus.UNSUPPORTED)
        self.assertFalse(self.catalog["distribution_policy"]["no_unsupported_format_promoted_to_pass"] is False)

    def test_real_advanced_offline_datasets_have_no_submaster_puzzles(self):
        advanced = bundled_advanced_puzzles()
        extreme = bundled_extreme_puzzles()
        self.assertEqual((len(advanced), len(extreme)), (16, 4))
        self.assertTrue(all(type(p["rating"]) is int and p["rating"] >= 2200
                            for p in advanced))
        self.assertTrue(all(type(p["puzzle_rating"]) is int
                            and p["puzzle_rating"] >= 3000 for p in extreme))
        self.assertTrue(self.catalog["distribution_policy"]["no_FIDE_rating_or_title_from_Lichess_puzzle_rating"])


if __name__ == "__main__":
    unittest.main()
