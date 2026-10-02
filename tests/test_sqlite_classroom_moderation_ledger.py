from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from acs.sqlite_classroom_moderation_ledger import (
    ClassroomModerationLedgerError,
    SqliteClassroomModerationLedger,
)


FP_A = "a" * 64
FP_B = "b" * 64


class SqliteClassroomModerationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "moderation.sqlite3"
        self.ledger = SqliteClassroomModerationLedger(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_reservation_is_pending_and_exact_retry_returns_same_state(self):
        first = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )
        second = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )
        self.assertEqual(first.fingerprint, FP_A)
        self.assertFalse(first.committed)
        self.assertEqual(second, first)
        self.assertEqual(
            self.ledger.operation_state(room_id="room-1", operation_id="op-1"),
            first,
        )

    def test_conflicting_reservation_never_rebinds_operation_id(self):
        original = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )
        conflict = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_B,
        )
        self.assertEqual(conflict, original)
        self.assertEqual(
            self.ledger.operation_state(room_id="room-1", operation_id="op-1"),
            original,
        )

    def test_commit_is_exact_idempotent_and_persistent_across_instances(self):
        self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )
        self.ledger.commit(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )
        self.ledger.commit(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )

        reopened = SqliteClassroomModerationLedger(self.path)
        state = reopened.operation_state(room_id="room-1", operation_id="op-1")
        self.assertIsNotNone(state)
        self.assertEqual(state.fingerprint, FP_A)
        self.assertTrue(state.committed)
        retried = reopened.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )
        self.assertTrue(retried.committed)

    def test_commit_requires_matching_existing_reservation(self):
        with self.assertRaisesRegex(
            ClassroomModerationLedgerError,
            "not reserved",
        ):
            self.ledger.commit(
                room_id="room-1",
                operation_id="missing",
                fingerprint=FP_A,
            )

        self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )
        with self.assertRaisesRegex(
            ClassroomModerationLedgerError,
            "fingerprint conflict",
        ):
            self.ledger.commit(
                room_id="room-1",
                operation_id="op-1",
                fingerprint=FP_B,
            )
        state = self.ledger.operation_state(room_id="room-1", operation_id="op-1")
        self.assertEqual(state.fingerprint, FP_A)
        self.assertFalse(state.committed)

    def test_room_scope_keeps_same_operation_id_independent(self):
        state_a = self.ledger.reserve(
            room_id="room-a",
            operation_id="same-op",
            fingerprint=FP_A,
        )
        state_b = self.ledger.reserve(
            room_id="room-b",
            operation_id="same-op",
            fingerprint=FP_B,
        )
        self.assertEqual(state_a.fingerprint, FP_A)
        self.assertEqual(state_b.fingerprint, FP_B)

    def test_two_independent_connections_cannot_race_conflicting_fingerprints(self):
        barrier = threading.Barrier(2)

        def reserve(fingerprint):
            local = SqliteClassroomModerationLedger(self.path, timeout_seconds=10)
            barrier.wait()
            return local.reserve(
                room_id="room-race",
                operation_id="op-race",
                fingerprint=fingerprint,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(reserve, value) for value in (FP_A, FP_B)]
            states = [future.result(timeout=15) for future in futures]

        self.assertEqual(len({state.fingerprint for state in states}), 1)
        final = self.ledger.operation_state(
            room_id="room-race",
            operation_id="op-race",
        )
        self.assertIn(final.fingerprint, (FP_A, FP_B))
        self.assertEqual(states[0], final)
        self.assertEqual(states[1], final)
        self.assertFalse(final.committed)

    def test_two_independent_connections_converge_on_exact_retry(self):
        barrier = threading.Barrier(2)

        def reserve():
            local = SqliteClassroomModerationLedger(self.path, timeout_seconds=10)
            barrier.wait()
            return local.reserve(
                room_id="room-race",
                operation_id="op-exact",
                fingerprint=FP_A,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            states = [
                future.result(timeout=15)
                for future in (executor.submit(reserve), executor.submit(reserve))
            ]
        self.assertEqual(states[0], states[1])
        self.assertEqual(states[0].fingerprint, FP_A)
        self.assertFalse(states[0].committed)

    def test_database_schema_enforces_unique_room_operation_key(self):
        self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
        )
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO classroom_moderation_operations
                        (room_id, operation_id, fingerprint, committed)
                    VALUES (?, ?, ?, 0)
                    """,
                    ("room-1", "op-1", FP_B),
                )
        finally:
            connection.close()

    def test_invalid_storage_inputs_fail_closed_without_path_in_repr(self):
        self.assertNotIn(str(self.path), repr(self.ledger))
        for room, operation, fingerprint in (
            (" room", "op", FP_A),
            ("room", "op space", FP_A),
            ("room", "op", "A" * 64),
            ("room", "op", "a" * 63),
        ):
            with self.subTest(room=room, operation=operation, fingerprint=fingerprint[:8]):
                with self.assertRaises(ClassroomModerationLedgerError):
                    self.ledger.reserve(
                        room_id=room,
                        operation_id=operation,
                        fingerprint=fingerprint,
                    )

        with self.assertRaises(ClassroomModerationLedgerError):
            SqliteClassroomModerationLedger(":memory:")
        with self.assertRaises(ClassroomModerationLedgerError):
            SqliteClassroomModerationLedger(self.path, timeout_seconds=True)
        with self.assertRaises(ClassroomModerationLedgerError):
            SqliteClassroomModerationLedger(self.path, timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
