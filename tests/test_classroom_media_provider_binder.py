from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from acs.classroom_media_host_transactions import (
    ClassroomMediaHostTransactionPort,
    ClassroomMediaHostTransactions,
    MediaHostRecoveryRequired,
    MediaHostTransactionError,
)
from acs.classroom_media_provider_binder import ClassroomMediaProviderBinder
from acs.classroom_media_provider_execution import (
    ClassroomMediaProviderExecutionArbiter,
    MediaProviderExecutionError,
    MediaProviderExecutionOwner,
    MediaProviderExecutionRecoveryRequired,
)
from acs.classroom_media_session_transactions import (
    ClassroomMediaSessionHostTransactions,
    ClassroomMediaSessionTransactionPort,
)
from acs.classroom_realtime_media import (
    ClassroomMediaController,
    ClassroomRole,
    JoinCredential,
    MediaSource,
)


NOW = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)
TOKEN = "shipping-binder-short-lived-secret"


class FakeRoster:
    def __init__(self, *, teacher_local: bool = False, student_count: int = 2) -> None:
        self.roles = {"teacher-1": ClassroomRole.TEACHER}
        self.roles.update(
            {
                f"student-{index}": ClassroomRole.STUDENT
                for index in range(1, student_count + 1)
            }
        )
        self.local_id = "teacher-1" if teacher_local else "student-1"

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]

    def board_control_allowed(self, participant_id):
        return participant_id == "teacher-1"


def credential(participant_id: str) -> JoinCredential:
    return JoinCredential(
        room_id="room-1",
        participant_id=participant_id,
        token=TOKEN,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )


def provider_snapshot(
    *,
    connected: bool,
    room_id: str | None,
    participant_id: str | None,
    microphone: bool = False,
    camera: bool = False,
    screen_share: bool = False,
    cleanup_required: bool = False,
):
    return {
        "connected": connected,
        "cleanup_required": cleanup_required,
        "room_id": room_id,
        "participant_id": participant_id,
        "microphone_enabled": microphone,
        "camera_enabled": camera,
        "screen_share_enabled": screen_share,
    }


class ClassroomMediaProviderBinderTests(unittest.TestCase):
    def make_composition(self, *, teacher_local: bool = False, student_count: int = 2):
        roster = FakeRoster(
            teacher_local=teacher_local,
            student_count=student_count,
        )
        session_port = ClassroomMediaSessionTransactionPort()
        outer_port = ClassroomMediaHostTransactionPort(session_port=session_port)
        controller = ClassroomMediaController(
            local_participant_id=roster.local_id,
            roster=roster,
            media=outer_port,
        )

        host_counter = {"value": 0}

        def host_id():
            host_counter["value"] += 1
            return f"host-{host_counter['value']:032x}"

        host = ClassroomMediaHostTransactions(
            controller,
            outer_port,
            transaction_id_factory=host_id,
        )

        session_counter = {"value": 0}

        def session_id():
            session_counter["value"] += 1
            return f"session-{session_counter['value']:032x}"

        sessions = ClassroomMediaSessionHostTransactions(
            controller,
            outer_port,
            session_port,
            host,
            transaction_id_factory=session_id,
            clock=lambda: NOW + timedelta(seconds=2),
        )
        arbiter = ClassroomMediaProviderExecutionArbiter()
        binder = ClassroomMediaProviderBinder(
            host,
            sessions,
            arbiter=arbiter,
        )
        return controller, roster, host, sessions, arbiter, binder

    def join(self, controller, roster, binder):
        value = credential(roster.local_id)
        lease = binder.prepare_join(
            value,
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(lease)
        self.assertIs(lease.owner, MediaProviderExecutionOwner.SESSION)
        transaction_id = lease.transaction_id
        self.assertIsNotNone(transaction_id)

        payload = binder.pending_browser_payload(transaction_id)
        self.assertEqual(payload["operation"], "connect")
        self.assertNotIn("token", payload)
        secret = binder.take_session_credential(transaction_id)
        self.assertEqual(secret["token"], TOKEN)
        binder.mark_provider_dispatched(transaction_id)
        result = binder.acknowledge_session_success(
            transaction_id,
            provider_snapshot(
                connected=True,
                room_id="room-1",
                participant_id=roster.local_id,
            ),
        )
        self.assertTrue(result.connected)
        self.assertTrue(controller.state.connected)
        self.assertIsNone(binder.active_lease)
        return result

    def test_session_lease_is_acquired_before_prepare_and_blocks_effect_prepare(self):
        _controller, roster, host, sessions, arbiter, binder = self.make_composition()
        lease = binder.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(lease)
        self.assertIs(arbiter.active_lease.owner, MediaProviderExecutionOwner.SESSION)
        self.assertIsNotNone(sessions.pending_effect)
        self.assertIsNone(host.pending_effect)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "already active",
        ):
            binder.prepare_local_source(MediaSource.CAMERA, True)

        self.assertIsNone(host.pending_effect)
        binder.provider_not_started(lease.transaction_id)
        self.assertIsNone(arbiter.active_lease)

    def test_effect_lease_blocks_session_prepare_before_session_coordinator_mutates(self):
        controller, roster, host, sessions, arbiter, binder = self.make_composition()
        self.join(controller, roster, binder)

        lease = binder.prepare_local_source(MediaSource.CAMERA, True)
        self.assertIsNotNone(lease)
        self.assertIs(arbiter.active_lease.owner, MediaProviderExecutionOwner.EFFECT)
        self.assertIsNotNone(host.pending_effect)
        self.assertIsNone(sessions.pending_effect)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "already active",
        ):
            binder.prepare_disconnect()

        self.assertIsNone(sessions.pending_effect)
        binder.provider_not_started(lease.transaction_id)
        self.assertIsNone(arbiter.active_lease)

    def test_connect_cannot_cross_provider_boundary_before_one_shot_credential_handoff(self):
        _controller, roster, _host, sessions, arbiter, binder = self.make_composition()
        lease = binder.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "requires credential handoff",
        ):
            binder.mark_provider_dispatched(lease.transaction_id)

        self.assertFalse(arbiter.active_lease.provider_boundary_crossed)
        self.assertIsNotNone(sessions.pending_effect)
        binder.provider_not_started(lease.transaction_id)

    def test_credential_handoff_without_provider_dispatch_latches_global_unknown_recovery(self):
        _controller, roster, _host, sessions, arbiter, binder = self.make_composition()
        lease = binder.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        handed = binder.take_session_credential(lease.transaction_id)
        self.assertEqual(handed["token"], TOKEN)

        with self.assertRaises(MediaHostRecoveryRequired):
            binder.provider_not_started(lease.transaction_id)

        self.assertIsNone(arbiter.active_lease)
        status = binder.recovery_status
        self.assertIsNotNone(status)
        self.assertTrue(status.provider_outcome_unknown)
        self.assertTrue(status.lease.provider_boundary_crossed)
        self.assertTrue(sessions.recovery_status.provider_outcome_unknown)
        self.assertIsNotNone(sessions.recovery_status)

        with self.assertRaises(MediaProviderExecutionRecoveryRequired):
            binder.prepare_local_source(MediaSource.CAMERA, True)

        binder.resolve_recovery(lease.transaction_id)
        self.assertIsNone(binder.recovery_status)
        self.assertIsNone(sessions.recovery_status)

    def test_session_success_commits_only_after_exact_dispatched_provider_snapshot(self):
        controller, roster, _host, _sessions, _arbiter, binder = self.make_composition()
        before = controller.state
        lease = binder.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(controller.state, before)
        binder.take_session_credential(lease.transaction_id)
        binder.mark_provider_dispatched(lease.transaction_id)

        result = binder.acknowledge_session_success(
            lease.transaction_id,
            provider_snapshot(
                connected=True,
                room_id="room-1",
                participant_id=roster.local_id,
            ),
        )

        self.assertTrue(result.connected)
        self.assertEqual(controller.state, result)
        self.assertIsNone(binder.active_lease)
        self.assertIsNone(binder.recovery_status)

    def test_verified_clean_connect_failure_releases_both_transaction_layers(self):
        _controller, roster, _host, sessions, arbiter, binder = self.make_composition()
        lease = binder.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        binder.take_session_credential(lease.transaction_id)
        binder.mark_provider_dispatched(lease.transaction_id)

        binder.provider_connection_failed_clean(
            lease.transaction_id,
            provider_snapshot(
                connected=False,
                room_id=None,
                participant_id=None,
            ),
        )

        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(arbiter.recovery_status)
        self.assertIsNone(sessions.pending_effect)
        self.assertIsNone(sessions.recovery_status)

    def test_unproven_connect_cleanup_failure_latches_both_recovery_layers(self):
        _controller, roster, _host, sessions, arbiter, binder = self.make_composition()
        lease = binder.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        binder.take_session_credential(lease.transaction_id)
        binder.mark_provider_dispatched(lease.transaction_id)

        with self.assertRaises(MediaHostRecoveryRequired):
            binder.provider_connection_failed_clean(
                lease.transaction_id,
                provider_snapshot(
                    connected=False,
                    cleanup_required=True,
                    room_id=None,
                    participant_id=None,
                ),
            )

        self.assertIsNotNone(sessions.recovery_status)
        self.assertIsNone(arbiter.active_lease)
        self.assertTrue(arbiter.recovery_status.provider_outcome_unknown)
        self.assertTrue(arbiter.recovery_status.lease.provider_boundary_crossed)

    def test_nonsecret_effect_keeps_global_lease_until_canonical_commit(self):
        controller, roster, host, _sessions, arbiter, binder = self.make_composition()
        self.join(controller, roster, binder)
        revision = controller.state.revision

        lease = binder.prepare_local_source(MediaSource.CAMERA, True)
        self.assertEqual(controller.state.revision, revision)
        payload = binder.pending_browser_payload(lease.transaction_id)
        self.assertEqual(payload["operation"], "set_local_source")
        binder.mark_provider_dispatched(lease.transaction_id)
        self.assertTrue(arbiter.active_lease.provider_boundary_crossed)

        committed = binder.commit_effect_success(lease.transaction_id)

        self.assertEqual(controller.state, committed)
        self.assertIn(MediaSource.CAMERA, controller.state.desired_sources)
        self.assertIsNone(host.pending_effect)
        self.assertIsNone(arbiter.active_lease)

    def test_multi_chunk_moderation_retains_same_global_lease_until_final_chunk(self):
        controller, roster, host, _sessions, arbiter, binder = self.make_composition(
            teacher_local=True,
            student_count=30,
        )
        self.join(controller, roster, binder)

        lease = binder.prepare_all_students_soft_mute(
            actor_id="teacher-1",
            muted=True,
            operation_id="mute-all",
        )
        effect = host.pending_effect
        self.assertIsNotNone(effect)
        self.assertEqual(effect.browser_payload_count(), 2)
        first_payload = binder.pending_browser_payload(lease.transaction_id)
        self.assertEqual(len(first_payload["operations"]), 24)

        binder.mark_provider_dispatched(lease.transaction_id)
        self.assertIsNone(
            binder.acknowledge_effect_chunk_success(
                lease.transaction_id,
                0,
            )
        )
        self.assertEqual(
            arbiter.active_lease.transaction_id,
            lease.transaction_id,
        )
        second_payload = binder.pending_browser_payload(lease.transaction_id)
        self.assertEqual(len(second_payload["operations"]), 6)

        binder.acknowledge_effect_chunk_success(
            lease.transaction_id,
            1,
        )
        self.assertIsNone(arbiter.active_lease)
        self.assertIsNone(host.pending_effect)

    def test_single_call_effect_commit_rejects_multi_chunk_before_any_acknowledgement(self):
        controller, roster, host, _sessions, arbiter, binder = self.make_composition(
            teacher_local=True,
            student_count=30,
        )
        self.join(controller, roster, binder)
        lease = binder.prepare_all_students_soft_mute(
            actor_id="teacher-1",
            muted=True,
            operation_id="mute-all-single-call",
        )
        binder.mark_provider_dispatched(lease.transaction_id)
        before_payload = binder.pending_browser_payload(lease.transaction_id)
        self.assertEqual(len(before_payload["operations"]), 24)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "multi-chunk",
        ):
            binder.commit_effect_success(lease.transaction_id)

        after_payload = binder.pending_browser_payload(lease.transaction_id)
        self.assertEqual(after_payload, before_payload)
        self.assertEqual(host.recovery_status, None)
        self.assertEqual(
            arbiter.active_lease.transaction_id,
            lease.transaction_id,
        )
        binder.provider_failed(lease.transaction_id)
        binder.resolve_recovery(lease.transaction_id)

    def test_expired_credential_before_handoff_releases_global_lease(self):
        _controller, roster, _host, sessions, arbiter, binder = self.make_composition()
        expired = JoinCredential(
            room_id="room-1",
            participant_id=roster.local_id,
            token="expired-secret",
            issued_at=NOW - timedelta(minutes=2),
            expires_at=NOW - timedelta(minutes=1),
        )
        # Preparation validates against the explicit prepare time, so use a
        # still-valid timestamp and let the handoff clock reject it later.
        lease = binder.prepare_join(
            expired,
            now=NOW - timedelta(minutes=1, seconds=30),
        )
        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "expired before browser handoff",
        ):
            binder.take_session_credential(lease.transaction_id)

        self.assertIsNone(sessions.pending_effect)
        self.assertIsNone(sessions.recovery_status)
        self.assertIsNone(arbiter.active_lease)
        retry = binder.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(retry)
        binder.provider_not_started(retry.transaction_id)

    def test_provider_failure_latches_global_recovery_and_blocks_other_owner(self):
        controller, roster, _host, _sessions, arbiter, binder = self.make_composition()
        self.join(controller, roster, binder)
        lease = binder.prepare_local_source(MediaSource.CAMERA, True)
        binder.mark_provider_dispatched(lease.transaction_id)

        binder.provider_failed(lease.transaction_id)

        status = arbiter.recovery_status
        self.assertIsNotNone(status)
        self.assertTrue(status.provider_outcome_unknown)
        with self.assertRaises(MediaProviderExecutionRecoveryRequired):
            binder.prepare_disconnect()

        binder.resolve_recovery(lease.transaction_id)
        self.assertIsNone(arbiter.recovery_status)

    def test_stale_canonical_revision_after_effect_success_is_known_partial_recovery(self):
        controller, roster, host, _sessions, arbiter, binder = self.make_composition()
        self.join(controller, roster, binder)
        lease = binder.prepare_local_source(MediaSource.MICROPHONE, True)
        binder.mark_provider_dispatched(lease.transaction_id)

        controller.mark_transport_lost()

        with self.assertRaises(MediaHostRecoveryRequired):
            binder.commit_effect_success(lease.transaction_id)

        self.assertIsNotNone(host.recovery_status)
        self.assertFalse(host.recovery_status.provider_outcome_unknown)
        self.assertIsNotNone(arbiter.recovery_status)
        self.assertFalse(arbiter.recovery_status.provider_outcome_unknown)
        self.assertTrue(arbiter.recovery_status.lease.provider_boundary_crossed)

    def test_wrong_recovery_transaction_cannot_release_global_or_local_latch(self):
        controller, roster, host, _sessions, arbiter, binder = self.make_composition()
        self.join(controller, roster, binder)
        lease = binder.prepare_local_source(MediaSource.CAMERA, True)
        binder.mark_provider_dispatched(lease.transaction_id)
        binder.provider_outcome_unknown(lease.transaction_id)

        with self.assertRaisesRegex(
            MediaProviderExecutionError,
            "recovery transaction is unknown",
        ):
            binder.resolve_recovery("host-" + "f" * 32)

        self.assertIsNotNone(host.recovery_status)
        self.assertIsNotNone(arbiter.recovery_status)
        binder.resolve_recovery(lease.transaction_id)
        self.assertIsNone(host.recovery_status)
        self.assertIsNone(arbiter.recovery_status)

    def test_public_binder_state_never_retains_or_renders_join_token(self):
        _controller, roster, _host, _sessions, arbiter, binder = self.make_composition()
        lease = binder.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        secret = binder.take_session_credential(lease.transaction_id)
        self.assertEqual(secret["token"], TOKEN)
        self.assertTrue(arbiter.active_lease.provider_boundary_crossed)
        self.assertEqual(repr(secret), "<redacted media session credential>")
        with self.assertRaisesRegex(TypeError, "credential handoff is immutable"):
            secret["token"] = "substitute-token"

        self.assertNotIn(TOKEN, repr(binder))
        self.assertNotIn(TOKEN, repr(binder.active_lease))
        self.assertNotIn(TOKEN, repr(arbiter))
        self.assertNotIn("token", repr(binder.pending_browser_payload(lease.transaction_id)).lower())

        with self.assertRaises(MediaHostRecoveryRequired):
            binder.provider_not_started(lease.transaction_id)
        self.assertNotIn(TOKEN, repr(binder.recovery_status))

    def test_shipping_binder_workflow_binds_live_parent_fail_closed(self):
        source = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "classroom-media-shipping-binder.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            source,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$EVENT_BASE_SHA" HEAD',
            source,
        )
        self.assertIn(
            'git fetch --no-tags origin "$PR_BASE_REF"',
            source,
        )
        self.assertIn(
            'base="$(git rev-parse "refs/remotes/origin/$PR_BASE_REF")"',
            source,
        )
        self.assertIn(
            'git diff --name-only "$base...HEAD"',
            source,
        )
        self.assertNotIn(
            'git diff --name-only "$EVENT_BASE_SHA"',
            source,
        )

    def test_binder_rejects_coordinators_that_do_not_share_exact_host_owner(self):
        _controller_a, _roster_a, host_a, sessions_a, _arbiter_a, _binder_a = (
            self.make_composition()
        )
        _controller_b, _roster_b, host_b, _sessions_b, _arbiter_b, _binder_b = (
            self.make_composition()
        )

        with self.assertRaisesRegex(
            ValueError,
            "share one host owner",
        ):
            ClassroomMediaProviderBinder(host_b, sessions_a)
        self.assertIsNot(host_a, host_b)


if __name__ == "__main__":
    unittest.main()
