from __future__ import annotations
import unittest

from acs.remote_connectivity import (
    AuthenticatedPrincipal,
    RemoteEndpointProfile,
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
        RemoteEndpointProfile("profile1", "relay.example.test", 443, "relay.example.test", "cred1"),
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
        RemoteLessonController(actor, log, connector(factory), Authorizer(allowed), durability),
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
        self.assertEqual(durability.point.snapshot_digest, controller.log.to_snapshot()["digest"])
        self.assertTrue(factory.providers[-1].connected)
        state = controller.presentation_state(teacher_label="Teacher", student_label="Student")
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

    def test_reconnect_requires_exact_durable_prefix_then_can_advance_checkpoint(self) -> None:
        controller, durability, _factory = make_controller()
        controller.connect()
        initial_digest = durability.point.snapshot_digest
        controller.mark_uncertain()
        event = RemoteSessionEvent(
            "session1", 1, RemoteEventKind.POINTER, {"square": "e4"}, "student1"
        )
        controller.log.append(event)
        self.assertEqual(durability.point.snapshot_digest, initial_digest)
        controller.reconnect()
        self.assertIs(controller.status, RemoteLifecycleStatus.CONNECTED)
        self.assertEqual(durability.point.last_sequence, 1)
        self.assertEqual(durability.point.snapshot_digest, controller.log.to_snapshot()["digest"])

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
