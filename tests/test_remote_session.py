from __future__ import annotations

import json
import unittest

from acs.chesscore import Board
from acs.remote_session import (
    MAX_REMOTE_EVENTS,
    RemoteEventKind,
    RemoteSessionError,
    RemoteSessionEvent,
    RemoteSessionLog,
)


class RemoteSessionDomainTests(unittest.TestCase):
    def event(self, sequence: int, kind: RemoteEventKind, payload: dict, *, actor_id: str | None = None):
        return RemoteSessionEvent(
            session_id="lesson-1",
            sequence=sequence,
            kind=kind,
            actor_id=actor_id,
            payload=payload,
        )

    def test_deterministic_replay_reconstructs_shared_state_without_second_chess_core(self) -> None:
        log = RemoteSessionLog("lesson-1")
        events = (
            self.event(1, RemoteEventKind.POSITION, {"fen": Board.START}),
            self.event(2, RemoteEventKind.POINTER, {"square": "f3"}, actor_id="teacher"),
            self.event(3, RemoteEventKind.HIGHLIGHT, {"square": "e4", "tag": "target"}),
            self.event(4, RemoteEventKind.ACTIVE_STUDENT, {"student_id": "student-7"}),
            self.event(
                5,
                RemoteEventKind.STUDENT_ANSWER,
                {"student_id": "student-7", "answer_type": "square", "value": "e4"},
            ),
            self.event(6, RemoteEventKind.SPECTATOR, {"enabled": True}),
            self.event(7, RemoteEventKind.DEMO, {"enabled": True}),
        )
        log.extend(events)
        restored = RemoteSessionLog.from_json(log.to_json())
        self.assertEqual(restored.events, log.events)
        self.assertEqual(restored.state, log.state)
        self.assertEqual(restored.state.position_fen, Board.START)
        self.assertEqual(restored.state.pointer_square, "f3")
        self.assertEqual(restored.state.active_student_id, "student-7")
        self.assertTrue(restored.state.spectator)
        self.assertTrue(restored.state.demo)

    def test_pointer_annotation_and_answer_events_never_mutate_position(self) -> None:
        log = RemoteSessionLog("lesson-1")
        log.append(self.event(1, RemoteEventKind.POSITION, {"fen": Board.START}))
        checkpoint = log.state.position_fen
        log.append(self.event(2, RemoteEventKind.POINTER, {"square": "a1"}))
        log.append(self.event(3, RemoteEventKind.HIGHLIGHT, {"square": "h8", "tag": None}))
        log.append(
            self.event(
                4,
                RemoteEventKind.STUDENT_ANSWER,
                {"student_id": "s", "answer_type": "text", "value": "answer"},
            )
        )
        self.assertEqual(log.state.position_fen, checkpoint)

    def test_exact_duplicate_is_idempotent_but_sequence_conflict_fails_closed(self) -> None:
        log = RemoteSessionLog("lesson-1")
        event = self.event(1, RemoteEventKind.POINTER, {"square": "a1"})
        self.assertTrue(log.append(event))
        self.assertFalse(log.append(event))
        with self.assertRaises(RemoteSessionError):
            log.append(self.event(1, RemoteEventKind.POINTER, {"square": "b1"}))
        self.assertEqual(len(log.events), 1)
        self.assertEqual(log.state.pointer_square, "a1")

    def test_gap_out_of_order_and_cross_session_events_are_atomic(self) -> None:
        log = RemoteSessionLog("lesson-1")
        with self.assertRaises(RemoteSessionError):
            log.append(self.event(2, RemoteEventKind.POINTER, {"square": "a1"}))
        foreign = RemoteSessionEvent(
            session_id="lesson-2",
            sequence=1,
            kind=RemoteEventKind.POINTER,
            payload={"square": "a1"},
        )
        with self.assertRaises(RemoteSessionError):
            log.append(foreign)
        self.assertEqual(log.events, ())
        self.assertEqual(log.state.last_sequence, 0)

    def test_extend_is_transactional_on_late_failure(self) -> None:
        log = RemoteSessionLog("lesson-1")
        first = self.event(1, RemoteEventKind.POINTER, {"square": "a1"})
        bad = self.event(3, RemoteEventKind.POINTER, {"square": "b1"})
        with self.assertRaises(RemoteSessionError):
            log.extend((first, bad))
        self.assertEqual(log.events, ())
        self.assertIsNone(log.state.pointer_square)

    def test_position_event_uses_canonical_board_validation_and_canonicalizes_abbreviated_fen(self) -> None:
        abbreviated = "8/8/8/8/8/8/4K3/7k w - -"
        event = self.event(1, RemoteEventKind.POSITION, {"fen": abbreviated})
        self.assertEqual(event.payload["fen"], abbreviated + " 0 1")
        with self.assertRaises(RemoteSessionError):
            self.event(1, RemoteEventKind.POSITION, {"fen": "not a fen"})

    def test_wire_schema_rejects_unknown_fields_bool_sequence_and_noncanonical_square(self) -> None:
        event = self.event(1, RemoteEventKind.POINTER, {"square": "a1"})
        record = event.to_record()
        record["extra"] = 1
        with self.assertRaises(RemoteSessionError):
            RemoteSessionEvent.from_record(record)
        with self.assertRaises(RemoteSessionError):
            RemoteSessionEvent(
                session_id="lesson-1",
                sequence=True,
                kind=RemoteEventKind.POINTER,
                payload={"square": "a1"},
            )
        with self.assertRaises(RemoteSessionError):
            self.event(1, RemoteEventKind.POINTER, {"square": "A1"})

    def test_event_id_is_content_bound_and_tamper_evident(self) -> None:
        event = self.event(1, RemoteEventKind.POINTER, {"square": "a1"})
        same = self.event(1, RemoteEventKind.POINTER, {"square": "a1"})
        different = self.event(1, RemoteEventKind.POINTER, {"square": "b1"})
        self.assertEqual(event.event_id, same.event_id)
        self.assertNotEqual(event.event_id, different.event_id)
        record = event.to_record()
        record["payload"]["square"] = "b1"
        with self.assertRaises(RemoteSessionError):
            RemoteSessionEvent.from_record(record)

    def test_snapshot_digest_and_replayed_state_are_both_verified(self) -> None:
        log = RemoteSessionLog("lesson-1")
        log.append(self.event(1, RemoteEventKind.POINTER, {"square": "a1"}))
        snapshot = log.to_snapshot()
        snapshot["state"]["pointer_square"] = "b1"
        with self.assertRaises(RemoteSessionError):
            RemoteSessionLog.from_snapshot(snapshot)

        clean = log.to_snapshot()
        clean["digest"] = "0" * 64
        with self.assertRaises(RemoteSessionError):
            RemoteSessionLog.from_snapshot(clean)

    def test_duplicate_json_keys_and_non_finite_constants_fail_closed(self) -> None:
        with self.assertRaises(RemoteSessionError):
            RemoteSessionLog.from_json('{"version":1,"version":1}')
        with self.assertRaises(RemoteSessionError):
            RemoteSessionLog.from_json('{"value":NaN}')

    def test_annotation_dedupe_and_clear_are_deterministic(self) -> None:
        log = RemoteSessionLog("lesson-1")
        log.append(self.event(1, RemoteEventKind.HIGHLIGHT, {"square": "e4", "tag": "x"}))
        log.append(self.event(2, RemoteEventKind.HIGHLIGHT, {"square": "e4", "tag": "x"}))
        self.assertEqual(len(log.state.annotations), 1)
        log.append(self.event(3, RemoteEventKind.CLEAR_ANNOTATIONS, {}))
        self.assertEqual(log.state.annotations, ())

    def test_active_student_can_be_cleared_without_coercion(self) -> None:
        log = RemoteSessionLog("lesson-1")
        log.append(self.event(1, RemoteEventKind.ACTIVE_STUDENT, {"student_id": "s1"}))
        log.append(self.event(2, RemoteEventKind.ACTIVE_STUDENT, {"student_id": None}))
        self.assertIsNone(log.state.active_student_id)
        with self.assertRaises(RemoteSessionError):
            self.event(1, RemoteEventKind.ACTIVE_STUDENT, {"student_id": 7})

    def test_event_limit_is_fail_closed_without_partial_append(self) -> None:
        log = RemoteSessionLog("lesson-1")
        log._events = [self.event(1, RemoteEventKind.POINTER, {"square": "a1"})] * MAX_REMOTE_EVENTS
        log._event_ids = {"placeholder"}
        before = log.state
        with self.assertRaises(RemoteSessionError):
            log.append(self.event(MAX_REMOTE_EVENTS + 1, RemoteEventKind.POINTER, {"square": "b1"}))
        self.assertEqual(log.state, before)

    def test_snapshot_json_is_deterministic(self) -> None:
        log = RemoteSessionLog("lesson-1")
        log.append(self.event(1, RemoteEventKind.POINTER, {"square": "f3"}, actor_id="teacher"))
        self.assertEqual(log.to_json(), log.to_json())
        parsed = json.loads(log.to_json())
        self.assertEqual(parsed["events"][0]["event_id"], log.events[0].event_id)


if __name__ == "__main__":
    unittest.main()
