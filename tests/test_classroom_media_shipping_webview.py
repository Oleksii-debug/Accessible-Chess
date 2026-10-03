from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from acs.classroom_media_host_transactions import (
    ClassroomMediaHostTransactionPort,
    ClassroomMediaHostTransactions,
)
from acs.classroom_media_provider_binder import ClassroomMediaProviderBinder
from acs.classroom_media_provider_execution import ClassroomMediaProviderExecutionArbiter
from acs.classroom_media_session_transactions import (
    ClassroomMediaSessionHostTransactions,
    ClassroomMediaSessionTransactionPort,
)
from acs.classroom_media_webview_bridge import ClassroomMediaWebViewBridge
from acs.classroom_media_webview_projection import ClassroomMediaWebViewProjection
from acs.classroom_media_webview_transactions import (
    ClassroomMediaBrowserProviderConfig,
    ClassroomMediaTransactionalWebView,
)
from acs.classroom_realtime_media import (
    ClassroomMediaController,
    ClassroomRole,
    JoinCredential,
    MediaSource,
)
from acs.full_product_ui_shell import UILanguage
from acs.version2_final_product_application import Version2FinalProductApplication


NOW = datetime(2026, 10, 3, 1, 15, tzinfo=timezone.utc)
TOKEN = "browser-one-shot-secret"


class FakeRoster:
    def __init__(self, *, teacher: bool = False, students: int = 2) -> None:
        self.local_id = "teacher-1" if teacher else "student-1"
        self.roles = {"teacher-1": ClassroomRole.TEACHER}
        self.roles.update(
            {
                f"student-{index}": ClassroomRole.STUDENT
                for index in range(1, students + 1)
            }
        )

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


def snapshot(
    participant_id: str | None,
    *,
    connected: bool,
    cleanup_required: bool = False,
    microphone: bool = False,
    camera: bool = False,
):
    return {
        "connected": connected,
        "cleanup_required": cleanup_required,
        "room_id": "room-1" if connected else None,
        "participant_id": participant_id if connected else None,
        "microphone_enabled": microphone,
        "camera_enabled": camera,
        "screen_share_enabled": False,
    }


def composition(*, teacher: bool = False, students: int = 2):
    roster = FakeRoster(teacher=teacher, students=students)
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

    session_counter = {"value": 0}

    def session_id():
        session_counter["value"] += 1
        return f"session-{session_counter['value']:032x}"

    host = ClassroomMediaHostTransactions(
        controller,
        outer_port,
        transaction_id_factory=host_id,
    )
    sessions = ClassroomMediaSessionHostTransactions(
        controller,
        outer_port,
        session_port,
        host,
        transaction_id_factory=session_id,
        clock=lambda: NOW + timedelta(seconds=2),
    )
    binder = ClassroomMediaProviderBinder(
        host,
        sessions,
        arbiter=ClassroomMediaProviderExecutionArbiter(),
    )
    labels = {participant_id: participant_id.replace("-", " ").title()
              for participant_id in roster.participant_ids()}
    projection = ClassroomMediaWebViewProjection(
        controller,
        lambda: dict(labels),
        language=UILanguage.EN,
        operation_id_factory=iter(
            [f"ui-{index:032x}" for index in range(1, 200)]
        ).__next__,
    )
    provider = ClassroomMediaBrowserProviderConfig(
        "wss://media.example.test",
        "moderation-service",
    )
    transactions = ClassroomMediaTransactionalWebView(
        projection,
        binder,
        provider,
    )
    bridge = ClassroomMediaWebViewBridge(
        projection,
        mutations=transactions,
    )
    return controller, roster, host, sessions, binder, projection, transactions, bridge


def connect(controller, roster, transactions):
    event = transactions.prepare_join(
        credential(roster.local_id),
        now=NOW + timedelta(seconds=1),
    )
    transaction_id = event.payload["transaction_id"]
    assert event.kind == "provider-dispatch"
    assert TOKEN not in repr(event)
    assert event.payload["provider"]["operation"] == "connect"
    assert event.payload["provider_boundary_crossed"] is False

    handed = transactions.dispatch_provider(
        "media.provider_take_credential",
        {"transaction_id": transaction_id},
    )
    assert handed.kind == "provider-credential"
    assert handed.payload["credential"]["token"] == TOKEN

    ready = transactions.dispatch_provider(
        "media.provider_dispatched",
        {"transaction_id": transaction_id},
    )
    assert ready.kind == "provider-ready"

    result = transactions.dispatch_provider(
        "media.provider_session_success",
        {
            "transaction_id": transaction_id,
            "snapshot": snapshot(roster.local_id, connected=True),
        },
    )
    assert result.kind == "media-updated"
    assert controller.state.connected
    return result


class ClassroomMediaShippingWebViewTests(unittest.TestCase):
    def test_local_source_commits_only_after_exact_provider_ack(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)
        before = controller.state

        event = bridge.dispatch(
            "media.local_source",
            {"source": "camera", "enabled": True},
        )

        self.assertEqual(event.kind, "provider-dispatch")
        transaction_id = event.payload["transaction_id"]
        self.assertEqual(event.payload["provider"]["operation"], "set_local_source")
        self.assertFalse(event.payload["provider_boundary_crossed"])
        self.assertEqual(controller.state, before)
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)

        ready = transactions.dispatch_provider(
            "media.provider_dispatched",
            {"transaction_id": transaction_id},
        )
        self.assertEqual(ready.kind, "provider-ready")
        self.assertTrue(binder.active_lease.provider_boundary_crossed)
        self.assertEqual(controller.state, before)

        completed = transactions.dispatch_provider(
            "media.provider_effect_success",
            {"transaction_id": transaction_id, "chunk_index": 0},
        )
        self.assertEqual(completed.kind, "media-updated")
        self.assertIn(MediaSource.CAMERA, controller.state.desired_sources)
        self.assertEqual(
            completed.payload["focus_target"],
            "media-own-camera-toggle",
        )
        self.assertIsNone(binder.active_lease)

    def test_join_dispatch_is_secret_free_and_credential_is_one_shot(self):
        _controller, roster, _host, _sessions, binder, _projection, transactions, _bridge = composition()
        event = transactions.prepare_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        transaction_id = event.payload["transaction_id"]

        self.assertNotIn(TOKEN, repr(event))
        self.assertNotIn("token", repr(event.payload["provider"]).lower())
        first = transactions.dispatch_provider(
            "media.provider_take_credential",
            {"transaction_id": transaction_id},
        )
        self.assertEqual(first.kind, "provider-credential")
        self.assertEqual(first.payload["credential"]["token"], TOKEN)
        # The credential mapping has redacted diagnostics even while serialization
        # can still hand its exact fields to the browser once.
        self.assertNotIn(TOKEN, repr(first.payload["credential"]))

        second = transactions.dispatch_provider(
            "media.provider_take_credential",
            {"transaction_id": transaction_id},
        )
        self.assertEqual(second.kind, "error")
        self.assertTrue(second.payload["recovery_required"])
        self.assertIn("snapshot", second.payload)
        self.assertIsNone(second.payload["snapshot"])
        self.assertIsNone(binder.active_lease)
        self.assertIsNotNone(binder.recovery_status)
        self.assertFalse(binder.recovery_status.provider_outcome_unknown)
        self.assertNotIn(transaction_id, transactions._focus_by_transaction)
        self.assertNotIn(TOKEN, repr(second))

    def test_multi_chunk_moderation_marks_boundary_only_on_first_dispatch(self):
        controller, roster, host, _sessions, binder, _projection, transactions, bridge = composition(
            teacher=True,
            students=30,
        )
        connect(controller, roster, transactions)

        event = bridge.dispatch(
            "media.all_soft_mute",
            {"muted": True},
        )
        self.assertEqual(event.kind, "provider-dispatch")
        transaction_id = event.payload["transaction_id"]
        self.assertFalse(event.payload["provider_boundary_crossed"])
        self.assertEqual(event.payload["provider"]["chunk_index"], 0)
        self.assertEqual(event.payload["provider"]["chunk_count"], 2)
        transactions.dispatch_provider(
            "media.provider_dispatched",
            {"transaction_id": transaction_id},
        )

        second = transactions.dispatch_provider(
            "media.provider_effect_success",
            {"transaction_id": transaction_id, "chunk_index": 0},
        )
        self.assertEqual(second.kind, "provider-dispatch")
        self.assertTrue(second.payload["provider_boundary_crossed"])
        self.assertEqual(second.payload["provider"]["chunk_index"], 1)
        self.assertEqual(
            binder.active_lease.transaction_id,
            transaction_id,
        )
        self.assertIsNotNone(host.pending_effect)

        completed = transactions.dispatch_provider(
            "media.provider_effect_success",
            {"transaction_id": transaction_id, "chunk_index": 1},
        )
        self.assertEqual(completed.kind, "media-updated")
        self.assertIsNone(binder.active_lease)
        self.assertIsNone(host.pending_effect)

    def test_malformed_callback_before_dispatch_retires_exact_lease(self):
        controller, roster, host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)
        before = controller.state
        event = bridge.dispatch(
            "media.local_source",
            {"source": "microphone", "enabled": True},
        )
        transaction_id = event.payload["transaction_id"]
        self.assertIsNotNone(binder.active_lease)
        self.assertIsNotNone(host.pending_effect)

        result = transactions.dispatch_provider(
            "media.provider_effect_success",
            {"transaction_id": transaction_id, "chunk_index": "not-an-int"},
        )

        self.assertEqual(result.kind, "error")
        self.assertNotIn("recovery_required", result.payload)
        self.assertIsNone(binder.active_lease)
        self.assertIsNone(binder.recovery_status)
        self.assertIsNone(host.pending_effect)
        self.assertEqual(controller.state, before)
        self.assertNotIn(MediaSource.MICROPHONE, controller.state.desired_sources)
        self.assertNotIn(transaction_id, transactions._focus_by_transaction)

    def test_malformed_callback_after_dispatch_enters_unknown_recovery(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)
        event = bridge.dispatch(
            "media.local_source",
            {"source": "microphone", "enabled": True},
        )
        transaction_id = event.payload["transaction_id"]
        transactions.dispatch_provider(
            "media.provider_dispatched",
            {"transaction_id": transaction_id},
        )

        result = transactions.dispatch_provider(
            "media.provider_effect_success",
            {"transaction_id": transaction_id, "chunk_index": "not-an-int"},
        )

        self.assertEqual(result.kind, "error")
        self.assertTrue(result.payload["recovery_required"])
        self.assertIn("snapshot", result.payload)
        self.assertIsNone(result.payload["snapshot"])
        self.assertIsNone(binder.active_lease)
        self.assertIsNotNone(binder.recovery_status)
        self.assertTrue(binder.recovery_status.provider_outcome_unknown)
        self.assertNotIn(MediaSource.MICROPHONE, controller.state.desired_sources)
        self.assertNotIn(transaction_id, transactions._focus_by_transaction)

    def test_duplicate_callback_after_recovery_preserves_recovery_surface(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)
        event = bridge.dispatch(
            "media.local_source",
            {"source": "microphone", "enabled": True},
        )
        transaction_id = event.payload["transaction_id"]
        transactions.dispatch_provider(
            "media.provider_dispatched",
            {"transaction_id": transaction_id},
        )

        first = transactions.dispatch_provider(
            "media.provider_effect_success",
            {"transaction_id": transaction_id, "chunk_index": "not-an-int"},
        )
        self.assertTrue(first.payload["recovery_required"])
        self.assertIsNone(first.payload["snapshot"])
        self.assertIsNone(binder.active_lease)
        self.assertIsNotNone(binder.recovery_status)

        retry = transactions.dispatch_provider(
            "media.provider_outcome_unknown",
            {"transaction_id": transaction_id},
        )

        self.assertEqual(retry.kind, "error")
        self.assertTrue(retry.payload["recovery_required"])
        self.assertIsNone(retry.payload["snapshot"])
        self.assertEqual(retry.payload["transaction_id"], transaction_id)
        self.assertIsNone(binder.active_lease)
        self.assertIsNotNone(binder.recovery_status)
        self.assertEqual(
            binder.recovery_status.lease.transaction_id,
            transaction_id,
        )
        self.assertNotIn(MediaSource.MICROPHONE, controller.state.desired_sources)

    def test_recovery_resolution_requires_trusted_host_reconciliation(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)

        pending = bridge.dispatch(
            "media.local_source",
            {"source": "microphone", "enabled": True},
        )
        transaction_id = pending.payload["transaction_id"]
        transactions.dispatch_provider(
            "media.provider_dispatched",
            {"transaction_id": transaction_id},
        )
        latched = transactions.dispatch_provider(
            "media.provider_outcome_unknown",
            {"transaction_id": transaction_id},
        )
        self.assertEqual(latched.kind, "error")
        self.assertTrue(latched.payload["recovery_required"])
        self.assertIsNotNone(binder.recovery_status)

        browser_attempt = transactions.dispatch_provider(
            "media.provider_resolve_recovery",
            {"transaction_id": transaction_id},
        )
        self.assertEqual(browser_attempt.kind, "error")
        self.assertTrue(browser_attempt.payload["recovery_required"])
        self.assertIsNotNone(binder.recovery_status)

        resolved = transactions.resolve_recovery_after_authoritative_reconciliation(
            transaction_id
        )
        self.assertEqual(resolved.kind, "media-updated")
        self.assertIsNone(binder.recovery_status)
        self.assertIsNone(binder.active_lease)

        next_event = bridge.dispatch(
            "media.local_source",
            {"source": "camera", "enabled": True},
        )
        self.assertEqual(next_event.kind, "provider-dispatch")
        next_transaction = next_event.payload["transaction_id"]
        retired = transactions.dispatch_provider(
            "media.provider_not_started",
            {"transaction_id": next_transaction},
        )
        self.assertEqual(retired.kind, "error")
        self.assertIsNone(binder.active_lease)

    def test_new_mutation_preserves_existing_provider_recovery_state(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)

        first = bridge.dispatch(
            "media.local_source",
            {"source": "microphone", "enabled": True},
        )
        transaction_id = first.payload["transaction_id"]
        transactions.dispatch_provider(
            "media.provider_dispatched",
            {"transaction_id": transaction_id},
        )
        latched = transactions.dispatch_provider(
            "media.provider_effect_success",
            {"transaction_id": transaction_id, "chunk_index": "invalid"},
        )
        self.assertTrue(latched.payload["recovery_required"])
        self.assertIsNotNone(binder.recovery_status)

        retry = bridge.dispatch(
            "media.local_source",
            {"source": "camera", "enabled": True},
        )

        self.assertEqual(retry.kind, "error")
        self.assertTrue(retry.payload["recovery_required"])
        self.assertIsNone(retry.payload["snapshot"])
        self.assertEqual(retry.payload["transaction_id"], transaction_id)
        self.assertEqual(
            retry.payload["focus_target"],
            "media-own-camera-toggle",
        )
        self.assertIsNone(binder.active_lease)
        self.assertEqual(
            binder.recovery_status.lease.transaction_id,
            transaction_id,
        )
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)

    def test_provider_transport_loss_preserves_reconnect_intent_and_retires_controls(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)

        source = bridge.dispatch(
            "media.local_source",
            {"source": "camera", "enabled": True},
        )
        source_transaction = source.payload["transaction_id"]
        transactions.dispatch_provider(
            "media.provider_dispatched",
            {"transaction_id": source_transaction},
        )
        transactions.dispatch_provider(
            "media.provider_effect_success",
            {"transaction_id": source_transaction, "chunk_index": 0},
        )
        self.assertIn(MediaSource.CAMERA, controller.state.desired_sources)

        lost = transactions.dispatch_provider(
            "media.provider_transport_lost",
            {"snapshot": snapshot(None, connected=False)},
        )

        self.assertEqual(lost.kind, "media-updated")
        self.assertFalse(controller.state.connected)
        self.assertEqual(controller.state.room_id, "room-1")
        self.assertIn(MediaSource.CAMERA, controller.state.desired_sources)
        self.assertIsNone(binder.active_lease)
        self.assertIsNone(binder.recovery_status)

        reconnect = transactions.prepare_reconnect(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(reconnect.kind, "provider-dispatch")
        self.assertEqual(reconnect.payload["provider"]["operation"], "reconnect")
        self.assertEqual(
            reconnect.payload["provider"]["enabled_sources"],
            ["camera"],
        )
        reconnect_transaction = reconnect.payload["transaction_id"]
        retired = transactions.dispatch_provider(
            "media.provider_not_started",
            {"transaction_id": reconnect_transaction},
        )
        self.assertEqual(retired.kind, "error")
        self.assertIsNone(binder.active_lease)

    def test_transport_loss_retires_pre_dispatch_mutation_then_marks_canonical_lost(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)

        pending = bridge.dispatch(
            "media.local_source",
            {"source": "camera", "enabled": True},
        )
        transaction_id = pending.payload["transaction_id"]
        self.assertIsNotNone(binder.active_lease)
        self.assertFalse(binder.active_lease.provider_boundary_crossed)
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)

        lost = transactions.dispatch_provider(
            "media.provider_transport_lost",
            {"snapshot": snapshot(None, connected=False)},
        )

        self.assertEqual(lost.kind, "media-updated")
        self.assertFalse(controller.state.connected)
        self.assertEqual(controller.state.room_id, "room-1")
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)
        self.assertIsNone(binder.active_lease)
        self.assertIsNone(binder.recovery_status)
        self.assertNotIn(transaction_id, transactions._focus_by_transaction)

    def test_transport_loss_after_provider_dispatch_latches_recovery_without_commit(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, bridge = composition()
        connect(controller, roster, transactions)

        pending = bridge.dispatch(
            "media.local_source",
            {"source": "camera", "enabled": True},
        )
        transaction_id = pending.payload["transaction_id"]
        transactions.dispatch_provider(
            "media.provider_dispatched",
            {"transaction_id": transaction_id},
        )
        self.assertTrue(binder.active_lease.provider_boundary_crossed)

        lost = transactions.dispatch_provider(
            "media.provider_transport_lost",
            {"snapshot": snapshot(None, connected=False)},
        )

        self.assertEqual(lost.kind, "error")
        self.assertTrue(lost.payload["recovery_required"])
        self.assertIsNone(lost.payload["snapshot"])
        self.assertEqual(lost.payload["transaction_id"], transaction_id)
        self.assertIsNone(binder.active_lease)
        self.assertIsNotNone(binder.recovery_status)
        self.assertTrue(binder.recovery_status.provider_outcome_unknown)
        self.assertEqual(
            binder.recovery_status.lease.transaction_id,
            transaction_id,
        )
        self.assertTrue(controller.state.connected)
        self.assertNotIn(MediaSource.CAMERA, controller.state.desired_sources)

    def test_provider_transport_loss_rejects_nonclean_snapshot(self):
        controller, roster, _host, _sessions, binder, _projection, transactions, _bridge = composition()
        connect(controller, roster, transactions)
        before = controller.state

        result = transactions.dispatch_provider(
            "media.provider_transport_lost",
            {
                "snapshot": snapshot(
                    roster.local_id,
                    connected=True,
                    microphone=True,
                )
            },
        )

        self.assertEqual(result.kind, "error")
        self.assertEqual(controller.state, before)
        self.assertTrue(controller.state.connected)
        self.assertIsNone(binder.active_lease)
        self.assertIsNone(binder.recovery_status)

    def test_transport_loss_rejects_numeric_boolean_lookalikes(self):
        flag_names = (
            "connected",
            "cleanup_required",
            "microphone_enabled",
            "camera_enabled",
            "screen_share_enabled",
        )
        for flag_name in flag_names:
            with self.subTest(flag=flag_name):
                controller, roster, _host, _sessions, binder, _projection, transactions, _bridge = composition()
                connect(controller, roster, transactions)
                before = controller.state
                malformed = snapshot(None, connected=False)
                malformed[flag_name] = 0

                result = transactions.dispatch_provider(
                    "media.provider_transport_lost",
                    {"snapshot": malformed},
                )

                self.assertEqual(result.kind, "error")
                self.assertEqual(controller.state, before)
                self.assertTrue(controller.state.connected)
                self.assertIsNone(binder.active_lease)
                self.assertIsNone(binder.recovery_status)

    def test_browser_provider_config_is_nonsecret_and_secure(self):
        _controller, _roster, _host, _sessions, _binder, _projection, transactions, _bridge = composition()
        result = transactions.dispatch_provider("media.provider_config", {})
        self.assertEqual(
            result.payload["config"],
            {
                "server_url": "wss://media.example.test",
                "moderation_participant_identity": "moderation-service",
            },
        )
        self.assertNotIn("api", repr(result).lower())
        self.assertNotIn("secret", repr(result).lower())

        with self.assertRaises(ValueError):
            ClassroomMediaBrowserProviderConfig(
                "ws://media.example.test",
                "moderation-service",
            )
        loopback = ClassroomMediaBrowserProviderConfig(
            "ws://127.0.0.1:7880/",
            "moderation-service",
        )
        self.assertEqual(loopback.server_url, "ws://127.0.0.1:7880")
        for bad in (
            "wss://user:password@media.example.test",
            "wss://media.example.test?token=x",
            "wss://media.example.test/#fragment",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ClassroomMediaBrowserProviderConfig(
                        bad,
                        "moderation-service",
                    )

    def test_application_queues_trusted_recovery_resolution_refresh(self):
        controller, roster, _host, _sessions, binder, _projection, _transactions, _bridge = composition()
        application = object.__new__(Version2FinalProductApplication)
        application.shell = SimpleNamespace(language=UILanguage.EN)
        application.media = None
        application.media_transactions = None
        application._assert_thread = lambda: None
        application._events = deque()
        labels = {
            participant_id: participant_id.replace("-", " ").title()
            for participant_id in roster.participant_ids()
        }
        application.bind_classroom_media(
            controller,
            lambda: dict(labels),
            provider_binder=binder,
            provider_config=ClassroomMediaBrowserProviderConfig(
                "wss://media.example.test",
                "moderation-service",
            ),
        )
        connect(controller, roster, application.media_transactions)

        pending = application.browser_command(
            "media",
            "media.local_source",
            {"source": "microphone", "enabled": True},
        )
        transaction_id = pending["payload"]["transaction_id"]
        application.browser_command(
            "media",
            "media.provider_dispatched",
            {"transaction_id": transaction_id},
        )
        latched = application.browser_command(
            "media",
            "media.provider_outcome_unknown",
            {"transaction_id": transaction_id},
        )
        self.assertTrue(latched["payload"]["recovery_required"])
        self.assertIsNotNone(binder.recovery_status)

        resolved = (
            application.resolve_classroom_media_recovery_after_authoritative_reconciliation(
                transaction_id
            )
        )
        self.assertEqual(resolved["kind"], "media-updated")
        self.assertIsNone(binder.recovery_status)
        self.assertEqual(application.drain_events(), [resolved])

    def test_application_transactional_binding_queues_trusted_join(self):
        controller, roster, _host, _sessions, binder, _projection, _transactions, _bridge = composition()
        application = object.__new__(Version2FinalProductApplication)
        application.shell = SimpleNamespace(language=UILanguage.EN)
        application.media = None
        application.media_transactions = None
        application._assert_thread = lambda: None
        application._events = deque()

        labels = {
            participant_id: participant_id.replace("-", " ").title()
            for participant_id in roster.participant_ids()
        }
        config = ClassroomMediaBrowserProviderConfig(
            "wss://media.example.test",
            "moderation-service",
        )

        with self.assertRaises(ValueError):
            application.bind_classroom_media(
                controller,
                lambda: dict(labels),
                provider_binder=binder,
            )

        application.bind_classroom_media(
            controller,
            lambda: dict(labels),
            provider_binder=binder,
            provider_config=config,
        )
        self.assertIsNotNone(application.media_transactions)

        rendered = application.prepare_classroom_media_join(
            credential(roster.local_id),
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(rendered["kind"], "provider-dispatch")
        self.assertNotIn(TOKEN, repr(rendered))
        events = application.drain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], rendered)

        with self.assertRaisesRegex(RuntimeError, "cannot be unbound"):
            application.unbind_classroom_media()

        transaction_id = rendered["payload"]["transaction_id"]
        application.browser_command(
            "media",
            "media.provider_not_started",
            {"transaction_id": transaction_id},
        )
        application.unbind_classroom_media()
        self.assertIsNone(application.media)
        self.assertIsNone(application.media_transactions)

    def test_application_rejects_transactional_unbind_while_connected(self):
        controller, roster, _host, _sessions, binder, _projection, _transactions, _bridge = composition()
        application = object.__new__(Version2FinalProductApplication)
        application.shell = SimpleNamespace(language=UILanguage.EN)
        application.media = None
        application.media_transactions = None
        application._assert_thread = lambda: None
        application._events = deque()
        labels = {
            participant_id: participant_id.replace("-", " ").title()
            for participant_id in roster.participant_ids()
        }
        application.bind_classroom_media(
            controller,
            lambda: dict(labels),
            provider_binder=binder,
            provider_config=ClassroomMediaBrowserProviderConfig(
                "wss://media.example.test",
                "moderation-service",
            ),
        )
        connect(controller, roster, application.media_transactions)

        with self.assertRaisesRegex(RuntimeError, "provider session is connected"):
            application.unbind_classroom_media()

        self.assertIsNotNone(application.media)
        self.assertIsNotNone(application.media_transactions)

    def test_application_rejects_nontransactional_unbind_while_connected(self):
        controller, roster, _host, _sessions, _binder, _projection, transactions, _bridge = composition()
        connect(controller, roster, transactions)

        application = object.__new__(Version2FinalProductApplication)
        application.shell = SimpleNamespace(language=UILanguage.EN)
        application.media = None
        application.media_transactions = None
        application._assert_thread = lambda: None
        application._events = deque()
        labels = {
            participant_id: participant_id.replace("-", " ").title()
            for participant_id in roster.participant_ids()
        }

        application.bind_classroom_media(
            controller,
            lambda: dict(labels),
        )
        self.assertIsNotNone(application.media)
        self.assertIsNone(application.media_transactions)

        with self.assertRaisesRegex(RuntimeError, "provider session is connected"):
            application.unbind_classroom_media()

        self.assertIsNotNone(application.media)
        self.assertIsNone(application.media_transactions)
        self.assertTrue(controller.state.connected)

    def test_transactional_binder_must_own_exact_projection_controller(self):
        controller_a, _roster_a, _host_a, _sessions_a, _binder_a, projection_a, _tx_a, _bridge_a = composition()
        _controller_b, _roster_b, _host_b, _sessions_b, binder_b, _projection_b, _tx_b, _bridge_b = composition()
        config = ClassroomMediaBrowserProviderConfig(
            "wss://media.example.test",
            "moderation-service",
        )
        with self.assertRaisesRegex(ValueError, "projection controller"):
            ClassroomMediaTransactionalWebView(
                projection_a,
                binder_b,
                config,
            )
        self.assertIsNotNone(controller_a)

    def test_release_application_configure_runs_before_browser_publication(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "acs"
            / "version2_release_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "application_configure: Callable[[Any], None] | None = None",
            source,
        )
        self.assertIn(
            'raise TypeError("application_configure must be callable")',
            source,
        )
        configure = source.index("application_configure(candidate)")
        publish = source.index("api.bind_version2_application(candidate)")
        self.assertLess(configure, publish)

    def test_shipping_files_are_required_and_loaded_in_provider_order(self):
        root = Path(__file__).resolve().parents[1]
        payload = (root / "acs" / "version2_release_payload.py").read_text(encoding="utf-8")
        preflight = (root / "acs" / "version2_package_preflight.py").read_text(encoding="utf-8")
        release = (root / "acs" / "version2_final_release.py").read_text(encoding="utf-8")

        for name in (
            "full_product_classroom_media.js",
            "livekit_classroom_media.js",
            "livekit_classroom_media_runtime.js",
        ):
            self.assertIn(name, payload)
            self.assertIn(name, preflight)

        sdk = release.index("LiveKit browser SDK")
        adapter = release.index("Classroom LiveKit media adapter")
        runtime = release.index("Classroom LiveKit transactional runtime")
        surface = release.index("V2 Classroom media surface")
        bootstrap = release.index("V2 final-product bootstrap")
        self.assertLess(sdk, adapter)
        self.assertLess(adapter, runtime)
        self.assertLess(runtime, surface)
        self.assertLess(surface, bootstrap)

    def test_v2_launcher_uses_loopback_http_server_path_before_webview_media(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "run_accessible_chess_v2.py").read_text(encoding="utf-8")
        release_ui = (root / "acs" / "version2_release_ui.py").read_text(
            encoding="utf-8"
        )
        safe_server = (root / "acs" / "webview_safe_server.py").read_text(
            encoding="utf-8"
        )

        install_call = "install_pywebview_safe_local_server_port()"
        main_import = "from acs.version2_upgrade_status_release import main"
        self.assertIn(install_call, launcher)
        self.assertIn(main_import, launcher)
        self.assertLess(launcher.index(install_call), launcher.index(main_import))

        # The V2 host passes a local file path as the URL so pywebview serves it
        # through its loopback HTTP server. Do not regress to an HTML-string /
        # about:blank navigation, which would remove the media-capable origin.
        self.assertIn('url=str(html)', release_ui)
        self.assertNotIn('html=str(html)', release_ui)
        self.assertNotIn('html=html', release_ui)
        self.assertIn('webview_module.start(gui="edgechromium", private_mode=True)', release_ui)

        self.assertIn('probe.bind(("127.0.0.1", port))', safe_server)
        self.assertIn('rewritten["http_port"] = safe_port', safe_server)

    def test_bootstrap_routes_actions_and_queued_sessions_through_one_runtime(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "web"
            / "version2_final_product_bootstrap.js"
        ).read_text(encoding="utf-8")
        self.assertIn("function executeMediaProviderEvent(event)", source)
        self.assertIn("function mediaProviderBoundaryCrossed(event)", source)
        self.assertIn("function retireMediaProviderRuntimeFailure(event, invoke)", source)
        self.assertIn("function mediaInvoke(command, payload)", source)
        self.assertIn("AccessibleChessClassroomMediaProviderRuntime", source)
        self.assertIn('event.kind === "provider-dispatch"', source)
        self.assertIn("media.provider_not_started", source)
        self.assertIn("media.provider_outcome_unknown", source)
        self.assertIn("function retireAfterRuntimeFailure()", source)
        runtime_failure_start = source.index("function retireAfterRuntimeFailure()")
        runtime_failure_end = source.index(
            "return Promise.resolve(runtime.execute(event, invoke))",
            runtime_failure_start,
        )
        runtime_failure = source[runtime_failure_start:runtime_failure_end]
        self.assertLess(
            runtime_failure.index('"media.provider_outcome_unknown"'),
            runtime_failure.index('"media.provider_not_started"'),
        )
        self.assertIn(
            "Once runtime.execute() was entered, the provider may have run",
            runtime_failure,
        )
        self.assertIn(
            "const mediaRecoveryRequired = mediaStatus.media_recovery_required === true;",
            source,
        )
        self.assertIn(
            "mediaRecoveryRequired ? null : (snapshot.media || null),",
            source,
        )
        self.assertIn("recovery_required: mediaRecoveryRequired", source)

        runtime_source = (
            Path(__file__).resolve().parents[1]
            / "web"
            / "livekit_classroom_media_runtime.js"
        ).read_text(encoding="utf-8")
        self.assertIn("Object.seal(", runtime_source)
        self.assertNotIn(
            "Object.freeze(\n    new ClassroomMediaProviderRuntime()",
            runtime_source,
        )
        self.assertIn("media.provider_outcome_unknown", runtime_source)
        self.assertIn("async reconcileTransport(invoke)", runtime_source)
        self.assertIn('"media.provider_transport_lost"', runtime_source)
        self.assertIn("this._transportLossSnapshot", runtime_source)

        adapter_source = (
            Path(__file__).resolve().parents[1]
            / "web"
            / "livekit_classroom_media.js"
        ).read_text(encoding="utf-8")
        self.assertIn("RoomEvent", adapter_source)
        self.assertIn("events.Disconnected", adapter_source)
        self.assertIn("_bindUnexpectedDisconnect(room)", adapter_source)
        self.assertIn("onTransportLost", adapter_source)

        self.assertIn(
            "function reconcileMediaProviderTransport()",
            source,
        )
        self.assertIn(
            "runtime.reconcileTransport(areaInvoke(\"media\"))",
            source,
        )
        self.assertIn("function drainQueuedEvents()", source)
        self.assertIn(
            "reconcileMediaProviderTransport().then(\n      drainQueuedEvents,\n      drainQueuedEvents",
            source,
        )
        self.assertLess(
            source.index("function reconcileMediaProviderTransport()"),
            source.index("function drainQueuedEvents()"),
        )
        self.assertLess(
            source.index("function drainQueuedEvents()"),
            source.index("function drainEvents()"),
        )
        self.assertIn("global.setInterval(drainEvents, 300)", source)


if __name__ == "__main__":
    unittest.main()
