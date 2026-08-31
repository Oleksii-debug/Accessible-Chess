import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "automation" / "V2_CBCLOUD_LOCAL_FORMAT_UNBLOCK.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_CBCLOUD_LOCAL_FORMAT_UNBLOCK.md"
WORKFLOW = ROOT / ".github" / "workflows" / "v2-cbcloud-local-format-unblock.yml"


class V2CbcloudLocalFormatUnblockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.evidence = EVIDENCE.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_capability_remains_blocked(self):
        self.assertEqual(self.data["format"], "CBCLOUD")
        self.assertEqual(self.data["status"], "BLOCKED")
        self.assertFalse(self.data["support_promotion_allowed"])
        self.assertFalse(self.data["product_decoder_available"])
        self.assertFalse(self.data["product_safe_to_import"])

    def test_only_officially_qualified_local_topology_is_claimed(self):
        official = self.data["official_evidence"]
        self.assertEqual(official["primary_extension"], ".cbcloud")
        self.assertTrue(official["local_database"])
        self.assertTrue(official["offline_local_copy_supported"])
        self.assertEqual(official["family_file_count"], 4)
        self.assertTrue(official["same_game_data_as_cbh_reported"])
        self.assertTrue(official["player_tournament_index_files_absent"])
        self.assertFalse(official["companion_suffixes_qualified"])

    def test_network_cloud_services_are_explicitly_excluded(self):
        self.assertIn("excludes ChessBase online/cloud service APIs", self.data["scope"])
        self.assertIn("online/cloud service APIs", self.evidence)
        self.assertIn("account/cloud APIs", self.evidence)

    def test_real_usage_is_not_reusable_acceptance_fixture(self):
        real = self.data["real_world_evidence"]
        self.assertTrue(real["official_real_local_database_examples_shown"])
        self.assertFalse(real["authentic_downloadable_family_found"])
        self.assertFalse(real["lawful_ci_reuse_proven"])
        self.assertFalse(real["independent_pgn_or_gametree_oracle_found"])
        self.assertFalse(real["exact_family_hashes_available"])

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
        self.assertTrue(all(not item["cbcloud_surface_found"] for item in probes.values()))
        self.assertIn("route `.cbcloud` to classic libcbh", self.evidence)

    def test_no_semantic_or_whole_family_integrity_claim_exists(self):
        self.assertTrue(all(value is False for value in self.data["semantic_claims"].values()))
        self.assertIn("hash only the `.cbcloud` primary", self.evidence)
        for blocker in (
            "lawfully reusable authentic CBCLOUD four-file family",
            "evidence-qualified companion suffixes and component roles",
            "pinned licensed CBCLOUD reader/backend",
            "independent PGN or GameTree oracle for the exact family",
        ):
            self.assertIn(blocker, self.data["blockers"])

    def test_workflow_is_dual_os_with_semantic_probe_and_broad_regression(self):
        self.assertIn("ubuntu-22.04", self.workflow)
        self.assertIn("windows-2025", self.workflow)
        self.assertIn("Full unittest", self.workflow)
        self.assertIn("Full pytest", self.workflow)
        self.assertIn("Probe exact CBCLOUD backend candidates", self.workflow)
        self.assertIn("*.cbcloud", self.workflow)


if __name__ == "__main__":
    unittest.main()
