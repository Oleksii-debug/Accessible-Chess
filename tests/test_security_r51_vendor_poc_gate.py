"""R51 signed independent PoC contracts; synthetic keys never imply real vendor approval."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.security_r51_vendor_poc_gate import assess_product_vendor, ProductEvidenceError


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class R51ProductVendorGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.artifact = self.root / "chess-protected-package"
        self.artifact.write_bytes(b"synthetic-only-not-real-vendor-protection")
        self.keys = self.root / "approved-reviewer-inventory.json"
        self.proof = self.root / "poc.json"
        self.source_sha = "a" * 64
        self.signer = Ed25519PrivateKey.generate()
        pub = self.signer.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()
        self.reviewer = "independent-test-reviewer"
        self.keys.write_text(json.dumps({
            "schema_version": 1, "reviewer_public_keys": {self.reviewer: pub},
        }))
        self.report = {
            "schema_version": 1,
            "vendor": "pace-ilok",
            "source_class": "independent-vendor-poc",
            "artifact_sha256": digest(self.artifact.read_bytes()),
            "review_id": "independent-review-01",
            "build_sha256": self.source_sha,
            "measurements": {
                "windows11": True, "nvda_keyboard": True,
                "offline_license": True, "subscription": True,
                "pricing_verified": True, "support_verified": True,
                "startup_p95_ms": 1200, "interaction_p95_ms": 200,
                "peak_memory_mib": 480,
            },
            "revoked": False, "stale": False,
        }
        self.write_signed_packet()

    def write_signed_packet(self):
        signed = (
            b"accessible-chess-r51-independent-poc-v1\x00"
            + json.dumps(
                {"assessment": self.report, "reviewer_id": self.reviewer},
                sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        )
        signature = self.signer.sign(signed).hex()
        self.proof.write_text(json.dumps({
            "schema_version": 1, "assessment": self.report,
            "reviewer_id": self.reviewer, "review_signature_hex": signature,
        }))

    def review(self):
        return assess_product_vendor(
            artifact=self.artifact, proof_file=self.proof,
            approved_reviewers=self.keys,
            approved_reviewers_sha256=digest(self.keys.read_bytes()),
            expected_build_sha256=self.source_sha,
        )

    def test_signed_physical_poc_is_still_not_vendor_selection_or_product_release(self):
        result = self.review()
        self.assertEqual(result["vendor_poc_assessment"], "QUALIFIED")
        self.assertIs(result["product_release_approved"], False)

    def test_signed_synthetic_fixture_is_inconclusive_not_qualified(self):
        self.report["source_class"] = "synthetic-fixture"
        self.write_signed_packet()
        result = self.review()
        self.assertEqual(result["vendor_poc_assessment"], "INCONCLUSIVE")
        self.assertIs(result["product_release_approved"], False)

    def test_forged_measurement_after_signing_fails_independent_verification(self):
        packet = json.loads(self.proof.read_text())
        packet["assessment"]["startup_p95_ms"] = 10
        self.proof.write_text(json.dumps(packet))
        result = self.review()
        self.assertEqual(result["vendor_poc_assessment"], "INCONCLUSIVE")

    def test_signed_failure_is_not_qualified(self):
        self.report["measurements"]["nvda_keyboard"] = False
        self.write_signed_packet()
        self.assertEqual(self.review()["vendor_poc_assessment"], "FAILED")

    def test_tampered_exact_artifact_is_rejected(self):
        self.artifact.write_bytes(b"substitution")
        with self.assertRaisesRegex(ProductEvidenceError, "R51_PRODUCT_BUILD_MISMATCH"):
            self.review()

    def test_trust_inventory_digest_not_caller_selected(self):
        with self.assertRaisesRegex(ProductEvidenceError, "R51_REVIEWER_TRUST_PIN_MISMATCH"):
            assess_product_vendor(
                artifact=self.artifact, proof_file=self.proof,
                approved_reviewers=self.keys,
                approved_reviewers_sha256="0" * 64,
                expected_build_sha256=self.source_sha,
            )

    def test_stale_or_revoked_review_is_inconclusive(self):
        for name in ("stale", "revoked"):
            self.report[name] = True
            self.write_signed_packet()
            self.assertEqual(self.review()["vendor_poc_assessment"], "INCONCLUSIVE")
            self.report[name] = False


if __name__ == "__main__":
    unittest.main()
