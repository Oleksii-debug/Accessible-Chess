from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.chessbase_adapter import probe_chessbase_source


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "docs" / "automation" / "V2_CBZ_REAL_ACCEPTANCE.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_CBZ_REAL_ACCEPTANCE.md"
SECURE_EXECUTION = ROOT / "docs" / "automation" / "V2_CBZ_SECURE_EXECUTION.json"
PARENT_SHA = "7f0c15bcc20dde101c79e41d074e1613dafee996"
UNCBV_COMMIT = "3c18e8a7c6a30c21f945a1ab5462521c306dca57"
UNCBV_FIXTURE_BLOB = "08bc5d6e53eecedc35e37d24cf29bbe0a5953839"


class Version2CbzRealAcceptanceTests(unittest.TestCase):
    def test_current_runtime_still_does_not_claim_cbz_semantic_support(self) -> None:
        probe = probe_chessbase_source("real-world.cbz")
        self.assertTrue(probe.recognized)
        self.assertTrue(probe.read_only)
        self.assertEqual(probe.source_kind, "encrypted_archive_container")
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)
        self.assertEqual(probe.status, "adapter_only")

    def test_manifest_requires_every_real_acceptance_dimension(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(payload["scope"], "cbz-real-world-semantic-acceptance-qualification")
        self.assertEqual(payload["parent"]["sha"], PARENT_SHA)
        self.assertEqual(payload["verdict"]["cbz_status"], "BLOCKED")
        self.assertFalse(payload["verdict"]["support_promotion_allowed"])
        required = payload["required_acceptance_dimensions"]
        self.assertEqual(
            required,
            [
                "authentic_chessbase_cbz",
                "lawful_reusable_bytes",
                "password_available_for_automated_acceptance",
                "real_world_not_synthetic_or_self_fixture",
                "independent_semantic_oracle",
                "canonical_end_to_end_equivalence",
            ],
        )
        candidates = payload["candidates"]
        self.assertGreaterEqual(len(candidates), 5)
        self.assertFalse(any(candidate["eligible"] for candidate in candidates))
        for candidate in candidates:
            self.assertTrue(
                any(not candidate[dimension] for dimension in required),
                candidate["id"],
            )

    def test_real_commercial_candidate_is_not_treated_as_reusable_or_independent(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        candidates = {candidate["id"]: candidate for candidate in payload["candidates"]}
        ultra = candidates["ultracorr2025-cbz"]
        self.assertTrue(ultra["authentic_chessbase_cbz"])
        self.assertTrue(ultra["real_world_not_synthetic_or_self_fixture"])
        self.assertGreaterEqual(ultra["reported_games"], 2_680_000)
        self.assertFalse(ultra["lawful_reusable_bytes"])
        self.assertFalse(ultra["password_available_for_automated_acceptance"])
        self.assertFalse(ultra["independent_semantic_oracle"])
        self.assertFalse(ultra["eligible"])

    def test_pinned_uncbv_fixture_remains_mechanics_only_not_independent_oracle(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        candidates = {candidate["id"]: candidate for candidate in payload["candidates"]}
        fixture = candidates["antoyo-uncbv-small-cbz"]
        self.assertEqual(fixture["commit"], UNCBV_COMMIT)
        self.assertEqual(fixture["fixture_blob"], UNCBV_FIXTURE_BLOB)
        self.assertTrue(fixture["lawful_reusable_bytes"])
        self.assertTrue(fixture["password_available_for_automated_acceptance"])
        self.assertFalse(fixture["real_world_not_synthetic_or_self_fixture"])
        self.assertFalse(fixture["independent_semantic_oracle"])
        self.assertFalse(fixture["eligible"])

        mechanics = json.loads(SECURE_EXECUTION.read_text(encoding="utf-8"))
        self.assertTrue(mechanics["acceptance"]["exact_upstream_fixture_mechanics_tested_in_ci"])
        self.assertFalse(mechanics["acceptance"]["upstream_fixture_is_semantic_support_proof"])
        self.assertFalse(mechanics["acceptance"]["support_promotion_allowed"])

    def test_public_discovery_result_cannot_be_confused_with_generic_cbz_extension_hits(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        candidates = {candidate["id"]: candidate for candidate in payload["candidates"]}
        discovery = candidates["github-public-code-search"]
        self.assertEqual(discovery["chess_specific_candidate_count"], 0)
        self.assertGreater(discovery["general_extension_result_count_observed"], 0)
        self.assertFalse(discovery["authentic_chessbase_cbz"])
        self.assertFalse(discovery["eligible"])

    def test_evidence_document_records_blocked_verdict_and_no_overclaim(self) -> None:
        evidence = EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("CBZ=BLOCKED", evidence)
        self.assertIn("support_promotion_allowed=false", evidence)
        self.assertIn("UltraCorr2025", evidence)
        self.assertIn(UNCBV_COMMIT, evidence)
        self.assertIn(UNCBV_FIXTURE_BLOB, evidence)
        self.assertIn("independent semantic oracle", evidence)
        self.assertIn("same decoder upstream", evidence)
        self.assertIn("0 chess-specific candidates", evidence)
        self.assertNotIn("CBZ=SUPPORTED", evidence)
        self.assertNotIn("CBZ=PARTIAL", evidence)


if __name__ == "__main__":
    unittest.main()
