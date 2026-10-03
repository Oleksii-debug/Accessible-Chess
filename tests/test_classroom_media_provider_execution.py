from __future__ import annotations

from threading import Thread
import unittest
from unittest import mock

from acs.classroom_media_provider_execution import (
    ClassroomMediaProviderExecutionArbiter,
    MediaProviderExecutionError,
    MediaProviderExecutionOwner,
    MediaProviderExecutionRecoveryRequired,
)


class ClassroomMediaProviderExecutionArbiterTests(unittest.TestCase):
    def make_arbiter(self):
        with mock.patch(
            "acs.classroom_media_provider_execution.secrets.token_hex",
            return_value="ab" * 8,
        ):
            return ClassroomMediaProviderExecutionArbiter()

    def test_session_lease_blocks_effect_lease_until_exact_completion(self):
        arbiter = self.make_arbiter()
        session = arbiter.begin(MediaProviderExecutionOwner.SESSION)
        arbiter.bind_transaction(session.lease_id, "session-" + "1" * 32)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "already active",
        ):
            arbiter.begin(MediaProviderExecutionOwner.EFFECT)

        arbiter.mark_provider_boundary_crossed(session.lease_id)
        arbiter.complete(session.lease_id)

        effect = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        self.assertEqual(effect.owner, MediaProviderExecutionOwner.EFFECT)

    def test_effect_lease_blocks_session_lease_until_exact_completion(self):
        arbiter = self.make_arbiter()
        effect = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(effect.lease_id, "host-" + "2" * 32)
        arbiter.mark_provider_boundary_crossed(effect.lease_id)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "already active",
        ):
            arbiter.begin(MediaProviderExecutionOwner.SESSION)

        arbiter.complete(effect.lease_id)
        session = arbiter.begin(MediaProviderExecutionOwner.SESSION)
        self.assertEqual(session.owner, MediaProviderExecutionOwner.SESSION)

    def test_owner_and_transaction_prefix_must_match(self):
        arbiter = self.make_arbiter()
        session = arbiter.begin(MediaProviderExecutionOwner.SESSION)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "does not match lease owner",
        ):
            arbiter.bind_transaction(session.lease_id, "host-" + "1" * 32)

        self.assertIsNone(arbiter.active_lease.transaction_id)
        bound = arbiter.bind_transaction(
            session.lease_id,
            "session-" + "1" * 32,
        )
        self.assertEqual(bound.transaction_id, "session-" + "1" * 32)

    def test_provider_boundary_requires_bound_transaction(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "bound transaction",
        ):
            arbiter.mark_provider_boundary_crossed(lease.lease_id)

        self.assertFalse(arbiter.active_lease.provider_boundary_crossed)

    def test_provider_boundary_can_be_crossed_only_once(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(lease.lease_id, "host-" + "3" * 32)
        arbiter.mark_provider_boundary_crossed(lease.lease_id)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "already crossed",
        ):
            arbiter.mark_provider_boundary_crossed(lease.lease_id)

        self.assertTrue(arbiter.active_lease.provider_boundary_crossed)

    def test_noop_or_validation_failure_releases_before_provider(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)

        arbiter.release_without_provider(lease.lease_id)

        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)
        next_lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        self.assertIsNotNone(next_lease)

    def test_bound_but_undispatched_transaction_can_be_released(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(lease.lease_id, "host-" + "4" * 32)

        arbiter.release_without_provider(lease.lease_id)

        self.assertIsNone(arbiter.active_lease)

    def test_crossed_provider_boundary_cannot_be_called_not_started(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(lease.lease_id, "host-" + "5" * 32)
        arbiter.mark_provider_boundary_crossed(lease.lease_id)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "crossed the provider boundary",
        ):
            arbiter.release_without_provider(lease.lease_id)

        self.assertEqual(arbiter.active_lease.lease_id, lease.lease_id)

    def test_verified_clean_failure_releases_dispatched_lease(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)
        arbiter.bind_transaction(lease.lease_id, "session-" + "6" * 32)
        arbiter.mark_provider_boundary_crossed(lease.lease_id)

        arbiter.release_after_verified_clean_failure(lease.lease_id)

        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)

    def test_media_effect_cannot_use_verified_clean_failure_shortcut(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(lease.lease_id, "host-" + "7" * 32)
        arbiter.mark_provider_boundary_crossed(lease.lease_id)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "not valid for media-effect",
        ):
            arbiter.release_after_verified_clean_failure(lease.lease_id)

        self.assertEqual(arbiter.active_lease.lease_id, lease.lease_id)
        recovery = arbiter.require_recovery(
            lease.lease_id,
            provider_outcome_unknown=True,
        )
        self.assertTrue(recovery.provider_outcome_unknown)

    def test_verified_clean_failure_rejects_undispatched_lease(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)
        arbiter.bind_transaction(lease.lease_id, "session-" + "7" * 32)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "exact dispatched transaction",
        ):
            arbiter.release_after_verified_clean_failure(lease.lease_id)

        self.assertEqual(arbiter.active_lease.lease_id, lease.lease_id)

    def test_completion_requires_bound_and_dispatched_transaction(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "before exact dispatch",
        ):
            arbiter.complete(lease.lease_id)

        arbiter.bind_transaction(lease.lease_id, "host-" + "8" * 32)
        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "before exact dispatch",
        ):
            arbiter.complete(lease.lease_id)

        arbiter.mark_provider_boundary_crossed(lease.lease_id)
        arbiter.complete(lease.lease_id)
        self.assertIsNone(arbiter.active_lease)

    def test_recovery_requires_exact_bound_coordinator_transaction(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "requires a bound transaction",
        ):
            arbiter.require_recovery(
                lease.lease_id,
                provider_outcome_unknown=False,
            )

        self.assertEqual(arbiter.active_lease.lease_id, lease.lease_id)
        self.assertIsNone(arbiter.recovery_status)

    def test_unknown_outcome_requires_crossed_provider_boundary(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(lease.lease_id, "host-" + "8" * 32)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "requires a crossed provider boundary",
        ):
            arbiter.require_recovery(
                lease.lease_id,
                provider_outcome_unknown=True,
            )

        self.assertEqual(arbiter.active_lease.lease_id, lease.lease_id)
        self.assertIsNone(arbiter.recovery_status)

    def test_unknown_outcome_latches_global_recovery_and_blocks_both_owners(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(lease.lease_id, "host-" + "9" * 32)
        arbiter.mark_provider_boundary_crossed(lease.lease_id)

        status = arbiter.require_recovery(
            lease.lease_id,
            provider_outcome_unknown=True,
        )

        self.assertIsNone(arbiter.active_lease)
        self.assertTrue(status.provider_outcome_unknown)
        self.assertEqual(status.lease.transaction_id, "host-" + "9" * 32)
        for owner in MediaProviderExecutionOwner:
            with self.assertRaises(MediaProviderExecutionRecoveryRequired):
                arbiter.begin(owner)

        arbiter.resolve_recovery(lease.lease_id)
        self.assertIsNone(arbiter.recovery_status)
        self.assertIsNotNone(arbiter.begin(MediaProviderExecutionOwner.SESSION))

    def test_known_partial_recovery_is_distinct_from_unknown_outcome(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)
        arbiter.bind_transaction(lease.lease_id, "session-" + "a" * 32)

        status = arbiter.require_recovery(
            lease.lease_id,
            provider_outcome_unknown=False,
        )

        self.assertFalse(status.provider_outcome_unknown)
        self.assertFalse(status.lease.provider_boundary_crossed)
        self.assertEqual(
            arbiter.recovery_status.lease.transaction_id,
            "session-" + "a" * 32,
        )

    def test_wrong_or_stale_lease_cannot_mutate_active_execution(self):
        arbiter = self.make_arbiter()
        first = arbiter.begin(MediaProviderExecutionOwner.SESSION)
        arbiter.release_without_provider(first.lease_id)
        second = arbiter.begin(MediaProviderExecutionOwner.EFFECT)

        with self.assertRaises(MediaProviderExecutionError):
            arbiter.bind_transaction(first.lease_id, "host-" + "b" * 32)
        with self.assertRaises(MediaProviderExecutionError):
            arbiter.release_without_provider("execution-" + "f" * 32)

        self.assertEqual(arbiter.active_lease.lease_id, second.lease_id)

    def test_recovery_can_only_be_resolved_by_exact_recovery_lease(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(lease.lease_id, "host-" + "c" * 32)
        arbiter.mark_provider_boundary_crossed(lease.lease_id)
        arbiter.require_recovery(
            lease.lease_id,
            provider_outcome_unknown=True,
        )

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "recovery lease is unknown",
        ):
            arbiter.resolve_recovery("execution-" + "f" * 32)

        self.assertIsNotNone(arbiter.recovery_status)

    def test_transaction_can_only_be_bound_once(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)
        arbiter.bind_transaction(lease.lease_id, "host-" + "d" * 32)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "already has a transaction",
        ):
            arbiter.bind_transaction(lease.lease_id, "host-" + "e" * 32)

        self.assertEqual(
            arbiter.active_lease.transaction_id,
            "host-" + "d" * 32,
        )

    def test_invalid_transaction_identity_does_not_change_active_lease(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.EFFECT)

        for transaction in (
            "bad",
            "host-" + "z" * 32,
            "session-" + "1" * 31,
            "host-" + "1" * 33,
        ):
            with self.assertRaises(MediaProviderExecutionError):
                arbiter.bind_transaction(lease.lease_id, transaction)

        self.assertIsNone(arbiter.active_lease.transaction_id)

    def test_non_owner_thread_mutation_is_rejected_without_state_change(self):
        arbiter = self.make_arbiter()
        errors = []

        def begin():
            try:
                arbiter.begin(MediaProviderExecutionOwner.SESSION)
            except Exception as exc:
                errors.append(exc)

        worker = Thread(target=begin)
        worker.start()
        worker.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaProviderExecutionError)
        self.assertIn("owner thread", str(errors[0]))
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)

    def test_public_status_is_non_secret_and_contains_no_payload(self):
        arbiter = self.make_arbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)
        bound = arbiter.bind_transaction(
            lease.lease_id,
            "session-" + "1" * 32,
        )

        self.assertEqual(
            set(bound.__dataclass_fields__),
            {
                "lease_id",
                "owner",
                "transaction_id",
                "provider_boundary_crossed",
            },
        )
        self.assertNotIn("token", repr(bound).lower())
        self.assertNotIn("credential", repr(bound).lower())

    def test_generated_lease_ids_are_bounded_without_tombstone_history(self):
        arbiter = self.make_arbiter()
        ids = []

        for _index in range(512):
            lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)
            ids.append(lease.lease_id)
            arbiter.release_without_provider(lease.lease_id)

        self.assertEqual(len(set(ids)), 512)
        self.assertEqual(
            ids[0],
            "execution-" + ("ab" * 8) + "0000000000000001",
        )
        self.assertEqual(
            ids[-1],
            "execution-" + ("ab" * 8) + "0000000000000200",
        )
        self.assertEqual(arbiter._counter, 512)
        self.assertFalse(hasattr(arbiter, "_used_lease_ids"))


if __name__ == "__main__":
    unittest.main()
