import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "automation" / "V2_CBONE_REAL_BACKEND_CORPUS_UNBLOCK.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_CBONE_REAL_BACKEND_CORPUS_UNBLOCK.md"
WORKFLOW = ROOT / ".github" / "workflows" / "v2-cbone-real-backend-corpus-unblock.yml"


class V2CboneRealBackendCorpusUnblockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.evidence = EVIDENCE.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_capability_remains_blocked(self):
        self.assertEqual(self.data["format"], "CBONE")
        self.assertEqual(self.data["status"], "BLOCKED")
        self.assertFalse(self.data["support_promotion_allowed"])
        self.assertFalse(self.data["product_decoder_available"])
        self.assertFalse(self.data["product_safe_to_import"])

    def test_official_contract_is_single_file_read_write_only(self):
        official = self.data["official_evidence"]
        self.assertTrue(official["single_file_database"])
        self.assertTrue(official["read_write_format"])
        self.assertTrue(official["whole_database_in_one_file"])
        self.assertEqual(official["games_exchangeable_with"], ["CBH", "CBF", "PGN"])
        self.assertFalse(official["payload_layout_documented"])
        self.assertFalse(official["relationship_to_2cbh_documented"])

    def test_real_usage_is_not_reusable_acceptance_fixture(self):
        usage = self.data["real_world_evidence"]["chessbase13_analysis_workflow"]
        self.assertTrue(usage["real_cb_one_usage_reported"])
        self.assertFalse(usage["raw_cb_one_bytes_available"])
        self.assertFalse(usage["lawful_ci_reuse_proven"])
        self.assertFalse(usage["independent_pgn_oracle_for_exact_bytes"])
        public = self.data["real_world_evidence"]["public_search"]
        self.assertFalse(public["downloadable_authentic_cb_one_candidate_found"])
        self.assertFalse(public["exact_bytes_authenticated"])
        self.assertFalse(public["independent_oracle_found"])

    def test_no_backend_compatibility_is_inferred(self):
        probes = self.data["open_source_backend_probe"]
        self.assertEqual(
            probes["rolandlo_libcbh"]["commit"],
            "9641c5c3949d8fb210b17dd9aa54455645843696",
        )
        self.assertEqual(
            probes["foolnotion_scidb"]["commit"],
            "7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415",
        )
        self.assertEqual(
            probes["isarhamster_chessx"]["commit"],
            "e734a075346ca2ad7e3f3e35b42140169637c5ca",
        )
        self.assertEqual(
            probes["antoyo_uncbv"]["commit"],
            "3c18e8a7c6a30c21f945a1ab5462521c306dca57",
        )
        self.assertTrue(all(not item["cbone_surface_found"] for item in probes.values()))
        self.assertIn("does not assume that CBONE is a packaged 2CBH", self.evidence)
        self.assertIn("feeding a CBONE file to the classic `libcbh` bridge", self.evidence)

    def test_no_semantic_decode_or_roundtrip_claim_exists(self):
        semantic = self.data["semantic_claims"]
        self.assertTrue(semantic)
        self.assertTrue(all(value is False for value in semantic.values()))
        for blocker in (
            "lawfully reusable authentic CBONE bytes",
            "pinned licensed CBONE reader/backend",
            "independent PGN or GameTree oracle for the exact CBONE bytes",
            "Library/Search/Open/Export/Reopen/Integrity end-to-end equivalence",
        ):
            self.assertIn(blocker, self.data["blockers"])

    def test_workflow_is_dual_os_with_broad_regression_and_semantic_probe(self):
        self.assertIn("ubuntu-22.04", self.workflow)
        self.assertIn("windows-2025", self.workflow)
        self.assertIn("Full unittest", self.workflow)
        self.assertIn("Full pytest", self.workflow)
        self.assertIn("Probe exact CBONE backend candidates", self.workflow)
        self.assertIn("*.cbone", self.workflow)
        self.assertIn("9641c5c3949d8fb210b17dd9aa54455645843696", self.workflow)
        self.assertIn("7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415", self.workflow)
        self.assertIn("e734a075346ca2ad7e3f3e35b42140169637c5ca", self.workflow)
        self.assertIn("3c18e8a7c6a30c21f945a1ab5462521c306dca57", self.workflow)


if __name__ == "__main__":
    unittest.main()
