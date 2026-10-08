"""CM/IM/GM QA scope: 25 × 16 × 2 cells with no fictional execution PASS."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import section38_39_master_matrix_report as qa


class MasterMatrixCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = qa.build_master_qa_matrix()

    def test_all_eight_hundred_combinations_have_independent_claim_boundary(self):
        r = self.report
        self.assertEqual(r["schema"], "acs-section38-39-advanced-cross-product-spec-v1")
        self.assertEqual(r["genres"], 25)
        self.assertEqual(r["formats"], 16)
        self.assertEqual(r["languages"], ["uk", "en"])
        self.assertEqual(r["requirement_cells"], 800)
        self.assertEqual(len(r["requirements"]), 800)
        self.assertEqual(len({x["requirement_id"] for x in r["requirements"]}), 800)
        self.assertEqual(
            r["evidence_class"], "SPECIFICATION_NOT_EXECUTED_REAL_CORPUS_VERDICT"
        )
        self.assertFalse(r["section38_terminal_done"])
        self.assertFalse(r["section39_terminal_done"])
        self.assertTrue(r["no_beginner_personal_course"])
        self.assertTrue(r["no_copy_of_protected_books"])
        self.assertTrue(r["needs_real_original_and_derived_per_cell_readback"])
        for x in r["requirements"]:
            self.assertEqual(x["evidence_status"], "COVERAGE_REQUIREMENT_NOT_PASS")
            self.assertEqual(x["independent_test_execution"], "NOT_ATTESTED_IN_THIS_MATRIX")
            self.assertEqual(
                x["expected_vs_actual_readback"],
                "NOT_EXECUTED_FOR_THIS_COMBINATION",
            )
            self.assertFalse(x["protected_book_bytes_present"])
            self.assertFalse(x["windows_nvda_human_pass"])
            self.assertGreater(len(x["semantic_oracle"]), 20)
            self.assertGreater(len(x["required_real_file"]), 20)

    def test_source_metadata_is_never_promoted_to_real_original_pass(self):
        r = self.report
        checked = [cell for cell in r["requirements"] if cell["real_source_candidate_ids"]]
        self.assertGreater(len(checked), 30)
        for row in checked:
            self.assertEqual(
                len(row["real_source_candidate_ids"]),
                len(row["real_candidate_statuses"]),
            )
            for source in row["real_candidate_statuses"]:
                self.assertEqual(
                    source["source_kind"],
                    "ORIGINAL_OR_DERIVED_DECLARED_NOT_THIS_CELL_PROVEN",
                )
                self.assertIsInstance(source["source_id"], str)
                self.assertIsInstance(source["acquisition"], str)
                self.assertIsInstance(source["rights"], str)
        cases = {cell["format"] for cell in checked}
        self.assertIn("PGN", cases)
        self.assertIn("EPD", cases)
        self.assertIn("CBH", cases)
        self.assertTrue(
            any(cell["format"] == "CBH"
                and any(s["acquisition"] == "BLOCKED_NO_LAWFUL_COMPLETE_SAMPLE"
                        for s in cell["real_candidate_statuses"])
                for cell in checked)
        )

    def test_legacy_and_modern_chessbase_are_never_classified_as_classic_cbh(self):
        matcher = qa._candidate_matches_format
        self.assertFalse(matcher("2cbh", "CBH"))
        self.assertTrue(matcher("2cbh", "2CBH"))
        self.assertFalse(matcher("cbf+cbi", "CBV"))
        self.assertTrue(matcher("cbf+cbi", "CBF"))
        self.assertFalse(matcher("pgn", "SAN"))
        self.assertFalse(matcher("epd.zip", "FEN"))
        self.assertTrue(matcher("cbh (multifile original companion family)", "CBH"))
        self.assertTrue(matcher("pgn.zst", "PGN"))
        self.assertFalse(matcher("cbone", "2CBH"))
        self.assertTrue(matcher("epub3/html/txt", "EPUB"))
        self.assertTrue(matcher("epub3/html/txt", "HTML"))
        self.assertTrue(matcher("epub3/html/txt", "TXT"))
        for case in (("2cbh", "CBH"), ("cbf+cbi", "CBV")):
            self.assertFalse(matcher(*case))
        rows = self.report["requirements"]
        for row in rows:
            with self.subTest(format=row["format"]):
                from acs.lawful_corpus_registry import load_catalog
                catalog = {rec["id"]: rec for rec in load_catalog()}
                for source in row["real_source_candidate_ids"]:
                    self.assertTrue(matcher(catalog[source]["format"], row["format"]))

    def test_tampered_genre_metadata_or_lost_language_fails_closed(self):
        actual = json.loads(qa.GENRES.read_text(encoding="utf-8"))
        for mutation in (
            lambda value: value.update(genre_count=1),
            lambda value: value["genres"].pop(),
            lambda value: value["genres"][0].update(
                original_or_derived_source_candidates=[
                    {"catalog_source_id": "FAKE_SOURCE", "role": "fabricated"}
                ]),
        ):
            with self.subTest(mutation=mutation.__code__.co_firstlineno):
                broken = json.loads(json.dumps(actual))
                mutation(broken)
                with tempfile.TemporaryDirectory() as temp:
                    source = Path(temp) / "spoofed.json"
                    source.write_text(json.dumps(broken), encoding="utf-8")
                    with patch.object(qa, "GENRES", source):
                        with self.assertRaises((ValueError, TypeError, KeyError)):
                            qa.build_master_qa_matrix()

    def test_manifest_is_deterministic_and_sha_bound_to_actual_catalog_bytes(self):
        again = qa.build_master_qa_matrix()
        self.assertEqual(self.report, again)
        self.assertEqual(
            self.report["genre_registry_sha256"],
            hashlib.sha256(qa.GENRES.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            self.report["format_matrix_sha256"],
            hashlib.sha256(qa.FORMAT_QA.read_bytes()).hexdigest(),
        )
        self.assertGreaterEqual(self.report["source_registry_count"], 50)


if __name__ == "__main__":
    unittest.main()
