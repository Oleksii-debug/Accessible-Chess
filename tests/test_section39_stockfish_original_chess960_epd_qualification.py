"""Section 39 honest original Stockfish FRC/EPD corpus and corruption gates."""
from __future__ import annotations
import unittest
from unittest.mock import patch
from acs.lawful_corpus_registry import LawfulCorpusError
from tools import section39_stockfish_original_chess960_epd_qualification as qa


class ActualChess960EpdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = qa.qualify_stockfish_real_positions()

    def test_both_real_pinned_originals_consume_every_record(self):
        self.assertEqual(self.evidence["source_count"], 2)
        self.assertEqual({x["source_id"] for x in self.evidence["sources"]}, set(qa.IDS))
        self.assertGreater(self.evidence["original_total_positions"], 1)
        self.assertEqual(
            self.evidence["original_total_positions"],
            self.evidence["original_semantic_supported_count"]
            + self.evidence["original_semantic_unsupported_count"],
        )
        for result in self.evidence["sources"]:
            self.assertTrue(result["real_source_read"])
            self.assertFalse(result["mocked"])
            self.assertEqual(len(result["source_zip_sha256"]), 64)
            self.assertEqual(len(result["original_member_sha256"]), 64)
            self.assertEqual(
                result["actual_canonical_position_roundtrip_count"]
                + result["unsupported_original_record_count"],
                result["original_record_count"],
            )
            self.assertIn(result["qualification"], {"PASS", "PARTIAL", "UNSUPPORTED"})
        self.assertFalse(self.evidence["section39_terminal_done"])

    def test_corrupt_original_cannot_be_counted_as_frc_pass(self):
        genuine = qa.read_verified_zip_member
        def corrupt(*args, **kwargs):
            if args[1]["id"] == qa.IDS[0]:
                return b"fake, not EPD, with invalid source identity"
            return genuine(*args, **kwargs)
        with patch.object(qa, "read_verified_zip_member", side_effect=corrupt):
            with self.assertRaises(LawfulCorpusError):
                qa.qualify_stockfish_real_positions()

    def test_missing_original_is_not_synthetic_chess960_success(self):
        actual = qa.load_catalog
        with patch.object(qa, "load_catalog", return_value=tuple(
            record for record in actual() if record["id"] != qa.IDS[0]
        )):
            with self.assertRaisesRegex(LawfulCorpusError, "unavailable"):
                qa.qualify_stockfish_real_positions()

if __name__ == "__main__":
    unittest.main()
