"""Authentic CC0 Lichess extreme >3000 original-source literal proof and negatives."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, verified_local_source
from tools.revised_section37_extreme_licensed_puzzles import (
    CATALOG,
    SOURCE_COMMIT,
    SOURCE_GIT_BLOB,
    verify_original_extreme_records,
)


class Extreme3000OriginalTests(unittest.TestCase):
    def test_exact_original_cc0_3000_plus_puzzles_are_present_and_high_rating(self):
        x = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(x["original_repo_git_blob"], SOURCE_GIT_BLOB)
        self.assertEqual(x["puzzle_count"], 4)
        self.assertEqual(
            [(item["puzzle_id"], item["puzzle_rating"]) for item in x["puzzles"]],
            [("2zH3K", 3000), ("VvOSE", 3030), ("NgGRN", 3164), ("gWyMk", 3166)],
        )
        self.assertTrue(all(item["puzzle_rating"] >= 3000 for item in x["puzzles"]))
        self.assertTrue(all(item["composed_study"] is False for item in x["puzzles"]))
        self.assertTrue(all(item["requires_opponent_first_move_before_presenting"] is True for item in x["puzzles"]))
        self.assertIn("NOT_OBTAINED", x["original_dataset_sha256"])

    def test_canonical_catalog_records_real_original_blob_and_local_curated_sha(self):
        sources = {x["id"]: x for x in load_catalog()}
        original = sources["lichess_cc0_fexd_offline_original_24595_puzzles"]
        self.assertEqual(original["upstream_git_blob"], SOURCE_GIT_BLOB)
        self.assertEqual(original["upstream_commit"], SOURCE_COMMIT)
        self.assertIsNone(original["sha256"])
        self.assertEqual(original["acquisition"], "SOURCE_PAGE_ONLY")
        curated = sources["lichess_cc0_extreme_4_original_derived_puzzles"]
        self.assertEqual(curated["license"], "CC0-1.0")
        self.assertEqual(curated["acquisition"], "VENDORED_SOURCE_VERIFIED")
        self.assertEqual(curated["redistribution"], "permitted")
        verified_local_source(CATALOG, curated)

    def test_exact_original_indexed_rows_required_for_per_source_proof(self):
        x = json.loads(CATALOG.read_text(encoding="utf-8"))
        rows = [""] * 24595
        for p in x["puzzles"]:
            rows[p["original_upstream_zero_based_line"]] = ",".join((
                p["puzzle_id"], p["fen_before_opponent_move"],
                p["uci_moves_opponent_first"], str(p["puzzle_rating"]),
            ))
        data = verify_original_extreme_records(x, rows)
        self.assertEqual(data["qualified_original_extreme_count"], 4)
        self.assertEqual(data["min_lichess_puzzle_rating"], 3000)
        self.assertEqual(data["max_lichess_puzzle_rating"], 3166)
        self.assertFalse(data["fide_rating_or_gm_title_claim"])
        self.assertTrue(data["original_rows_exactly_identical"])
        for p in x["puzzles"]:
            i = p["original_upstream_zero_based_line"]
            original = rows[i]
            rows[i] = original.replace(",", ";", 1)
            with self.assertRaises(LawfulCorpusError):
                verify_original_extreme_records(x, rows)
            rows[i] = original

    def test_junior_spoofed_rating_wrong_blob_duplicate_and_study_spoof_fail_closed(self):
        source = json.loads(CATALOG.read_text(encoding="utf-8"))
        rows = [""] * 24595
        for p in source["puzzles"]:
            rows[p["original_upstream_zero_based_line"]] = ",".join((
                p["puzzle_id"], p["fen_before_opponent_move"],
                p["uci_moves_opponent_first"], str(p["puzzle_rating"]),
            ))
        alterations = [
            {"original_repo_git_blob": "0" * 40},
            {"puzzles": [*source["puzzles"], source["puzzles"][0]]},
            {"puzzles": [{**source["puzzles"][0], "puzzle_rating": 900}, *source["puzzles"][1:]]},
            {"puzzles": [{**source["puzzles"][0], "composed_study": True}, *source["puzzles"][1:]]},
            {"puzzles": [{**source["puzzles"][0], "puzzle_id": "../bad"}, *source["puzzles"][1:]]},
            {"puzzles": [{**source["puzzles"][0], "uci_moves_opponent_first": "e2e4"}, *source["puzzles"][1:]]},
        ]
        for bad in alterations:
            with self.subTest(alteration=tuple(bad)):
                with self.assertRaises(LawfulCorpusError):
                    verify_original_extreme_records({**source, **bad}, rows)


if __name__ == "__main__":
    unittest.main()
