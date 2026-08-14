from datetime import datetime, timedelta, timezone
import unittest

from acs.security_contracts import (
    AccessDecision,
    AccountSession,
    DEFAULT_BETA_FEATURES,
    DefaultLicensePolicy,
    Entitlement,
    EntitlementState,
    FeatureGate,
    FEATURE_CLOUD_SYNC,
    FEATURE_ENGINE_ANALYSIS,
    FEATURE_LOCAL_CHESS,
    RemotePolicy,
    permissive_beta_entitlement,
)


NOW = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)


class SecurityContractTests(unittest.TestCase):
    def test_free_beta_can_be_switched_to_paid_without_changing_feature_gate(self):
        gate = FeatureGate()
        beta = permissive_beta_entitlement()
        paid = Entitlement(
            state=EntitlementState.PAID_MONTHLY,
            feature_ids=frozenset({FEATURE_LOCAL_CHESS, FEATURE_ENGINE_ANALYSIS}),
            valid_until=NOW + timedelta(days=30),
        )
        self.assertTrue(gate.allows(beta, FEATURE_LOCAL_CHESS, now=NOW))
        self.assertTrue(gate.allows(paid, FEATURE_LOCAL_CHESS, now=NOW))

    def test_revoked_and_expired_entitlements_deny_protected_features(self):
        gate = FeatureGate()
        features = frozenset({FEATURE_LOCAL_CHESS})
        revoked = Entitlement(EntitlementState.REVOKED, features)
        expired_state = Entitlement(EntitlementState.EXPIRED, features)
        timed_out = Entitlement(
            EntitlementState.PAID_YEARLY,
            features,
            valid_until=NOW - timedelta(seconds=1),
        )
        for entitlement in (revoked, expired_state, timed_out):
            self.assertEqual(
                gate.decision(entitlement, FEATURE_LOCAL_CHESS, now=NOW),
                AccessDecision.DENY,
            )

    def test_update_required_is_distinct_from_payment_denial(self):
        gate = FeatureGate()
        entitlement = Entitlement(
            EntitlementState.UPDATE_REQUIRED,
            frozenset({FEATURE_LOCAL_CHESS}),
        )
        self.assertEqual(
            gate.decision(entitlement, FEATURE_LOCAL_CHESS, now=NOW),
            AccessDecision.UPDATE_REQUIRED,
        )

    def test_feature_ids_are_explicit_not_blanket_subscription_flags(self):
        gate = FeatureGate()
        paid = Entitlement(
            EntitlementState.PAID_MONTHLY,
            frozenset({FEATURE_LOCAL_CHESS}),
            valid_until=NOW + timedelta(days=1),
        )
        self.assertTrue(gate.allows(paid, FEATURE_LOCAL_CHESS, now=NOW))
        self.assertFalse(gate.allows(paid, FEATURE_CLOUD_SYNC, now=NOW))

    def test_beta_registry_does_not_accidentally_unlock_future_online_features(self):
        self.assertIn(FEATURE_LOCAL_CHESS, DEFAULT_BETA_FEATURES)
        self.assertIn(FEATURE_ENGINE_ANALYSIS, DEFAULT_BETA_FEATURES)
        self.assertNotIn(FEATURE_CLOUD_SYNC, DEFAULT_BETA_FEATURES)

    def test_grace_state_can_preserve_access_temporarily(self):
        gate = FeatureGate(DefaultLicensePolicy())
        grace = Entitlement(
            EntitlementState.GRACE,
            frozenset({FEATURE_LOCAL_CHESS}),
            valid_until=NOW + timedelta(hours=48),
        )
        self.assertTrue(gate.allows(grace, FEATURE_LOCAL_CHESS, now=NOW))
        self.assertFalse(gate.allows(grace, FEATURE_LOCAL_CHESS, now=NOW + timedelta(hours=49)))

    def test_account_session_validation_is_time_bounded(self):
        session = AccountSession(
            subject_id="user-1",
            session_id="session-1",
            issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=10),
        )
        self.assertTrue(session.is_valid(NOW))
        self.assertFalse(session.is_valid(NOW + timedelta(minutes=11)))

    def test_remote_policy_rejects_invalid_refresh_and_grace_values(self):
        with self.assertRaises(ValueError):
            RemotePolicy(refresh_after_seconds=0)
        with self.assertRaises(ValueError):
            RemotePolicy(grace_period_seconds=-1)

    def test_feature_gate_rejects_unstable_blank_or_padded_identifier(self):
        gate = FeatureGate()
        entitlement = permissive_beta_entitlement()
        with self.assertRaises(ValueError):
            gate.decision(entitlement, "", now=NOW)
        with self.assertRaises(ValueError):
            gate.decision(entitlement, " local_chess ", now=NOW)


if __name__ == "__main__":
    unittest.main()
