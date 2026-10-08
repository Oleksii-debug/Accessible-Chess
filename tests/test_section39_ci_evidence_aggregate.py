"""Section 39 aggregate accepts no synthetic, stale, or unlicensed evidence."""
from __future__ import annotations

import copy
import unittest

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.section39_ci_evidence_aggregate import (
    EXPECTED_SCHEMAS, merge_real_receipts,
)
from tools.section39_real_format_qualification import FORMATS

HEAD = "a" * 40
POSITION_IDS = ("original_epd2doc_7men_human_epd", "original_epd2doc_opening_fen")
BOOK_IDS = (
    "gutenberg_blue_book_chess_staunton",
    "gutenberg_chess_history_bird_original_txt",
    "gutenberg_checkmates_three_fishburne_original_txt",
    "original_gpl_chastity_chess_chapters_markdown",
    "cc0_capablanca_open_pdf_original_source",
)


def synthetic_evidence():
    """Explicitly fabricated inputs for negative tests, never a real CI PASS."""
    catalog = load_catalog()
    lookup = {entry["id"]: entry for entry in catalog}
    base = {
        "schema": EXPECTED_SCHEMAS[0], "source_commit_sha": HEAD,
        "format_rows": [{
            "format": name, "source_ids": [], "qualification": "BLOCKED",
            "actual": "SYNTHETIC_TEST_ONLY", "coverage": "NO_PROOF",
        } for name in FORMATS],
        "source_receipts": [{
            "source_id": item["id"], "actual_sha256": None,
            "actual_bytes": None, "status": "BLOCKED",
        } for item in catalog],
        "terminal_done": False,
    }
    positions = {
        "schema": EXPECTED_SCHEMAS[1], "source_commit_sha": HEAD,
        "sources": [{
            "source_id": key, "format": "EPD" if "epd" in key else "FEN",
            "original_sha256": lookup[key]["sha256"],
            "original_git_blob": lookup[key]["upstream_git_blob"],
            "license_sha256": lookup[key]["external_license_sha256"],
            "original_record_count": lookup[key]["expected_line_count"],
            "actual": {"counts": {
                "PASS": lookup[key]["expected_line_count"], "PARTIAL": 0, "FAIL": 0,
            }},
            "qualification": "PASS", "actual_importer": "synthetic",
            "real_source_read": False,
        } for key in POSITION_IDS],
    }
    books = {
        "schema": EXPECTED_SCHEMAS[2], "source_commit_sha": HEAD,
        "sources": [{
            "source_id": key,
            "source_format": lookup[key]["format"],
            "source_sha256": lookup[key].get("sha256") or "0" * 64,
            "original_git_blob": lookup[key]["upstream_git_blob"],
            "license_sha256": lookup[key].get("external_license_sha256") or "0" * 64,
            "qualification": "UNSUPPORTED" if lookup[key]["format"] == "pdf" else "PARTIAL",
            "read": "UNSUPPORTED" if lookup[key]["format"] == "pdf" else "PASS",
            "actual_importer": None if lookup[key]["format"] == "pdf" else "fake",
            "actual": {"semantic_blocks_identical_after_reimport": True,
                       "book_progress_restart": "PASS"},
            "real_source_read": False,
        } for key in BOOK_IDS],
    }
    return catalog, base, positions, books


class EvidenceJoinSafety(unittest.TestCase):
    def test_no_fake_source_may_enter_real_evidence_matrix(self):
        catalog, base, positions, books = synthetic_evidence()
        with self.assertRaisesRegex(LawfulCorpusError, "synthetic"):
            merge_real_receipts(base, positions, books, catalog, HEAD)

    def test_stale_source_sha_is_denied_before_reading_format_assertions(self):
        catalog, base, positions, books = synthetic_evidence()
        positions["source_commit_sha"] = "b" * 40
        with self.assertRaisesRegex(LawfulCorpusError, "exact candidate"):
            merge_real_receipts(base, positions, books, catalog, HEAD)

    def test_true_values_cannot_rescue_unpinned_license(self):
        catalog, base, positions, books = synthetic_evidence()
        for record in positions["sources"]:
            record["real_source_read"] = True
        positions["sources"][0]["license_sha256"] = "0" * 64
        with self.assertRaisesRegex(LawfulCorpusError, "license digest"):
            merge_real_receipts(base, positions, books, catalog, HEAD)

    def test_premature_done_is_denied_even_with_signed_artifact_shape(self):
        catalog, base, positions, books = synthetic_evidence()
        books["section39_terminal_done"] = True
        with self.assertRaisesRegex(LawfulCorpusError, "falsely declares"):
            merge_real_receipts(base, positions, books, catalog, HEAD)

    def test_skipped_real_cbh_oracle_cannot_join_three_external_families(self):
        catalog, base, positions, books = synthetic_evidence()
        cbh = {
            "schema": "accessible-chess-section39-cbh-authentic-oracle-v1",
            "source_commit_sha": HEAD,
            "sources": [],
            "all_three_real_semantic_tests_executed": False,
            "all_three_real_semantic_tests_success": False,
            "full_cb_family_format_supported": False,
            "original_source_bytes_packaged": False,
        }
        with self.assertRaisesRegex(LawfulCorpusError, "CBH real source oracle"):
            merge_real_receipts(base, positions, books, catalog, HEAD, cbh)

    def test_forged_cbh_family_component_hash_must_be_rejected(self):
        catalog, base, positions, books = synthetic_evidence()
        lookup = {record["id"]: record for record in catalog}
        names = (
            "libcbh_gpl_original_annotation_cbh_family",
            "libcbh_gpl_original_nested_variations_cbh_family",
            "libcbh_gpl_original_unusual_start_cbh_family",
        )
        cbh_rows = []
        for number, key in enumerate(names):
            registered = lookup[key]
            members = {name: meta["sha256"]
                       for name, meta in registered["external_companion_source_checksums"].items()}
            if number == 0:
                name = sorted(members)[0]
                members[name] = "0" * 64
            cbh_rows.append({
                "source_id": key, "qualification": "PARTIAL" if number == 2 else "PASS",
                "original_source_read": True, "mock_used": False,
                "backend_commit": registered["upstream_commit"],
                "original_member_count": 11,
                "original_member_sha256": members,
                "semantic_oracle_test": "fake test - MUST be refused",
                "actual_importer": "fake",
            })
        cbh = {
            "schema": "accessible-chess-section39-cbh-authentic-oracle-v1",
            "source_commit_sha": HEAD,
            "sources": cbh_rows,
            "all_three_real_semantic_tests_executed": True,
            "all_three_real_semantic_tests_success": True,
            "full_cb_family_format_supported": False,
            "original_source_bytes_packaged": False,
        }
        with self.assertRaisesRegex(LawfulCorpusError, "CBH companion SHA256s"):
            merge_real_receipts(base, positions, books, catalog, HEAD, cbh)

    def test_missing_external_format_cannot_be_called_complete(self):
        catalog, base, positions, books = synthetic_evidence()
        books["sources"].pop()
        with self.assertRaisesRegex(LawfulCorpusError, "incomplete"):
            merge_real_receipts(base, positions, books, catalog, HEAD)


if __name__ == "__main__":
    unittest.main()
