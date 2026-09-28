from __future__ import annotations
import unittest

from acs.remote_connectivity import RemoteConnectivityError, RemoteMessageKind
from acs.remote_controller import RemoteLifecycleStatus
from acs.remote_event_delivery import RemoteEventDelivery, RemoteEventDeliveryError
from acs.remote_protocol_control import acknowledgement_for
from acs.remote_session import RemoteEventKind, RemoteSessionEvent
from tests.test_remote_controller import Factory, make_controller


def event(sequence=1, square="e4") -> RemoteSessionEvent:
    return RemoteSessionEvent(
        "session1",
        sequence,
        RemoteEventKind.POINTER,
        {"square": square},
        "student1",
    )


class RemoteEventDeliveryTests(unittest.TestCase):
    def test_success_requires_peer_ack_then_durable_checkpoint(self) -> None:
        controller, durability, _factory = make_controller()
        controller.connect()
        delivery = RemoteEventDelivery(controller)
        delivery.publish(event())
        self.assertIs(controller.status, RemoteLifecycleStatus.CONNECTED)
        self.assertEqual(controller.log.state.last_sequence, 1)
        self.assertEqual(durability.point.last_sequence, 1)
        self.assertEqual(durability.point.snapshot_digest, controller.log.to_snapshot()["digest"])

    def test_disconnect_after_local_accept_leaves_recoverable_uncertain_state(self) -> None:
        def handler(request):
            if request.kind is RemoteMessageKind.EVENT:
                raise RemoteConnectivityError("simulated disconnect after accept")
            return acknowledgement_for(request)

        factory = Factory(__import__("tests.test_remote_controller", fromlist=["principal"]).principal(), handler)
        controller, durability, _ = make_controller(factory=factory)
        controller.connect()
        durable_before = durability.point.snapshot_digest
        delivery = RemoteEventDelivery(controller)
        with self.assertRaisesRegex(RemoteEventDeliveryError, "resume is required"):
            delivery.publish(event())
        self.assertIs(controller.status, RemoteLifecycleStatus.ERROR)
        self.assertEqual(controller.log.state.last_sequence, 1)
        self.assertEqual(durability.point.last_sequence, 0)
        self.assertEqual(durability.point.snapshot_digest, durable_before)

        controller.reconnect()
        self.assertIs(controller.status, RemoteLifecycleStatus.CONNECTED)
        self.assertEqual(durability.point.last_sequence, 1)
        self.assertEqual(durability.point.snapshot_digest, controller.log.to_snapshot()["digest"])

    def test_revoked_membership_fails_before_local_mutation(self) -> None:
        controller, durability, factory = make_controller()
        controller.connect()
        checkpoint_calls = durability.calls
        controller.authorizer.allowed = False
        with self.assertRaisesRegex(RemoteEventDeliveryError, "not authorized"):
            RemoteEventDelivery(controller).publish(event())
        self.assertEqual(controller.log.state.last_sequence, 0)
        self.assertEqual(durability.calls, checkpoint_calls)
        self.assertIs(controller.status, RemoteLifecycleStatus.ERROR)
        self.assertFalse(factory.providers[-1].connected)

    def test_exact_latest_retry_is_idempotent_locally(self) -> None:
        controller, durability, _factory = make_controller()
        controller.connect()
        delivery = RemoteEventDelivery(controller)
        same = event()
        delivery.publish(same)
        delivery.publish(same)
        self.assertEqual(len(controller.log.events), 1)
        self.assertEqual(controller.log.state.last_sequence, 1)
        self.assertEqual(durability.point.last_sequence, 1)

    def test_same_sequence_different_content_fails_closed(self) -> None:
        controller, _durability, _factory = make_controller()
        controller.connect()
        delivery = RemoteEventDelivery(controller)
        delivery.publish(event(square="e4"))
        with self.assertRaises(RemoteEventDeliveryError):
            delivery.publish(event(square="d4"))
        self.assertEqual(len(controller.log.events), 1)
        self.assertIs(controller.status, RemoteLifecycleStatus.ERROR)

    def test_mismatched_ack_never_publishes_durable_event_checkpoint(self) -> None:
        def handler(request):
            response = acknowledgement_for(request)
            if request.kind is not RemoteMessageKind.EVENT:
                return response
            return type(response)(
                response.version,
                response.kind,
                response.message_id,
                response.session_id,
                response.actor_id,
                response.role,
                response.sequence,
                response.payload,
                "0" * 64,
            )

        from tests.test_remote_controller import principal
        controller, durability, _factory = make_controller(factory=Factory(principal(), handler))
        controller.connect()
        before = durability.calls
        with self.assertRaises(RemoteEventDeliveryError):
            RemoteEventDelivery(controller).publish(event())
        self.assertEqual(durability.calls, before)
        self.assertEqual(controller.log.state.last_sequence, 1)
        self.assertIs(controller.status, RemoteLifecycleStatus.ERROR)


if __name__ == "__main__":
    unittest.main()
