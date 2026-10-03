from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from acs.sqlite_classroom_moderation_ledger import (
    ClassroomModerationLedgerError,
    SqliteClassroomModerationLedger,
)


FP_A = "a" * 64
FP_B = "b" * 64
OWNER_A = "service-owner-a"
OWNER_B = "service-owner-b"


class SqliteClassroomModerationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "moderation.sqlite3"
        self.ledger = SqliteClassroomModerationLedger(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_workflow_binds_scope_to_immutable_pull_request_base(self):
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "classroom-moderation-sqlite-ledger.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$EVENT_BASE_SHA" HEAD', workflow)
        self.assertIn(
            'test "$(git merge-base "$EVENT_BASE_SHA" HEAD)" = "$EVENT_BASE_SHA"',
            workflow,
        )
        self.assertIn('git diff --check "$EVENT_BASE_SHA...HEAD"', workflow)
        self.assertIn(
            'git diff --name-only "$EVENT_BASE_SHA...HEAD"',
            workflow,
        )
        self.assertNotIn("refs/remotes/origin/$EXPECTED_BASE_REF", workflow)

    def test_constructor_and_read_path_have_complete_connection_lifecycle_imports(self):
        second_path = Path(self.temp.name) / "constructor-read.sqlite3"
        second = SqliteClassroomModerationLedger(second_path)
        self.assertIsNone(
            second.operation_state(
                room_id="room-constructor",
                operation_id="op-constructor",
            )
        )
        self.assertTrue(second_path.exists())

    def test_reservation_is_pending_owned_and_exact_same_owner_retry_returns_same_state(self):
        first = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        second = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        self.assertEqual(first.fingerprint, FP_A)
        self.assertFalse(first.committed)
        self.assertEqual(first.reservation_owner, OWNER_A)
        self.assertEqual(second, first)
        self.assertEqual(
            self.ledger.operation_state(room_id="room-1", operation_id="op-1"),
            first,
        )

    def test_exact_retry_from_another_owner_cannot_take_over_pending_reservation(self):
        original = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        second = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_B,
        )
        self.assertEqual(second, original)
        self.assertEqual(second.reservation_owner, OWNER_A)

        with self.assertRaisesRegex(
            ClassroomModerationLedgerError,
            "reservation owner conflict",
        ):
            self.ledger.commit(
                room_id="room-1",
                operation_id="op-1",
                fingerprint=FP_A,
                reservation_owner=OWNER_B,
            )

        pending = self.ledger.operation_state(room_id="room-1", operation_id="op-1")
        self.assertEqual(pending, original)
        self.assertFalse(pending.committed)

    def test_conflicting_reservation_never_rebinds_operation_id_or_owner(self):
        original = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        conflict = self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_B,
            reservation_owner=OWNER_B,
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
            reservation_owner=OWNER_A,
        )
        self.ledger.commit(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        self.ledger.commit(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )

        reopened = SqliteClassroomModerationLedger(self.path)
        state = reopened.operation_state(room_id="room-1", operation_id="op-1")
        self.assertIsNotNone(state)
        self.assertEqual(state.fingerprint, FP_A)
        self.assertTrue(state.committed)
        self.assertIsNone(state.reservation_owner)

        retried = reopened.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_B,
        )
        self.assertTrue(retried.committed)
        self.assertIsNone(retried.reservation_owner)

    def test_commit_requires_matching_existing_owned_reservation(self):
        with self.assertRaisesRegex(
            ClassroomModerationLedgerError,
            "not reserved",
        ):
            self.ledger.commit(
                room_id="room-1",
                operation_id="missing",
                fingerprint=FP_A,
                reservation_owner=OWNER_A,
            )

        self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        with self.assertRaisesRegex(
            ClassroomModerationLedgerError,
            "fingerprint conflict",
        ):
            self.ledger.commit(
                room_id="room-1",
                operation_id="op-1",
                fingerprint=FP_B,
                reservation_owner=OWNER_A,
            )
        state = self.ledger.operation_state(room_id="room-1", operation_id="op-1")
        self.assertEqual(state.fingerprint, FP_A)
        self.assertFalse(state.committed)
        self.assertEqual(state.reservation_owner, OWNER_A)

    def test_commit_rejects_non_owner_of_pending_reservation(self):
        self.ledger.reserve(
            room_id="room-owner",
            operation_id="op-owner",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        with self.assertRaisesRegex(
            ClassroomModerationLedgerError,
            "reservation owner conflict",
        ):
            self.ledger.commit(
                room_id="room-owner",
                operation_id="op-owner",
                fingerprint=FP_A,
                reservation_owner=OWNER_B,
            )
        state = self.ledger.operation_state(
            room_id="room-owner",
            operation_id="op-owner",
        )
        self.assertIsNotNone(state)
        self.assertFalse(state.committed)
        self.assertEqual(state.reservation_owner, OWNER_A)

    def test_room_scope_keeps_same_operation_id_independent(self):
        state_a = self.ledger.reserve(
            room_id="room-a",
            operation_id="same-op",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        state_b = self.ledger.reserve(
            room_id="room-b",
            operation_id="same-op",
            fingerprint=FP_B,
            reservation_owner=OWNER_B,
        )
        self.assertEqual(state_a.fingerprint, FP_A)
        self.assertEqual(state_a.reservation_owner, OWNER_A)
        self.assertEqual(state_b.fingerprint, FP_B)
        self.assertEqual(state_b.reservation_owner, OWNER_B)

    def test_two_independent_connections_cannot_race_conflicting_fingerprints_or_owners(self):
        barrier = threading.Barrier(2)

        def reserve(fingerprint, owner):
            local = SqliteClassroomModerationLedger(self.path, timeout_seconds=10)
            barrier.wait()
            return local.reserve(
                room_id="room-race",
                operation_id="op-race",
                fingerprint=fingerprint,
                reservation_owner=owner,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(reserve, FP_A, OWNER_A),
                executor.submit(reserve, FP_B, OWNER_B),
            ]
            states = [future.result(timeout=15) for future in futures]

        final = self.ledger.operation_state(
            room_id="room-race",
            operation_id="op-race",
        )
        self.assertIsNotNone(final)
        self.assertIn(final.fingerprint, (FP_A, FP_B))
        self.assertIn(final.reservation_owner, (OWNER_A, OWNER_B))
        self.assertEqual(states[0], final)
        self.assertEqual(states[1], final)
        self.assertFalse(final.committed)

    def test_two_independent_connections_exact_retry_has_one_owner(self):
        barrier = threading.Barrier(2)

        def reserve(owner):
            local = SqliteClassroomModerationLedger(self.path, timeout_seconds=10)
            barrier.wait()
            return local.reserve(
                room_id="room-race",
                operation_id="op-exact",
                fingerprint=FP_A,
                reservation_owner=owner,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            states = [
                future.result(timeout=15)
                for future in (
                    executor.submit(reserve, OWNER_A),
                    executor.submit(reserve, OWNER_B),
                )
            ]
        self.assertEqual(states[0], states[1])
        self.assertEqual(states[0].fingerprint, FP_A)
        self.assertIn(states[0].reservation_owner, (OWNER_A, OWNER_B))
        self.assertFalse(states[0].committed)

    def test_database_schema_enforces_unique_key_and_owner_state_invariant(self):
        self.ledger.reserve(
            room_id="room-1",
            operation_id="op-1",
            fingerprint=FP_A,
            reservation_owner=OWNER_A,
        )
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO classroom_moderation_operations
                        (
                            room_id,
                            operation_id,
                            fingerprint,
                            committed,
                            reservation_owner
                        )
                    VALUES (?, ?, ?, 0, ?)
                    """,
                    ("room-1", "op-1", FP_B, OWNER_B),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO classroom_moderation_operations
                        (
                            room_id,
                            operation_id,
                            fingerprint,
                            committed,
                            reservation_owner
                        )
                    VALUES (?, ?, ?, 0, NULL)
                    """,
                    ("room-2", "pending-without-owner", FP_A),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO classroom_moderation_operations
                        (
                            room_id,
                            operation_id,
                            fingerprint,
                            committed,
                            reservation_owner
                        )
                    VALUES (?, ?, ?, 1, ?)
                    """,
                    ("room-2", "committed-with-owner", FP_A, OWNER_A),
                )
        finally:
            connection.close()

    def test_failed_connection_setup_closes_opened_sqlite_handle(self):
        class FailingPragmaConnection:
            def __init__(self):
                self.closed = False

            def execute(self, statement):
                if statement == "PRAGMA synchronous=FULL":
                    raise sqlite3.OperationalError("private pragma failure")
                return self

            def close(self):
                self.closed = True

        failing = FailingPragmaConnection()
        with patch(
            "acs.sqlite_classroom_moderation_ledger.sqlite3.connect",
            return_value=failing,
        ):
            with self.assertRaisesRegex(
                ClassroomModerationLedgerError,
                "^moderation ledger storage is unavailable$",
            ) as caught:
                self.ledger._connect()

        self.assertTrue(failing.closed)
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("private pragma failure", str(caught.exception))

    def test_invalid_storage_inputs_fail_closed_without_path_in_repr(self):
        self.assertNotIn(str(self.path), repr(self.ledger))
        for room, operation, fingerprint, owner in (
            (" room", "op", FP_A, OWNER_A),
            ("room", "op space", FP_A, OWNER_A),
            ("room", "op", "A" * 64, OWNER_A),
            ("room", "op", "a" * 63, OWNER_A),
            ("room", "op", FP_A, "bad owner"),
            ("room", "op", FP_A, ""),
        ):
            with self.subTest(
                room=room,
                operation=operation,
                fingerprint=fingerprint[:8],
                owner=owner,
            ):
                with self.assertRaises(ClassroomModerationLedgerError):
                    self.ledger.reserve(
                        room_id=room,
                        operation_id=operation,
                        fingerprint=fingerprint,
                        reservation_owner=owner,
                    )

        with self.assertRaises(ClassroomModerationLedgerError):
            SqliteClassroomModerationLedger(":memory:")
        with self.assertRaises(ClassroomModerationLedgerError):
            SqliteClassroomModerationLedger(self.path, timeout_seconds=True)
        with self.assertRaises(ClassroomModerationLedgerError):
            SqliteClassroomModerationLedger(self.path, timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
