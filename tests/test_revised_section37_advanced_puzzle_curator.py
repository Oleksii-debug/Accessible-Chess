"""Real, above-first-category CC0 chess-puzzle training source acquisition checks."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.lawful_corpus_registry import LawfulCorpusError
from tools.revised_section37_advanced_puzzle_curator import (
    BANDS, parse_puzzle_line, curate_original_lines, rating_band,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_ADVANCED = ROOT / "tests/real_corpus/advanced_training/lichess_cc0_advanced_puzzles_100_sample.json"


def as_original_json(puzzle):
    return json.dumps({
        "puzzle": {
            "PuzzleId": puzzle["puzzle_id"],
            "FEN": puzzle["fen_before_opponent_move"],
            "Moves": puzzle["uci_moves_with_opponent_first"],
            "Rating": str(puzzle["rating"]),
            "Themes": " ".join(puzzle["themes"]),
            "GameUrl": puzzle["game_url"],
        },
        "game": {"analysis": [], "pgn": "original game intentionally not synthesized"},
    }).encode("utf-8") + b"\n"


class GenuineAdvancedChessCuratorTests(unittest.TestCase):
    def test_genuine_cc0_source_subset_has_no_below_2200_or_fide_claims(self):
        original = json.loads(REAL_ADVANCED.read_text(encoding="utf-8"))
        self.assertEqual(
            original["source_original_git_blob"],
            "d7b86f83c1a355fa511420a36dbdc656a3cc6fef",
        )
        self.assertEqual(original["license"], "CC0-1.0")
        self.assertEqual(original["source_count"], 100)
        self.assertEqual(original["retained_count"], 16)
        self.assertFalse(original["composed_endgame_studies"])
        self.assertEqual(len(original["puzzles"]), 16)
        self.assertTrue(all(p["rating"] >= 2200 for p in original["puzzles"]))
        self.assertEqual(len({p["puzzle_id"] for p in original["puzzles"]}), 16)
        self.assertTrue(any("endgame" in p["themes"] for p in original["puzzles"]))
        self.assertTrue(any("middlegame" in p["themes"] for p in original["puzzles"]))
        self.assertTrue(any("master" in p["themes"] for p in original["puzzles"]))
        self.assertTrue(any(p["rating"] >= 2600 for p in original["puzzles"]))
        self.assertFalse(any(p["rating"] >= 3000 for p in original["puzzles"]))
        self.assertIn("first UCI move", original["display_rule"])

    def test_real_puzzle_readback_recovers_identity_all_moves_themes(self):
        original = json.loads(REAL_ADVANCED.read_text(encoding="utf-8"))
        for p in original["puzzles"]:
            with self.subTest(puzzle=p["puzzle_id"]):
                actual = parse_puzzle_line(as_original_json(p))
                self.assertEqual(actual["puzzle_id"], p["puzzle_id"])
                self.assertEqual(actual["puzzle_rating"], p["rating"])
                self.assertEqual(actual["themes"], p["themes"])
                self.assertEqual(
                    actual["uci_moves_opponent_first"],
                    p["uci_moves_with_opponent_first"],
                )
                self.assertEqual(actual["fen_before_opponent_move"], p["fen_before_opponent_move"])
                self.assertEqual(actual["source_game"], p["game_url"])
                self.assertFalse(actual["composed_study"])
                self.assertTrue(actual["lichess_rating_not_fide"])

    def test_original_16_can_recurate_deterministically_and_exclude_junior_rows(self):
        original = json.loads(REAL_ADVANCED.read_text(encoding="utf-8"))
        all_rows = [as_original_json(p) for p in original["puzzles"]]
        result = curate_original_lines(all_rows, max_selected=50)
        self.assertEqual(result["original_rows_seen"], 16)
        self.assertEqual(len(result["puzzles"]), 16)
        self.assertEqual(result["eligible_original_count_by_band"], {
            BANDS[0]: 15, BANDS[1]: 1, BANDS[2]: 0,
        })
        self.assertEqual({x["puzzle_id"] for x in result["puzzles"]},
                         {x["puzzle_id"] for x in original["puzzles"]})
        below = dict(original["puzzles"][0], puzzle_id="START", rating=500)
        modified = curate_original_lines([as_original_json(below)] + all_rows)
        self.assertEqual(modified["original_rows_seen"], 17)
        self.assertEqual(len(modified["puzzles"]), 16)

    def test_high_puzzle_tiers_are_not_fide_or_titles(self):
        self.assertIsNone(rating_band(2199))
        self.assertEqual(rating_band(2200), BANDS[0])
        self.assertEqual(rating_band(2599), BANDS[0])
        self.assertEqual(rating_band(2600), BANDS[1])
        self.assertEqual(rating_band(2999), BANDS[1])
        self.assertEqual(rating_band(3000), BANDS[2])
        self.assertIsNone(rating_band(5001))
        self.assertIsNone(rating_band("3000"))

    def test_malformed_external_game_and_solution_metadata_rejected(self):
        original = json.loads(REAL_ADVANCED.read_text(encoding="utf-8"))["puzzles"][0]
        for bad in (
            {"puzzle_id": "../etc"},
            {"fen_before_opponent_move": "bad fen"},
            {"uci_moves_with_opponent_first": "e2e4"},
            {"uci_moves_with_opponent_first": "evil 0a0a"},
            {"game_url": "https://not-lichess.example/abcdEF12#3"},
            {"themes": []},
            {"rating": 6000},
        ):
            with self.subTest(bad=bad):
                row = as_original_json({**original, **bad})
                if "rating" in bad:
                    self.assertIsNone(parse_puzzle_line(row))
                else:
                    with self.assertRaises(LawfulCorpusError):
                        parse_puzzle_line(row)

    def test_invalid_puzzle_identity_duplicate_and_capacity_fail_closed(self):
        original = json.loads(REAL_ADVANCED.read_text(encoding="utf-8"))["puzzles"][0]
        row = as_original_json(original)
        with self.assertRaises(LawfulCorpusError):
            curate_original_lines([row, row])
        with self.assertRaises(LawfulCorpusError):
            curate_original_lines([row], max_selected=0)
        with self.assertRaises(LawfulCorpusError):
            curate_original_lines([row], max_selected=True)


if __name__ == "__main__":
    unittest.main()
