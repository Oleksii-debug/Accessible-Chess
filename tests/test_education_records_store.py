import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_records as er
from acs import education_records_store as store


STAMP = "2026-08-23T12:30:00Z"


def classroom():
    student = cd.Student("s1", "Knight-17")
    lesson = cd.Lesson("lesson1", "course1", "Rook endings", (), STAMP)
    course = cd.Course("course1", "Endgames", ("lesson1",))
    cohort = cd.Cohort("cohort1", "course1", ("s1",))
    assignment = cd.Assignment("a1", "lesson1", "cohort1", "Practice", STAMP)
    return cd.ClassroomSnapshot(
        students=(student,),
        courses=(course,),
        cohorts=(cohort,),
        lessons=(lesson,),
        assignments=(assignment,),
    )


def submitted_ledger(snapshot):
    ledger = er.EducationLedger.empty(snapshot)
    return er.submit_assignment(
        ledger,
        snapshot,
        submission_id="sub1",
        operation_id="op1",
        student_id="s1",
        assignment_id="a1",
        response_ref="response.s1",
        submitted_at=STAMP,
        expected_revision=0,
    )


class EducationRecordsStoreTests(unittest.TestCase):
    def test_create_load_update_and_reopen_round_trip(self):
        snapshot = classroom()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "education-records.json"
            persistence = store.EducationRecordsStore(target)
            initial = er.EducationLedger.empty(snapshot)
            revision1 = persistence.save(initial, expected_revision=None)
            loaded1 = persistence.load()
            self.assertIsNotNone(loaded1)
            self.assertEqual(loaded1.revision, revision1)
            self.assertEqual(loaded1.ledger, initial)

            updated = er.submit_assignment(
                loaded1.ledger,
                snapshot,
                submission_id="sub1",
                operation_id="op1",
                student_id="s1",
                assignment_id="a1",
                response_ref="response.s1",
                submitted_at=STAMP,
                expected_revision=0,
            )
            revision2 = persistence.save(updated, expected_revision=revision1)
            self.assertNotEqual(revision1, revision2)
            reopened = store.EducationRecordsStore(target).load()
            self.assertEqual(reopened.revision, revision2)
            self.assertEqual(reopened.ledger, updated)

    def test_create_only_and_stale_writer_fail_without_overwrite(self):
        snapshot = classroom()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "education-records.json"
            persistence = store.EducationRecordsStore(target)
            initial = er.EducationLedger.empty(snapshot)
            revision = persistence.save(initial, expected_revision=None)
            before = target.read_bytes()
            with self.assertRaises(store.EducationRecordsConflictError):
                persistence.save(initial, expected_revision=None)
            with self.assertRaises(store.EducationRecordsConflictError):
                persistence.save(submitted_ledger(snapshot), expected_revision="0" * 64)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(persistence.load().revision, revision)

    def test_peer_lock_fails_closed_and_does_not_touch_file(self):
        snapshot = classroom()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "education-records.json"
            persistence = store.EducationRecordsStore(target)
            revision = persistence.save(er.EducationLedger.empty(snapshot), expected_revision=None)
            before = target.read_bytes()
            persistence._lock_path.mkdir()
            try:
                with self.assertRaises(store.EducationRecordsBusyError):
                    persistence.save(submitted_ledger(snapshot), expected_revision=revision)
            finally:
                persistence._lock_path.rmdir()
            self.assertEqual(target.read_bytes(), before)

    def test_replace_failure_preserves_last_durable_file_and_cleans_temp(self):
        snapshot = classroom()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "education-records.json"
            persistence = store.EducationRecordsStore(target)
            revision = persistence.save(er.EducationLedger.empty(snapshot), expected_revision=None)
            before = target.read_bytes()
            with patch("acs.education_records_store.os.replace", side_effect=OSError("publish failed")):
                with self.assertRaises(OSError):
                    persistence.save(submitted_ledger(snapshot), expected_revision=revision)
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse(persistence._lock_path.exists())
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_corrupt_duplicate_unknown_schema_and_tampered_ledger_fail_closed(self):
        snapshot = classroom()
        ledger = er.EducationLedger.empty(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "education-records.json"
            persistence = store.EducationRecordsStore(target)

            target.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaises(store.EducationRecordsStoreError):
                persistence.load()

            target.write_text('{"schema_version":2,"ledger":{}}', encoding="utf-8")
            with self.assertRaises(store.EducationRecordsStoreError):
                persistence.load()

            envelope = {"schema_version": 1, "ledger": ledger.to_record()}
            envelope["ledger"]["revision"] = 7
            target.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaises(store.EducationRecordsStoreError):
                persistence.load()

    def test_oversized_file_is_rejected_with_bounded_read(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "education-records.json"
            target.write_bytes(b"x" * 101)
            persistence = store.EducationRecordsStore(target)
            with patch.object(store, "MAX_STORE_BYTES", 100):
                with self.assertRaises(store.EducationRecordsStoreError):
                    persistence.load()

    def test_revision_and_path_boundaries_are_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            persistence = store.EducationRecordsStore(Path(directory) / "records.json")
            with self.assertRaises(store.EducationRecordsStoreError):
                persistence.save(er.EducationLedger("a" * 64), expected_revision=True)
            with self.assertRaises(TypeError):
                store.EducationRecordsStore(3)


if __name__ == "__main__":
    unittest.main()
