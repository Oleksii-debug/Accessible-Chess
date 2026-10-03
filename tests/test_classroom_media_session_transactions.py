from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Thread
import traceback
import unittest
from unittest import mock

from acs.classroom_media_host_transactions import (
    ClassroomMediaHostTransactionPort,
    ClassroomMediaHostTransactions,
    MediaHostRecoveryRequired,
    MediaHostSingleFlightGate,
    MediaHostTransactionError,
)
from acs.classroom_media_session_transactions import (
    ClassroomMediaSessionHostTransactions,
    ClassroomMediaSessionTransactionPort,
    MediaSessionEffectKind,
)
from acs.classroom_realtime_media import (
    ClassroomMediaController,
    ClassroomMediaError,
    ClassroomRole,
    JoinCredential,
    MediaSource,
)


NOW = datetime(2026, 10, 3, 0, 15, tzinfo=timezone.utc)
TOKEN = "short-lived-provider-token-never-public"


class FakeRoster:
    def __init__(self) -> None:
        self.roles = {
            "student-1": ClassroomRole.STUDENT,
            "teacher-1": ClassroomRole.TEACHER,
        }

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]

    def board_control_allowed(self, participant_id):
        return participant_id == "teacher-1"


def credential(
    *,
    token: str = TOKEN,
    issued_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(minutes=1),
) -> JoinCredential:
    return JoinCredential(
        room_id="room-1",
        participant_id="student-1",
        token=token,
        issued_at=issued_at,
        expires_at=expires_at,
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


class ClassroomMediaSessionHostTransactionTests(unittest.TestCase):
    def make_composition(self, *, session_id=None, host_id=None, clock=None):
        roster = FakeRoster()
        session_port = ClassroomMediaSessionTransactionPort()
        outer_port = ClassroomMediaHostTransactionPort(session_port=session_port)
        controller = ClassroomMediaController(
            local_participant_id="student-1",
            roster=roster,
            media=outer_port,
        )
        gate = MediaHostSingleFlightGate()

        host_counter = {"value": 0}

        def next_host_id():
            host_counter["value"] += 1
            return f"host-{host_counter['value']:032x}"

        nonsecret = ClassroomMediaHostTransactions(
            controller,
            outer_port,
            activity_gate=gate,
            transaction_id_factory=host_id or next_host_id,
        )

        session_counter = {"value": 0}

        def next_session_id():
            session_counter["value"] += 1
            return f"session-{session_counter['value']:032x}"

        sessions = ClassroomMediaSessionHostTransactions(
            controller,
            outer_port,
            session_port,
            nonsecret,
            transaction_id_factory=session_id or next_session_id,
            clock=clock or (lambda: NOW + timedelta(seconds=2)),
        )
        return controller, roster, gate, nonsecret, sessions

    def join(self, controller, sessions, *, value=None):
        value = value or credential()
        effect = sessions.prepare_join(value, now=NOW + timedelta(seconds=1))
        self.assertIsNotNone(effect)
        secret = sessions.take_credential(effect.transaction_id)
        result = sessions.acknowledge_provider_success(
            effect.transaction_id,
            provider_snapshot(
                connected=True,
                room_id=value.room_id,
                participant_id=value.participant_id,
            ),
        )
        self.assertTrue(result.connected)
        self.assertTrue(controller.state.connected)
        return effect

    def test_join_prepares_without_state_commit_or_auto_publish(self):
        controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        before = controller.state

        effect = sessions.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )

        self.assertEqual(effect.kind, MediaSessionEffectKind.CONNECT)
        self.assertEqual(effect.enabled_sources, ())
        self.assertEqual(controller.state, before)
        self.assertTrue(gate.occupied)
        payload = sessions.pending_browser_payload
        self.assertEqual(payload["operation"], "connect")
        self.assertEqual(payload["enabled_sources"], [])
        self.assertTrue(payload["credential_required"])
        self.assertNotIn(TOKEN, repr(effect))
        self.assertNotIn(TOKEN, repr(payload))
        self.assertNotIn("token", payload)

    def test_join_credential_is_exact_and_one_shot(self):
        controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        value = credential()
        effect = sessions.prepare_join(value, now=NOW + timedelta(seconds=1))

        handed = sessions.take_credential(effect.transaction_id)

        self.assertEqual(
            handed,
            {
                "room_id": "room-1",
                "participant_id": "student-1",
                "token": TOKEN,
            },
        )
        self.assertNotIn(TOKEN, repr(handed))
        self.assertNotIn("room-1", repr(handed))
        self.assertNotIn("student-1", repr(handed))
        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "already handed off",
        ):
            sessions.take_credential(effect.transaction_id)

        committed = sessions.acknowledge_provider_success(
            effect.transaction_id,
            provider_snapshot(
                connected=True,
                room_id="room-1",
                participant_id="student-1",
            ),
        )
        self.assertTrue(committed.connected)
        self.assertEqual(committed.desired_sources, frozenset())
        self.assertFalse(gate.occupied)
        self.assertTrue(controller.state.connected)

    def test_direct_join_outside_session_transaction_fails_before_state_commit(self):
        controller, _roster, _gate, _nonsecret, _sessions = self.make_composition()
        before = controller.state

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "active host transaction",
        ):
            controller.join(credential(), now=NOW + timedelta(seconds=1))

        self.assertEqual(controller.state, before)

    def test_expired_between_prepare_and_handoff_never_exposes_token(self):
        current = {"value": NOW + timedelta(seconds=1)}
        controller, _roster, gate, _nonsecret, sessions = self.make_composition(
            clock=lambda: current["value"],
        )
        value = credential(
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=5),
        )
        effect = sessions.prepare_join(value, now=NOW + timedelta(seconds=1))
        current["value"] = NOW + timedelta(seconds=6)

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "^media session credential expired before browser handoff$",
        ) as caught:
            sessions.take_credential(effect.transaction_id)

        self.assertIsNone(caught.exception.__cause__)

        self.assertIsNone(sessions.pending_effect)
        self.assertFalse(gate.occupied)
        self.assertEqual(controller.state.room_id, None)
        self.assertNotIn(TOKEN, repr(sessions))

    def test_clock_failure_before_handoff_is_sanitized_and_releases_gate(self):
        def broken_clock():
            raise RuntimeError("private clock detail")

        _controller, _roster, gate, _nonsecret, sessions = self.make_composition(
            clock=broken_clock,
        )
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "^media session credential clock failed$",
        ) as caught:
            sessions.take_credential(effect.transaction_id)

        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(sessions.pending_effect)
        self.assertFalse(gate.occupied)
        self.assertNotIn("private clock detail", str(caught.exception))

    def test_provider_not_started_is_safe_only_before_secret_handoff(self):
        controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.provider_not_started(effect.transaction_id)

        self.assertFalse(gate.occupied)
        self.assertIsNone(sessions.pending_effect)
        self.assertEqual(controller.state.room_id, None)

        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)
        with self.assertRaisesRegex(
            MediaHostRecoveryRequired,
            "credential already crossed",
        ):
            sessions.provider_not_started(effect.transaction_id)

        status = sessions.recovery_status
        self.assertIsNotNone(status)
        self.assertTrue(status.provider_outcome_unknown)
        self.assertTrue(status.credential_handed_off)
        self.assertNotIn(TOKEN, repr(status))
        self.assertNotIn(TOKEN, repr(sessions))
        self.assertTrue(gate.occupied)

    def test_verified_clean_connect_failure_allows_fresh_retry_without_recovery(self):
        controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)

        sessions.provider_connection_failed_clean(
            effect.transaction_id,
            provider_snapshot(
                connected=False,
                room_id=None,
                participant_id=None,
            ),
        )

        self.assertFalse(gate.occupied)
        self.assertIsNone(sessions.pending_effect)
        self.assertIsNone(sessions.recovery_status)
        self.assertEqual(controller.state.room_id, None)
        retry = sessions.prepare_join(
            credential(token="fresh-after-clean-failure"),
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(retry)
        self.assertNotEqual(retry.transaction_id, effect.transaction_id)

    def test_unproven_connect_cleanup_failure_latches_recovery(self):
        controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)

        with self.assertRaisesRegex(
            MediaHostRecoveryRequired,
            "has not proven clean teardown",
        ) as caught:
            sessions.provider_connection_failed_clean(
                effect.transaction_id,
                provider_snapshot(
                    connected=False,
                    cleanup_required=True,
                    room_id=None,
                    participant_id=None,
                ),
            )

        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(gate.occupied)
        self.assertIsNotNone(sessions.recovery_status)
        self.assertEqual(controller.state.room_id, None)

    def test_verified_clean_failure_does_not_apply_to_disconnect(self):
        controller, _roster, _gate, _nonsecret, sessions = self.make_composition()
        self.join(controller, sessions)
        effect = sessions.prepare_disconnect()

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "only to connect or reconnect",
        ):
            sessions.provider_connection_failed_clean(
                effect.transaction_id,
                provider_snapshot(
                    connected=False,
                    room_id=None,
                    participant_id=None,
                ),
            )

        self.assertEqual(sessions.pending_effect, effect)
        self.assertTrue(controller.state.connected)

    def test_provider_failure_drops_secret_from_recovery_and_blocks_new_effects(self):
        controller, _roster, gate, nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)
        sessions.provider_failed(effect.transaction_id)

        status = sessions.recovery_status
        self.assertIsNotNone(status)
        self.assertNotIn(TOKEN, repr(status))
        self.assertIsNone(sessions.pending_effect)
        self.assertTrue(gate.occupied)
        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "already active",
        ):
            nonsecret.prepare_local_source(MediaSource.CAMERA, True)

        sessions.resolve_recovery(effect.transaction_id)
        self.assertFalse(gate.occupied)
        self.assertEqual(controller.state.room_id, None)

    def test_success_snapshot_must_match_exact_room_identity_and_zero_sources(self):
        controller, _roster, _gate, _nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)

        with self.assertRaisesRegex(
            MediaHostRecoveryRequired,
            "provider result requires recovery",
        ) as caught:
            sessions.acknowledge_provider_success(
                effect.transaction_id,
                provider_snapshot(
                    connected=True,
                    room_id="room-other",
                    participant_id="student-1",
                    microphone=True,
                ),
            )

        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(TOKEN, "".join(traceback.format_exception(caught.exception)))
        self.assertEqual(controller.state.room_id, None)
        status = sessions.recovery_status
        self.assertIsNotNone(status)
        self.assertTrue(status.provider_outcome_unknown)

    def test_commit_failure_drops_internal_cause_and_private_provider_detail(self):
        controller, _roster, _gate, _nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)

        with mock.patch.object(
            sessions._session_port,
            "_commit",
            side_effect=RuntimeError("private provider detail " + TOKEN),
        ):
            with self.assertRaisesRegex(
                MediaHostRecoveryRequired,
                "^provider session succeeded but canonical commit requires recovery$",
            ) as caught:
                sessions.acknowledge_provider_success(
                    effect.transaction_id,
                    provider_snapshot(
                        connected=True,
                        room_id="room-1",
                        participant_id="student-1",
                    ),
                )

        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("private provider detail", rendered)
        self.assertNotIn(TOKEN, rendered)
        self.assertEqual(controller.state.room_id, None)
        self.assertFalse(sessions.recovery_status.provider_outcome_unknown)

    def test_cleanup_required_snapshot_never_commits_connected_state(self):
        controller, _roster, _gate, _nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)

        with self.assertRaises(MediaHostRecoveryRequired):
            sessions.acknowledge_provider_success(
                effect.transaction_id,
                provider_snapshot(
                    connected=False,
                    cleanup_required=True,
                    room_id=None,
                    participant_id=None,
                ),
            )

        self.assertFalse(controller.state.connected)
        self.assertIsNotNone(sessions.recovery_status)

    def test_reconnect_republishes_only_canonical_desired_and_permitted_sources(self):
        controller, _roster, gate, nonsecret, sessions = self.make_composition()
        self.join(controller, sessions)

        mic = nonsecret.prepare_local_source(MediaSource.MICROPHONE, True)
        nonsecret.commit_provider_success(mic.transaction_id)
        self.assertIn(MediaSource.MICROPHONE, controller.state.desired_sources)

        controller.mark_transport_lost()
        self.assertFalse(controller.state.connected)
        fresh = credential(
            token="fresh-reconnect-token",
            issued_at=NOW + timedelta(seconds=2),
            expires_at=NOW + timedelta(minutes=1),
        )
        effect = sessions.prepare_reconnect(
            fresh,
            now=NOW + timedelta(seconds=3),
        )

        self.assertEqual(effect.kind, MediaSessionEffectKind.RECONNECT)
        self.assertEqual(effect.enabled_sources, (MediaSource.MICROPHONE,))
        payload = sessions.pending_browser_payload
        self.assertEqual(payload["enabled_sources"], ["microphone"])
        handed = sessions.take_credential(effect.transaction_id)
        self.assertEqual(handed["token"], "fresh-reconnect-token")

        sessions.acknowledge_provider_success(
            effect.transaction_id,
            provider_snapshot(
                connected=True,
                room_id="room-1",
                participant_id="student-1",
                microphone=True,
            ),
        )
        self.assertTrue(controller.state.connected)
        self.assertEqual(
            controller.state.desired_sources,
            frozenset({MediaSource.MICROPHONE}),
        )
        self.assertFalse(gate.occupied)

    def test_disconnect_keeps_canonical_connected_until_exact_teardown_ack(self):
        controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        self.join(controller, sessions)
        revision = controller.state.revision

        effect = sessions.prepare_disconnect()

        self.assertEqual(effect.kind, MediaSessionEffectKind.DISCONNECT)
        self.assertTrue(controller.state.connected)
        self.assertEqual(controller.state.revision, revision)
        self.assertFalse(sessions.pending_browser_payload["credential_required"])
        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "has no credential",
        ):
            sessions.take_credential(effect.transaction_id)

        committed = sessions.acknowledge_provider_success(
            effect.transaction_id,
            provider_snapshot(
                connected=False,
                room_id=None,
                participant_id=None,
            ),
        )
        self.assertFalse(committed.connected)
        self.assertIsNone(committed.room_id)
        self.assertFalse(gate.occupied)

    def test_disconnect_not_started_leaves_session_connected(self):
        controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        self.join(controller, sessions)
        before = controller.state

        effect = sessions.prepare_disconnect()
        sessions.provider_not_started(effect.transaction_id)

        self.assertEqual(controller.state, before)
        self.assertFalse(gate.occupied)
        self.assertIsNone(sessions.pending_effect)

    def test_shared_gate_blocks_nonsecret_effect_while_disconnect_is_pending(self):
        controller, _roster, _gate, nonsecret, sessions = self.make_composition()
        self.join(controller, sessions)
        effect = sessions.prepare_disconnect()

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "already active",
        ):
            nonsecret.prepare_local_source(MediaSource.CAMERA, True)

        sessions.provider_not_started(effect.transaction_id)
        local = nonsecret.prepare_local_source(MediaSource.CAMERA, True)
        self.assertIsNotNone(local)

    def test_shared_gate_blocks_disconnect_while_nonsecret_effect_is_pending(self):
        controller, _roster, _gate, nonsecret, sessions = self.make_composition()
        self.join(controller, sessions)
        local = nonsecret.prepare_local_source(MediaSource.CAMERA, True)

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "already active",
        ):
            sessions.prepare_disconnect()

        nonsecret.provider_not_started(local.transaction_id)
        disconnect = sessions.prepare_disconnect()
        self.assertIsNotNone(disconnect)

    def test_stale_canonical_revision_after_provider_success_requires_recovery(self):
        controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        self.join(controller, sessions)
        effect = sessions.prepare_disconnect()
        prepared_revision = controller.state.revision

        # A real transport-loss callback can arrive while browser disconnect is
        # in flight. It changes canonical revision without running another
        # provider effect, so the eventual provider success must not overwrite it.
        controller.mark_transport_lost()
        self.assertGreater(controller.state.revision, prepared_revision)

        with self.assertRaisesRegex(
            MediaHostRecoveryRequired,
            "canonical media state changed",
        ):
            sessions.acknowledge_provider_success(
                effect.transaction_id,
                provider_snapshot(
                    connected=False,
                    room_id=None,
                    participant_id=None,
                ),
            )
        self.assertTrue(gate.occupied)
        self.assertFalse(controller.state.connected)
        self.assertFalse(sessions.recovery_status.provider_outcome_unknown)

    def test_validation_failure_releases_gate_and_unexposed_injected_id(self):
        repeated = "session-" + "a" * 32
        controller, _roster, gate, _nonsecret, sessions = self.make_composition(
            session_id=lambda: repeated,
        )
        expired = credential(
            issued_at=NOW - timedelta(minutes=2),
            expires_at=NOW - timedelta(minutes=1),
        )

        with self.assertRaises(ClassroomMediaError):
            sessions.prepare_join(expired, now=NOW)

        self.assertFalse(gate.occupied)
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        self.assertEqual(effect.transaction_id, repeated)
        self.assertEqual(controller.state.room_id, None)

    def test_noop_disconnect_releases_gate_and_does_not_expose_identity(self):
        repeated = "session-" + "b" * 32
        _controller, _roster, gate, _nonsecret, sessions = self.make_composition(
            session_id=lambda: repeated,
        )

        self.assertIsNone(sessions.prepare_disconnect())
        self.assertFalse(gate.occupied)
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        self.assertEqual(effect.transaction_id, repeated)

    def test_exposed_session_transaction_identity_is_never_reused(self):
        repeated = "session-" + "c" * 32
        _controller, _roster, _gate, _nonsecret, sessions = self.make_composition(
            session_id=lambda: repeated,
        )
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.provider_not_started(effect.transaction_id)

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "reused an identity",
        ):
            sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))

    def test_session_mutation_is_owner_thread_affine(self):
        _controller, _roster, _gate, _nonsecret, sessions = self.make_composition()
        errors = []

        def mutate():
            try:
                sessions.prepare_join(
                    credential(),
                    now=NOW + timedelta(seconds=1),
                )
            except Exception as exc:
                errors.append(exc)

        worker = Thread(target=mutate)
        worker.start()
        worker.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaHostTransactionError)
        self.assertIn("owner thread", str(errors[0]))
        self.assertIsNone(sessions.pending_effect)

    def test_session_coordinator_requires_exact_nonsecret_host_owner(self):
        roster = FakeRoster()

        session_a = ClassroomMediaSessionTransactionPort()
        outer_a = ClassroomMediaHostTransactionPort(session_port=session_a)
        controller_a = ClassroomMediaController(
            local_participant_id="student-1",
            roster=roster,
            media=outer_a,
        )
        host_a = ClassroomMediaHostTransactions(
            controller_a,
            outer_a,
            transaction_id_factory=lambda: "host-" + "1" * 32,
        )

        session_b = ClassroomMediaSessionTransactionPort()
        outer_b = ClassroomMediaHostTransactionPort(session_port=session_b)
        controller_b = ClassroomMediaController(
            local_participant_id="student-1",
            roster=roster,
            media=outer_b,
        )
        host_b = ClassroomMediaHostTransactions(
            controller_b,
            outer_b,
            transaction_id_factory=lambda: "host-" + "2" * 32,
        )

        with self.assertRaisesRegex(
            ValueError,
            "share the exact non-secret host owner",
        ):
            ClassroomMediaSessionHostTransactions(
                controller_a,
                outer_a,
                session_a,
                host_b,
                transaction_id_factory=lambda: "session-" + "e" * 32,
                clock=lambda: NOW + timedelta(seconds=2),
            )

        sessions = ClassroomMediaSessionHostTransactions(
            controller_a,
            outer_a,
            session_a,
            host_a,
            transaction_id_factory=lambda: "session-" + "f" * 32,
            clock=lambda: NOW + timedelta(seconds=2),
        )
        self.assertIsNone(sessions.pending_effect)
        self.assertIs(sessions._activity_gate, host_a.activity_gate)

    def test_provider_success_ack_is_single_use(self):
        controller, _roster, _gate, _nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)
        snapshot = provider_snapshot(
            connected=True,
            room_id="room-1",
            participant_id="student-1",
        )
        sessions.acknowledge_provider_success(effect.transaction_id, snapshot)
        after = controller.state

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "unknown or already consumed",
        ):
            sessions.acknowledge_provider_success(effect.transaction_id, snapshot)
        self.assertEqual(controller.state, after)

    def test_recovery_resolution_is_exact_and_releases_shared_gate(self):
        _controller, _roster, gate, _nonsecret, sessions = self.make_composition()
        effect = sessions.prepare_join(credential(), now=NOW + timedelta(seconds=1))
        sessions.take_credential(effect.transaction_id)
        sessions.provider_outcome_unknown(effect.transaction_id)

        with self.assertRaises(MediaHostTransactionError):
            sessions.resolve_recovery("session-" + "f" * 32)
        self.assertTrue(gate.occupied)

        sessions.resolve_recovery(effect.transaction_id)
        self.assertFalse(gate.occupied)
        self.assertIsNone(sessions.recovery_status)


if __name__ == "__main__":
    unittest.main()
