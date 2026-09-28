from __future__ import annotations
import unittest

from acs.remote_user_journey import (
    RemoteLessonUserJourney,
    RemoteUserCommand,
    RemoteUserJourneyError,
)
from acs.remote_session import RemoteEventKind, RemoteSessionEvent
from tests.test_remote_controller import Factory, StatefulPeer, make_controller, principal


def pointer_event(sequence: int = 1, square: str = "e4") -> RemoteSessionEvent:
    return RemoteSessionEvent(
        "session1",
        sequence,
        RemoteEventKind.POINTER,
        {"square": square},
        "student1",
    )


class RemoteUserJourneyTests(unittest.TestCase):
    def test_snapshot_is_semantic_secret_free_and_keyboard_dispatchable(self) -> None:
        controller, _durability, _factory = make_controller()
        journey = RemoteLessonUserJourney(
            controller,
            teacher_label="Teacher",
            student_label="Student",
        )
        state = journey.snapshot()
        self.assertEqual(state.status, "disconnected")
        self.assertEqual(state.status_text, "Remote lesson disconnected.")
        self.assertEqual(state.available_commands, ("connect",))
        self.assertEqual(state.last_activity_text, "No remote activity yet.")
        self.assertEqual(state.teacher_label, "Teacher")
        self.assertEqual(state.student_label, "Student")
        exposed = repr(state).lower()
        self.assertNotIn("runtime-secret", exposed)
        self.assertNotIn("cred1", exposed)

    def test_connect_publish_leave_reaches_complete_end_user_lifecycle(self) -> None:
        controller, durability, _factory = make_controller()
        journey = RemoteLessonUserJourney(controller)

        connected = journey.invoke(RemoteUserCommand.CONNECT)
        self.assertEqual(connected.status, "connected")
        self.assertTrue(connected.accepting_mutations)
        self.assertEqual(
            connected.available_commands,
            ("publish_event", "leave"),
        )

        delivered = journey.invoke(
            "publish_event",
            event=pointer_event(),
        )
        self.assertEqual(delivered.last_sequence, 1)
        self.assertEqual(delivered.last_activity_text, "pointer; sequence 1.")
        self.assertEqual(delivered.notice, "Remote activity delivered.")
        self.assertEqual(durability.point.last_sequence, 1)

        closed = journey.invoke(
            "leave",
            closed_at="2026-09-11T18:40:00Z",
        )
        self.assertEqual(closed.status, "disconnected")
        self.assertEqual(closed.notice, "Remote lesson closed.")
        self.assertEqual(closed.available_commands, ())
        self.assertTrue(durability.point.closed)

    def test_failed_connect_has_stable_user_notice_without_auth_detail(self) -> None:
        controller, _durability, _factory = make_controller(allowed=False)
        journey = RemoteLessonUserJourney(controller)
        with self.assertRaisesRegex(RemoteUserJourneyError, "Remote connection failed"):
            journey.invoke("connect")
        state = journey.snapshot()
        self.assertEqual(state.status, "error")
        self.assertEqual(state.notice, "Remote connection failed.")
        exposed = repr(state).lower()
        self.assertNotIn("authorized", exposed)
        self.assertNotIn("runtime-secret", exposed)
        self.assertNotIn("cred1", exposed)

    def test_uncertain_delivery_exposes_reconnect_and_recovers_same_log(self) -> None:
        actor = principal()
        peer = StatefulPeer(actor)
        peer.drop_next_event_ack_after_accept = True
        controller, durability, _factory = make_controller(
            factory=Factory(actor, peer)
        )
        journey = RemoteLessonUserJourney(controller)
        journey.invoke("connect")
        durable_before = durability.point.snapshot_digest

        with self.assertRaisesRegex(RemoteUserJourneyError, "delivery is uncertain"):
            journey.invoke("publish_event", event=pointer_event())
        uncertain = journey.snapshot()
        self.assertEqual(uncertain.status, "error")
        self.assertEqual(uncertain.available_commands, ("reconnect",))
        self.assertEqual(uncertain.last_sequence, 1)
        self.assertEqual(peer.log.state.last_sequence, 1)
        self.assertEqual(durability.point.snapshot_digest, durable_before)

        resumed = journey.invoke("reconnect")
        self.assertEqual(resumed.status, "connected")
        self.assertEqual(resumed.last_sequence, 1)
        self.assertEqual(peer.log.events, controller.log.events)
        self.assertEqual(durability.point.last_sequence, 1)
        self.assertEqual(
            durability.point.snapshot_digest, controller.log.to_snapshot()["digest"]
        )

    def test_invalid_command_payload_never_mutates_canonical_log(self) -> None:
        controller, durability, _factory = make_controller()
        journey = RemoteLessonUserJourney(controller)
        with self.assertRaisesRegex(RemoteUserJourneyError, "canonical event"):
            journey.invoke("publish_event")
        self.assertEqual(controller.log.state.last_sequence, 0)
        self.assertEqual(durability.calls, 0)
        with self.assertRaisesRegex(RemoteUserJourneyError, "unsupported"):
            journey.invoke("not-a-command")
        self.assertEqual(controller.log.state.last_sequence, 0)


if __name__ == "__main__":
    unittest.main()
