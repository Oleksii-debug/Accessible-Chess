from __future__ import annotations

import json
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
from acs.student_progress_store import (
    StudentProgressBusyError,
    StudentProgressConflictError,
    StudentProgressStore,
)


class StudentProgressStoreTests(unittest.TestCase):
    def _ledger(self, *, record_id: str = "r1", sequence: int = 1) -> StudentProgressLedger:
        ledger = StudentProgressLedger()
        ledger.append(
            StudentReviewRecord(
                record_id=record_id,
                student_id="student-1",
                session_id="session-1",
                kind=ReviewKind.GAME,
                source_id="game-1",
                source_revision="rev-1",
                sequence=sequence,
                attempts=0,
                mistakes=0,
                hints_used=0,
                completed=True,
            )
        )
        return ledger

    def test_create_load_and_update_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            store = StudentProgressStore(path)
            ledger = self._ledger()

            revision1 = store.save(ledger, expected_revision=None)
            loaded1 = store.load()
            self.assertIsNotNone(loaded1)
            assert loaded1 is not None
            self.assertEqual(loaded1.revision, revision1)
            self.assertEqual(loaded1.ledger.snapshot(), ledger.snapshot())

            loaded1.ledger.append(
                StudentReviewRecord(
                    record_id="r2",
                    student_id="student-1",
                    session_id="session-1",
                    kind=ReviewKind.GAME,
                    source_id="game-2",
                    source_revision="rev-2",
                    sequence=2,
                    attempts=0,
                    mistakes=0,
                    hints_used=0,
                    completed=True,
                )
            )
            revision2 = store.save(
                loaded1.ledger,
                expected_revision=loaded1.revision,
            )
            self.assertNotEqual(revision2, revision1)
            loaded2 = store.load()
            self.assertIsNotNone(loaded2)
            assert loaded2 is not None
            self.assertEqual(loaded2.revision, revision2)
            self.assertEqual(
                [record.record_id for record in loaded2.ledger.records("student-1", "session-1")],
                ["r1", "r2"],
            )

    def test_create_only_never_overwrites_existing_progress(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            first = self._ledger()
            revision = store.save(first, expected_revision=None)
            original = store.path.read_bytes()

            with self.assertRaises(StudentProgressConflictError):
                store.save(self._ledger(record_id="other"), expected_revision=None)

            self.assertEqual(store.path.read_bytes(), original)
            self.assertEqual(store.load().revision, revision)  # type: ignore[union-attr]

    def test_stale_revision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            revision1 = store.save(self._ledger(), expected_revision=None)
            loaded = store.load()
            assert loaded is not None
            loaded.ledger.append(
                StudentReviewRecord(
                    record_id="r2",
                    student_id="student-1",
                    session_id="session-1",
                    kind=ReviewKind.GAME,
                    source_id="game-2",
                    source_revision="rev-2",
                    sequence=2,
                    attempts=0,
                    mistakes=0,
                    hints_used=0,
                    completed=True,
                )
            )
            revision2 = store.save(loaded.ledger, expected_revision=revision1)

            with self.assertRaises(StudentProgressConflictError):
                store.save(self._ledger(record_id="stale"), expected_revision=revision1)

            self.assertEqual(store.load().revision, revision2)  # type: ignore[union-attr]

    def test_peer_lock_reports_busy_without_touching_data(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            revision = store.save(self._ledger(), expected_revision=None)
            original = store.path.read_bytes()
            store._lock_path.mkdir()
            try:
                with self.assertRaises(StudentProgressBusyError):
                    store.save(self._ledger(record_id="r2"), expected_revision=revision)
            finally:
                store._lock_path.rmdir()
            self.assertEqual(store.path.read_bytes(), original)

    def test_publication_failure_preserves_prior_file_and_cleans_temp_and_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            revision = store.save(self._ledger(), expected_revision=None)
            original = store.path.read_bytes()
            loaded = store.load()
            assert loaded is not None
            loaded.ledger.append(
                StudentReviewRecord(
                    record_id="r2",
                    student_id="student-1",
                    session_id="session-1",
                    kind=ReviewKind.GAME,
                    source_id="game-2",
                    source_revision="rev-2",
                    sequence=2,
                    attempts=0,
                    mistakes=0,
                    hints_used=0,
                    completed=True,
                )
            )

            with patch("acs.student_progress_store.os.replace", side_effect=OSError("publish failed")):
                with self.assertRaisesRegex(OSError, "publish failed"):
                    store.save(loaded.ledger, expected_revision=revision)

            self.assertEqual(store.path.read_bytes(), original)
            self.assertFalse(store._lock_path.exists())
            self.assertEqual(list(store.path.parent.glob(f".{store.path.name}.*.tmp")), [])

    def test_strict_envelope_and_snapshot_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            store = StudentProgressStore(path)

            for payload in (
                [],
                {"schema_version": 1},
                {"schema_version": 1, "snapshot": {}, "extra": True},
                {"schema_version": True, "snapshot": {}},
                {"schema_version": 99, "snapshot": {}},
                {"schema_version": 1, "snapshot": []},
            ):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises((TypeError, ValueError)):
                    store.load()

    def test_expected_revision_is_exact_lowercase_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            ledger = self._ledger()
            for bad in (True, 1, "ABC", "a" * 63, "A" * 64, "g" * 64):
                with self.assertRaises((TypeError, ValueError)):
                    store.save(ledger, expected_revision=bad)  # type: ignore[arg-type]

    def test_serialized_store_contains_review_metadata_not_engine_answer_material(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = StudentProgressStore(Path(raw_dir) / "student-progress.json")
            store.save(self._ledger(), expected_revision=None)
            payload = store.path.read_text(encoding="utf-8")
            self.assertNotIn('"pv"', payload)
            self.assertNotIn('"score"', payload)
            self.assertIn('"record_id":"r1"', payload)

    def test_restore_rejects_oversized_record_list_before_record_validation(self) -> None:
        payload = {
            "schema_version": STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION,
            "records": [object()] * (STUDENT_PROGRESS_MAX_SNAPSHOT_RECORDS + 1),
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
