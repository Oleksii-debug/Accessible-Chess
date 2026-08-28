from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.cbv_extractor import (
    CbvExtractCode,
    CbvExtractError,
    ExternalCbvExtractorConfig,
    extract_cbv_external,
)
from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_integrity import (
    ChessBaseSourceChangedError,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "docs" / "automation" / "V2_CBZ_2CBZ_EVIDENCE.json"
EVIDENCE = ROOT / "docs" / "automation" / "V2_CBZ_2CBZ_EVIDENCE.md"
CBV_EXTRACTOR = ROOT / "acs" / "cbv_extractor.py"
PARENT_SHA = "e3c13d07a338d79764e71e4bef096900aa860cac"
UNCBV_COMMIT = "3c18e8a7c6a30c21f945a1ab5462521c306dca57"
CBV_EXTRACTOR_BLOB = "0ff079754a963186daad47597e16d7fa3de32782"
ALLOWED = {"SUPPORTED", "PARTIAL", "UNSUPPORTED", "BLOCKED"}


class Version2CbzTwoCbzEvidenceTests(unittest.TestCase):
    def test_encrypted_archives_are_recognized_without_support_claim(self) -> None:
        expected = {
            ".cbz": "encrypted_archive_container",
            ".2cbz": "encrypted_archive_container_unqualified_payload",
        }
        for suffix, source_kind in expected.items():
            with self.subTest(suffix=suffix):
                probe = probe_chessbase_source("archive" + suffix)
                self.assertTrue(probe.recognized)
                self.assertTrue(probe.is_primary_source)
                self.assertTrue(probe.read_only)
                self.assertEqual(probe.source_kind, source_kind)
                self.assertFalse(probe.decoder_available)
                self.assertFalse(probe.safe_to_import)
                self.assertEqual(probe.status, "adapter_only")
                rendered = " ".join(probe.warnings).casefold()
                self.assertIn("encrypted", rendered)
                self.assertIn("blocked", rendered)

    def test_encrypted_archive_integrity_is_source_only_and_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix in (".cbz", ".2cbz"):
                with self.subTest(suffix=suffix):
                    source = root / ("archive" + suffix)
                    source.write_bytes(b"opaque-encrypted-source")
                    snapshot = capture_integrity_snapshot(source)
                    self.assertEqual(len(snapshot.files), 1)
                    self.assertEqual(snapshot.files[0].extension, suffix)
                    self.assertEqual(snapshot.files[0].size_bytes, 23)
                    self.assertEqual(verify_integrity_snapshot(snapshot), snapshot)
                    self.assertEqual(source.read_bytes(), b"opaque-encrypted-source")

    def test_encrypted_archive_mutation_invalidates_integrity_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "archive.cbz"
            source.write_bytes(b"ciphertext-v1")
            snapshot = capture_integrity_snapshot(source)
            source.write_bytes(b"ciphertext-v2")
            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)

    def test_current_cbv_extractor_fails_closed_for_cbz_and_2cbz(self) -> None:
        config = ExternalCbvExtractorConfig(
            executable=Path("uncbv-not-invoked"),
            expected_backend_sha256="0" * 64,
        )
        for suffix in (".cbz", ".2cbz"):
            with self.subTest(suffix=suffix):
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory)
                    with self.assertRaises(CbvExtractError) as caught:
                        extract_cbv_external("archive" + suffix, output, config)
                self.assertEqual(caught.exception.code, CbvExtractCode.UNSUPPORTED_SOURCE)

    def test_current_product_has_no_password_transport_path(self) -> None:
        source = CBV_EXTRACTOR.read_text(encoding="utf-8")
        self.assertIn("stdin=subprocess.DEVNULL", source)
        self.assertIn('source_path.suffix.lower() != ".cbv"', source)
        self.assertNotIn("password=", source)

    def test_manifest_records_exact_evidence_and_keeps_both_formats_blocked(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(payload["scope"], "cbz-2cbz-encrypted-archive-evidence-only")
        self.assertEqual(set(payload["status_vocabulary"]), ALLOWED)
        self.assertEqual(payload["upstream_product"]["sha"], PARENT_SHA)
        formats = {item["id"]: item for item in payload["formats"]}
        self.assertEqual(set(formats), {"cbz", "2cbz"})
        self.assertTrue(all(item["status"] == "BLOCKED" for item in formats.values()))
        self.assertTrue(formats["cbz"]["official_format_documented"])
        self.assertFalse(formats["2cbz"]["official_general_specification_found"])
        backend = payload["backend_evidence"]
        self.assertEqual(backend["commit"], UNCBV_COMMIT)
        self.assertEqual(backend["product_cbv_extractor_blob"], CBV_EXTRACTOR_BLOB)
        self.assertEqual(backend["password_transport"], "interactive stdin")
        self.assertFalse(backend["product_password_transport_qualified"])
        acceptance = payload["real_world_acceptance"]
        self.assertTrue(acceptance["real_world_corpus_found"])
        self.assertFalse(acceptance["legally_reusable_acceptance_fixture_found"])
        self.assertFalse(acceptance["independent_semantic_oracle_found"])
        rendered = json.dumps(payload, sort_keys=True).casefold()
        self.assertNotIn('"status": "supported"', rendered)
        self.assertNotIn('"status": "partial"', rendered)

    def test_evidence_document_distinguishes_backend_mechanics_from_product_support(self) -> None:
        evidence = EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("CBZ=BLOCKED", evidence)
        self.assertIn("2CBZ=BLOCKED", evidence)
        self.assertIn(UNCBV_COMMIT, evidence)
        self.assertIn(CBV_EXTRACTOR_BLOB, evidence)
        self.assertIn("stdin=subprocess.DEVNULL", evidence)
        self.assertIn("synthetic/upstream fixtures do not prove Product support", evidence)
        self.assertIn("real_world_corpus_found=true", evidence)
        self.assertIn("legally_reusable_acceptance_fixture_found=false", evidence)
        self.assertIn("independent_semantic_oracle_found=false", evidence)
        self.assertNotIn("CBZ=SUPPORTED", evidence)
        self.assertNotIn("2CBZ=SUPPORTED", evidence)


if __name__ == "__main__":
    unittest.main()
