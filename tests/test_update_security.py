import hashlib
import json
import unittest

from acs.entitlements import ProductVersion
from acs.update_security import (
    UpdateDecisionCode,
    UpdateManifest,
    UpdateSignatureVerifier,
    verify_update,
)


PAYLOAD = b"accessible-chess-update-payload\x00v2"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class ExactVerifier:
    def __init__(self, *, expected_message: bytes | None = None, accepted: bool = True):
        self.expected_message = expected_message
        self.accepted = accepted
        self.calls = []

    def verify(self, *, key_id: str, message: bytes, signature: str) -> bool:
        self.calls.append((key_id, message, signature))
        if self.expected_message is not None and message != self.expected_message:
            return False
        return self.accepted and key_id == "release-2026" and signature == "signed-metadata"


class ExplodingVerifier:
    def verify(self, *, key_id: str, message: bytes, signature: str) -> bool:
        raise RuntimeError("trust store unavailable")


def manifest_mapping(**overrides):
    value = {
        "version": "2.1.0",
        "minimum_source_version": "2.0.0",
        "payload_sha256": DIGEST,
        "payload_size": len(PAYLOAD),
        "download_url": "https://updates.example.invalid/releases/2.1.0/AccessibleChess.exe",
        "key_id": "release-2026",
        "signature": "signed-metadata",
    }
    value.update(overrides)
    return value


class UpdateSecurityTests(unittest.TestCase):
    def manifest(self, **overrides):
        return UpdateManifest.from_mapping(manifest_mapping(**overrides))

    def test_signature_verifier_is_provider_neutral_runtime_contract(self):
        self.assertIsInstance(ExactVerifier(), UpdateSignatureVerifier)

    def test_valid_signed_newer_payload_is_accepted(self):
        manifest = self.manifest()
        verifier = ExactVerifier(expected_message=manifest.signed_bytes())
        decision = verify_update(
            manifest,
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=verifier,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.ACCEPT)
        self.assertEqual(len(verifier.calls), 1)

    def test_canonical_signed_bytes_are_deterministic_and_exclude_signature(self):
        manifest = self.manifest()
        first = manifest.signed_bytes()
        second = manifest.signed_bytes()
        self.assertEqual(first, second)
        decoded = json.loads(first.decode("ascii"))
        self.assertEqual(decoded["version"], "2.1.0")
        self.assertEqual(decoded["payload_sha256"], DIGEST)
        self.assertEqual(decoded["payload_size"], len(PAYLOAD))
        self.assertEqual(decoded["key_id"], "release-2026")
        self.assertNotIn("signature", decoded)

    def test_each_security_relevant_metadata_change_changes_signed_bytes(self):
        baseline = self.manifest().signed_bytes()
        mutations = (
            {"version": "2.2.0"},
            {"minimum_source_version": "1.9.0"},
            {"payload_sha256": "0" * 64},
            {"payload_size": len(PAYLOAD) + 1},
            {"download_url": "https://mirror.example.invalid/update.exe"},
            {"key_id": "release-2027"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertNotEqual(self.manifest(**mutation).signed_bytes(), baseline)

    def test_invalid_signature_fails_closed_before_payload_acceptance(self):
        decision = verify_update(
            self.manifest(),
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(accepted=False),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.SIGNATURE_INVALID)

    def test_signature_verifier_exception_fails_closed_without_leaking_exception(self):
        decision = verify_update(
            self.manifest(),
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=ExplodingVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.SIGNATURE_INVALID)
        self.assertEqual(decision.reason, "signature verifier failed closed")

    def test_equal_version_replay_is_blocked(self):
        decision = verify_update(
            self.manifest(version="2.0.0", minimum_source_version=None),
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.ROLLBACK_BLOCKED)

    def test_downgrade_is_blocked_even_when_metadata_signature_is_valid(self):
        decision = verify_update(
            self.manifest(version="1.9.9", minimum_source_version=None),
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.ROLLBACK_BLOCKED)

    def test_source_floor_blocks_incremental_update_from_unsupported_old_build(self):
        decision = verify_update(
            self.manifest(minimum_source_version="2.0.0"),
            current_version="1.9.9",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.SOURCE_TOO_OLD)

    def test_source_floor_boundary_is_allowed(self):
        decision = verify_update(
            self.manifest(minimum_source_version="2.0.0"),
            current_version=ProductVersion.parse("2.0.0"),
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertTrue(decision.allowed)

    def test_payload_size_mismatch_fails_closed(self):
        decision = verify_update(
            self.manifest(payload_size=len(PAYLOAD) + 1),
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.PAYLOAD_SIZE_MISMATCH)

    def test_payload_hash_mismatch_fails_closed(self):
        manifest = self.manifest(payload_sha256=hashlib.sha256(b"other").hexdigest())
        decision = verify_update(
            manifest,
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.PAYLOAD_HASH_MISMATCH)

    def test_non_bytes_payload_fails_closed_before_verifier_or_hashing(self):
        verifier = ExactVerifier()
        decision = verify_update(
            self.manifest(),
            current_version="2.0.0",
            payload="not-bytes",
            signature_verifier=verifier,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.INVALID_PAYLOAD)
        self.assertEqual(verifier.calls, [])

    def test_wrong_manifest_object_fails_closed(self):
        decision = verify_update(
            manifest_mapping(),
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.INVALID_METADATA)

    def test_direct_manifest_construction_with_wrong_runtime_types_fails_closed(self):
        malformed = UpdateManifest(
            version="2.1.0",
            minimum_source_version=None,
            payload_sha256=DIGEST,
            payload_size=len(PAYLOAD),
            download_url="https://updates.example.invalid/update.exe",
            key_id="release-2026",
            signature="signed-metadata",
        )
        decision = verify_update(
            malformed,
            current_version="2.0.0",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.INVALID_METADATA)

    def test_manifest_rejects_non_https_ambiguous_and_credentialed_urls(self):
        invalid_urls = (
            "http://updates.example.invalid/update.exe",
            "file:///C:/update.exe",
            "https://user:pass@updates.example.invalid/update.exe",
            "https://updates.example.invalid/update.exe#fragment",
            "https:///update.exe",
            "https://updates.example.invalid\\@other.example/update.exe",
            "https://updates.example.invalid/update\n.exe",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    self.manifest(download_url=url)

    def test_manifest_rejects_digest_case_length_and_non_hex(self):
        invalid = (DIGEST.upper(), "a" * 63, "a" * 65, "z" * 64)
        for digest in invalid:
            with self.subTest(digest=digest):
                with self.assertRaises(ValueError):
                    self.manifest(payload_sha256=digest)

    def test_manifest_rejects_non_positive_or_non_integer_size(self):
        for size in (0, -1, True, 1.5, "31"):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    self.manifest(payload_size=size)

    def test_manifest_parser_rejects_missing_and_unknown_fields(self):
        missing = manifest_mapping()
        del missing["signature"]
        with self.assertRaises(ValueError):
            UpdateManifest.from_mapping(missing)

        unknown = manifest_mapping(untrusted_extension="yes")
        with self.assertRaises(ValueError):
            UpdateManifest.from_mapping(unknown)

    def test_manifest_parser_rejects_noncanonical_or_non_text_security_fields(self):
        cases = (
            {"version": " 2.1.0"},
            {"payload_sha256": 123},
            {"download_url": " https://updates.example.invalid/update.exe"},
            {"key_id": "release-2026\n"},
            {"signature": ""},
        )
        for mutation in cases:
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    self.manifest(**mutation)

    def test_invalid_current_version_returns_fail_closed_decision(self):
        decision = verify_update(
            self.manifest(),
            current_version="not-a-version",
            payload=PAYLOAD,
            signature_verifier=ExactVerifier(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, UpdateDecisionCode.INVALID_METADATA)


if __name__ == "__main__":
    unittest.main()
