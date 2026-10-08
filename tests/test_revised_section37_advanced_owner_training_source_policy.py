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

    def test_owner_advanced_collection_has_twenty_real_licensed_tasks_and_no_easy_puzzles(self):
        first = json.loads(ADVANCED.read_text(encoding="utf-8"))
        extreme_file = ROOT / "tests/real_corpus/advanced_training/lichess_cc0_extreme_3000_3166_original_puzzles.json"
        extreme = json.loads(extreme_file.read_text(encoding="utf-8"))
        registry = {entry["id"]: entry for entry in load_catalog()}
        qualified = registry["lichess_cc0_extreme_4_original_derived_puzzles"]
        self.assertEqual(qualified["license"], "CC0-1.0")
        verified_local_source(extreme_file, qualified)
        self.assertEqual(first["retained_count"] + extreme["puzzle_count"], 20)
        ids = {p["puzzle_id"] for p in first["puzzles"]}
        for item in extreme["puzzles"]:
            self.assertGreaterEqual(item["puzzle_rating"], 3000)
            self.assertNotIn(item["puzzle_id"], ids)
            self.assertFalse(item["composed_study"])
            self.assertTrue(item["requires_opponent_first_move_before_presenting"])
            ids.add(item["puzzle_id"])
        self.assertEqual(len(ids), 20)
        self.assertEqual(
            sorted(p["puzzle_rating"] for p in extreme["puzzles"]),
            [3000, 3030, 3164, 3166],
        )
        self.assertEqual(
            registry["lichess_cc0_fexd_offline_original_24595_puzzles"]["acquisition"],
            "SOURCE_PAGE_ONLY",
        )
        self.assertIsNone(
            registry["lichess_cc0_fexd_offline_original_24595_puzzles"]["sha256"],
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
            "ibca_2019_world_individual_376_real_pgn_archive",
            "ibca_2017_olympiad_465_real_pgn_archive",
            "ibca_world_team_643262_111_real_pgn_archive",
            "blind_six_nations_2015_historical_game_pgn_archive",
            "ibca_2012_olympiad_india_414_real_pgn_archive",
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
        reference_counts = (
            ("ibca_13th_world_individual_real_351_games", 351, "128264"),
            ("ibca_2019_world_individual_376_real_pgn_archive", 376, "422502"),
            ("ibca_2017_olympiad_465_real_pgn_archive", 465, "281869"),
            ("ibca_2012_olympiad_india_414_real_pgn_archive", 414, "78816"),
            ("ibca_world_team_643262_111_real_pgn_archive", 111, "643262"),
            ("blind_six_nations_2015_historical_game_pgn_archive", 60, "sixnations"),
        )
        self.assertEqual(sum(n for _, n, _ in reference_counts), 1777)
        for key, game_count, event_identifier in reference_counts:
            with self.subTest(tournament=key):
                record = source[key]
                self.assertEqual(record["external_search_page_reported_game_count"], game_count)
                self.assertIn(event_identifier, record["event_link"])
                self.assertEqual(record["public_release"], "EXCLUDED")
                self.assertIsNone(record["sha256"])

    def test_genuine_historical_study_sources_have_authorship_but_no_licensed_original_bytes(self):
        originals = {item["id"]: item for item in load_catalog()}
        for ident, blob in (
            ("grigoriev_historical_original_studies_pgn_unlicensed", "17d0dacf901c5c2fdef68f1d8aa39f70f44890cb"),
            ("kasparian_domination_original_studies_pgn_unlicensed", "f5bf291e576282bfbe1ae85fb6901690267ac4db"),
        ):
            with self.subTest(studies=ident):
                r = originals[ident]
                self.assertEqual(r["upstream_git_blob"], blob)
                self.assertEqual(r["acquisition"], "SOURCE_PAGE_ONLY")
                self.assertEqual(r["redistribution"], "NOT_CLEARED")
                self.assertEqual(r["public_release"], "EXCLUDED")
                self.assertEqual(r["test_access"], "EXTERNAL_LINK_ONLY")
                self.assertIsNone(r["download_url"])
                self.assertIsNone(r["sha256"])
                self.assertEqual(r["max_bytes"], 0)

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
