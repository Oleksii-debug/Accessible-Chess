from __future__ import annotations

import copy
import json
import threading
import unittest

from acs.analysis_service import AnalysisLine
from acs.engine_assisted_workflows import AudienceAnalysisResult, EngineVisibility
from acs.student_progress import (
    ReviewKind,
    STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION,
    StudentProgressLedger,
    StudentReviewRecord,
)
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep


FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def make_training_session() -> ExerciseSession:
    return ExerciseSession(
        ExerciseDefinition(
            exercise_id="exercise-1",
            start_fen=FEN,
            steps=(
                ExerciseStep(frozenset({"e4"}), hint="Control the centre."),
                ExerciseStep(frozenset({"e5"})),
            ),
        )
    )


def visible_engine_result(
    *, generation: int = 7, stale: bool = False
) -> AudienceAnalysisResult:
    if stale:
        return AudienceAnalysisResult(
            fen=FEN,
            generation=generation,
            visibility=EngineVisibility.VISIBLE_TO_TEACHER,
            stale=True,
        )
    line = AnalysisLine(
        multipv=1,
        depth=12,
        score_kind="cp",
        score_value=42,
        pv=("e2e4", "e7e5"),
    )
    return AudienceAnalysisResult(
        fen=FEN,
        generation=generation,
        visibility=EngineVisibility.VISIBLE_TO_TEACHER,
        stale=False,
        teacher_lines=(line,),
    )


class StudentProgressTests(unittest.TestCase):
    def test_training_review_binds_student_session_definition_and_counters(self):
        session = make_training_session()
        session.request_hint()
        session.submit("d4")
        session.submit("e4")
        ledger = StudentProgressLedger()
        record = ledger.append_training_review(
            record_id="review-1",
            student_id="student-a",
            session_id="lesson-1",
            sequence=1,
            training_session=session,
            engine_result=visible_engine_result(),
        )
        snapshot = session.snapshot()
        self.assertEqual(record.kind, ReviewKind.TRAINING)
        self.assertEqual(record.source_id, "exercise-1")
        self.assertEqual(record.source_revision, snapshot["definition_digest"])
        self.assertEqual((record.attempts, record.mistakes, record.hints_used), (2, 1, 1))
        self.assertFalse(record.completed)
        self.assertEqual(record.engine_generation, 7)
        self.assertTrue(record.engine_available)

    def test_review_record_serialization_never_persists_engine_pv_or_score(self):
        session = make_training_session()
        ledger = StudentProgressLedger()
        ledger.append_training_review(
            record_id="review-1",
            student_id="student-a",
            session_id="lesson-1",
            sequence=1,
            training_session=session,
            engine_result=visible_engine_result(),
        )
        encoded = json.dumps(ledger.snapshot(), sort_keys=True, separators=(",", ":"))
        self.assertNotIn("e2e4", encoded)
        self.assertNotIn('"pv"', encoded)
        self.assertNotIn('"score', encoded)
        self.assertIn('"engine_generation":7', encoded)

    def test_duplicate_record_id_cannot_overwrite_prior_attempt(self):
        ledger = StudentProgressLedger()
        first = StudentReviewRecord(
            record_id="same-id",
            student_id="student-a",
            session_id="lesson-1",
            kind=ReviewKind.GAME,
            source_id="game-1",
            source_revision="rev-1",
            sequence=1,
            attempts=0,
            mistakes=0,
            hints_used=0,
            completed=True,
        )
        ledger.append(first)
        with self.assertRaises(ValueError):
            ledger.append(
                StudentReviewRecord(
                    record_id="same-id",
                    student_id="student-a",
                    session_id="lesson-1",
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
        self.assertEqual(ledger.records("student-a", "lesson-1"), (first,))

    def test_nonincreasing_session_sequence_fails_atomically(self):
        ledger = StudentProgressLedger()
        ledger.append_game_review(
            record_id="review-2",
            student_id="student-a",
            session_id="lesson-1",
            sequence=2,
            game_ref="game-1",
            source_revision="rev-1",
        )
        before = ledger.snapshot()
        with self.assertRaises(ValueError):
            ledger.append_game_review(
                record_id="review-1",
                student_id="student-a",
                session_id="lesson-1",
                sequence=2,
                game_ref="game-2",
                source_revision="rev-2",
            )
        self.assertEqual(ledger.snapshot(), before)

    def test_session_keyset_paging_is_bounded_and_stable(self):
        ledger = StudentProgressLedger()
        for sequence in range(1, 8):
            ledger.append_game_review(
                record_id=f"review-{sequence}",
                student_id="student-a",
                session_id="lesson-1",
                sequence=sequence,
                game_ref=f"game-{sequence}",
                source_revision=f"rev-{sequence}",
            )
        first = ledger.records("student-a", "lesson-1", limit=3)
        second = ledger.records(
            "student-a", "lesson-1", after_sequence=first[-1].sequence, limit=3
        )
        third = ledger.records(
            "student-a", "lesson-1", after_sequence=second[-1].sequence, limit=3
        )
        self.assertEqual([record.sequence for record in first + second + third], list(range(1, 8)))
        with self.assertRaises(ValueError):
            ledger.records("student-a", "lesson-1", limit=1001)
        for invalid in (True, 1.0, "3"):
            with self.subTest(limit=repr(invalid)):
                with self.assertRaises((TypeError, ValueError)):
                    ledger.records("student-a", "lesson-1", limit=invalid)

    def test_summary_aggregates_attempt_quality_hints_and_review_counts(self):
        ledger = StudentProgressLedger()
        first = make_training_session()
        first.request_hint()
        first.submit("d4")
        first.submit("e4")
        ledger.append_training_review(
            record_id="training-1",
            student_id="student-a",
            session_id="lesson-1",
            sequence=1,
            training_session=first,
            engine_result=visible_engine_result(generation=2),
        )
        second = make_training_session()
        second.submit("e4")
        second.submit("e5")
        ledger.append_training_review(
            record_id="training-2",
            student_id="student-a",
            session_id="lesson-1",
            sequence=2,
            training_session=second,
        )
        ledger.append_game_review(
            record_id="game-1",
            student_id="student-a",
            session_id="lesson-1",
            sequence=3,
            game_ref="game-77",
            source_revision="sha256:abc",
            engine_result=visible_engine_result(generation=3, stale=True),
        )
        summary = ledger.summary("student-a", "lesson-1")
        self.assertEqual((summary.record_count, summary.training_reviews, summary.game_reviews), (3, 2, 1))
        self.assertEqual(summary.completed_training_reviews, 1)
        self.assertEqual((summary.attempts, summary.mistakes, summary.hints_used), (4, 1, 1))
        self.assertEqual((summary.accepted_attempts, summary.accuracy_permille), (3, 750))
        self.assertEqual((summary.engine_reviews, summary.stale_engine_reviews), (2, 1))

    def test_student_and_session_records_remain_isolated(self):
        ledger = StudentProgressLedger()
        inputs = (
            ("a-1", "student-a", "lesson-a", 1),
            ("a-2", "student-a", "lesson-b", 1),
            ("b-1", "student-b", "lesson-a", 1),
        )
        for record_id, student, session, sequence in inputs:
            ledger.append_game_review(
                record_id=record_id,
                student_id=student,
                session_id=session,
                sequence=sequence,
                game_ref=record_id,
                source_revision="rev-1",
            )
        self.assertEqual(
            [item.record_id for item in ledger.records("student-a", "lesson-a")],
            ["a-1"],
        )
        self.assertEqual(ledger.summary("student-a", "lesson-a").record_count, 1)

    def test_snapshot_roundtrip_preserves_append_only_identity_and_order(self):
        ledger = StudentProgressLedger()
        for sequence in (1, 2):
            ledger.append_game_review(
                record_id=f"r-{sequence}",
                student_id="student-a",
                session_id="lesson-1",
                sequence=sequence,
                game_ref=f"g-{sequence}",
                source_revision=f"rev-{sequence}",
            )
        snapshot = ledger.snapshot()
        restored = StudentProgressLedger.restore(snapshot)
        self.assertEqual(restored.snapshot(), snapshot)
        with self.assertRaises(ValueError):
            restored.append_game_review(
                record_id="r-2",
                student_id="student-a",
                session_id="lesson-1",
                sequence=3,
                game_ref="g-3",
                source_revision="rev-3",
            )

    def test_restore_rejects_future_schema_unknown_fields_and_duplicate_sequence(self):
        ledger = StudentProgressLedger()
        ledger.append_game_review(
            record_id="r-1",
            student_id="student-a",
            session_id="lesson-1",
            sequence=1,
            game_ref="g-1",
            source_revision="rev-1",
        )
        payload = ledger.snapshot()
        future = copy.deepcopy(payload)
        future["schema_version"] = STUDENT_PROGRESS_SNAPSHOT_SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            StudentProgressLedger.restore(future)
        unknown = copy.deepcopy(payload)
        unknown["extra"] = "no"
        with self.assertRaises(ValueError):
            StudentProgressLedger.restore(unknown)
        duplicate_sequence = copy.deepcopy(payload)
        second = copy.deepcopy(duplicate_sequence["records"][0])
        second["record_id"] = "r-2"
        duplicate_sequence["records"].append(second)
        with self.assertRaises(ValueError):
            StudentProgressLedger.restore(duplicate_sequence)

    def test_record_scalars_and_relationships_fail_closed(self):
        base = {
            "record_id": "r-1",
            "student_id": "student-a",
            "session_id": "lesson-1",
            "kind": ReviewKind.TRAINING,
            "source_id": "exercise-1",
            "source_revision": "rev-1",
            "sequence": 1,
            "attempts": 1,
            "mistakes": 0,
            "hints_used": 0,
            "completed": False,
        }
        for field_name, invalid in (
            ("sequence", True),
            ("attempts", 1.0),
            ("mistakes", "0"),
            ("hints_used", False),
            ("completed", 1),
        ):
            with self.subTest(field=field_name):
                payload = dict(base)
                payload[field_name] = invalid
                with self.assertRaises((TypeError, ValueError)):
                    StudentReviewRecord(**payload)
        invalid_relationship = dict(base)
        invalid_relationship["mistakes"] = 2
        with self.assertRaises(ValueError):
            StudentReviewRecord(**invalid_relationship)
        stale_available = dict(base)
        stale_available.update(
            {"engine_generation": 1, "engine_stale": True, "engine_available": True}
        )
        with self.assertRaises(ValueError):
            StudentReviewRecord(**stale_available)

    def test_stale_engine_review_records_status_without_claiming_available_answer(self):
        session = make_training_session()
        ledger = StudentProgressLedger()
        record = ledger.append_training_review(
            record_id="training-1",
            student_id="student-a",
            session_id="lesson-1",
            sequence=1,
            training_session=session,
            engine_result=visible_engine_result(generation=9, stale=True),
        )
        self.assertEqual(record.engine_generation, 9)
        self.assertTrue(record.engine_stale)
        self.assertFalse(record.engine_available)

    def test_concurrent_same_sequence_allows_only_one_append(self):
        ledger = StudentProgressLedger()
        barrier = threading.Barrier(2)
        successes = []
        failures = []

        def writer(record_id: str) -> None:
            barrier.wait()
            try:
                successes.append(
                    ledger.append_game_review(
                        record_id=record_id,
                        student_id="student-a",
                        session_id="lesson-1",
                        sequence=1,
                        game_ref=record_id,
                        source_revision="rev-1",
                    )
                )
            except ValueError as exc:
                failures.append(str(exc))

        threads = [
            threading.Thread(target=writer, args=("r-a",)),
            threading.Thread(target=writer, args=("r-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual((len(successes), len(failures)), (1, 1))
        self.assertEqual(len(ledger.records("student-a", "lesson-1")), 1)


if __name__ == "__main__":
    unittest.main()
