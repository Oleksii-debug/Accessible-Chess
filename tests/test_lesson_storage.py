from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.lesson_plan import AssignmentTarget, LessonItem, LessonItemKind, LessonPlan, LessonPosition, PositionAssignment
from acs.lesson_storage import DeploymentRecord, LessonConflictError, LessonSQLiteStore, LessonStorageError
from acs.local_profile import LocalProfile
from acs.usage_statistics import UsageStatisticsSnapshot


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def core_validator(fen: str) -> None:
    if " invalid " in f" {fen} ":
        raise ValueError("invalid FEN")
    if len(fen.split()) != 6:
        raise ValueError("expected six FEN fields")


def make_plan(*, fen: str = START_FEN, title: str = "Lesson") -> LessonPlan:
    position = LessonPosition(
        "pos.start",
        "Start",
        fen,
        prompt="Student prompt",
        teacher_notes="Private teacher note",
        tags=("opening",),
    )
    return LessonPlan(
        "lesson.one",
        title,
        "8-10",
        "beginner",
        (
            LessonItem("warmup", LessonItemKind.WARM_UP, "Warm-up", 5),
            LessonItem("position", LessonItemKind.POSITION, "Position", 10, "pos.start"),
        ),
        positions=(position,),
        assignments=(
            PositionAssignment(
                "assign.one",
                "pos.start",
                AssignmentTarget.PARTICIPANTS,
                participant_ids=("student-a", "student-b"),
            ),
        ),
    )


class LessonSQLiteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "teaching.sqlite3"
        self.store = LessonSQLiteStore(self.db_path, fen_validator=core_validator)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schema_migration_is_versioned_and_reopen_is_idempotent(self) -> None:
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0], 1)
        LessonSQLiteStore(self.db_path, fen_validator=core_validator).integrity_check()

    def test_save_load_preserves_order_exact_fen_and_private_teacher_notes(self) -> None:
        exact_fen = START_FEN + "  "
        plan = make_plan(fen=exact_fen)
        revision = self.store.save_new(plan)
        loaded, loaded_revision = self.store.load(plan.lesson_id)
        self.assertEqual(revision.revision, 1)
        self.assertEqual(loaded_revision, revision)
        self.assertEqual(loaded.positions[0].fen, exact_fen)
        self.assertEqual(loaded.positions[0].prompt, "Student prompt")
        self.assertEqual(loaded.positions[0].teacher_notes, "Private teacher note")
        self.assertEqual([item.item_id for item in loaded.items], ["warmup", "position"])
        self.assertEqual(loaded.assignments[0].participant_ids, ("student-a", "student-b"))

    def test_core_validation_happens_before_write_and_rejected_fen_is_not_persisted(self) -> None:
        plan = make_plan(fen="invalid")
        with self.assertRaisesRegex(ValueError, "Core rejected FEN"):
            self.store.save_new(plan)
        with self.assertRaises(LessonStorageError):
            self.store.load(plan.lesson_id)

    def test_existing_lesson_is_never_silently_overwritten(self) -> None:
        plan = make_plan()
        self.store.save_new(plan)
        with self.assertRaises(LessonConflictError):
            self.store.save_new(make_plan(title="Changed"))
        loaded, revision = self.store.load(plan.lesson_id)
        self.assertEqual(loaded.title, "Lesson")
        self.assertEqual(revision.revision, 1)

    def test_update_is_atomic_and_requires_expected_revision(self) -> None:
        plan = make_plan()
        self.store.save_new(plan)
        changed = make_plan(title="Changed")
        revision = self.store.update(changed, expected_revision=1)
        self.assertEqual(revision.revision, 2)
        with self.assertRaises(LessonConflictError):
            self.store.update(make_plan(title="Stale"), expected_revision=1)
        loaded, current = self.store.load(plan.lesson_id)
        self.assertEqual(loaded.title, "Changed")
        self.assertEqual(current.revision, 2)

    def test_ordered_queries_and_search_do_not_expose_notes_as_search_surface(self) -> None:
        self.store.save_new(make_plan())
        self.assertEqual([i.item_id for i in self.store.ordered_items("lesson.one")], ["warmup", "position"])
        self.assertEqual([p.position_id for p in self.store.ordered_positions("lesson.one")], ["pos.start"])
        self.assertEqual(len(self.store.search_positions("opening")), 1)
        self.assertEqual(len(self.store.search_positions("Private teacher note")), 0)

    def test_deployment_identity_is_idempotent_for_reconnect(self) -> None:
        self.store.save_new(make_plan())
        record = DeploymentRecord(
            "deploy.one", "lesson.one", "assign.one", "pos.start", "participant", "student-a", "session.one", 0
        )
        self.assertEqual(self.store.record_deployment(record), record)
        self.assertEqual(self.store.record_deployment(record), record)
        self.assertEqual(self.store.deployment_timeline("session.one"), (record,))
        conflicting = DeploymentRecord(
            "deploy.one", "lesson.one", "assign.one", "pos.start", "participant", "student-b", "session.one", 0
        )
        with self.assertRaises(LessonConflictError):
            self.store.record_deployment(conflicting)

    def test_profile_and_aggregate_statistics_round_trip_without_raw_lesson_telemetry(self) -> None:
        profile = LocalProfile("install-1", "Teacher", False)
        stats = UsageStatisticsSnapshot("install-1", sessions_started=2, classroom_sessions=1, classroom_seconds=90)
        self.store.save_local_profile(profile)
        self.store.save_usage_statistics(stats)
        self.assertEqual(self.store.load_local_profile(), profile)
        self.assertEqual(self.store.load_usage_statistics("install-1"), stats)
        with sqlite3.connect(self.db_path) as db:
            payload = db.execute("SELECT payload_json FROM aggregate_usage WHERE installation_id='install-1'").fetchone()[0]
        self.assertNotIn("fen", payload.lower())
        self.assertNotIn("pgn", payload.lower())
        self.assertNotIn("teacher", payload.lower())

    def test_future_schema_fails_closed_without_mutation(self) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE schema_meta SET value=999 WHERE key='schema_version'")
        with self.assertRaisesRegex(LessonStorageError, "unsupported lesson database schema"):
            LessonSQLiteStore(self.db_path, fen_validator=core_validator)
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0], 999)


if __name__ == "__main__":
    unittest.main()
