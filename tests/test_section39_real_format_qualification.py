"""Section 39 genuine format qualification contract and false-PASS regressions."""
from __future__ import annotations

from collections import Counter
from unittest import TestCase
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError
from tools.section39_real_format_qualification import (
    FORMATS, PGN_ID, SOURCE_IDS, build_report,
)


class RealFileFormatQualificationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_report()

    def test_exact_sixteen_formats_with_per_capability_truth(self):
        rows = self.report["format_rows"]
        self.assertEqual(len(rows), 16)
        self.assertEqual({row["format"] for row in rows}, set(FORMATS))
        self.assertEqual(len(SOURCE_IDS), 16)
        self.assertEqual(len(Counter(row["format"] for row in rows)), 16)
        self.assertEqual(self.report["section"], 39)
        self.assertFalse(self.report["terminal_done"])
        self.assertFalse(self.report["full_matrix_completed"])
        self.assertFalse(self.report["windows_packaged_verified"])
        self.assertFalse(self.report["manual_nvda_verified"])
        self.assertIsNone(self.report["evidence"]["ci_run_id"]) if (
            self.report["evidence"]["ci_run_id"] is None
        ) else self.assertTrue(self.report["evidence"]["ci_run_id"])
        self.assertEqual(self.report["evidence"]["ci_completion"],
                         "NOT_ATTESTED_BY_THIS_REPORT")
        for row in rows:
            self.assertIn(row["read"], {"PASS", "PARTIAL", "BLOCKED", "UNSUPPORTED"})
            self.assertIn(row["write"], {"PASS", "PARTIAL", "BLOCKED", "UNSUPPORTED"})
            self.assertIn(row["roundtrip"], {"PASS", "PARTIAL", "BLOCKED", "UNSUPPORTED"})
            self.assertIn(row["qualification"], {"PASS", "PARTIAL", "BLOCKED", "UNSUPPORTED"})
            self.assertEqual(row["coverage"] == "EXECUTED_BOUNDED_SLICE",
                             row["qualification"] in {"PASS", "PARTIAL"})

    def test_upstream_original_pgn_and_fen_have_real_bounded_roundtrip(self):
        rows = {row["format"]: row for row in self.report["format_rows"]}
        for name in ("FEN", "PGN"):
            with self.subTest(format=name):
                self.assertEqual(rows[name]["qualification"], "PASS")
                self.assertEqual(rows[name]["read"], "PASS")
                self.assertEqual(rows[name]["write"], "PASS")
                self.assertEqual(rows[name]["roundtrip"], "PASS")
                self.assertEqual(rows[name]["source_kind"], "PINNED_GENUINE_UPSTREAM_BYTES")
                self.assertEqual(rows[name]["actual"]["semantic_loss"], 0)
        self.assertEqual(rows["PGN"]["actual"]["games"], 24)
        self.assertEqual(rows["FEN"]["actual"]["positions"], 1)

    def test_book_and_database_do_not_claim_more_than_the_executed_slice(self):
        rows = {row["format"]: row for row in self.report["format_rows"]}
        self.assertEqual(rows["TXT"]["qualification"], "PARTIAL")
        self.assertEqual(rows["TXT"]["read"], "PASS")
        self.assertEqual(rows["TXT"]["write"], "BLOCKED")
        self.assertGreater(rows["TXT"]["actual"]["semantic_blocks"], 20)
        self.assertEqual(rows["ACSDB"]["qualification"], "PARTIAL")
        self.assertEqual(rows["ACSDB"]["actual"]["semantic_loss"], 0)
        self.assertEqual(rows["ACSDB"]["roundtrip"], "PARTIAL")
        self.assertEqual(rows["ACSDB"]["source_kind"], "DERIVED_FROM_PINNED_UPSTREAM_PGN")
        self.assertEqual(rows["SAN"]["qualification"], "PARTIAL")
        self.assertGreater(rows["SAN"]["actual"]["moves"], 0)
        self.assertEqual(rows["SAN"]["roundtrip"], "PARTIAL")

    def test_unverified_proprietary_and_absent_real_file_have_no_false_pass(self):
        rows = {row["format"]: row for row in self.report["format_rows"]}
        for name in ("EPD", "EPUB", "HTML", "Markdown", "DOCX",
                     "PDF", "CBH", "CBV", "CBF", "2CBH", "CBONE"):
            with self.subTest(format=name):
                row = rows[name]
                self.assertEqual(row["qualification"], "BLOCKED")
                self.assertIsNone(row["actual_importer"])
                self.assertEqual(row["coverage"], "NO_PROOF")
                self.assertEqual(row["source_kind"], "NO_EXECUTED_REAL_FILE_READBACK")

    def test_source_receipts_pin_real_bytes_and_distinguish_not_downloaded(self):
        sources = self.report["source_receipts"]
        self.assertGreaterEqual(len(sources), 30)
        self.assertEqual(len({item["source_id"] for item in sources}), len(sources))
        lookup = {item["source_id"]: item for item in sources}
        self.assertEqual(lookup[PGN_ID]["status"], "PASS")
        self.assertEqual(lookup[PGN_ID]["expected_sha256"],
                         lookup[PGN_ID]["actual_sha256"])
        self.assertNotEqual(lookup["lichess_standard_rated_2013_01"]["status"],
                            "PASS", "declared but not downloaded Lichess PGN must not be PASS")
        self.assertIsNone(lookup["lichess_standard_rated_2013_01"]["actual_sha256"])
        self.assertNotEqual(lookup["original_epd2doc_opening_fen"]["status"], "PASS")
        self.assertEqual(lookup["gitenberg_capablanca_33870_original_txt"]["status"],
                         "PARTIAL")
        self.assertIsNone(lookup["chessbase_family_complete_real_samples"]["actual_sha256"])
        self.assertEqual(lookup["chessbase_family_complete_real_samples"]["status"],
                         "BLOCKED")
        self.assertTrue(all(item["status"] != "PASS" or
                            item["actual_sha256"] == item["expected_sha256"]
                            for item in sources))
        self.assertTrue(all("source_commit_sha" not in item for item in sources))

    def test_mocked_confirmation_cannot_be_promoted_to_real_pass(self):
        fake = {
            "read": "PASS", "write": "PASS", "roundtrip": "PASS",
            "real_source_read": False, "importer": "mock",
        }
        with patch("tools.section39_real_format_qualification._genuine_readbacks",
                   return_value={"PGN": fake}):
            with self.assertRaisesRegex(LawfulCorpusError,
                                        "cannot arise from synthetic data"):
                build_report()


if __name__ == "__main__":
    import unittest
    unittest.main()
