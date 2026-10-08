"""R73 production-evidence handoff tests; synthetic crypto never means product PASS."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from continuum_runtime.protection_convergence import (
    CONTROL_LAYERS, LayerAttestation, signable_layer,
)
from scripts.security_r73_product_evidence_gate import (
    ProductEvidenceError, assess_product_release,
)

H = "a" * 64
S = "b" * 64
R = "c" * 64
NOW = 1791478800


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class ProductR73EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / "AccessibleChess.zip"
        self.artifact.write_bytes(b"synthetic-test-archive-not-a-real-release")
        self.artifact_hash = _sha(self.artifact.read_bytes())
        self.evidence = self.root / "attestations.json"
        self.keys = self.root / "independent-trusted-verifier-keys.json"
        self.signer = Ed25519PrivateKey.generate()
        self.key_id = "independent-test-only"
        self._write_keys(self.signer)
        self._write_layers("PHYSICAL")

    def _write_keys(self, signer):
        key = signer.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()
        self.keys.write_text(json.dumps({
            "schema_version": 1, "verifier_public_keys": {self.key_id: key},
        }, sort_keys=True), encoding="utf-8")

    def _write_layers(self, evidence_class):
        records = []
        for index, name in enumerate(CONTROL_LAYERS):
            unsigned = LayerAttestation(
                layer=name, integration_state="INTEGRATED",
                evidence_class=evidence_class, outcome="ACCEPTED",
                source_sha256=H, artifact_sha256=self.artifact_hash,
                scope_sha256=S, residual_risks_sha256=R,
                build_id="chess-product-build-1", channel="candidate",
                sequence=index + 1, witnessed_at=NOW,
                nonce=f"nonce-{index+1}", verifier_id=self.key_id,
                signature_hex="0" * 128,
            )
            records.append(asdict(replace(
                unsigned,
                signature_hex=self.signer.sign(signable_layer(unsigned)).hex()
            )))
        self.evidence.write_text(
            json.dumps({"schema_version": 1, "layers": records}, sort_keys=True),
            encoding="utf-8",
        )

    def _review(self):
        return assess_product_release(
            artifact=self.artifact,
            evidence=self.evidence,
            approved_keys=self.keys,
            approved_keys_sha256=_sha(self.keys.read_bytes()),
            source_sha256=H, scope_sha256=S, residual_risks_sha256=R,
            build_id="chess-product-build-1", channel="candidate", now=NOW,
        )

    def test_even_all_valid_signed_physical_evidence_never_issues_release_pass(self):
        r = self._review()
        self.assertEqual(r["status"], "PHYSICAL_EVIDENCE_REQUIRES_INDEPENDENT_RELEASE_DECISION")
        self.assertIs(r["release_approved"], False)
        self.assertEqual(len(r["covered"]), len(CONTROL_LAYERS))
        self.assertEqual(r["missing"], [])

    def test_all_signed_synthetic_source_evidence_stays_non_releasing(self):
        self._write_layers("SOURCE")
        r = self._review()
        self.assertEqual(r["status"], "SOURCE_EVIDENCE_ONLY")
        self.assertIs(r["release_approved"], False)

    def test_missing_layer_stays_inconclusive(self):
        value = json.loads(self.evidence.read_text())
        value["layers"].pop()
        self.evidence.write_text(json.dumps(value))
        r = self._review()
        self.assertEqual(r["status"], "INCONCLUSIVE_NOT_INTEGRATED")
        self.assertEqual(len(r["missing"]), 1)

    def test_tampered_product_bytes_are_never_covered_by_old_signed_proof(self):
        self.artifact.write_bytes(b"tampered-product")
        with self.assertRaisesRegex(ProductEvidenceError, "R73_INDEPENDENT_EVIDENCE_DENIED"):
            self._review()

    def test_forged_verifier_key_inventory_is_not_trusted(self):
        rogue = Ed25519PrivateKey.generate()
        self._write_keys(rogue)
        with self.assertRaisesRegex(ProductEvidenceError, "R73_INDEPENDENT_EVIDENCE_DENIED"):
            self._review()

    def test_modified_key_inventory_rejected_by_independent_digest_pin(self):
        with self.assertRaisesRegex(ProductEvidenceError, "INDEPENDENT_VERIFIER_KEY_INVENTORY_MISMATCH"):
            assess_product_release(
                artifact=self.artifact, evidence=self.evidence,
                approved_keys=self.keys, approved_keys_sha256="0" * 64,
                source_sha256=H, scope_sha256=S,
                residual_risks_sha256=R,
                build_id="chess-product-build-1", channel="candidate", now=NOW,
            )

    def test_replaced_trusted_key_file_between_metadata_and_open_is_rejected(self):
        from unittest.mock import patch
        from scripts.security_r73_product_evidence_gate import _strict_json

        approved_digest = _sha(self.keys.read_bytes())
        replacement = self.root / "substituted-trusted-keys.json"
        replacement.write_text(json.dumps({
            "schema_version": 1,
            "verifier_public_keys": {"untrusted-replacement": "0" * 64},
        }), encoding="utf-8")
        original_open = Path.open
        swapped = []

        def swap_at_open(path, *args, **kwargs):
            if path == self.keys and not swapped:
                replacement.replace(self.keys)
                swapped.append(True)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", swap_at_open):
            with self.assertRaisesRegex(ProductEvidenceError, "EVIDENCE_FILE_MUTATED"):
                _strict_json(
                    self.keys, maximum=64 * 1024,
                    expected_sha256=approved_digest,
                    mismatch_code="INDEPENDENT_VERIFIER_KEY_INVENTORY_MISMATCH",
                )
        self.assertEqual(swapped, [True])

    def test_same_file_bytes_must_match_external_trust_pin(self):
        from scripts.security_r73_product_evidence_gate import _strict_json

        approved_digest = _sha(self.keys.read_bytes())
        self.keys.write_text(json.dumps({
            "schema_version": 1, "verifier_public_keys": {"other": "1" * 64},
        }), encoding="utf-8")
        with self.assertRaisesRegex(
            ProductEvidenceError, "INDEPENDENT_VERIFIER_KEY_INVENTORY_MISMATCH"
        ):
            _strict_json(
                self.keys, maximum=64 * 1024,
                expected_sha256=approved_digest,
                mismatch_code="INDEPENDENT_VERIFIER_KEY_INVENTORY_MISMATCH",
            )

    def test_duplicate_json_keys_fail_closed(self):
        self.evidence.write_text('{"schema_version":1,"schema_version":1,"layers":[]}')
        with self.assertRaisesRegex(ProductEvidenceError, "EVIDENCE_DUPLICATE_KEY"):
            self._review()

    def test_forged_integration_flag_invalidates_signature(self):
        value = json.loads(self.evidence.read_text())
        value["layers"][0]["integration_state"] = "NOT_INTEGRATED"
        self.evidence.write_text(json.dumps(value))
        with self.assertRaisesRegex(ProductEvidenceError, "R73_INDEPENDENT_EVIDENCE_DENIED"):
            self._review()

    def test_replaced_artifact_between_stat_and_open_is_rejected(self):
        from unittest.mock import patch
        from scripts.security_r73_product_evidence_gate import _sha256_file

        replacement = self.root / "substituted-artifact.zip"
        replacement.write_bytes(b"replaced-after-check")
        original_open = Path.open
        swapped = []

        def swap_at_open(path, *args, **kwargs):
            if path == self.artifact and not swapped:
                replacement.replace(self.artifact)
                swapped.append(True)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", swap_at_open):
            with self.assertRaisesRegex(ProductEvidenceError, "FILE_MUTATED_DURING_REVIEW"):
                _sha256_file(self.artifact, maximum=1024 * 1024)
        self.assertEqual(swapped, [True])

    def test_key_inventory_symlink_rejected(self):
        target = self.root / "actual-keys"
        self.keys.rename(target)
        try:
            self.keys.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not supported by this host")
        with self.assertRaisesRegex(ProductEvidenceError, "FILE_MISSING_OR_UNSAFE"):
            self._review()


if __name__ == "__main__":
    unittest.main()
