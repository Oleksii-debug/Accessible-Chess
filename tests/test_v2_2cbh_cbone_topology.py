from __future__ import annotations

from pathlib import Path
import json
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
MANIFEST = ROOT / "docs" / "automation" / "V2_2CBH_CBONE_CAPABILITIES.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_2CBH_CBONE_TOPOLOGY_EVIDENCE.md"
ALLOWED = {"SUPPORTED", "PARTIAL", "UNSUPPORTED", "BLOCKED"}
PARENT_SHA = "0454f9e19854da9c2261bba4b5d64e688fa3b909"


class Version2TwoCbhCboneTopologyTests(unittest.TestCase):
    def test_2cbh_is_not_misclassified_as_single_file(self) -> None:
        probe = probe_chessbase_source("sample.2cbh")
        self.assertTrue(probe.recognized)
        self.assertTrue(probe.is_primary_source)
        self.assertEqual(probe.source_kind, "multi_file_database_unqualified_topology")
        self.assertEqual(probe.components, ())
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)
        rendered = " ".join(probe.warnings).casefold()
        self.assertIn("multi-file", rendered)
        self.assertIn("fail closed", rendered)

    def test_cbone_remains_truthfully_single_file_without_support_claim(self) -> None:
        probe = probe_chessbase_source("sample.cbone")
        self.assertTrue(probe.recognized)
        self.assertTrue(probe.is_primary_source)
        self.assertEqual(probe.source_kind, "single_file_database")
        self.assertEqual(probe.components, ())
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)
        self.assertTrue(any("single-file" in item.casefold() for item in probe.warnings))

    def test_2cbh_integrity_snapshot_fails_closed_even_when_primary_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "modern.2cbh"
            primary.write_bytes(b"header")
            with self.assertRaises(ChessBaseIntegrityIOError) as caught:
                capture_integrity_snapshot(primary)
        self.assertIn("multi-file", str(caught.exception).casefold())
        self.assertIn("not evidence-qualified", str(caught.exception).casefold())

    def test_2cbh_does_not_guess_that_one_observed_companion_completes_family(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "modern.2cbh"
            primary.write_bytes(b"header")
            (root / "modern.2cbg").write_bytes(b"moves")
            with self.assertRaises(ChessBaseIntegrityIOError):
                capture_integrity_snapshot(primary)

    def test_cbone_single_file_integrity_round_trip_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "portable.cbone"
            source.write_bytes(b"single-file-database")
            snapshot = capture_integrity_snapshot(source)
            self.assertEqual([item.extension for item in snapshot.files], [".cbone"])
            self.assertEqual([item.size_bytes for item in snapshot.files], [20])
            self.assertEqual(verify_integrity_snapshot(snapshot), snapshot)

    def test_evidence_manifest_is_scoped_and_never_promotes_support(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(set(payload["status_vocabulary"]), ALLOWED)
        self.assertEqual(payload["scope"], "2cbh-cbone-topology-evidence-only")
        self.assertEqual(payload["upstream_product"]["sha"], PARENT_SHA)
        self.assertEqual([item["id"] for item in payload["formats"]], ["2cbh", "cbone"])
        self.assertTrue(all(item["status"] == "BLOCKED" for item in payload["formats"]))
        self.assertFalse(payload["formats"][0]["complete_companion_map_qualified"])
        self.assertTrue(payload["formats"][1]["complete_companion_map_qualified"])
        rendered = json.dumps(payload, sort_keys=True).casefold()
        self.assertNotIn('"status": "supported"', rendered)
        self.assertNotIn('"status": "partial"', rendered)

    def test_evidence_doc_keeps_real_fixture_and_semantic_oracle_blocked(self) -> None:
        evidence = EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("2CBH=BLOCKED", evidence)
        self.assertIn("CBONE=BLOCKED", evidence)
        self.assertIn("real_fixture_found=false", evidence)
        self.assertIn("independent_semantic_oracle_found=false", evidence)
        self.assertIn("does not invent", evidence)
        self.assertNotIn("2CBH=SUPPORTED", evidence)
        self.assertNotIn("CBONE=SUPPORTED", evidence)

    def test_cbone_mutation_invalidates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "portable.cbone"
            source.write_bytes(b"version-one")
            snapshot = capture_integrity_snapshot(source)
            source.write_bytes(b"version-two")
            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
