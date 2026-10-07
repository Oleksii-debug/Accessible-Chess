import unittest
from datetime import datetime, timedelta, timezone

from acs.entitlement_runtime_security import (
    ClockSecurityDecision,
    LeaseObservation,
    LockedShellPolicy,
    ProtectedRollbackState,
    RollbackResistantLeaseGuard,
    SAFE_LOCKED_ACTION_IDS,
)
from acs.entitlements import (
    EntitlementSnapshot,
    EntitlementState,
    FeatureId,
    RemotePolicy,
)


NOW = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)


class FakeProtectedStore:
    def __init__(self) -> None:
        self.floor = 0
        self.state = None
        self.conflict = False
        self.raise_on_read = False
        self.raise_on_commit = False
        self.fake_success = False

    def load(self, installation_id):
        if self.raise_on_read:
            raise OSError("provider-private")
        return self.state

    def generation_floor(self, installation_id):
        if self.raise_on_read:
            raise OSError("provider-private")
        return self.floor

    def compare_and_swap(self, installation_id, *, expected_generation, new_state):
        if self.raise_on_commit:
            raise OSError("provider-private")
        if self.conflict or expected_generation != self.floor:
            return False
        if self.fake_success:
            return True
        self.state = new_state
        self.floor = new_state.generation
        return True


def snapshot(
    state=EntitlementState.PAID_YEARLY,
    *,
    server_time=NOW,
    expires_at=NOW + timedelta(days=2),
    refresh_after=NOW + timedelta(hours=12),
):
    return EntitlementSnapshot(
        state=state,
        feature_ids=frozenset(
            {
                FeatureId.PLAY_ENGINE.value,
                FeatureId.ANALYSIS_ENGINE.value,
                FeatureId.DATA_EXPORT.value,
                FeatureId.DATA_RECOVERY.value,
            }
        ),
        server_time=server_time,
        expires_at=expires_at,
        policy=RemotePolicy(refresh_after=refresh_after),
        source="verified_offline_lease",
    )


def observation(
    *,
    lease_id="lease-0001",
    issued_at=NOW - timedelta(minutes=1),
    server_time=NOW,
    expires_at=NOW + timedelta(days=2),
    state=EntitlementState.PAID_YEARLY,
):
    return LeaseObservation(
        installation_id="installation-0001",
        lease_id=lease_id,
        issued_at=issued_at,
        snapshot=snapshot(
            state,
            server_time=server_time,
            expires_at=expires_at,
            refresh_after=min(expires_at, server_time + timedelta(hours=12)),
        ),
    )


class SecuritySection13RollbackResistanceTests(unittest.TestCase):
    def test_verified_lease_requires_server_time_and_finite_expiry(self):
        base = snapshot()
        with self.assertRaisesRegex(ValueError, "server_time"):
            LeaseObservation(
                "installation-0001",
                "lease-0001",
                NOW,
                EntitlementSnapshot(
                    state=base.state,
                    feature_ids=base.feature_ids,
                    expires_at=base.expires_at,
                    server_time=None,
                ),
            )
        with self.assertRaisesRegex(ValueError, "expires_at"):
            LeaseObservation(
                "installation-0001",
                "lease-0001",
                NOW,
                EntitlementSnapshot(
                    state=base.state,
                    feature_ids=base.feature_ids,
                    expires_at=None,
                    server_time=NOW,
                ),
            )

    def test_initial_observation_advances_protected_generation(self):
        store = FakeProtectedStore()
        decision = RollbackResistantLeaseGuard(store).observe(
            observation(), wall_time=NOW
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "trusted_time_advanced")
        self.assertEqual(decision.generation, 1)
        self.assertEqual(decision.effective_time, NOW)
        self.assertEqual(store.floor, 1)
        self.assertEqual(store.state.generation, 1)
        self.assertEqual(store.state.lease_id, "lease-0001")

    def test_small_backward_clock_adjustment_never_moves_authorization_time_backward(self):
        store = FakeProtectedStore()
        guard = RollbackResistantLeaseGuard(store)
        first = guard.observe(observation(), wall_time=NOW + timedelta(minutes=2))
        second = guard.observe(observation(), wall_time=NOW - timedelta(minutes=2))
        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertEqual(second.generation, 2)
        self.assertEqual(second.effective_time, first.effective_time)

    def test_obvious_clock_rollback_fails_closed_without_lowering_floor(self):
        store = FakeProtectedStore()
        guard = RollbackResistantLeaseGuard(store)
        accepted = guard.observe(observation(), wall_time=NOW)
        before = store.state
        denied = guard.observe(
            observation(), wall_time=NOW - timedelta(hours=3)
        )
        self.assertTrue(accepted.allowed)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "clock_rollback")
        self.assertEqual(store.state, before)
        self.assertEqual(store.floor, 1)

    def test_stale_lease_replay_fails_closed(self):
        store = FakeProtectedStore()
        guard = RollbackResistantLeaseGuard(store)
        newer = observation(
            lease_id="lease-0002",
            issued_at=NOW + timedelta(hours=1),
            server_time=NOW + timedelta(hours=1, minutes=1),
        )
        self.assertTrue(
            guard.observe(newer, wall_time=NOW + timedelta(hours=1, minutes=1)).allowed
        )
        stale = observation(
            lease_id="lease-0001",
            issued_at=NOW - timedelta(hours=1),
            server_time=NOW + timedelta(hours=1, minutes=2),
        )
        decision = guard.observe(
            stale, wall_time=NOW + timedelta(hours=1, minutes=2)
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "stale_lease_replay")

    def test_same_time_conflicting_lease_nonce_fails_closed(self):
        store = FakeProtectedStore()
        guard = RollbackResistantLeaseGuard(store)
        first = observation(lease_id="lease-a")
        self.assertTrue(guard.observe(first, wall_time=NOW).allowed)
        conflict = observation(lease_id="lease-b")
        decision = guard.observe(conflict, wall_time=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "conflicting_lease_generation")

    def test_older_signed_server_time_fails_closed(self):
        store = FakeProtectedStore()
        guard = RollbackResistantLeaseGuard(store)
        newer = observation(
            lease_id="lease-new",
            issued_at=NOW,
            server_time=NOW + timedelta(hours=2),
        )
        self.assertTrue(
            guard.observe(newer, wall_time=NOW + timedelta(hours=2)).allowed
        )
        replay = observation(
            lease_id="lease-new",
            issued_at=NOW,
            server_time=NOW + timedelta(hours=1),
        )
        decision = guard.observe(replay, wall_time=NOW + timedelta(hours=2))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "stale_server_time_replay")

    def test_replayed_protected_state_is_detected_by_monotonic_anchor(self):
        store = FakeProtectedStore()
        store.floor = 7
        store.state = ProtectedRollbackState(
            installation_id="installation-0001",
            generation=6,
            lease_id="lease-0001",
            lease_issued_at=NOW - timedelta(minutes=1),
            server_time_floor=NOW,
            effective_time_floor=NOW,
        )
        decision = RollbackResistantLeaseGuard(store).observe(
            observation(), wall_time=NOW
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "protected_state_replay")

    def test_missing_payload_with_existing_anchor_is_state_replay(self):
        store = FakeProtectedStore()
        store.floor = 3
        decision = RollbackResistantLeaseGuard(store).observe(
            observation(), wall_time=NOW
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "protected_state_replay")

    def test_concurrent_stale_publication_fails_closed(self):
        store = FakeProtectedStore()
        store.conflict = True
        decision = RollbackResistantLeaseGuard(store).observe(
            observation(), wall_time=NOW
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "protected_state_conflict")

    def test_false_provider_commit_success_is_not_trusted(self):
        store = FakeProtectedStore()
        store.fake_success = True
        decision = RollbackResistantLeaseGuard(store).observe(
            observation(), wall_time=NOW
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "protected_state_commit_unverified")

    def test_protected_store_failures_are_sanitized_fail_closed(self):
        store = FakeProtectedStore()
        store.raise_on_read = True
        decision = RollbackResistantLeaseGuard(store).observe(
            observation(), wall_time=NOW
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "protected_state_unavailable")
        self.assertNotIn("provider-private", decision.reason)


class SecuritySection14LockedShellTests(unittest.TestCase):
    def setUp(self):
        self.policy = LockedShellPolicy(current_version="2.0.0")
        self.clock_ok = ClockSecurityDecision(True, "trusted_time_advanced", NOW, 3)
        self.clock_bad = ClockSecurityDecision(False, "clock_rollback", None, 3)

    def test_active_verified_lease_allows_entitled_premium_capability(self):
        result = self.policy.evaluate(FeatureId.PLAY_ENGINE, snapshot(), self.clock_ok)
        self.assertTrue(result.capability_allowed)
        self.assertFalse(result.premium_locked)
        self.assertEqual(result.reason, "entitled")
        self.assertTrue(result.preserve_user_data)
        self.assertFalse(result.destructive_action)

    def test_expired_revoked_update_and_unavailable_lock_premium(self):
        cases = (
            snapshot(EntitlementState.EXPIRED),
            snapshot(EntitlementState.REVOKED),
            snapshot(EntitlementState.UPDATE_REQUIRED),
            None,
        )
        for item in cases:
            with self.subTest(snapshot=item):
                result = self.policy.evaluate(
                    FeatureId.PLAY_ENGINE, item, self.clock_ok
                )
                self.assertFalse(result.capability_allowed)
                self.assertTrue(result.premium_locked)
                self.assertTrue(result.preserve_user_data)
                self.assertFalse(result.destructive_action)

    def test_clock_or_state_replay_failure_locks_premium(self):
        result = self.policy.evaluate(
            FeatureId.ANALYSIS_ENGINE, snapshot(), self.clock_bad
        )
        self.assertFalse(result.capability_allowed)
        self.assertTrue(result.premium_locked)
        self.assertEqual(result.reason, "clock_rollback")

    def test_locked_shell_keeps_only_bounded_recovery_actions_reachable(self):
        result = self.policy.evaluate(
            FeatureId.PLAY_ENGINE,
            snapshot(EntitlementState.REVOKED),
            self.clock_ok,
        )
        self.assertEqual(
            set(result.safe_action_ids),
            {
                "account.login",
                "account.recovery",
                "entitlement.refresh",
                "app.update",
                "help.open",
                "data.export",
                "data.recovery",
                "security.status",
            },
        )
        self.assertEqual(result.safe_action_ids, SAFE_LOCKED_ACTION_IDS)

    def test_user_owned_export_and_recovery_remain_available_during_rollback(self):
        for feature in (FeatureId.DATA_EXPORT, FeatureId.DATA_RECOVERY):
            with self.subTest(feature=feature):
                result = self.policy.evaluate(
                    feature,
                    snapshot(EntitlementState.REVOKED),
                    self.clock_bad,
                )
                self.assertTrue(result.capability_allowed)
                self.assertTrue(result.premium_locked)
                self.assertEqual(result.reason, "local_data_safety")
                self.assertFalse(result.destructive_action)

    def test_expired_time_floor_cannot_be_bypassed_by_local_clock(self):
        expired = snapshot(
            server_time=NOW,
            expires_at=NOW + timedelta(minutes=30),
            refresh_after=NOW + timedelta(minutes=20),
        )
        later_clock = ClockSecurityDecision(
            True, "trusted_time_advanced", NOW + timedelta(hours=2), 8
        )
        result = self.policy.evaluate(
            FeatureId.PLAY_ENGINE, expired, later_clock
        )
        self.assertFalse(result.capability_allowed)
        self.assertTrue(result.premium_locked)
        self.assertIn(result.reason, {"expired", "refresh_required"})

    def test_shell_contract_is_presentation_neutral_and_non_destructive(self):
        result = self.policy.evaluate(
            FeatureId.PLAY_ENGINE,
            snapshot(EntitlementState.REVOKED),
            self.clock_ok,
        ).as_dict()
        self.assertTrue(result["premiumLocked"])
        self.assertTrue(result["preserveUserData"])
        self.assertFalse(result["destructiveAction"])
        self.assertEqual(result["featureId"], "play.engine")
        self.assertIsInstance(result["safeActionIds"], list)


if __name__ == "__main__":
    unittest.main()
