"""Fail-closed genuine Section37 advanced and extreme chess source QA."""
from __future__ import annotations
import unittest
from unittest.mock import patch
from acs.lawful_corpus_registry import LawfulCorpusError
from tools import section39_real_section37_advanced_training_qualification as qualified

class Section37LatestPuzzlesQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = qualified.qualify_real_advanced_training()

    def test_original_bytes_and_all_twenty_positions_are_real(self):
        receipt = self.evidence
        self.assertEqual(receipt["original_source_count"], 2)
        self.assertEqual(receipt["total_real_legal_puzzles"], 20)
        self.assertFalse(receipt["original_raw_source_full_dataset_verified"])
        self.assertFalse(receipt["section39_terminal_done"])
        self.assertEqual([x["actual"]["puzzle_count"] for x in receipt["sources"]], [16, 4])
        for item in receipt["sources"]:
            self.assertTrue(item["real_original_source_read"])
            self.assertFalse(item["mocked"])
            self.assertEqual(item["qualification"], "PASS")
            self.assertEqual(item["actual"]["bookdocument_roundtrip"], "PASS")
            self.assertTrue(item["actual"]["uk_en_same_canonical_positions"])
            self.assertEqual(item["actual"]["replayed_legal_chess_positions"],
                             item["actual"]["puzzle_count"])

    def test_damaged_embedded_source_cannot_be_accepted_as_original(self):
        genuine = qualified.read_verified_source_snapshot
        def damaged(path, record):
            raw = genuine(path, record)
            return raw[:-1] if record["id"] == qualified.TRAINING_CASES[0][0] else raw
        with patch.object(qualified, "read_verified_source_snapshot", side_effect=damaged):
            with self.assertRaisesRegex(LawfulCorpusError, "differs from production"):
                qualified.qualify_real_advanced_training()

    def test_unauthorized_source_cannot_be_promoted(self):
        genuine = qualified.load_catalog
        def corrupted():
            return tuple({**x, "redistribution": "NOT_CLEARED"}
                         if x["id"] == qualified.TRAINING_CASES[1][0] else x
                         for x in genuine())
        with patch.object(qualified, "load_catalog", side_effect=corrupted):
            with self.assertRaisesRegex(LawfulCorpusError, "not authorized"):
                qualified.qualify_real_advanced_training()

if __name__ == "__main__":
    unittest.main()
