import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "automation" / "V2_2CBH_BACKEND_CONTRACT_20260831.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_2CBH_BACKEND_CONTRACT_20260831.md"
MODULE = ROOT / "acs" / "chessbase_2cbh_backend.py"


class V2TwoCbhBackendEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.text = EVIDENCE.read_text(encoding="utf-8")
        cls.module = MODULE.read_text(encoding="utf-8").casefold()

    def test_support_remains_explicitly_blocked(self):
        self.assertEqual(self.data["format"], "2CBH")
        self.assertEqual(self.data["status"], "BLOCKED")
        self.assertFalse(self.data["support_promotion_allowed"])
        self.assertFalse(self.data["product_decoder_available"])
        self.assertFalse(self.data["product_safe_to_import"])
        self.assertFalse(self.data["default_windows_third_party_2cbh_backend"])

    def test_observed_files_are_not_misrepresented_as_normative_topology(self):
        observed = self.data["observed_real_family"]
        self.assertEqual(
            observed["same_root_members_observed_in_official_example"],
            [".2cba", ".2cbg", ".2cbh", ".2lcd", ".2lgd", ".2lid", ".ini"],
        )
        self.assertFalse(observed["complete_normative_component_set_qualified"])
        self.assertFalse(observed["component_semantic_roles_qualified"])
        self.assertFalse(observed["mandatory_optional_map_qualified"])
        self.assertIn("does not infer semantic role", observed["policy"])

    def test_product_module_does_not_embed_unqualified_companion_suffix_map(self):
        for suffix in (".2cba", ".2cbg", ".2lcd", ".2lgd", ".2lid", ".ini"):
            self.assertNotIn(suffix, self.module)
        self.assertIn('primary_extension = ".2cbh"', self.module)
        self.assertNotIn("semantic_role", self.module)

    def test_no_candidate_is_promoted_to_product_decoder(self):
        decoder = self.data["decoder_availability"]
        self.assertFalse(decoder["chessbase_18"]["product_backend_qualified"])
        self.assertFalse(decoder["chess_combine_0_1_168_beta"]["product_backend_qualified"])
        self.assertFalse(decoder["chess_combine_0_1_168_beta"]["documented_stable_cli_or_api_found"])
        self.assertFalse(decoder["chess_combine_0_1_168_beta"]["product_backend_license_qualified"])
        self.assertFalse(decoder["chess_combine_0_1_168_beta"]["automation_permission_qualified"])
        probes = decoder["pinned_open_source_candidates"]
        self.assertTrue(all(not item["2cbh_surface_found"] for item in probes.values()))

    def test_real_corpus_is_not_claimed_as_reusable_or_oracle(self):
        ultracorr = self.data["real_corpus"]["ultracorr2025"]
        self.assertTrue(ultracorr["real_database"])
        self.assertGreaterEqual(ultracorr["games_reported_at_least"], 2_680_000)
        self.assertTrue(ultracorr["archive_encrypted"])
        self.assertFalse(ultracorr["redistributable_ci_fixture"])
        self.assertFalse(ultracorr["automation_password_available"])
        self.assertFalse(ultracorr["independent_semantic_oracle_for_exact_bytes"])
        self.assertFalse(ultracorr["accepted_as_product_test_corpus"])

    def test_independent_semantic_oracle_remains_unqualified(self):
        oracle = self.data["independent_semantic_oracle"]
        self.assertFalse(oracle["qualified"])
        self.assertFalse(
            oracle["chess_combine_reader"]["lawful_reproducible_export_path_qualified"]
        )
        self.assertFalse(oracle["generated_open_pgn_to_2cbh_strategy"]["qualified_now"])

    def test_backend_abstraction_is_fail_closed_and_backend_free(self):
        package = self.data["product_backend_abstraction"]
        self.assertTrue(package["shipping_registry_empty"])
        self.assertTrue(package["topology_rules_backend_evidence_supplied_only"])
        self.assertFalse(package["semantic_role_field_present"])
        self.assertTrue(package["external_executable_only"])
        self.assertTrue(package["backend_sha256_required"])
        self.assertTrue(package["lawful_independent_semantic_oracle_required"])
        self.assertTrue(package["source_read_only"])
        self.assertTrue(package["source_topology_mutation_detection"])

    def test_evidence_text_states_exact_remaining_gate(self):
        for phrase in (
            "support not advertised / import not enabled",
            "does **not** find the evidence set required",
            "does not create a hard-coded mapping",
            "No independent semantic oracle is qualified today",
            "default Accessible Chess package remains backend-free",
        ):
            self.assertIn(phrase, self.text)
        self.assertGreaterEqual(len(self.data["remaining_blockers"]), 8)


if __name__ == "__main__":
    unittest.main()
