from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_integrity import (
    ChessBaseIntegrityIOError,
    ChessBaseSourceChangedError,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "docs" / "automation" / "V2_CHESSBASE_CAPABILITIES.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_CBF_CBI_EVIDENCE.md"

ALLOWED = {"SUPPORTED", "PARTIAL", "UNSUPPORTED", "BLOCKED"}
UPSTREAM_SHA = "b18ac89bb7f1ef3d4106517fe3521179ab4522a1"
SCIDB_COMMIT = "7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415"


class Version2CbfCbiCapabilityEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_status_vocabulary_is_exact(self) -> None:
        self.assertEqual(set(self.payload["status_vocabulary"]), ALLOWED)
        self.assertEqual(
            self.payload["scope"],
            "legacy-cbf-cbi-evidence-only",
        )

    def test_manifest_is_not_a_competing_cbh_or_cbv_capability_authority(self) -> None:
        formats = self.payload["formats"]
        self.assertEqual([item["id"] for item in formats], ["legacy-cbf-cbi"])
        rendered = json.dumps(self.payload, sort_keys=True).lower()
        self.assertNotIn('"id": "cbh"', rendered)
        self.assertNotIn('"id": "cbv"', rendered)
        self.assertIn(
            "pr #295",
            self.payload["out_of_scope"]["cbh_cbv_capability_status"].casefold(),
        )

    def test_cbf_cbi_remains_blocked_despite_pinned_decoder_research(self) -> None:
        legacy = self.payload["formats"][0]
        self.assertEqual(legacy["status"], "BLOCKED")
        self.assertEqual(set(legacy["extensions"]), {".cbf", ".cbi"})

        evidence = self.payload["cbf_cbi_evidence"]
        self.assertTrue(evidence["pair_required"])
        self.assertTrue(evidence["source_read_only"])
        self.assertFalse(evidence["real_fixture_found"])
        self.assertFalse(evidence["independent_semantic_oracle_found"])
        self.assertEqual(evidence["support_status"], "BLOCKED")
        self.assertGreaterEqual(len(evidence["unlock_requires"]), 5)

        candidate = self.payload["backends"][0]
        self.assertEqual(candidate["id"], "scidb-cbf-research-candidate")
        self.assertEqual(candidate["commit"], SCIDB_COMMIT)
        self.assertEqual(candidate["role"], "research_candidate_only")
        self.assertFalse(candidate["build_qualified"])
        self.assertFalse(candidate["semantic_support"])
        self.assertFalse(candidate["bundled_by_default"])

    def test_exact_upstream_product_and_research_source_pins_are_preserved(self) -> None:
        self.assertEqual(self.payload["upstream_product"]["sha"], UPSTREAM_SHA)
        candidate = self.payload["backends"][0]
        self.assertEqual(candidate["repository"], "foolnotion/scidb")
        self.assertEqual(candidate["commit"], SCIDB_COMMIT)
        self.assertEqual(
            candidate["source_blobs"]["src/db/cbf/cbf_codec.cpp"],
            "c9608dc93e704070c5ec7f8294d09e6c52374b53",
        )
        self.assertEqual(
            candidate["source_blobs"]["src/db/cbf/cbf_decoder.cpp"],
            "27172abed77db4961d7158337240d00d57474084",
        )

    def test_cbi_is_component_only_in_runtime_probe(self) -> None:
        probe = probe_chessbase_source("legacy.cbi")
        self.assertTrue(probe.recognized)
        self.assertFalse(probe.is_primary_source)
        self.assertEqual(probe.source_kind, "component")
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)

    def test_evidence_doc_does_not_promote_cbf_or_claim_lossless_support(self) -> None:
        evidence = EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("Status: `BLOCKED`", evidence)
        self.assertIn(SCIDB_COMMIT, evidence)
        self.assertIn("real_fixture_found=false", evidence)
        self.assertIn("independent_semantic_oracle_found=false", evidence)
        self.assertNotIn("CBF/CBI = SUPPORTED", evidence)
        self.assertNotIn("lossless cbf", evidence.casefold())


class Version2CbfCbiIntegrityTests(unittest.TestCase):
    def test_complete_pair_is_one_integrity_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cbf = root / "Legacy.CBF"
            cbi = root / "legacy.cbi"
            cbf.write_bytes(b"games")
            cbi.write_bytes(b"index")

            snapshot = capture_integrity_snapshot(cbf)

            self.assertEqual([item.extension for item in snapshot.files], [".cbf", ".cbi"])
            self.assertEqual([item.size_bytes for item in snapshot.files], [5, 5])
            self.assertEqual(verify_integrity_snapshot(snapshot), snapshot)

    def test_missing_or_wrong_stem_index_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cbf = root / "legacy.cbf"
            cbf.write_bytes(b"games")
            (root / "other.cbi").write_bytes(b"wrong index")

            with self.assertRaises(ChessBaseIntegrityIOError) as caught:
                capture_integrity_snapshot(cbf)
            self.assertIn("same-stem .cbi", str(caught.exception))

    def test_index_mutation_invalidates_entire_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cbf = root / "legacy.cbf"
            cbi = root / "legacy.cbi"
            cbf.write_bytes(b"games")
            cbi.write_bytes(b"index-v1")
            snapshot = capture_integrity_snapshot(cbf)

            cbi.write_bytes(b"index-v2")

            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
