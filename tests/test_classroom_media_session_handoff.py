from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
import unittest
from unittest import mock

from acs.classroom_media_session_handoff import (
    ClassroomMediaSessionHandoffPort,
    ClassroomMediaSessionHandoffs,
    MediaSessionHandoffError,
    MediaSessionOperation,
    MediaSessionRecoveryRequired,
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
    def __init__(self) -> None:
        self.roles = {
            "teacher-1": ClassroomRole.TEACHER,
            "student-1": ClassroomRole.STUDENT,
        }

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]

    def board_control_allowed(self, participant_id):
        return True


class CompositeMediaPort:
    """Future composition shape: session handoff + separate non-secret effects."""

    def __init__(self, session_port: ClassroomMediaSessionHandoffPort) -> None:
        self._session_port = session_port
        self.local_calls = []
        self.moderation_calls = []
        self.device_calls = []

    def connect(self, credential, *, enabled_sources):
        return self._session_port.connect(
            credential,
            enabled_sources=enabled_sources,
        )

    def reconnect(self, credential, *, enabled_sources):
        return self._session_port.reconnect(
            credential,
            enabled_sources=enabled_sources,
        )

    def disconnect(self):
        return self._session_port.disconnect()

    def set_local_source(self, source, enabled):
        self.local_calls.append((source, enabled))

    def apply_moderation(self, commands):
        self.moderation_calls.append(commands)

    def recover_device(self, kind, device_id, *, republish_enabled):
        self.device_calls.append((kind, device_id, republish_enabled))


def credential(
    token: str = "secret-server-issued-token",
    *,
    issued_at: datetime = NOW,
) -> JoinCredential:
    return JoinCredential(
        room_id="room-1",
        participant_id="student-1",
        token=token,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=2),
    )


class ClassroomMediaSessionHandoffTests(unittest.TestCase):
    def make_host(self, *, transaction_id_factory=None, use_default_ids=False):
        roster = FakeRoster()
        session_port = ClassroomMediaSessionHandoffPort()
        composite = CompositeMediaPort(session_port)
        controller = ClassroomMediaController(
            local_participant_id="student-1",
            roster=roster,
            media=composite,
        )
        counter = {"value": 0}

        def transaction_id():
            counter["value"] += 1
            return f"session-{counter['value']:032x}"

        host = ClassroomMediaSessionHandoffs(
            controller,
            session_port,
            transaction_id_factory=(
                None
                if use_default_ids
                else (transaction_id_factory or transaction_id)
            ),
        )
        return controller, composite, session_port, host

    def complete_join(self, controller, host, value=None):
        value = value or credential()
        effect = host.prepare_join(value, now=NOW + timedelta(seconds=1))
        self.assertIsNotNone(effect)
        payload = host.claim_browser_payload(effect.transaction_id)
        state = host.acknowledge_provider_success(effect.transaction_id)
        self.assertTrue(state.connected)
        return payload

    def test_join_is_two_phase_and_never_auto_publishes(self):
        controller, _composite, _session, host = self.make_host()
        before = controller.state

        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )

        self.assertEqual(effect.operation, MediaSessionOperation.CONNECT)
        self.assertEqual(effect.enabled_sources, ())
        self.assertFalse(effect.credential_exposed)
        self.assertEqual(controller.state, before)

        payload = host.claim_browser_payload(effect.transaction_id)
        self.assertEqual(payload["operation"], "connect")
        self.assertEqual(payload["enabled_sources"], [])
        self.assertEqual(
            payload["credential"]["token"],
            "secret-server-issued-token",
        )
        self.assertEqual(controller.state, before)

        committed = host.acknowledge_provider_success(effect.transaction_id)
        self.assertTrue(committed.connected)
        self.assertEqual(committed.room_id, "room-1")
        self.assertEqual(committed.desired_sources, frozenset())
        self.assertIsNone(host.pending_effect)

    def test_secret_payload_is_claimable_exactly_once(self):
        _controller, _composite, _session, host = self.make_host()
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )

        first = host.claim_browser_payload(effect.transaction_id)
        self.assertEqual(
            first["credential"]["token"],
            "secret-server-issued-token",
        )
        with self.assertRaisesRegex(
            MediaSessionHandoffError,
            "already claimed",
        ):
            host.claim_browser_payload(effect.transaction_id)

    def test_secret_never_appears_in_pending_or_recovery_metadata_repr(self):
        _controller, _composite, _session, host = self.make_host()
        effect = host.prepare_join(
            credential("do-not-log-this-token"),
            now=NOW + timedelta(seconds=1),
        )
        self.assertNotIn("do-not-log-this-token", repr(effect))
        self.assertNotIn("do-not-log-this-token", repr(host.pending_effect))

        host.claim_browser_payload(effect.transaction_id)
        host.provider_failed(effect.transaction_id)

        status = host.recovery_status
        self.assertIsNotNone(status)
        self.assertTrue(status.effect.credential_exposed)
        self.assertTrue(status.provider_outcome_unknown)
        self.assertNotIn("do-not-log-this-token", repr(status))

    def test_reconnect_projects_only_current_desired_allowed_sources(self):
        controller, composite, _session, host = self.make_host()
        self.complete_join(controller, host)

        controller.set_local_source(MediaSource.MICROPHONE, True)
        self.assertEqual(
            composite.local_calls,
            [(MediaSource.MICROPHONE, True)],
        )
        controller.mark_transport_lost()
        reconnect_credential = credential(
            "fresh-reconnect-token",
            issued_at=NOW + timedelta(seconds=5),
        )

        effect = host.prepare_reconnect(
            reconnect_credential,
            now=NOW + timedelta(seconds=6),
        )
        self.assertEqual(
            effect.enabled_sources,
            (MediaSource.MICROPHONE,),
        )
        payload = host.claim_browser_payload(effect.transaction_id)
        self.assertEqual(payload["enabled_sources"], ["microphone"])
        self.assertEqual(
            payload["credential"]["token"],
            "fresh-reconnect-token",
        )

        state = host.acknowledge_provider_success(effect.transaction_id)
        self.assertTrue(state.connected)
        self.assertEqual(
            state.desired_sources,
            frozenset({MediaSource.MICROPHONE}),
        )

    def test_leave_waits_for_provider_disconnect_and_has_no_secret_payload(self):
        controller, _composite, _session, host = self.make_host()
        self.complete_join(controller, host)
        before = controller.state

        effect = host.prepare_leave()

        self.assertEqual(effect.operation, MediaSessionOperation.DISCONNECT)
        self.assertEqual(controller.state, before)
        payload = host.claim_browser_payload(effect.transaction_id)
        self.assertEqual(
            payload,
            {
                "transaction_id": effect.transaction_id,
                "operation": "disconnect",
            },
        )
        state = host.acknowledge_provider_success(effect.transaction_id)
        self.assertFalse(state.connected)
        self.assertIsNone(state.room_id)

    def test_leave_without_session_is_canonical_noop_and_exposes_nothing(self):
        controller, _composite, _session, host = self.make_host()

        self.assertIsNone(host.prepare_leave())
        self.assertIsNone(host.pending_effect)
        self.assertIsNone(controller.state.room_id)

    def test_unclaimed_provider_not_started_discards_without_recovery(self):
        controller, _composite, _session, host = self.make_host()
        before = controller.state
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )

        host.provider_not_started(effect.transaction_id)

        self.assertEqual(controller.state, before)
        self.assertIsNone(host.pending_effect)
        self.assertIsNone(host.recovery_status)

    def test_claimed_credential_cannot_be_discarded_as_not_started(self):
        controller, _composite, _session, host = self.make_host()
        before = controller.state
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )
        host.claim_browser_payload(effect.transaction_id)

        with self.assertRaisesRegex(
            MediaSessionRecoveryRequired,
            "claimed session credential",
        ):
            host.provider_not_started(effect.transaction_id)

        self.assertEqual(controller.state, before)
        status = host.recovery_status
        self.assertIsNotNone(status)
        self.assertTrue(status.effect.credential_exposed)
        self.assertFalse(status.provider_outcome_unknown)

    def test_claimed_disconnect_can_be_discarded_when_provider_never_started(self):
        controller, _composite, _session, host = self.make_host()
        self.complete_join(controller, host)
        before = controller.state
        effect = host.prepare_leave()
        host.claim_browser_payload(effect.transaction_id)

        host.provider_not_started(effect.transaction_id)

        self.assertEqual(controller.state, before)
        self.assertIsNone(host.recovery_status)
        self.assertIsNone(host.pending_effect)

    def test_verified_clean_connect_failure_drops_pending_without_recovery(self):
        controller, _composite, _session, host = self.make_host()
        before = controller.state
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )
        host.claim_browser_payload(effect.transaction_id)

        host.provider_connection_failed_clean(
            effect.transaction_id,
            connected=False,
            cleanup_required=False,
        )

        self.assertEqual(controller.state, before)
        self.assertIsNone(host.pending_effect)
        self.assertIsNone(host.recovery_status)
        next_effect = host.prepare_join(
            credential("fresh-after-clean-failure"),
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(next_effect)

    def test_verified_clean_failure_rejects_unclean_adapter_snapshot(self):
        _controller, _composite, _session, host = self.make_host()
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )
        host.claim_browser_payload(effect.transaction_id)

        with self.assertRaisesRegex(
            MediaSessionHandoffError,
            "not proven clean",
        ):
            host.provider_connection_failed_clean(
                effect.transaction_id,
                connected=False,
                cleanup_required=True,
            )
        self.assertEqual(host.pending_effect.transaction_id, effect.transaction_id)

        with self.assertRaisesRegex(
            MediaSessionHandoffError,
            "not proven clean",
        ):
            host.provider_connection_failed_clean(
                effect.transaction_id,
                connected=True,
                cleanup_required=False,
            )
        self.assertEqual(host.pending_effect.transaction_id, effect.transaction_id)

    def test_disconnect_failure_cannot_use_clean_connect_shortcut(self):
        controller, _composite, _session, host = self.make_host()
        self.complete_join(controller, host)
        effect = host.prepare_leave()
        host.claim_browser_payload(effect.transaction_id)

        with self.assertRaisesRegex(
            MediaSessionHandoffError,
            "only to connect or reconnect",
        ):
            host.provider_connection_failed_clean(
                effect.transaction_id,
                connected=False,
                cleanup_required=False,
            )
        self.assertEqual(host.pending_effect.transaction_id, effect.transaction_id)

    def test_provider_failure_latches_recovery_and_blocks_next_session_effect(self):
        _controller, _composite, _session, host = self.make_host()
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )
        host.claim_browser_payload(effect.transaction_id)

        host.provider_failed(effect.transaction_id)

        with self.assertRaises(MediaSessionRecoveryRequired):
            host.prepare_leave()
        host.resolve_recovery(effect.transaction_id)
        self.assertIsNone(host.recovery_status)

    def test_provider_success_without_claim_fails_closed_into_recovery(self):
        controller, _composite, _session, host = self.make_host()
        before = controller.state
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(
            MediaSessionRecoveryRequired,
            "without a claimed browser payload",
        ):
            host.acknowledge_provider_success(effect.transaction_id)

        self.assertEqual(controller.state, before)
        self.assertTrue(host.recovery_status.provider_outcome_unknown)

    def test_stale_canonical_revision_after_provider_success_requires_recovery(self):
        controller, _composite, _session, host = self.make_host()
        self.complete_join(controller, host)
        controller.mark_transport_lost()
        effect = host.prepare_reconnect(
            credential(
                "reconnect-token",
                issued_at=NOW + timedelta(seconds=5),
            ),
            now=NOW + timedelta(seconds=6),
        )
        host.claim_browser_payload(effect.transaction_id)

        # Disconnected leave is a local canonical transition with no provider
        # call, so it deliberately races the pending reconnect for this test.
        controller.leave()

        with self.assertRaisesRegex(
            MediaSessionRecoveryRequired,
            "changed before session acknowledgement",
        ):
            host.acknowledge_provider_success(effect.transaction_id)

        self.assertIsNotNone(host.recovery_status)
        self.assertFalse(host.recovery_status.provider_outcome_unknown)

    def test_validation_failure_releases_unexposed_injected_identity(self):
        repeated = "session-" + "c" * 32
        _controller, _composite, _session, host = self.make_host(
            transaction_id_factory=lambda: repeated,
        )

        with self.assertRaises(ClassroomMediaError):
            host.prepare_join(
                credential(),
                now=NOW - timedelta(seconds=1),
            )

        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(effect.transaction_id, repeated)

    def test_exposed_transaction_identity_cannot_be_reused(self):
        repeated = "session-" + "d" * 32
        _controller, _composite, _session, host = self.make_host(
            transaction_id_factory=lambda: repeated,
        )
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )
        host.provider_not_started(effect.transaction_id)

        with self.assertRaisesRegex(
            MediaSessionHandoffError,
            "reused a session transaction identity",
        ):
            host.prepare_join(
                credential("another-token"),
                now=NOW + timedelta(seconds=1),
            )

    def test_default_transaction_ids_are_bounded_without_tombstones(self):
        with mock.patch(
            "acs.classroom_media_session_handoff.secrets.token_hex",
            return_value="ab" * 8,
        ):
            _controller, _composite, _session, host = self.make_host(
                use_default_ids=True,
            )

        ids = []
        for _index in range(128):
            effect = host.prepare_join(
                credential(),
                now=NOW + timedelta(seconds=1),
            )
            ids.append(effect.transaction_id)
            host.provider_not_started(effect.transaction_id)

        self.assertEqual(len(set(ids)), 128)
        self.assertEqual(
            ids[0],
            "session-" + ("ab" * 8) + "0000000000000001",
        )
        self.assertEqual(host._injected_transaction_ids, set())
        self.assertEqual(host._transaction_counter, 128)

    def test_non_owner_thread_mutation_is_rejected_without_state_change(self):
        controller, _composite, _session, host = self.make_host()
        before = controller.state
        errors = []

        def mutate():
            try:
                host.prepare_join(
                    credential(),
                    now=NOW + timedelta(seconds=1),
                )
            except Exception as exc:
                errors.append(exc)

        worker = Thread(target=mutate)
        worker.start()
        worker.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaSessionHandoffError)
        self.assertIn("owner thread", str(errors[0]))
        self.assertEqual(controller.state, before)
        self.assertIsNone(host.pending_effect)

    def test_second_coordinator_is_rejected_without_poisoning_first(self):
        controller, _composite, session, host = self.make_host()

        with self.assertRaisesRegex(
            MediaSessionHandoffError,
            "already has a coordinator",
        ):
            ClassroomMediaSessionHandoffs(
                controller,
                session,
                transaction_id_factory=lambda: "session-" + "f" * 32,
            )

        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )
        self.assertIsNotNone(effect)

    def test_constructor_failure_before_binding_does_not_poison_port(self):
        roster = FakeRoster()
        session = ClassroomMediaSessionHandoffPort()
        composite = CompositeMediaPort(session)
        controller = ClassroomMediaController(
            local_participant_id="student-1",
            roster=roster,
            media=composite,
        )

        with mock.patch(
            "acs.classroom_media_session_handoff.secrets.token_hex",
            side_effect=RuntimeError("entropy unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "entropy unavailable"):
                ClassroomMediaSessionHandoffs(controller, session)

        host = ClassroomMediaSessionHandoffs(
            controller,
            session,
            transaction_id_factory=lambda: "session-" + "e" * 32,
        )
        self.assertIsNone(host.pending_effect)

    def test_controller_must_route_session_calls_through_supplied_port(self):
        roster = FakeRoster()
        right = ClassroomMediaSessionHandoffPort()
        wrong = ClassroomMediaSessionHandoffPort()
        controller = ClassroomMediaController(
            local_participant_id="student-1",
            roster=roster,
            media=CompositeMediaPort(right),
        )

        with self.assertRaisesRegex(
            ValueError,
            "must route session lifecycle",
        ):
            ClassroomMediaSessionHandoffs(controller, wrong)

    def test_session_port_rejects_non_session_provider_effects(self):
        session = ClassroomMediaSessionHandoffPort()
        with self.assertRaisesRegex(MediaSessionHandoffError, "local-source"):
            session.set_local_source(MediaSource.MICROPHONE, True)

    def test_browser_payload_matches_current_livekit_session_method_contract(self):
        source = LIVEKIT_ADAPTER.read_text(encoding="utf-8")
        self.assertIn(
            "async connect(credentialValue, enabledSourcesValue)",
            source,
        )
        self.assertIn(
            "async reconnect(credentialValue, enabledSourcesValue)",
            source,
        )
        self.assertIn("async disconnect()", source)
        self.assertIn("cleanup_required: this._cleanupRoom !== null", source)
        self.assertIn("connected: false", source)
        self.assertIn(
            'const allowed = ["participant_id", "room_id", "token"]',
            source,
        )

        _controller, _composite, _session, host = self.make_host()
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )
        payload = host.claim_browser_payload(effect.transaction_id)
        self.assertEqual(
            set(payload),
            {"transaction_id", "operation", "credential", "enabled_sources"},
        )
        self.assertEqual(
            set(payload["credential"]),
            {"participant_id", "room_id", "token"},
        )

    def test_unknown_transaction_ids_do_not_clear_pending(self):
        _controller, _composite, _session, host = self.make_host()
        effect = host.prepare_join(
            credential(),
            now=NOW + timedelta(seconds=1),
        )

        with self.assertRaises(MediaSessionHandoffError):
            host.provider_failed("bad")
        with self.assertRaises(MediaSessionHandoffError):
            host.provider_failed("session-" + "f" * 32)
        self.assertEqual(host.pending_effect.transaction_id, effect.transaction_id)


if __name__ == "__main__":
    unittest.main()
