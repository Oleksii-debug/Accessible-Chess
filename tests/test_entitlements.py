import unittest
from datetime import datetime, timedelta, timezone

from acs.entitlements import (
    AccountSession,
    CORE_FEATURE_IDS,
    EntitlementSnapshot,
    EntitlementState,
    FeatureGate,
    FeatureId,
    FreeBetaLicensePolicy,
    LicensePolicy,
    ProductVersion,
    RemotePolicy,
)


NOW = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)


class EntitlementTests(unittest.TestCase):
    def gate(self, version="0.4.0"):
        return FeatureGate(current_version=version)

    def snapshot(self, state=EntitlementState.FREE_BETA, **kwargs):
        return EntitlementSnapshot(
            state=state,
            feature_ids=frozenset({"play.engine", "data.export"}),
            server_time=NOW,
            **kwargs,
        )

    def test_product_version_is_dependency_free_and_comparable(self):
        self.assertLess(ProductVersion.parse("0.4"), ProductVersion.parse("0.4.1"))
        self.assertEqual(str(ProductVersion.parse("1.2.3")), "1.2.3")
        with self.assertRaises(ValueError):
            ProductVersion.parse("1.2-beta")

    def test_free_beta_trial_paid_and_organization_use_same_feature_gate(self):
        for state in (
            EntitlementState.FREE_BETA,
            EntitlementState.TRIAL,
            EntitlementState.PAID_MONTHLY,
            EntitlementState.PAID_YEARLY,
            EntitlementState.ORGANIZATION,
        ):
            with self.subTest(state=state):
                decision = self.gate().evaluate("play.engine", self.snapshot(state), now=NOW)
                self.assertTrue(decision.allowed)
                self.assertEqual(decision.reason, "entitled")

    def test_feature_ids_are_stable_normalized_claims(self):
        snapshot = EntitlementSnapshot(
            EntitlementState.PAID_MONTHLY,
            frozenset({"PLAY.ENGINE", "Data.Export"}),
        )
        self.assertIn("play.engine", snapshot.feature_ids)
        self.assertTrue(self.gate().evaluate("PLAY.ENGINE", snapshot, now=NOW).allowed)
        with self.assertRaises(ValueError):
            EntitlementSnapshot(EntitlementState.FREE_BETA, frozenset({"bad id"}))

    def test_feature_catalog_values_are_unique_and_gate_accepts_enum(self):
        values = [feature.value for feature in FeatureId]
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(CORE_FEATURE_IDS, frozenset(values))
        decision = self.gate().evaluate(FeatureId.PLAY_ENGINE, self.snapshot(), now=NOW)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.feature_id, "play.engine")

    def test_free_beta_policy_enables_known_features_without_provider_or_network(self):
        policy = FreeBetaLicensePolicy()
        self.assertIsInstance(policy, LicensePolicy)
        snapshot = policy.entitlement_for()
        self.assertEqual(snapshot.state, EntitlementState.FREE_BETA)
        self.assertEqual(snapshot.feature_ids, CORE_FEATURE_IDS)
        self.assertEqual(snapshot.source, "local_free_beta")
        for feature in FeatureId:
            with self.subTest(feature=feature):
                self.assertTrue(self.gate().evaluate(feature, snapshot, now=NOW).allowed)

    def test_free_beta_policy_carries_only_non_secret_signed_in_identity(self):
        session = AccountSession("acct-1", True, "org-1")
        snapshot = FreeBetaLicensePolicy().entitlement_for(session)
        self.assertEqual(snapshot.account_id, "acct-1")
        self.assertEqual(snapshot.organization_id, "org-1")

        signed_out = FreeBetaLicensePolicy().entitlement_for(
            AccountSession("stale-account", False, "stale-org")
        )
        self.assertIsNone(signed_out.account_id)
        self.assertIsNone(signed_out.organization_id)

    def test_free_beta_policy_can_be_narrowed_for_characterization(self):
        snapshot = FreeBetaLicensePolicy(
            feature_ids=frozenset({FeatureId.DATA_EXPORT.value})
        ).entitlement_for()
        self.assertTrue(self.gate().evaluate(FeatureId.DATA_EXPORT, snapshot, now=NOW).allowed)
        self.assertFalse(self.gate().evaluate(FeatureId.PLAY_ENGINE, snapshot, now=NOW).allowed)

    def test_missing_feature_is_denied_without_provider_specific_logic(self):
        decision = self.gate().evaluate("cloud.sync", self.snapshot(), now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "feature_not_entitled")

    def test_wildcard_can_support_permissive_beta_policy(self):
        snapshot = EntitlementSnapshot(
            EntitlementState.FREE_BETA,
            frozenset({"*"}),
        )
        self.assertTrue(self.gate().evaluate("future.feature", snapshot, now=NOW).allowed)

    def test_revocation_always_wins_over_feature_claim(self):
        decision = self.gate().evaluate(
            "data.export",
            self.snapshot(EntitlementState.REVOKED),
            now=NOW,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "revoked")

    def test_minimum_supported_version_forces_update(self):
        snapshot = self.snapshot(
            policy=RemotePolicy(minimum_supported_version=ProductVersion.parse("0.5.0")),
        )
        decision = self.gate("0.4.0").evaluate("play.engine", snapshot, now=NOW)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_update)
        self.assertEqual(decision.state, EntitlementState.UPDATE_REQUIRED)

    def test_expired_cached_entitlement_can_use_bounded_grace_period(self):
        snapshot = self.snapshot(
            expires_at=NOW - timedelta(hours=1),
            policy=RemotePolicy(grace_until=NOW + timedelta(hours=23)),
        )
        decision = self.gate().evaluate("play.engine", snapshot, now=NOW)
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.using_grace)
        self.assertEqual(decision.state, EntitlementState.GRACE_PERIOD)

    def test_grace_period_expires_closed(self):
        snapshot = self.snapshot(
            EntitlementState.GRACE_PERIOD,
            policy=RemotePolicy(grace_until=NOW - timedelta(seconds=1)),
        )
        decision = self.gate().evaluate("play.engine", snapshot, now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "grace_expired")

    def test_expiry_without_grace_is_denied(self):
        snapshot = self.snapshot(expires_at=NOW - timedelta(seconds=1))
        decision = self.gate().evaluate("play.engine", snapshot, now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.state, EntitlementState.EXPIRED)

    def test_unavailable_entitlement_fails_closed_for_protected_feature(self):
        decision = self.gate().evaluate("play.engine", None, now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "entitlement_unavailable")

    def test_datetime_inputs_must_be_timezone_aware(self):
        with self.assertRaises(ValueError):
            RemotePolicy(grace_until=datetime(2026, 8, 14, 20, 0))
        with self.assertRaises(ValueError):
            self.gate().evaluate("play.engine", self.snapshot(), now=datetime(2026, 8, 14, 20, 0))

    def test_account_session_contains_no_token_or_secret_fields(self):
        session = AccountSession("acct-1", True, "org-1")
        self.assertEqual(session.account_id, "acct-1")
        self.assertFalse(hasattr(session, "access_token"))
        self.assertFalse(hasattr(session, "client_secret"))


if __name__ == "__main__":
    unittest.main()
