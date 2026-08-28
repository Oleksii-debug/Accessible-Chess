import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "automation" / "V2_2CBH_REAL_BACKEND_CORPUS_UNBLOCK.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_2CBH_REAL_BACKEND_CORPUS_UNBLOCK.md"
WORKFLOW = ROOT / ".github" / "workflows" / "v2-2cbh-real-backend-corpus-unblock.yml"


class V2TwoCbhRealBackendCorpusUnblockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.evidence = EVIDENCE.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_capability_remains_blocked(self):
        self.assertEqual(self.data["format"], "2CBH")
        self.assertEqual(self.data["status"], "BLOCKED")
        self.assertFalse(self.data["support_promotion_allowed"])
        self.assertFalse(self.data["product_decoder_available"])
        self.assertFalse(self.data["product_safe_to_import"])

    def test_official_example_suffixes_are_exact_not_truncated(self):
        observed = self.data["official_evidence"]["official_example_observed_same_root_members"]
        self.assertEqual(
            observed,
            [".2cba", ".2cbg", ".2cbh", ".2lcd", ".2lgd", ".2lid", ".ini"],
        )
        for false_suffix in (".2cd", ".2gd", ".2ld"):
            self.assertNotIn(false_suffix, observed)
            self.assertIn(
                false_suffix,
                self.data["official_evidence"]["false_truncated_suffixes_rejected"],
            )

    def test_observed_files_are_not_promoted_to_guessed_roles(self):
        official = self.data["official_evidence"]
        self.assertFalse(official["component_roles_qualified"])
        self.assertFalse(official["complete_normative_component_map_qualified"])
        self.assertIn("does not publish a normative description", self.evidence)
        self.assertIn("not to invent `_2CBH_COMPONENT_EXTENSIONS`", self.evidence)

    def test_real_corpus_does_not_satisfy_acceptance_rule(self):
        corpus = self.data["real_world_evidence"]["ultracorr2025"]
        self.assertTrue(corpus["real_database"])
        self.assertGreaterEqual(corpus["games_reported"], 2_680_000)
        self.assertEqual(corpus["archive_expands_to_reported_files"], 7)
        self.assertFalse(corpus["redistributable_ci_fixture"])
        self.assertFalse(corpus["automatable_password_available"])
        self.assertFalse(corpus["independent_pgn_oracle"])

    def test_open_source_candidates_make_no_2cbh_claim(self):
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
        self.assertTrue(all(not item["2cbh_surface_found"] for item in probes.values()))

    def test_no_semantic_decode_or_end_to_end_claim_exists(self):
        semantic = self.data["semantic_claims"]
        self.assertTrue(semantic)
        self.assertTrue(all(value is False for value in semantic.values()))
        for required in (
            "lawfully reusable real 2CBH family",
            "independent PGN or GameTree oracle for the exact family",
            "canonical legality and GameTree validation",
            "Library/Search/Open/Export/Reopen/Integrity end-to-end equivalence",
        ):
            self.assertIn(required, self.data["blockers"])

    def test_workflow_is_dual_os_with_broad_regression_and_upstream_probe(self):
        self.assertIn("ubuntu-22.04", self.workflow)
        self.assertIn("windows-2025", self.workflow)
        self.assertIn("Full unittest", self.workflow)
        self.assertIn("Full pytest", self.workflow)
        self.assertIn("Probe exact open-source candidates", self.workflow)
        self.assertIn("9641c5c3949d8fb210b17dd9aa54455645843696", self.workflow)
        self.assertIn("7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415", self.workflow)
        self.assertIn("e734a075346ca2ad7e3f3e35b42140169637c5ca", self.workflow)


if __name__ == "__main__":
    unittest.main()
