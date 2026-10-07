from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Thread
import unittest
from unittest import mock

from acs.classroom_media_host_transactions import (
    ClassroomMediaHostTransactionPort,
    ClassroomMediaHostTransactions,
    MAX_BROWSER_MODERATION_COMMANDS_PER_CHUNK,
    MediaHostRecoveryRequired,
    MediaHostTransactionError,
    MediaProviderEffect,
    MediaProviderEffectKind,
)
from acs.classroom_realtime_media import (
    ClassroomMediaController,
    ClassroomMediaError,
    ClassroomRole,
    JoinCredential,
    MediaDeviceKind,
    MediaSource,
    ModerationAction,
    ModerationCommand,
)


NOW = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
HOST_TRANSACTION_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "classroom-media-host-transaction.yml"
)


class FakeRoster:
    def __init__(self, student_count: int = 2) -> None:
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


class FakeSessionPort:
    def __init__(self) -> None:
        self.connect_calls = []
        self.reconnect_calls = []
        self.disconnect_calls = 0
        self.local_calls = []
        self.moderation_calls = []
        self.device_calls = []

    def connect(self, credential, *, enabled_sources):
        self.connect_calls.append((credential, enabled_sources))

    def reconnect(self, credential, *, enabled_sources):
        self.reconnect_calls.append((credential, enabled_sources))

    def disconnect(self):
        self.disconnect_calls += 1

    def set_local_source(self, source, enabled):
        self.local_calls.append((source, enabled))

    def apply_moderation(self, commands):
        self.moderation_calls.append(commands)

    def recover_device(self, kind, device_id, *, republish_enabled):
        self.device_calls.append((kind, device_id, republish_enabled))


def credential(participant_id: str) -> JoinCredential:
    return JoinCredential(
        room_id="room-1",
        participant_id=participant_id,
        token="secret-server-issued-token",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )


class ClassroomMediaHostTransactionTests(unittest.TestCase):
    def make_host(
        self,
        participant_id="student-1",
        *,
        student_count=2,
        transaction_id_factory=None,
        use_default_transaction_ids=False,
    ):
        roster = FakeRoster(student_count=student_count)
        session = FakeSessionPort()
        port = ClassroomMediaHostTransactionPort(session_port=session)
        controller = ClassroomMediaController(
            local_participant_id=participant_id,
            roster=roster,
            media=port,
        )
        counter = {"value": 0}

        def transaction_id():
            counter["value"] += 1
            return f"host-{counter['value']:032x}"

        host = ClassroomMediaHostTransactions(
            controller,
            port,
            transaction_id_factory=(
                None
                if use_default_transaction_ids
                else (transaction_id_factory or transaction_id)
            ),
        )
        controller.join(
            credential(participant_id),
            now=NOW + timedelta(seconds=1),
        )
        return controller, roster, session, port, host

    def test_prepare_local_source_does_not_commit_until_provider_success(self):
        controller, _roster, session, _port, host = self.make_host()
        revision = controller.state.revision

        effect = host.prepare_local_source(MediaSource.MICROPHONE, True)

        self.assertIsNotNone(effect)
        self.assertEqual(effect.kind, MediaProviderEffectKind.LOCAL_SOURCE)
        self.assertEqual(effect.source, MediaSource.MICROPHONE)
        self.assertTrue(effect.enabled)
        self.assertEqual(controller.state.revision, revision)
        self.assertEqual(controller.state.desired_sources, frozenset())
        self.assertEqual(session.local_calls, [])

        committed = host.commit_provider_success(effect.transaction_id)
        self.assertEqual(
            committed.desired_sources,
            frozenset({MediaSource.MICROPHONE}),
        )
        self.assertEqual(controller.state.revision, revision + 1)
        self.assertIsNone(host.pending_effect)
        self.assertIsNone(host.recovery_effect)

    def test_direct_provider_effect_outside_transaction_fails_closed(self):
        controller, _roster, _session, _port, _host = self.make_host()
        before = controller.state
        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "active host transaction",
        ):
            controller.set_local_source(MediaSource.CAMERA, True)
        self.assertEqual(controller.state, before)

    def test_provider_not_started_can_discard_without_state_change(self):
        controller, _roster, _session, _port, host = self.make_host()
        before = controller.state
        effect = host.prepare_local_source(MediaSource.CAMERA, True)

        host.provider_not_started(effect.transaction_id)

        self.assertEqual(controller.state, before)
        self.assertIsNone(host.pending_effect)
        retry = host.prepare_local_source(MediaSource.CAMERA, True)
        self.assertIsNotNone(retry)
        self.assertNotEqual(retry.transaction_id, effect.transaction_id)

    def test_provider_failure_requires_recovery_for_possible_partial_effect(self):
        controller, _roster, _session, _port, host = self.make_host()
        before = controller.state
        effect = host.prepare_local_source(MediaSource.CAMERA, True)

        host.provider_failed(effect.transaction_id)

        self.assertEqual(controller.state, before)
        self.assertEqual(host.recovery_effect, effect)
        status = host.recovery_status
        self.assertEqual(status.effect, effect)
        self.assertEqual(status.confirmed_chunk_count, 0)
        self.assertEqual(status.total_chunk_count, 1)
        self.assertTrue(status.provider_outcome_unknown)
        with self.assertRaises(MediaHostRecoveryRequired):
            host.prepare_local_source(MediaSource.MICROPHONE, True)

    def test_unknown_provider_outcome_requires_explicit_recovery(self):
        controller, _roster, _session, _port, host = self.make_host()
        before = controller.state
        effect = host.prepare_local_source(MediaSource.CAMERA, True)

        host.provider_outcome_unknown(effect.transaction_id)

        self.assertEqual(controller.state, before)
        self.assertIsNone(host.pending_effect)
        self.assertEqual(host.recovery_effect, effect)
        status = host.recovery_status
        self.assertEqual(status.confirmed_chunk_count, 0)
        self.assertEqual(status.total_chunk_count, 1)
        self.assertTrue(status.provider_outcome_unknown)
        with self.assertRaises(MediaHostRecoveryRequired):
            host.prepare_local_source(MediaSource.MICROPHONE, True)
        host.resolve_recovery(effect.transaction_id)
        self.assertIsNone(host.recovery_effect)
        self.assertIsNone(host.recovery_status)

    def test_stale_revision_after_provider_success_latches_recovery(self):
        controller, _roster, _session, _port, host = self.make_host()
        effect = host.prepare_local_source(MediaSource.CAMERA, True)

        controller.mark_transport_lost()
        state_after_loss = controller.state

        with self.assertRaisesRegex(
            MediaHostRecoveryRequired,
            "changed before provider acknowledgement",
        ):
            host.commit_provider_success(effect.transaction_id)
        self.assertEqual(controller.state, state_after_loss)
        self.assertEqual(host.recovery_effect, effect)
        status = host.recovery_status
        self.assertEqual(status.confirmed_chunk_count, 1)
        self.assertEqual(status.total_chunk_count, 1)
        self.assertFalse(status.provider_outcome_unknown)
        self.assertIsNone(host.pending_effect)

    def test_success_ack_is_single_use(self):
        controller, _roster, _session, _port, host = self.make_host()
        effect = host.prepare_local_source(MediaSource.MICROPHONE, True)
        host.commit_provider_success(effect.transaction_id)
        after = controller.state

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "unknown or already consumed",
        ):
            host.commit_provider_success(effect.transaction_id)
        self.assertEqual(controller.state, after)

    def test_transaction_mutation_from_non_owner_thread_is_rejected(self):
        controller, _roster, _session, _port, host = self.make_host()
        before = controller.state
        errors = []

        def mutate():
            try:
                host.prepare_local_source(MediaSource.CAMERA, True)
            except Exception as exc:
                errors.append(exc)

        worker = Thread(target=mutate)
        worker.start()
        worker.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaHostTransactionError)
        self.assertIn("owner thread", str(errors[0]))
        self.assertEqual(controller.state, before)
        self.assertIsNone(host.pending_effect)

    def test_only_one_provider_effect_can_be_in_flight(self):
        _controller, _roster, _session, _port, host = self.make_host()
        effect = host.prepare_local_source(MediaSource.MICROPHONE, True)

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "already pending",
        ):
            host.prepare_local_source(MediaSource.CAMERA, True)
        self.assertEqual(host.pending_effect, effect)

    def test_constructor_failure_before_binding_does_not_poison_port(self):
        roster = FakeRoster()
        session = FakeSessionPort()
        port = ClassroomMediaHostTransactionPort(session_port=session)
        controller = ClassroomMediaController(
            local_participant_id="student-1",
            roster=roster,
            media=port,
        )

        with mock.patch(
            "acs.classroom_media_host_transactions.secrets.token_hex",
            side_effect=RuntimeError("entropy unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "entropy unavailable"):
                ClassroomMediaHostTransactions(controller, port)

        host = ClassroomMediaHostTransactions(
            controller,
            port,
            transaction_id_factory=lambda: "host-" + "e" * 32,
        )
        self.assertIsNone(host.pending_effect)
        self.assertIsNone(host.recovery_effect)

    def test_transaction_port_rejects_second_coordinator_without_poisoning_first(self):
        controller, _roster, _session, port, host = self.make_host()

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "already has a coordinator",
        ):
            ClassroomMediaHostTransactions(
                controller,
                port,
                transaction_id_factory=lambda: "host-" + "f" * 32,
            )

        effect = host.prepare_local_source(MediaSource.MICROPHONE, True)
        self.assertIsNotNone(effect)
        committed = host.commit_provider_success(effect.transaction_id)
        self.assertIn(MediaSource.MICROPHONE, committed.desired_sources)

    def test_moderation_effect_is_exact_and_commits_policy_only_after_success(self):
        controller, _roster, session, _port, host = self.make_host("teacher-1")
        before = controller.participant_policy("student-1")
        self.assertTrue(before.source(MediaSource.CAMERA).publish_allowed)

        effect = host.prepare_publish_permission(
            actor_id="teacher-1",
            target_id="student-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="lock-camera-1",
        )

        self.assertEqual(effect.kind, MediaProviderEffectKind.MODERATION)
        self.assertEqual(len(effect.commands), 1)
        command = effect.commands[0]
        self.assertEqual(command.action, ModerationAction.PUBLISH_PERMISSION)
        self.assertEqual(command.target_id, "student-1")
        self.assertEqual(command.source, MediaSource.CAMERA)
        self.assertFalse(command.value)
        self.assertTrue(
            controller.participant_policy("student-1")
            .source(MediaSource.CAMERA)
            .publish_allowed
        )
        self.assertEqual(session.moderation_calls, [])

        committed = host.commit_provider_success(effect.transaction_id)
        self.assertFalse(committed.source(MediaSource.CAMERA).publish_allowed)

    def test_roster_change_between_prepare_and_commit_requires_recovery(self):
        controller, roster, _session, _port, host = self.make_host("teacher-1")
        effect = host.prepare_soft_mute(
            actor_id="teacher-1",
            target_id="student-1",
            muted=True,
            operation_id="mute-1",
        )

        roster.roles["teacher-1"] = ClassroomRole.STUDENT

        with self.assertRaises(MediaHostRecoveryRequired):
            host.commit_provider_success(effect.transaction_id)
        self.assertEqual(host.recovery_effect, effect)
        status = host.recovery_status
        self.assertEqual(status.confirmed_chunk_count, 1)
        self.assertEqual(status.total_chunk_count, 1)
        self.assertFalse(status.provider_outcome_unknown)
        self.assertFalse(
            controller.participant_policy("student-1")
            .source(MediaSource.MICROPHONE)
            .soft_muted
        )

    def test_bulk_moderation_preserves_exact_operation_ids(self):
        controller, _roster, _session, _port, host = self.make_host("teacher-1")
        effect = host.prepare_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.MICROPHONE,
            allowed=False,
            operation_id="bulk-lock",
        )

        self.assertEqual(
            [command.operation_id for command in effect.commands],
            ["bulk-lock:1", "bulk-lock:2"],
        )
        host.commit_provider_success(effect.transaction_id)
        for participant_id in ("student-1", "student-2"):
            self.assertFalse(
                controller.participant_policy(participant_id)
                .source(MediaSource.MICROPHONE)
                .publish_allowed
            )

    def test_large_bulk_moderation_is_planned_as_ordered_bounded_chunks(self):
        controller, _roster, _session, _port, host = self.make_host(
            "teacher-1",
            student_count=60,
        )
        effect = host.prepare_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="large-lock",
        )

        payloads = effect.browser_payloads()
        self.assertEqual(
            [len(payload["commands"]) for payload in payloads],
            [24, 24, 12],
        )
        self.assertEqual(
            [payload["chunk_index"] for payload in payloads],
            [0, 1, 2],
        )
        self.assertTrue(
            all(payload["chunk_count"] == 3 for payload in payloads)
        )
        flattened_ids = [
            command["operation_id"]
            for payload in payloads
            for command in payload["commands"]
        ]
        self.assertEqual(
            flattened_ids,
            [command.operation_id for command in effect.commands],
        )
        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "multiple ordered browser payload chunks",
        ):
            effect.browser_payload()

        for index in range(1, 61):
            self.assertTrue(
                controller.participant_policy(f"student-{index}")
                .source(MediaSource.CAMERA)
                .publish_allowed
            )

        self.assertEqual(host.pending_browser_payload, payloads[0])
        self.assertIsNone(
            host.acknowledge_provider_chunk_success(effect.transaction_id, 0)
        )
        self.assertEqual(host.pending_browser_payload, payloads[1])
        for index in range(1, 61):
            self.assertTrue(
                controller.participant_policy(f"student-{index}")
                .source(MediaSource.CAMERA)
                .publish_allowed
            )

        self.assertIsNone(
            host.acknowledge_provider_chunk_success(effect.transaction_id, 1)
        )
        committed = host.acknowledge_provider_chunk_success(
            effect.transaction_id,
            2,
        )
        self.assertEqual(len(committed), 60)
        self.assertIsNone(host.pending_browser_payload)
        for index in range(1, 61):
            self.assertFalse(
                controller.participant_policy(f"student-{index}")
                .source(MediaSource.CAMERA)
                .publish_allowed
            )

    def test_runtime_chunk_progress_does_not_materialize_full_plan(self):
        _controller, _roster, _session, _port, host = self.make_host(
            "teacher-1",
            student_count=60,
        )
        effect = host.prepare_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="large-lock-addressed",
        )

        with mock.patch.object(
            MediaProviderEffect,
            "browser_payloads",
            side_effect=AssertionError("runtime must not build the full plan"),
        ):
            first = host.pending_browser_payload
            self.assertEqual(first["chunk_index"], 0)
            self.assertEqual(len(first["commands"]), 24)
            self.assertIsNone(
                host.acknowledge_provider_chunk_success(
                    effect.transaction_id,
                    0,
                )
            )
            second = host.pending_browser_payload
            self.assertEqual(second["chunk_index"], 1)
            self.assertEqual(len(second["commands"]), 24)
            self.assertIsNone(
                host.acknowledge_provider_chunk_success(
                    effect.transaction_id,
                    1,
                )
            )
            third = host.pending_browser_payload
            self.assertEqual(third["chunk_index"], 2)
            self.assertEqual(len(third["commands"]), 12)
            committed = host.acknowledge_provider_chunk_success(
                effect.transaction_id,
                2,
            )

        self.assertEqual(len(committed), 60)
        self.assertIsNone(host.pending_browser_payload)

    def test_multi_chunk_effect_cannot_commit_through_single_call_helper(self):
        controller, _roster, _session, _port, host = self.make_host(
            "teacher-1",
            student_count=60,
        )
        effect = host.prepare_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="large-lock-helper",
        )

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "per-chunk provider acknowledgement",
        ):
            host.commit_provider_success(effect.transaction_id)

        self.assertEqual(host.pending_effect, effect)
        for index in range(1, 61):
            self.assertTrue(
                controller.participant_policy(f"student-{index}")
                .source(MediaSource.CAMERA)
                .publish_allowed
            )

    def test_out_of_order_chunk_success_latches_recovery(self):
        controller, _roster, _session, _port, host = self.make_host(
            "teacher-1",
            student_count=60,
        )
        effect = host.prepare_all_students_soft_mute(
            actor_id="teacher-1",
            muted=True,
            operation_id="large-mute-order",
        )

        with self.assertRaisesRegex(
            MediaHostRecoveryRequired,
            "chunks completed out of order",
        ):
            host.acknowledge_provider_chunk_success(effect.transaction_id, 1)

        self.assertIsNone(host.pending_effect)
        self.assertEqual(host.recovery_effect, effect)
        status = host.recovery_status
        self.assertEqual(status.confirmed_chunk_count, 0)
        self.assertEqual(status.total_chunk_count, 3)
        self.assertTrue(status.provider_outcome_unknown)
        for index in range(1, 61):
            self.assertFalse(
                controller.participant_policy(f"student-{index}")
                .source(MediaSource.MICROPHONE)
                .soft_muted
            )

    def test_partial_large_batch_failure_latches_recovery_without_policy_commit(self):
        controller, _roster, _session, _port, host = self.make_host(
            "teacher-1",
            student_count=60,
        )
        effect = host.prepare_all_students_soft_mute(
            actor_id="teacher-1",
            muted=True,
            operation_id="large-mute",
        )
        payloads = effect.browser_payloads()
        self.assertGreater(len(payloads), 1)
        self.assertIsNone(
            host.acknowledge_provider_chunk_success(effect.transaction_id, 0)
        )
        self.assertEqual(host.pending_browser_payload, payloads[1])

        # A later browser chunk may fail after earlier chunks reached the provider.
        # That outcome is never treated as a clean rollback.
        host.provider_failed(effect.transaction_id)

        self.assertEqual(host.recovery_effect, effect)
        status = host.recovery_status
        self.assertEqual(status.confirmed_chunk_count, 1)
        self.assertEqual(status.total_chunk_count, 3)
        self.assertTrue(status.provider_outcome_unknown)
        for index in range(1, 61):
            self.assertFalse(
                controller.participant_policy(f"student-{index}")
                .source(MediaSource.MICROPHONE)
                .soft_muted
            )
        with self.assertRaises(MediaHostRecoveryRequired):
            host.prepare_local_source(MediaSource.CAMERA, True)

    def test_multi_chunk_final_success_with_stale_canonical_state_records_all_chunks(self):
        controller, _roster, _session, _port, host = self.make_host(
            "teacher-1",
            student_count=60,
        )
        effect = host.prepare_all_students_publish_permission(
            actor_id="teacher-1",
            source=MediaSource.CAMERA,
            allowed=False,
            operation_id="large-lock-stale-final",
        )

        self.assertIsNone(
            host.acknowledge_provider_chunk_success(effect.transaction_id, 0)
        )
        self.assertIsNone(
            host.acknowledge_provider_chunk_success(effect.transaction_id, 1)
        )
        controller.mark_transport_lost()

        with self.assertRaisesRegex(
            MediaHostRecoveryRequired,
            "changed before provider acknowledgement",
        ):
            host.acknowledge_provider_chunk_success(effect.transaction_id, 2)

        status = host.recovery_status
        self.assertEqual(status.effect, effect)
        self.assertEqual(status.confirmed_chunk_count, 3)
        self.assertEqual(status.total_chunk_count, 3)
        self.assertFalse(status.provider_outcome_unknown)
        for index in range(1, 61):
            self.assertTrue(
                controller.participant_policy(f"student-{index}")
                .source(MediaSource.CAMERA)
                .publish_allowed
            )

    def test_provider_not_started_after_confirmed_prefix_records_known_partial_state(self):
        _controller, _roster, _session, _port, host = self.make_host(
            "teacher-1",
            student_count=60,
        )
        effect = host.prepare_all_students_soft_mute(
            actor_id="teacher-1",
            muted=True,
            operation_id="large-mute-not-started",
        )

        self.assertIsNone(
            host.acknowledge_provider_chunk_success(effect.transaction_id, 0)
        )
        with self.assertRaisesRegex(
            MediaHostRecoveryRequired,
            "already partially applied",
        ):
            host.provider_not_started(effect.transaction_id)

        status = host.recovery_status
        self.assertEqual(status.effect, effect)
        self.assertEqual(status.confirmed_chunk_count, 1)
        self.assertEqual(status.total_chunk_count, 3)
        self.assertFalse(status.provider_outcome_unknown)

    def test_moderation_chunk_size_fits_current_livekit_rpc_envelope(self):
        commands = tuple(
            ModerationCommand(
                operation_id=("o" * 123) + f"{index:05d}",
                actor_id="a" * 128,
                target_id="t" * 128,
                action=ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.SCREEN_SHARE,
                value=False,
            )
            for index in range(MAX_BROWSER_MODERATION_COMMANDS_PER_CHUNK)
        )
        effect = MediaProviderEffect(
            transaction_id="host-" + "1" * 32,
            kind=MediaProviderEffectKind.MODERATION,
            commands=commands,
        )
        payload = effect.browser_payload()
        provider_rpc_body = {
            "version": 1,
            "room_id": "r" * 128,
            "operations": payload["commands"],
        }
        encoded = json.dumps(
            provider_rpc_body,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertLessEqual(
            len(encoded),
            15 * 1024,
            "host chunk plan must fit the current LiveKit moderation RPC bound",
        )

    def test_device_recovery_uses_prepared_republish_state(self):
        controller, _roster, session, _port, host = self.make_host()
        enable = host.prepare_local_source(MediaSource.MICROPHONE, True)
        host.commit_provider_success(enable.transaction_id)
        revision = controller.state.revision

        effect = host.prepare_device_recovery(
            MediaDeviceKind.MICROPHONE,
            "microphone-device-2",
        )

        self.assertEqual(effect.kind, MediaProviderEffectKind.RECOVER_DEVICE)
        self.assertEqual(effect.device_kind, MediaDeviceKind.MICROPHONE)
        self.assertEqual(effect.device_id, "microphone-device-2")
        self.assertTrue(effect.republish_enabled)
        self.assertEqual(controller.state.revision, revision)
        self.assertEqual(session.device_calls, [])

        host.commit_provider_success(effect.transaction_id)
        self.assertEqual(controller.state.revision, revision + 1)

    def test_browser_payload_is_non_secret_and_json_shaped(self):
        _controller, _roster, _session, _port, host = self.make_host()
        effect = host.prepare_local_source(MediaSource.CAMERA, True)
        payload = effect.browser_payload()

        self.assertEqual(payload["transaction_id"], effect.transaction_id)
        self.assertEqual(payload["operation"], "set_local_source")
        self.assertEqual(payload["source"], "camera")
        self.assertNotIn("secret-server-issued-token", repr(payload))
        self.assertNotIn("token", payload)

    def test_session_join_is_delegated_without_entering_effect_payload(self):
        controller, _roster, session, _port, host = self.make_host()
        self.assertEqual(len(session.connect_calls), 1)
        self.assertEqual(session.connect_calls[0][1], ())
        self.assertIsNone(host.pending_effect)
        self.assertTrue(controller.state.connected)

    def test_default_transaction_ids_do_not_accumulate_tombstones(self):
        with mock.patch(
            "acs.classroom_media_host_transactions.secrets.token_hex",
            return_value="ab" * 8,
        ):
            controller, _roster, _session, _port, host = self.make_host(
                use_default_transaction_ids=True,
            )

        identities = []
        for _index in range(512):
            effect = host.prepare_local_source(MediaSource.CAMERA, True)
            identities.append(effect.transaction_id)
            host.provider_not_started(effect.transaction_id)

        self.assertEqual(len(set(identities)), 512)
        self.assertEqual(
            identities[0],
            "host-" + ("ab" * 8) + "0000000000000001",
        )
        self.assertEqual(
            identities[-1],
            "host-" + ("ab" * 8) + "0000000000000200",
        )
        self.assertEqual(host._injected_transaction_ids, set())
        self.assertEqual(host._transaction_counter, 512)
        self.assertEqual(controller.state.desired_sources, frozenset())

    def test_noop_prepare_does_not_retire_unexposed_transaction_identity(self):
        repeated = "host-" + "b" * 32
        _controller, _roster, _session, _port, host = self.make_host(
            transaction_id_factory=lambda: repeated,
        )

        self.assertIsNone(host.prepare_local_source(MediaSource.CAMERA, False))
        effect = host.prepare_local_source(MediaSource.CAMERA, True)

        self.assertIsNotNone(effect)
        self.assertEqual(effect.transaction_id, repeated)

    def test_validation_failure_does_not_retire_unexposed_transaction_identity(self):
        repeated = "host-" + "c" * 32
        _controller, _roster, _session, _port, host = self.make_host(
            transaction_id_factory=lambda: repeated,
        )

        with self.assertRaises(ClassroomMediaError):
            host.prepare_local_source(MediaSource.CAMERA, "yes")

        effect = host.prepare_local_source(MediaSource.CAMERA, True)
        self.assertIsNotNone(effect)
        self.assertEqual(effect.transaction_id, repeated)

    def test_transaction_identity_cannot_be_reused_after_safe_discard(self):
        repeated = "host-" + "a" * 32
        controller, _roster, _session, _port, host = self.make_host(
            transaction_id_factory=lambda: repeated,
        )
        effect = host.prepare_local_source(MediaSource.CAMERA, True)
        self.assertEqual(effect.transaction_id, repeated)
        host.provider_not_started(repeated)

        with self.assertRaisesRegex(
            MediaHostTransactionError,
            "reused a media transaction identity",
        ):
            host.prepare_local_source(MediaSource.MICROPHONE, True)
        self.assertEqual(controller.state.desired_sources, frozenset())
        self.assertIsNone(host.pending_effect)

    def test_invalid_and_unknown_transaction_ids_do_not_clear_pending(self):
        _controller, _roster, _session, _port, host = self.make_host()
        effect = host.prepare_local_source(MediaSource.CAMERA, True)

        with self.assertRaises(MediaHostTransactionError):
            host.provider_failed("bad")
        with self.assertRaises(MediaHostTransactionError):
            host.provider_failed("host-" + "f" * 32)
        self.assertEqual(host.pending_effect, effect)

    def test_workflow_scope_is_bound_to_immutable_pull_request_base_sha(self):
        workflow = HOST_TRANSACTION_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn(
            'git diff --name-only "$EVENT_BASE_SHA...HEAD"',
            workflow,
        )
        self.assertIn(
            'git diff --check "$EVENT_BASE_SHA...HEAD"',
            workflow,
        )
        self.assertNotIn(
            'refs/remotes/origin/$PR_BASE_REF',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
