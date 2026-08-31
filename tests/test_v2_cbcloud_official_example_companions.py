import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "automation" / "V2_CBCLOUD_OFFICIAL_EXAMPLE_COMPANIONS.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_CBCLOUD_OFFICIAL_EXAMPLE_COMPANIONS.md"
WORKFLOW = ROOT / ".github" / "workflows" / "v2-cbcloud-official-example-companions.yml"


class V2CbcloudOfficialExampleCompanionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.evidence = EVIDENCE.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_capability_stays_blocked_and_evidence_only(self):
        self.assertEqual(self.data["format"], "CBCLOUD")
        self.assertEqual(self.data["status"], "BLOCKED")
        self.assertFalse(self.data["support_promotion_allowed"])
        self.assertFalse(self.data["product_mutation"])

    def test_exact_official_example_suffix_set_is_recorded(self):
        official = self.data["official_example_evidence"]
        self.assertEqual(official["family_file_count_documented"], 4)
        self.assertEqual(
            official["observed_same_root_suffixes"],
            [".cbcloud", ".cbclmov", ".cbclhdr", ".cbclatt"],
        )
        self.assertEqual(official["english_manual_example_root"], "WhiteRepertoire")
        self.assertEqual(official["german_manual_example_root"], "BlackRepertoire")

    def test_example_is_not_promoted_to_normative_role_map(self):
        official = self.data["official_example_evidence"]
        self.assertFalse(official["normative_required_optional_map_qualified"])
        self.assertFalse(official["binary_component_roles_qualified"])
        self.assertIn("official-example observed", self.evidence)
        self.assertIn("does not infer", self.evidence)

    def test_pdf_screenshot_limitation_is_not_hidden(self):
        official = self.data["official_example_evidence"]
        self.assertFalse(official["screenshot_materialization_succeeded"])
        self.assertIn("oversized official PDF", official["screenshot_failure_reason"])
        self.assertIn("screenshot call was attempted", self.evidence)

    def test_real_world_acceptance_is_not_claimed(self):
        acceptance = self.data["real_world_acceptance"]
        self.assertTrue(acceptance["official_real_examples_exist"])
        self.assertFalse(acceptance["downloadable_exact_family_bytes"])
        self.assertFalse(acceptance["stable_family_hashes"])
        self.assertFalse(acceptance["lawful_automated_ci_reuse_proven"])
        self.assertFalse(acceptance["independent_pgn_or_gametree_oracle"])
        self.assertFalse(acceptance["semantic_decode_executed"])

    def test_no_semantic_decode_claim_exists(self):
        self.assertTrue(all(value is False for value in self.data["semantic_claims"].values()))
        self.assertIn("pinned licensed CBCLOUD reader/backend", self.data["blockers"])
        self.assertIn("canonical GameTree validation", self.data["blockers"])

    def test_secondary_corroboration_cannot_define_roles(self):
        secondary = self.data["secondary_corroboration"]
        self.assertTrue(secondary["file_association_sources_list_all_four_as_chessbase_database_extensions"])
        self.assertFalse(secondary["authoritative_for_binary_roles"])

    def test_workflow_covers_companion_tokens_dual_os_and_broad_regression(self):
        for token in ("cbcloud", "cbclmov", "cbclhdr", "cbclatt"):
            self.assertIn(token, self.workflow.lower())
        self.assertIn("ubuntu-22.04", self.workflow)
        self.assertIn("windows-2025", self.workflow)
        self.assertIn("Full unittest", self.workflow)
        self.assertIn("Full pytest", self.workflow)


if __name__ == "__main__":
    unittest.main()
