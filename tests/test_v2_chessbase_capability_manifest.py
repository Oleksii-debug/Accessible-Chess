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
MATRIX = ROOT / "docs" / "automation" / "DEV4_CHESSBASE_CAPABILITY_MATRIX.md"

ALLOWED = {"SUPPORTED", "PARTIAL", "UNSUPPORTED", "BLOCKED"}
UPSTREAM_SHA = "b18ac89bb7f1ef3d4106517fe3521179ab4522a1"
SCIDB_COMMIT = "7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415"


class Version2ChessBaseCapabilityManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_status_vocabulary_is_exact_and_every_format_uses_it(self) -> None:
        self.assertEqual(set(self.payload["status_vocabulary"]), ALLOWED)
        formats = self.payload["formats"]
        self.assertTrue(formats)
        self.assertTrue(all(item["status"] in ALLOWED for item in formats))

    def test_cbh_and_cbv_are_supported_only_with_explicit_external_requirements(self) -> None:
        by_id = {item["id"]: item for item in self.payload["formats"]}
        self.assertEqual(by_id["cbh"]["status"], "SUPPORTED")
        self.assertIn("requires", by_id["cbh"]["availability"])
        self.assertIn("libcbh", by_id["cbh"]["availability"])
        self.assertEqual(by_id["cbv"]["status"], "SUPPORTED")
        self.assertIn("uncbv", by_id["cbv"]["availability"])
        self.assertIn("libcbh", by_id["cbv"]["availability"])

    def test_cbf_cbi_remains_blocked_despite_pinned_decoder_research(self) -> None:
        by_id = {item["id"]: item for item in self.payload["formats"]}
        legacy = by_id["legacy-cbf-cbi"]
        self.assertEqual(legacy["status"], "BLOCKED")
        self.assertEqual(set(legacy["extensions"]), {".cbf", ".cbi"})

        evidence = self.payload["cbf_cbi_evidence"]
        self.assertTrue(evidence["pair_required"])
        self.assertTrue(evidence["source_read_only"])
        self.assertFalse(evidence["real_fixture_found"])
        self.assertFalse(evidence["independent_semantic_oracle_found"])
        self.assertEqual(evidence["support_status"], "BLOCKED")
        self.assertGreaterEqual(len(evidence["unlock_requires"]), 5)

        candidate = next(
            item
            for item in self.payload["backends"]
            if item["id"] == "scidb-cbf-research-candidate"
        )
        self.assertEqual(candidate["commit"], SCIDB_COMMIT)
        self.assertEqual(candidate["role"], "research_candidate_only")
        self.assertFalse(candidate["build_qualified"])
        self.assertFalse(candidate["semantic_support"])
        self.assertFalse(candidate["bundled_by_default"])

    def test_exact_upstream_product_and_existing_backend_pins_are_preserved(self) -> None:
        self.assertEqual(self.payload["upstream_product"]["sha"], UPSTREAM_SHA)
        backends = {item["id"]: item for item in self.payload["backends"]}
        self.assertEqual(
            backends["libcbh"]["commit"],
            "9641c5c3949d8fb210b17dd9aa54455645843696",
        )
        self.assertEqual(
            backends["uncbv"]["commit"],
            "3c18e8a7c6a30c21f945a1ab5462521c306dca57",
        )
        self.assertFalse(backends["libcbh"]["bundled_by_default"])
        self.assertFalse(backends["uncbv"]["bundled_by_default"])

    def test_cbi_is_component_only_in_runtime_probe(self) -> None:
        probe = probe_chessbase_source("legacy.cbi")
        self.assertTrue(probe.recognized)
        self.assertFalse(probe.is_primary_source)
        self.assertEqual(probe.source_kind, "component")
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)

    def test_evidence_docs_do_not_promote_cbf_or_claim_lossless_support(self) -> None:
        evidence = EVIDENCE.read_text(encoding="utf-8")
        matrix = MATRIX.read_text(encoding="utf-8")
        combined = evidence + "\n" + matrix
        self.assertIn("Status: `BLOCKED`", evidence)
        self.assertIn(SCIDB_COMMIT, combined)
        self.assertIn("real_fixture_found=false", evidence)
        self.assertIn("independent_semantic_oracle_found=false", evidence)
        self.assertNotIn("CBF/CBI | SUPPORTED", combined)
        self.assertNotIn("lossless cbf", combined.casefold())


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
