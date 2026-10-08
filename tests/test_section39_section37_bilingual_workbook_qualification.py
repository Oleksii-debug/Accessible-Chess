"""Section 39 continuous real-original provenance check for all 10 Section37 books."""
from __future__ import annotations
import unittest
from unittest.mock import patch
from acs.lawful_corpus_registry import LawfulCorpusError
from tools import section39_section37_bilingual_workbook_qualification as qa

class Section37RealBilingualMultiFormatQualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence, cls.books = qa.qualify_bilingual_books()

    def test_source_identity_and_all_ten_actual_user_readable_formats(self):
        proof = self.evidence
        self.assertEqual(proof["original_lesson_count"], 12)
        self.assertEqual(proof["language_count"], 2)
        self.assertEqual(proof["source_native_derived_format_count"], 5)
        self.assertEqual(proof["observed_derivative_count"], 10)
        self.assertEqual(len(self.books), 10)
        self.assertTrue(proof["real_original_cc0_position_provenance"])
        self.assertFalse(proof["original_third_party_publisher_file_claim"])
        self.assertFalse(proof["section39_terminal_done"])
        self.assertEqual(len(proof["workbook_source_sha256"]), 64)
        self.assertEqual(len(proof["workbook_original_git_blob"]), 40)
        self.assertTrue(proof["production_embedded_source_is_byte_identical"])
        self.assertEqual(
            {(x["language"], x["format"]) for x in proof["sources"]},
            {(lang, ext.upper()) for lang in ("uk", "en")
             for ext in ("txt", "md", "html", "epub", "docx")},
        )
        for row in proof["sources"]:
            self.assertEqual(len(self.books[row["filename"]]), row["derived_bytes"])
            self.assertGreater(row["derived_bytes"], 250)
            self.assertFalse(row["independent_publisher_original_file"])
            self.assertEqual(row["bookdocument_semantic_reimport"], "PASS")
            self.assertEqual(row["book_progress_disk_restart"], "PASS")
            self.assertEqual(row["explicit_fen_positions"],
                             12 if row["format"] in {"MD", "HTML", "EPUB"} else 0)
            self.assertTrue(row["all_twelve_original_prompts_present"])
            self.assertEqual(
                row["source_fen_sequence_identical"],
                True if row["format"] in {"MD", "HTML", "EPUB"}
                else "NO_EXPLICIT_FEN_METADATA_IN_TEXT_DOCX",
            )

    def test_original_source_not_matching_embedded_product_is_not_qualified(self):
        with patch.object(qa, "_ORIGINAL_SOURCE_TEXT", "{}"):
            with self.assertRaisesRegex(LawfulCorpusError, "production offline Books source bytes diverged"):
                qa.qualify_bilingual_books()

    def test_license_changed_in_original_cc0_catalog_fails_before_derivation(self):
        original = qa.load_catalog
        def malicious(path):
            return tuple(
                {**entry, "redistribution": "NOT_CLEARED"}
                if entry["id"] == qa.SOURCES[0][0] else entry
                for entry in original(path)
            )
        with patch.object(qa, "load_catalog", side_effect=malicious):
            with self.assertRaisesRegex(LawfulCorpusError, "rights/identity"):
                qa.qualify_bilingual_books()

    def test_missing_real_cc0_chess_puzzle_cannot_be_replaced_with_dummy(self):
        original = qa.read_verified_source_snapshot
        def altered(path, record):
            if record["id"] == qa.SOURCES[0][0]:
                return original(path, record)[:-1]
            return original(path, record)
        with patch.object(qa, "read_verified_source_snapshot", side_effect=altered):
            with self.assertRaises(LawfulCorpusError):
                qa.qualify_bilingual_books()

if __name__ == "__main__":
    unittest.main()
