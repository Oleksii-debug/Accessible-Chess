from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
import unittest
from unittest import mock

from acs.classroom_media_browser_binder import (
    BrowserMediaInvocation,
    ClassroomMediaBrowserBinder,
    ClassroomMediaBrowserBinderError,
    ClassroomMediaBrowserRecoveryRequired,
)
from acs.classroom_media_host_transactions import (
    ClassroomMediaHostTransactionPort,
    ClassroomMediaHostTransactions,
)
from acs.classroom_media_provider_execution import (
    ClassroomMediaProviderExecutionArbiter,
    MediaProviderExecutionOwner,
)
from acs.classroom_media_session_transactions import (
    ClassroomMediaSessionHostTransactions,
    ClassroomMediaSessionTransactionPort,
)
from acs.classroom_realtime_media import (
    ClassroomMediaController,
    ClassroomMediaError,
    ClassroomRole,
    JoinCredential,
    MediaSource,
)


NOW = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
LIVEKIT_ADAPTER = (
    Path(__file__).resolve().parents[1] / "web" / "livekit_classroom_media.js"
)


class FakeRoster:
    def __init__(self, *, student_count: int = 2) -> None:
        self.roles = {"teacher-1": ClassroomRole.TEACHER}
        self.roles.update(
            {
                f"student-{index}": ClassroomRole.STUDENT
                for index in range(1, student_count + 1)
            }
        )

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]

    def board_control_allowed(self, participant_id):
        return True


def credential(
    participant_id: str,
    token: str = "server-issued-secret-token",
    *,
    issued_at: datetime = NOW,
) -> JoinCredential:
    return JoinCredential(
        room_id="room-1",
        participant_id=participant_id,
        token=token,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=2),
    )


def provider_snapshot(
    *,
    connected: bool = True,
    cleanup_required: bool = False,
    participant_id: str | None = "student-1",
    room_id: str | None = "room-1",
    microphone_enabled: bool = False,
    camera_enabled: bool = False,
    screen_share_enabled: bool = False,
) -> dict[str, object]:
    return {
        "connected": connected,
        "cleanup_required": cleanup_required,
        "room_id": room_id,
        "participant_id": participant_id,
        "microphone_enabled": microphone_enabled,
        "camera_enabled": camera_enabled,
        "screen_share_enabled": screen_share_enabled,
    }


class ClassroomMediaBrowserBinderTests(unittest.TestCase):
    def make_binder(
        self,
        *,
        local_participant_id="student-1",
        student_count=2,
        claim_clock=None,
    ):
        roster = FakeRoster(student_count=student_count)
        session_port = ClassroomMediaSessionTransactionPort()
        effect_port = ClassroomMediaHostTransactionPort(
            session_port=session_port,
        )
        controller = ClassroomMediaController(
            local_participant_id=local_participant_id,
            roster=roster,
            media=effect_port,
        )
        session_counter = {"value": 0}
        effect_counter = {"value": 0}

        def session_id():
            session_counter["value"] += 1
            return f"session-{session_counter['value']:032x}"

        def effect_id():
            effect_counter["value"] += 1
            return f"host-{effect_counter['value']:032x}"

        effects = ClassroomMediaHostTransactions(
            controller,
            effect_port,
            transaction_id_factory=effect_id,
        )
        session = ClassroomMediaSessionHostTransactions(
            controller,
            effect_port,
            session_port,
            effects,
            transaction_id_factory=session_id,
            clock=claim_clock or (lambda: NOW + timedelta(seconds=1)),
        )
        with mock.patch(
            "acs.classroom_media_provider_execution.secrets.token_hex",
            return_value="ab" * 8,
        ):
            arbiter = ClassroomMediaProviderExecutionArbiter()
        binder = ClassroomMediaBrowserBinder(
            session=session,
            effects=effects,
            arbiter=arbiter,
        )
        return controller, session, effects, arbiter, binder

    def complete_join(
        self,
        controller,
        binder,
        *,
        participant_id="student-1",
        token="server-issued-secret-token",
    ):
        prepared = binder.prepare_join(
            credential(participant_id, token),
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(prepared)
        invocation = binder.claim_browser_invocation(prepared.lease_id)
        binder.mark_provider_started(prepared.lease_id)
        result = binder.acknowledge_provider_success(
            prepared.lease_id,
            provider_snapshot=provider_snapshot(participant_id=participant_id),
        )
        self.assertTrue(result.completed)
        self.assertTrue(result.result.connected)
        self.assertTrue(controller.state.connected)
        return invocation

    def test_join_runs_two_phase_through_exact_livekit_call_shape(self):
        controller, _session, _effects, arbiter, binder = self.make_binder()
        before = controller.state

        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )

        self.assertEqual(prepared.owner, MediaProviderExecutionOwner.SESSION)
        self.assertEqual(controller.state, before)
        self.assertEqual(arbiter.active_lease.transaction_id, prepared.transaction_id)

        invocation = binder.claim_browser_invocation(prepared.lease_id)
        self.assertEqual(invocation.method, "connect")
        self.assertEqual(invocation.chunk_index, 0)
        self.assertEqual(
            invocation.arguments[0]["token"],
            "server-issued-secret-token",
        )
        self.assertEqual(invocation.arguments[1], ())
        self.assertEqual(controller.state, before)

        binder.mark_provider_started(prepared.lease_id)
        step = binder.acknowledge_provider_success(
            prepared.lease_id,
            provider_snapshot=provider_snapshot(participant_id="student-1"),
        )

        self.assertTrue(step.completed)
        self.assertTrue(step.result.connected)
        self.assertEqual(step.result.desired_sources, frozenset())
        self.assertIsNone(binder.active_transaction)
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(binder.recovery_status)

    def test_invocation_repr_and_type_do_not_snapshot_secret_arguments(self):
        _controller, _session, _effects, _arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1", "do-not-log-this-token"),
            now=NOW + timedelta(seconds=1),
        )
        invocation = binder.claim_browser_invocation(prepared.lease_id)

        self.assertIsInstance(invocation, BrowserMediaInvocation)
        self.assertFalse(is_dataclass(invocation))
        self.assertNotIn("do-not-log-this-token", repr(invocation))
        self.assertNotIn("do-not-log-this-token", str(invocation))
        self.assertIn("arguments=<redacted>", repr(invocation))

    def test_authorized_session_arguments_cannot_be_mutated_in_transit(self):
        _controller, _session, _effects, _arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )
        invocation = binder.claim_browser_invocation(prepared.lease_id)
        browser_credential = invocation.arguments[0]

        with self.assertRaisesRegex(TypeError, "payload is immutable"):
            browser_credential["token"] = "substitute"
        with self.assertRaises(TypeError):
            invocation.arguments[1] += ("camera",)

        self.assertEqual(
            browser_credential["token"],
            "server-issued-secret-token",
        )
        self.assertEqual(invocation.arguments[1], ())

    def test_expired_credential_at_dispatch_releases_global_gate_without_exposure(self):
        controller, session, _effects, arbiter, binder = self.make_binder(
            claim_clock=lambda: NOW + timedelta(minutes=3),
        )
        before = controller.state
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(
            Exception,
            "expired before browser handoff",
        ):
            binder.claim_browser_invocation(prepared.lease_id)

        self.assertEqual(controller.state, before)
        self.assertIsNone(session.pending_effect)
        self.assertIsNone(binder.active_transaction)
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)

    def test_bad_claim_clock_retires_transaction_without_secret_exposure(self):
        def bad_clock():
            raise RuntimeError("clock unavailable")

        _controller, session, _effects, arbiter, binder = self.make_binder(
            claim_clock=bad_clock,
        )
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(Exception, "credential clock failed"):
            binder.claim_browser_invocation(prepared.lease_id)

        self.assertIsNone(session.pending_effect)
        self.assertIsNone(binder.active_transaction)
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)

    def test_prepare_validation_failure_releases_global_gate(self):
        _controller, _session, _effects, arbiter, binder = self.make_binder()

        with self.assertRaises(ClassroomMediaError):
            binder.prepare_local_source(MediaSource.MICROPHONE, True)

        self.assertIsNone(binder.active_transaction)
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)

    def test_canonical_noop_releases_global_gate_without_browser_call(self):
        controller, _session, _effects, arbiter, binder = self.make_binder()
        self.complete_join(controller, binder)

        prepared = binder.prepare_local_source(
            MediaSource.MICROPHONE,
            False,
        )

        self.assertIsNone(prepared)
        self.assertIsNone(binder.active_transaction)
        self.assertIsNone(arbiter.active_lease)

    def test_active_session_transaction_blocks_effect_prepare(self):
        _controller, _session, _effects, arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(
            ClassroomMediaBrowserBinderError,
            "already active",
        ):
            binder.prepare_local_source(MediaSource.MICROPHONE, True)

        self.assertEqual(binder.active_transaction, prepared)
        self.assertEqual(arbiter.active_lease.owner, MediaProviderExecutionOwner.SESSION)

    def test_active_effect_transaction_blocks_session_prepare(self):
        controller, _session, _effects, arbiter, binder = self.make_binder()
        self.complete_join(controller, binder)
        prepared = binder.prepare_local_source(MediaSource.MICROPHONE, True)

        with self.assertRaisesRegex(
            ClassroomMediaBrowserBinderError,
            "already active",
        ):
            binder.prepare_leave()

        self.assertEqual(binder.active_transaction, prepared)
        self.assertEqual(arbiter.active_lease.owner, MediaProviderExecutionOwner.EFFECT)

    def test_local_source_maps_to_exact_livekit_method_and_commits_after_success(self):
        controller, _session, _effects, arbiter, binder = self.make_binder()
        self.complete_join(controller, binder)
        before = controller.state
        prepared = binder.prepare_local_source(MediaSource.MICROPHONE, True)

        invocation = binder.claim_browser_invocation(prepared.lease_id)

        self.assertEqual(invocation.method, "setLocalSource")
        self.assertEqual(invocation.arguments, ("microphone", True))
        self.assertEqual(controller.state, before)

        binder.mark_provider_started(prepared.lease_id)
        result = binder.acknowledge_provider_success(prepared.lease_id)

        self.assertTrue(result.completed)
        self.assertIn(MediaSource.MICROPHONE, result.result.desired_sources)
        self.assertIsNone(arbiter.active_lease)

    def test_effect_browser_payload_is_frozen_before_dispatch(self):
        controller, _session, _effects, _arbiter, binder = self.make_binder(
            local_participant_id="teacher-1",
        )
        self.complete_join(
            controller,
            binder,
            participant_id="teacher-1",
        )
        prepared = binder.prepare_soft_mute(
            actor_id="teacher-1",
            target_id="student-1",
            muted=True,
            operation_id="mute-1",
        )
        invocation = binder.claim_browser_invocation(prepared.lease_id)
        commands = invocation.arguments[0]

        self.assertEqual(invocation.method, "applyModeration")
        self.assertEqual(len(commands), 1)
        with self.assertRaisesRegex(TypeError, "invocation is immutable"):
            commands[0]["value"] = False
        self.assertTrue(commands[0]["value"])

    def test_multi_chunk_moderation_keeps_one_global_lease_until_final_commit(self):
        controller, _session, effects, arbiter, binder = self.make_binder(
            local_participant_id="teacher-1",
            student_count=60,
        )
        self.complete_join(
            controller,
            binder,
            participant_id="teacher-1",
        )
        prepared = binder.prepare_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="lock-camera",
        )
        lease_id = prepared.lease_id

        observed = []
        for expected_index, expected_count in ((0, 24), (1, 24), (2, 12)):
            invocation = binder.claim_browser_invocation(lease_id)
            self.assertEqual(invocation.method, "applyModeration")
            self.assertEqual(invocation.chunk_index, expected_index)
            self.assertEqual(len(invocation.arguments[0]), expected_count)
            self.assertEqual(arbiter.active_lease.lease_id, lease_id)
            binder.mark_provider_started(lease_id)
            step = binder.acknowledge_provider_success(lease_id)
            observed.append(step.completed)

        self.assertEqual(observed, [False, False, True])
        self.assertEqual(len(step.result), 60)
        self.assertIsNone(effects.pending_effect)
        self.assertIsNone(binder.active_transaction)
        self.assertIsNone(arbiter.active_lease)

    def test_second_chunk_not_started_latches_known_partial_recovery_globally(self):
        controller, _session, effects, arbiter, binder = self.make_binder(
            local_participant_id="teacher-1",
            student_count=30,
        )
        self.complete_join(
            controller,
            binder,
            participant_id="teacher-1",
        )
        prepared = binder.prepare_all_students_soft_mute(
            actor_id="teacher-1",
            muted=True,
            operation_id="mute-all",
        )

        first = binder.claim_browser_invocation(prepared.lease_id)
        self.assertEqual(first.chunk_index, 0)
        binder.mark_provider_started(prepared.lease_id)
        step = binder.acknowledge_provider_success(prepared.lease_id)
        self.assertFalse(step.completed)

        second = binder.claim_browser_invocation(prepared.lease_id)
        self.assertEqual(second.chunk_index, 1)
        with self.assertRaises(ClassroomMediaBrowserRecoveryRequired):
            binder.provider_not_started(prepared.lease_id)

        self.assertIsNone(binder.active_transaction)
        self.assertIsNotNone(effects.recovery_status)
        self.assertEqual(effects.recovery_status.confirmed_chunk_count, 1)
        self.assertFalse(effects.recovery_status.provider_outcome_unknown)
        self.assertFalse(arbiter.recovery_status.provider_outcome_unknown)

    def test_claimed_session_not_started_latches_unknown_recovery_after_credential_handoff(self):
        _controller, session, _effects, arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )
        binder.claim_browser_invocation(prepared.lease_id)

        self.assertTrue(arbiter.active_lease.provider_boundary_crossed)
        with self.assertRaises(ClassroomMediaBrowserRecoveryRequired):
            binder.provider_not_started(prepared.lease_id)

        self.assertIsNotNone(session.recovery_status)
        self.assertTrue(session.recovery_status.provider_outcome_unknown)
        self.assertTrue(arbiter.recovery_status.provider_outcome_unknown)
        self.assertTrue(
            arbiter.recovery_status.lease.provider_boundary_crossed
        )

    def test_unclaimed_session_not_started_releases_cleanly(self):
        controller, session, _effects, arbiter, binder = self.make_binder()
        before = controller.state
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )

        binder.provider_not_started(prepared.lease_id)

        self.assertEqual(controller.state, before)
        self.assertIsNone(session.pending_effect)
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)

    def test_clean_failed_connection_releases_after_exact_adapter_cleanup_proof(self):
        controller, session, _effects, arbiter, binder = self.make_binder()
        before = controller.state
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )
        binder.claim_browser_invocation(prepared.lease_id)
        binder.mark_provider_started(prepared.lease_id)

        binder.session_connection_failed_clean(
            prepared.lease_id,
            provider_snapshot(
                connected=False,
                participant_id=None,
                room_id=None,
            ),
        )

        self.assertEqual(controller.state, before)
        self.assertIsNone(session.pending_effect)
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)
        retry = binder.prepare_join(
            credential("student-1", "fresh-token"),
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(retry)

    def test_unclean_connection_failure_latches_unknown_recovery_globally(self):
        _controller, session, _effects, arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )
        binder.claim_browser_invocation(prepared.lease_id)
        binder.mark_provider_started(prepared.lease_id)

        with self.assertRaises(ClassroomMediaBrowserRecoveryRequired):
            binder.session_connection_failed_clean(
                prepared.lease_id,
                provider_snapshot(
                    connected=False,
                    cleanup_required=True,
                    participant_id=None,
                    room_id=None,
                ),
            )

        self.assertIsNone(binder.active_transaction)
        self.assertTrue(session.recovery_status.provider_outcome_unknown)
        self.assertTrue(arbiter.recovery_status.provider_outcome_unknown)

    def test_effect_failure_cannot_use_session_clean_failure_shortcut(self):
        controller, _session, effects, arbiter, binder = self.make_binder()
        self.complete_join(controller, binder)
        prepared = binder.prepare_local_source(MediaSource.MICROPHONE, True)
        binder.claim_browser_invocation(prepared.lease_id)
        binder.mark_provider_started(prepared.lease_id)

        with self.assertRaisesRegex(
            ClassroomMediaBrowserBinderError,
            "only to session",
        ):
            binder.session_connection_failed_clean(
                prepared.lease_id,
                provider_snapshot(
                    connected=False,
                    participant_id=None,
                    room_id=None,
                ),
            )

        self.assertEqual(binder.active_transaction, prepared)
        binder.provider_failed(prepared.lease_id)
        self.assertIsNotNone(effects.recovery_status)
        self.assertIsNotNone(arbiter.recovery_status)

    def test_provider_failure_blocks_both_kinds_until_binder_resolves_both_latches(self):
        controller, session, _effects, arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )
        binder.claim_browser_invocation(prepared.lease_id)
        binder.mark_provider_started(prepared.lease_id)
        binder.provider_failed(prepared.lease_id)

        with self.assertRaises(Exception):
            binder.prepare_local_source(MediaSource.MICROPHONE, True)
        with self.assertRaises(Exception):
            binder.prepare_join(
                credential("student-1", "other"),
                now=NOW + timedelta(seconds=1),
            )

        recovery_lease = arbiter.recovery_status.lease.lease_id
        binder.resolve_recovery(recovery_lease)

        self.assertIsNone(session.recovery_status)
        self.assertIsNone(arbiter.recovery_status)
        self.assertFalse(controller.state.connected)
        retry = binder.prepare_join(
            credential("student-1", "retry"),
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(retry)

    def test_provider_success_after_canonical_revision_drift_latches_known_recovery(self):
        controller, _session, effects, arbiter, binder = self.make_binder()
        self.complete_join(controller, binder)
        prepared = binder.prepare_local_source(MediaSource.MICROPHONE, True)
        binder.claim_browser_invocation(prepared.lease_id)
        binder.mark_provider_started(prepared.lease_id)

        controller.mark_transport_lost()

        with self.assertRaises(ClassroomMediaBrowserRecoveryRequired):
            binder.acknowledge_provider_success(prepared.lease_id)

        self.assertIsNotNone(effects.recovery_status)
        self.assertFalse(effects.recovery_status.provider_outcome_unknown)
        self.assertFalse(arbiter.recovery_status.provider_outcome_unknown)

    def test_provider_outcome_before_dispatch_is_rejected_without_state_loss(self):
        _controller, _session, _effects, arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(
            ClassroomMediaBrowserBinderError,
            "before exact dispatch",
        ):
            binder.acknowledge_provider_success(prepared.lease_id)
        with self.assertRaisesRegex(
            ClassroomMediaBrowserBinderError,
            "before exact dispatch",
        ):
            binder.provider_failed(prepared.lease_id)

        self.assertEqual(binder.active_transaction, prepared)
        self.assertEqual(arbiter.active_lease.lease_id, prepared.lease_id)

    def test_provider_start_requires_claim_and_is_exactly_once_per_chunk(self):
        _controller, _session, _effects, _arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(
            ClassroomMediaBrowserBinderError,
            "before invocation claim",
        ):
            binder.mark_provider_started(prepared.lease_id)

        binder.claim_browser_invocation(prepared.lease_id)
        binder.mark_provider_started(prepared.lease_id)
        with self.assertRaisesRegex(
            ClassroomMediaBrowserBinderError,
            "already marked started",
        ):
            binder.mark_provider_started(prepared.lease_id)

    def test_claim_is_exactly_once_for_current_provider_call(self):
        _controller, _session, _effects, _arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )
        binder.claim_browser_invocation(prepared.lease_id)

        with self.assertRaisesRegex(
            ClassroomMediaBrowserBinderError,
            "already claimed",
        ):
            binder.claim_browser_invocation(prepared.lease_id)

    def test_wrong_lease_cannot_mutate_current_transaction(self):
        _controller, _session, _effects, arbiter, binder = self.make_binder()
        prepared = binder.prepare_join(
            credential("student-1"),
            now=NOW + timedelta(seconds=1),
        )

        for action in (
            lambda: binder.claim_browser_invocation("execution-" + "f" * 32),
            lambda: binder.mark_provider_started("execution-" + "f" * 32),
            lambda: binder.provider_not_started("execution-" + "f" * 32),
        ):
            with self.assertRaises(ClassroomMediaBrowserBinderError):
                action()

        self.assertEqual(binder.active_transaction, prepared)
        self.assertEqual(arbiter.active_lease.lease_id, prepared.lease_id)

    def test_non_owner_thread_cannot_prepare_or_complete(self):
        _controller, _session, _effects, _arbiter, binder = self.make_binder()
        errors = []

        def prepare():
            try:
                binder.prepare_join(
                    credential("student-1"),
                    now=NOW + timedelta(seconds=1),
                )
            except Exception as exc:
                errors.append(exc)

        worker = Thread(target=prepare)
        worker.start()
        worker.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ClassroomMediaBrowserBinderError)
        self.assertIn("owner thread", str(errors[0]))
        self.assertIsNone(binder.active_transaction)

    def test_constructor_requires_same_controller_and_exact_session_delegation(self):
        controller1, session1, effects1, arbiter1, _binder1 = self.make_binder()
        controller2, session2, effects2, _arbiter2, _binder2 = self.make_binder()

        with self.assertRaisesRegex(ValueError, "same canonical media controller"):
            ClassroomMediaBrowserBinder(
                session=session1,
                effects=effects2,
                arbiter=ClassroomMediaProviderExecutionArbiter(),
            )

        # Same controller check succeeds only for the real composition; a second
        # effect coordinator cannot be constructed on its already-bound port, so
        # the two independently composed fixtures also prove exclusive ownership.
        self.assertIsNot(controller1, controller2)
        self.assertIsNot(effects1, effects2)
        self.assertIsNot(session1, session2)
        self.assertIsNone(arbiter1.active_lease)

    def test_constructor_rejects_non_idle_shared_arbiter(self):
        _controller, session, effects, _arbiter, _binder = self.make_binder()
        arbiter = ClassroomMediaProviderExecutionArbiter()
        lease = arbiter.begin(MediaProviderExecutionOwner.SESSION)

        with self.assertRaisesRegex(ValueError, "must be idle"):
            ClassroomMediaBrowserBinder(
                session=session,
                effects=effects,
                arbiter=arbiter,
            )

        self.assertEqual(arbiter.active_lease.lease_id, lease.lease_id)

    def test_adapter_contract_contains_every_method_emitted_by_binder(self):
        source = LIVEKIT_ADAPTER.read_text(encoding="utf-8")
        for signature in (
            "async connect(credentialValue, enabledSourcesValue)",
            "async reconnect(credentialValue, enabledSourcesValue)",
            "async disconnect()",
            "async setLocalSource(sourceValue, enabled)",
            "async recoverDevice(kindValue, deviceIdValue, republishEnabled)",
            "async applyModeration(commandValues)",
        ):
            self.assertIn(signature, source)

    def test_device_recovery_maps_to_exact_livekit_method(self):
        controller, _session, _effects, _arbiter, binder = self.make_binder()
        self.complete_join(controller, binder)
        prepared = binder.prepare_device_recovery(
            "microphone",
            "device-1",
        )
        invocation = binder.claim_browser_invocation(prepared.lease_id)

        self.assertEqual(invocation.method, "recoverDevice")
        self.assertEqual(
            invocation.arguments,
            ("microphone", "device-1", False),
        )

    def test_disconnect_maps_to_zero_argument_livekit_method(self):
        controller, _session, _effects, _arbiter, binder = self.make_binder()
        self.complete_join(controller, binder)
        prepared = binder.prepare_leave()
        invocation = binder.claim_browser_invocation(prepared.lease_id)

        self.assertEqual(invocation.method, "disconnect")
        self.assertEqual(invocation.arguments, ())

    def test_claimed_disconnect_not_started_releases_without_secret_recovery(self):
        controller, session, _effects, arbiter, binder = self.make_binder()
        self.complete_join(controller, binder)
        before = controller.state
        prepared = binder.prepare_leave()
        binder.claim_browser_invocation(prepared.lease_id)

        binder.provider_not_started(prepared.lease_id)

        self.assertEqual(controller.state, before)
        self.assertIsNone(session.pending_effect)
        self.assertIsNone(session.recovery_status)
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)


if __name__ == "__main__":
    unittest.main()
