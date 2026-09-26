from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import unittest

from acs.entitlements import EntitlementState
from acs.signed_entitlement_policy import (
    EntitlementReplayGuard,
    SIGNED_POLICY_SCHEMA,
    SignedEntitlementPolicyError,
    canonical_entitlement_signature_message,
    verify_signed_entitlement_policy,
)


@dataclass
class FakeVerifier:
    accept: bool = True
    raise_error: bool = False
    last_key_id: str | None = None
    last_message: bytes | None = None
    last_signature: bytes | None = None

    def verify(self, *, key_id: str, message: bytes, signature: bytes) -> bool:
        self.last_key_id = key_id
        self.last_message = message
        self.last_signature = signature
        if self.raise_error:
            raise RuntimeError("provider-private failure")
        return self.accept


def payload(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "policy_id": "policy-20260926-0001",
        "state": "paid_yearly",
        "feature_ids": ["analysis.engine", "data.export"],
        "issued_at": "2026-09-26T18:00:00Z",
        "expires_at": "2027-09-26T18:00:00Z",
        "server_time": "2026-09-26T18:00:05Z",
        "minimum_supported_version": "2.0.0",
        "refresh_after": "2026-09-26T19:00:00Z",
        "grace_until": "2027-10-03T18:00:00Z",
        "account_id": "acct-123",
        "organization_id": None,
    }
    result.update(overrides)
    return result


def envelope_bytes(
    p: dict[str, object] | None = None,
    *,
    schema: str = SIGNED_POLICY_SCHEMA,
    key_id: str = "release-key-1",
    signature: bytes = b"s" * 64,
) -> bytes:
    document = {
        "schema": schema,
        "key_id": key_id,
        "payload": payload() if p is None else p,
        "signature": base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class SignedEntitlementPolicyTests(unittest.TestCase):
    def test_valid_signature_projects_existing_entitlement_model(self) -> None:
        verifier = FakeVerifier()
        policy = verify_signed_entitlement_policy(envelope_bytes(), verifier=verifier)

        self.assertEqual(policy.key_id, "release-key-1")
        self.assertEqual(policy.snapshot.state, EntitlementState.PAID_YEARLY)
        self.assertEqual(policy.snapshot.source, "signed_remote:release-key-1")
        self.assertEqual(policy.snapshot.account_id, "acct-123")
        self.assertEqual(
            policy.snapshot.feature_ids,
            frozenset({"analysis.engine", "data.export"}),
        )
        self.assertEqual(str(policy.snapshot.policy.minimum_supported_version), "2.0.0")
        self.assertEqual(verifier.last_signature, b"s" * 64)
        self.assertEqual(
            verifier.last_message,
            canonical_entitlement_signature_message(
                schema=SIGNED_POLICY_SCHEMA,
                key_id="release-key-1",
                payload=payload(),
            ),
        )

    def test_signature_failure_does_not_project_claims(self) -> None:
        with self.assertRaisesRegex(SignedEntitlementPolicyError, "signature is invalid"):
            verify_signed_entitlement_policy(envelope_bytes(), verifier=FakeVerifier(accept=False))

    def test_verifier_exception_is_sanitized(self) -> None:
        with self.assertRaises(SignedEntitlementPolicyError) as raised:
            verify_signed_entitlement_policy(
                envelope_bytes(), verifier=FakeVerifier(raise_error=True)
            )
        self.assertNotIn("provider-private", str(raised.exception))

    def test_signature_binds_schema_key_id_and_payload(self) -> None:
        verifier = FakeVerifier()
        first = verify_signed_entitlement_policy(envelope_bytes(), verifier=verifier)
        first_message = verifier.last_message
        changed = payload(account_id="acct-456")
        second = verify_signed_entitlement_policy(envelope_bytes(changed), verifier=verifier)
        self.assertNotEqual(first_message, verifier.last_message)
        self.assertNotEqual(first.message_sha256, second.message_sha256)

    def test_duplicate_json_field_fails_closed_before_verifier(self) -> None:
        verifier = FakeVerifier()
        raw = (
            b'{"schema":"accessible-chess-entitlement-policy-v1",'
            b'"schema":"accessible-chess-entitlement-policy-v1",'
            b'"key_id":"release-key-1","payload":{},"signature":"c3Nz"}'
        )
        with self.assertRaisesRegex(SignedEntitlementPolicyError, "duplicate"):
            verify_signed_entitlement_policy(raw, verifier=verifier)
        self.assertIsNone(verifier.last_message)

    def test_unknown_top_level_field_fails_closed(self) -> None:
        document = json.loads(envelope_bytes())
        document["debug"] = True
        with self.assertRaisesRegex(SignedEntitlementPolicyError, "fields are invalid"):
            verify_signed_entitlement_policy(
                json.dumps(document).encode(), verifier=FakeVerifier()
            )

    def test_unknown_payload_field_fails_closed(self) -> None:
        p = payload()
        p["provider_plan"] = "secret-premium"
        with self.assertRaisesRegex(SignedEntitlementPolicyError, "fields are invalid"):
            verify_signed_entitlement_policy(envelope_bytes(p), verifier=FakeVerifier())

    def test_noncanonical_signature_encoding_fails_closed(self) -> None:
        document = json.loads(envelope_bytes())
        document["signature"] += "="
        with self.assertRaisesRegex(SignedEntitlementPolicyError, "unpadded"):
            verify_signed_entitlement_policy(
                json.dumps(document).encode(), verifier=FakeVerifier()
            )

    def test_feature_ids_must_be_sorted_unique_and_canonical(self) -> None:
        bad_lists = [
            ["data.export", "analysis.engine"],
            ["analysis.engine", "analysis.engine"],
            ["Analysis.Engine", "data.export"],
            ["analysis.engine", "data export"],
        ]
        for features in bad_lists:
            with self.subTest(features=features):
                with self.assertRaises(SignedEntitlementPolicyError):
                    verify_signed_entitlement_policy(
                        envelope_bytes(payload(feature_ids=features)), verifier=FakeVerifier()
                    )

    def test_timestamps_are_canonical_utc_seconds(self) -> None:
        bad = [
            "2026-09-26T18:00:05+00:00",
            "2026-09-26T18:00:05.100Z",
            "2026-09-26T19:00:05+01:00",
        ]
        for timestamp in bad:
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(SignedEntitlementPolicyError):
                    verify_signed_entitlement_policy(
                        envelope_bytes(payload(server_time=timestamp)), verifier=FakeVerifier()
                    )

    def test_temporal_contradictions_fail_closed(self) -> None:
        cases = [
            payload(issued_at="2026-09-26T18:01:00Z", server_time="2026-09-26T18:00:00Z"),
            payload(refresh_after="2026-09-26T17:59:59Z"),
            payload(expires_at="2026-09-26T17:59:59Z"),
            payload(expires_at="2027-09-26T18:00:00Z", grace_until="2027-09-26T17:59:59Z"),
        ]
        for p in cases:
            with self.subTest(p=p):
                with self.assertRaises(SignedEntitlementPolicyError):
                    verify_signed_entitlement_policy(envelope_bytes(p), verifier=FakeVerifier())

    def test_replay_guard_rejects_older_signed_server_time(self) -> None:
        guard = EntitlementReplayGuard()
        verify_signed_entitlement_policy(envelope_bytes(), verifier=FakeVerifier(), replay_guard=guard)
        older = payload(
            policy_id="policy-older",
            issued_at="2026-09-26T17:00:00Z",
            server_time="2026-09-26T17:30:00Z",
            refresh_after="2026-09-26T18:30:00Z",
        )
        with self.assertRaisesRegex(SignedEntitlementPolicyError, "older"):
            verify_signed_entitlement_policy(
                envelope_bytes(older), verifier=FakeVerifier(), replay_guard=guard
            )

    def test_replay_guard_accepts_idempotent_replay_and_newer_policy(self) -> None:
        guard = EntitlementReplayGuard()
        first_bytes = envelope_bytes()
        first = verify_signed_entitlement_policy(first_bytes, verifier=FakeVerifier(), replay_guard=guard)
        repeated = verify_signed_entitlement_policy(first_bytes, verifier=FakeVerifier(), replay_guard=guard)
        self.assertEqual(first.message_sha256, repeated.message_sha256)

        newer = payload(
            policy_id="policy-20260926-0002",
            issued_at="2026-09-26T18:01:00Z",
            server_time="2026-09-26T18:10:00Z",
        )
        verify_signed_entitlement_policy(
            envelope_bytes(newer), verifier=FakeVerifier(), replay_guard=guard
        )

    def test_replay_guard_rejects_conflict_at_same_server_time(self) -> None:
        guard = EntitlementReplayGuard()
        verify_signed_entitlement_policy(envelope_bytes(), verifier=FakeVerifier(), replay_guard=guard)
        conflict = payload(policy_id="policy-conflict", account_id="acct-other")
        with self.assertRaisesRegex(SignedEntitlementPolicyError, "conflicting"):
            verify_signed_entitlement_policy(
                envelope_bytes(conflict), verifier=FakeVerifier(), replay_guard=guard
            )

    def test_private_signing_key_material_is_not_part_of_contract(self) -> None:
        verifier = FakeVerifier()
        policy = verify_signed_entitlement_policy(envelope_bytes(), verifier=verifier)
        rendered = repr(policy)
        self.assertNotIn("private", rendered.lower())
        self.assertNotIn("provider-private", rendered)


if __name__ == "__main__":
    unittest.main()
