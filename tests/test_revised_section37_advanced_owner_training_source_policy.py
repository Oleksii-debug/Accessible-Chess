"""Owner first-category-to-GM source selection and blinded-tournament rights truth."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from acs.lawful_corpus_registry import (
    LawfulCorpusError, _https_url, load_catalog, verified_local_source,
)

ROOT = Path(__file__).resolve().parents[1]
ADVANCED = ROOT / "tests/real_corpus/advanced_training/lichess_cc0_advanced_puzzles_100_sample.json"
SYLLABUS = ROOT / "docs/corpus/SECTION37_ADVANCED_MASTER_TRAINING_UK.md"


class OwnerLevelAndProvenanceTests(unittest.TestCase):
    def test_genuine_curated_cc0_advanced_puzzles_match_exact_corpus_sha(self):
        source = {r["id"]: r for r in load_catalog()}
        record = source["lichess_cc0_advanced_16_original_derived"]
        self.assertEqual(record["local_source"], "tests/real_corpus/advanced_training/lichess_cc0_advanced_puzzles_100_sample.json")
        self.assertEqual(record["license"].split(" ")[0], "CC0-1.0")
        self.assertEqual(record["redistribution"], "permitted")
        self.assertEqual(record["acquisition"], "VENDORED_SOURCE_VERIFIED")
        verified_local_source(ADVANCED, record)
        self.assertEqual(hashlib.sha256(ADVANCED.read_bytes()).hexdigest(), record["sha256"])
        data = json.loads(ADVANCED.read_text(encoding="utf-8"))
        self.assertEqual(data["retained_count"], 16)
        self.assertEqual(data["source_count"], 100)
        self.assertTrue(all(item["rating"] >= 2200 for item in data["puzzles"]))
        self.assertEqual(sum(x["rating"] >= 3000 for x in data["puzzles"]), 0)
        self.assertEqual(
            data["source_original_git_blob"],
            source["lichess_cc0_combined_original_100_source"]["upstream_git_blob"],
        )

    def test_full_50k_and_latest_puzzle_database_remain_truthfully_unqualified(self):
        source = {r["id"]: r for r in load_catalog()}
        original = source["lichess_cc0_combined_original_50000_source"]
        self.assertEqual(original["upstream_git_blob"], "c72d5988f2aa5caf634d90e130688b26525be33e")
        self.assertEqual(original["acquisition"], "SOURCE_PAGE_ONLY")
        self.assertIsNone(original["sha256"])
        self.assertIsNone(original["download_url"])
        self.assertEqual(original["license"], "CC0-1.0 original Lichess data, source README and LICENSE")
        dynamic = source["lichess_official_complete_puzzle_database_dynamic"]
        self.assertEqual(dynamic["acquisition"], "SOURCE_PAGE_ONLY")
        self.assertIsNone(dynamic["sha256"])
        self.assertEqual(dynamic["max_bytes"], 0)
        self.assertIsNone(dynamic["download_url"])

    def test_blind_championships_are_real_discoveries_not_fake_downloaded_games(self):
        source = {r["id"]: r for r in load_catalog()}
        ids = (
            "ibca_13th_world_individual_real_351_games",
            "ibca_2026_world_team_petrovac_game_search",
            "ibca_2025_world_individual_classical_game_search",
            "ibca_2025_world_individual_rapid_game_search",
            "uk_bca_2026_classical_championship_results",
        )
        for ident in ids:
            with self.subTest(source=ident):
                item = source[ident]
                self.assertEqual(item["acquisition"], "SOURCE_PAGE_ONLY")
                self.assertEqual(item["redistribution"], "NOT_CLEARED")
                self.assertEqual(item["public_release"], "EXCLUDED")
                self.assertEqual(item["test_access"], "EXTERNAL_LINK_ONLY")
                self.assertIsNone(item["download_url"])
                self.assertIsNone(item["sha256"])
                self.assertEqual(
                    item["source_page"],
                    _https_url(item["source_page"], source_page=True),
                )
                with self.assertRaises(LawfulCorpusError):
                    _https_url(item["source_page"])  # metadata not a download authority
        thirteen = source[ids[0]]
        self.assertEqual(thirteen["external_search_page_reported_game_count"], 351)
        self.assertIn("PGN", thirteen["notes"])
        self.assertIn("128264", thirteen["event_link"])

    def test_authentic_composed_study_scope_is_distinct_from_practical_endgames(self):
        source = {r["id"]: r for r in load_catalog()}
        source_page = source["chessbase_online_genuine_endgame_studies"]
        self.assertEqual(source_page["acquisition"], "SOURCE_PAGE_ONLY")
        self.assertEqual(source_page["public_release"], "EXCLUDED")
        self.assertIsNone(source_page["sha256"])
        text = SYLLABUS.read_text(encoding="utf-8")
        self.assertIn("Dvoretsky", text)
        self.assertIn("Pervakov", text)
        self.assertIn("Timman", text)
        self.assertIn("Kling", text)
        self.assertIn("Horwitz", text)
        self.assertIn("Chess Studies", text)
        self.assertIn("351", text)
        self.assertIn("NVDA", text)
        self.assertIn("NOT DONE", text)
        self.assertIn("Lichess puzzle rating", text)
        self.assertIn("FIDE", text)


if __name__ == "__main__":
    unittest.main()
