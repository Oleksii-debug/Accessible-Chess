from __future__ import annotations
import unittest

from acs.remote_connectivity import (
    AuthenticatedPrincipal,
    RemoteConnectivityError,
    RemoteEndpointProfile,
    RemoteMessageKind,
    RemoteRetryPolicy,
    RemoteRole,
)
from acs.remote_controller import (
    RemoteControllerError,
    RemoteLessonController,
    RemoteLifecycleStatus,
)
from acs.remote_durability import RemoteDurablePoint
from acs.remote_protocol_control import acknowledgement_for
from acs.remote_provider import InProcessRemoteProvider, RemoteConnector
from acs.remote_session import RemoteEventKind, RemoteSessionEvent, RemoteSessionLog


class Secrets:
    def get_secret(self, _key: str) -> str:
        return "runtime-secret"


class Authorizer:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def authorize(self, _principal) -> bool:
        return self.allowed


class MemoryDurability:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.point = None
        self.calls = 0

    def current(self):
        return self.point

    def checkpoint(self, log, *, operation_id, closed_at=None):
        self.calls += 1
        self.point = RemoteDurablePoint(
            self.session_id,
            log.state.last_sequence,
            log.to_snapshot()["digest"],
            self.calls - 1,
            self.calls,
            "a" * 64,
            closed_at,
        )
        return self.point


class StatefulPeer:
    """Deterministic peer with history independent from the client request."""

    def __init__(self, actor: AuthenticatedPrincipal) -> None:
        self.actor = actor
        self.log = RemoteSessionLog(actor.session_id)
        self.reject_next_event_before_accept = False
        self.drop_next_event_ack_after_accept = False

    def __call__(self, request):
        if request.kind is RemoteMessageKind.EVENT:
            if self.reject_next_event_before_accept:
                self.reject_next_event_before_accept = False
                raise RemoteConnectivityError(
                    "simulated disconnect before peer acceptance"
                )
            event = RemoteSessionEvent.from_record(request.payload)
            if (
                event.session_id != self.actor.session_id
                or event.actor_id != self.actor.person_id
                or event.sequence != request.sequence
            ):
                raise RemoteConnectivityError("peer event identity mismatch")
            self.log.append(event)
            peer_digest = self.log.to_snapshot()["digest"]
            if (
                request.sequence != self.log.state.last_sequence
                or request.checkpoint_digest != peer_digest
            ):
                raise RemoteConnectivityError("peer event checkpoint mismatch")
            if self.drop_next_event_ack_after_accept:
                self.drop_next_event_ack_after_accept = False
                raise RemoteConnectivityError(
                    "simulated acknowledgement loss after peer acceptance"
                )
        return acknowledgement_for(
            request,
            checkpoint_sequence=self.log.state.last_sequence,
            checkpoint_digest=self.log.to_snapshot()["digest"],
        )


class Factory:
    def __init__(self, principal, handler=None) -> None:
        self.principal = principal
        self.handler = handler or acknowledgement_for
        self.providers = []

    def __call__(self, _profile, _policy):
        provider = InProcessRemoteProvider(
            lambda candidate, secret: candidate
            if candidate == self.principal and secret == "runtime-secret"
            else None,
            self.handler,
        )
        self.providers.append(provider)
        return provider


def principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("class1", "session1", "student1", RemoteRole.STUDENT)


def connector(factory: Factory) -> RemoteConnector:
    return RemoteConnector(
        RemoteEndpointProfile(
            "profile1", "relay.example.test", 443, "relay.example.test", "cred1"
        ),
        Secrets(),
        factory,
        RemoteRetryPolicy(max_attempts=1),
        sleep=lambda _delay: None,
    )


def make_controller(*, allowed=True, durability=None, factory=None, log=None):
    actor = principal()
    durability = durability or MemoryDurability(actor.session_id)
    factory = factory or Factory(actor)
    log = log or RemoteSessionLog(actor.session_id)
    return (
        RemoteLessonController(
            actor, log, connector(factory), Authorizer(allowed), durability
        ),
        durability,
        factory,
    )


class RemoteControllerTests(unittest.TestCase):
    def test_connect_requires_auth_membership_peer_ack_and_durable_checkpoint(self) -> None:
        controller, durability, factory = make_controller()
        controller.connect()
        self.assertIs(controller.status, RemoteLifecycleStatus.CONNECTED)
        self.assertTrue(controller.accepting_mutations)
        self.assertEqual(durability.point.last_sequence, 0)
        self.assertEqual(
            durability.point.snapshot_digest, controller.log.to_snapshot()["digest"]
        )
        self.assertTrue(factory.providers[-1].connected)
        state = controller.presentation_state(
            teacher_label="Teacher", student_label="Student"
        )
        self.assertEqual(state["status"], "connected")
        self.assertNotIn("secret", repr(state).lower())

    def test_membership_denial_fails_before_durable_publication_and_closes_provider(self) -> None:
        controller, durability, factory = make_controller(allowed=False)
        with self.assertRaises(RemoteControllerError):
            controller.connect()
        self.assertIs(controller.status, RemoteLifecycleStatus.ERROR)
        self.assertFalse(controller.accepting_mutations)
        self.assertEqual(durability.calls, 0)
        self.assertFalse(factory.providers[-1].connected)

    def test_reconnect_replays_local_tail_only_when_peer_is_at_durable_point(self) -> None:
        actor = principal()
        peer = StatefulPeer(actor)
        controller, durability, _factory = make_controller(
            factory=Factory(actor, peer)
        )
        controller.connect()
        initial_digest = durability.point.snapshot_digest
        controller.mark_uncertain()
        event = RemoteSessionEvent(
            "session1", 1, RemoteEventKind.POINTER, {"square": "e4"}, "student1"
        )
        controller.log.append(event)
        self.assertEqual(durability.point.snapshot_digest, initial_digest)
        self.assertEqual(peer.log.state.last_sequence, 0)

        controller.reconnect()

        self.assertIs(controller.status, RemoteLifecycleStatus.CONNECTED)
        self.assertEqual(peer.log.events, controller.log.events)
        self.assertEqual(durability.point.last_sequence, 1)
        self.assertEqual(
            durability.point.snapshot_digest, controller.log.to_snapshot()["digest"]
        )

    def test_reconnect_fails_closed_on_same_sequence_different_peer_history(self) -> None:
        actor = principal()
        peer = StatefulPeer(actor)
        peer.log.append(
            RemoteSessionEvent(
                "session1", 1, RemoteEventKind.POINTER, {"square": "e4"}, "student1"
            )
        )
        empty = RemoteSessionLog(actor.session_id)
        durability = MemoryDurability(actor.session_id)
        durability.point = RemoteDurablePoint(
            actor.session_id,
            0,
            empty.to_snapshot()["digest"],
            0,
            1,
            "a" * 64,
            None,
        )
        local = RemoteSessionLog(actor.session_id)
        local.append(
            RemoteSessionEvent(
                "session1", 1, RemoteEventKind.POINTER, {"square": "d4"}, "student1"
            )
        )
        controller, _, factory = make_controller(
            durability=durability,
            factory=Factory(actor, peer),
            log=local,
        )

        with self.assertRaisesRegex(
            RemoteControllerError, "peer history conflicts"
        ):
            controller.reconnect()

        self.assertIs(controller.status, RemoteLifecycleStatus.ERROR)
        self.assertFalse(controller.accepting_mutations)
        self.assertEqual(durability.point.last_sequence, 0)
        self.assertFalse(factory.providers[-1].connected)

    def test_divergent_durable_prefix_fails_closed_before_network_resume(self) -> None:
        durability = MemoryDurability("session1")
        durability.point = RemoteDurablePoint(
            "session1", 0, "0" * 64, 0, 1, "a" * 64, None
        )
        factory = Factory(principal())
        controller, _, _ = make_controller(durability=durability, factory=factory)
        with self.assertRaises(RemoteControllerError):
            controller.reconnect()
        self.assertIs(controller.status, RemoteLifecycleStatus.ERROR)
        self.assertEqual(factory.providers, [])

    def test_leave_is_not_success_until_durable_closed_checkpoint_exists(self) -> None:
        controller, durability, factory = make_controller()
        controller.connect()
        provider = factory.providers[-1]
        controller.leave("2026-09-11T15:00:00Z")
        self.assertIs(controller.status, RemoteLifecycleStatus.DISCONNECTED)
        self.assertFalse(controller.accepting_mutations)
        self.assertTrue(durability.point.closed)
        self.assertFalse(provider.connected)

    def test_closed_session_cannot_silently_reopen(self) -> None:
        durability = MemoryDurability("session1")
        empty = RemoteSessionLog("session1")
        durability.point = RemoteDurablePoint(
            "session1",
            0,
            empty.to_snapshot()["digest"],
            1,
            1,
            "a" * 64,
            "2026-09-11T15:00:00Z",
        )
        controller, _, factory = make_controller(durability=durability, log=empty)
        with self.assertRaisesRegex(RemoteControllerError, "cannot be reopened"):
            controller.connect()
        self.assertEqual(factory.providers, [])


if __name__ == "__main__":
    unittest.main()
