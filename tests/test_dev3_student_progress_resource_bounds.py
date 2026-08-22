from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.student_progress import (
    ReviewKind,
    STUDENT_PROGRESS_MAX_SNAPSHOT_RECORDS,
    STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION,
    StudentProgressLedger,
    StudentReviewRecord,
)
from acs.student_progress_store import StudentProgressStore


class StudentProgressResourceBoundsTests(unittest.TestCase):
    def _ledger(self) -> StudentProgressLedger:
        ledger = StudentProgressLedger()
        ledger.append(
            StudentReviewRecord(
                record_id="r1",
                student_id="student-1",
                session_id="session-1",
                kind=ReviewKind.GAME,
                source_id="game-1",
                source_revision="rev-1",
                sequence=1,
                attempts=0,
                mistakes=0,
                hints_used=0,
                completed=True,
            )
        )
        return ledger

    def test_restore_rejects_oversized_record_list_before_record_validation(self) -> None:
        invalid_record = object()
        payload = {
            "schema_version": STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION,
            "records": [invalid_record] * (STUDENT_PROGRESS_MAX_SNAPSHOT_RECORDS + 1),
        }

        with self.assertRaisesRegex(ValueError, "maximum record count"):
            StudentProgressLedger.restore(payload)

    def test_store_load_reads_only_bound_plus_one_before_rejecting(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            path.write_bytes(b"x" * 129)
            store = StudentProgressStore(path)

            with patch(
                "acs.student_progress_store.STUDENT_PROGRESS_STORE_MAX_BYTES", 128
            ):
                with self.assertRaisesRegex(ValueError, "maximum size"):
                    store.load()

    def test_store_save_rejects_oversized_payload_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")

            with patch(
                "acs.student_progress_store.STUDENT_PROGRESS_STORE_MAX_BYTES", 64
            ):
                with self.assertRaisesRegex(ValueError, "payload exceeds maximum size"):
                    store.save(self._ledger(), expected_revision=None)

            self.assertFalse(store.path.exists())
            self.assertFalse(store._lock_path.exists())
            self.assertEqual(list(store.path.parent.glob(f".{store.path.name}.*.tmp")), [])

    def test_store_round_trip_remains_supported_under_default_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            ledger = self._ledger()
            revision = store.save(ledger, expected_revision=None)
            loaded = store.load()

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.revision, revision)
            self.assertEqual(loaded.ledger.snapshot(), ledger.snapshot())


if __name__ == "__main__":
    unittest.main()
