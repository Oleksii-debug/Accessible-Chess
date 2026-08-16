import tempfile
import unittest
from pathlib import Path

from acs.child_coaching_ui import LessonTemplate, LessonTemplateBlock
from acs.lesson_application_service import LessonApplicationService
from acs.lesson_plan import (
    AssignmentTarget,
    ClassroomPairing,
    LessonItemKind,
    LessonPosition,
    PositionAssignment,
)
from acs.lesson_session_storage import LessonSessionSQLiteStore
from acs.lesson_storage import LessonSQLiteStore
from acs.lesson_template_storage import (
    LessonTemplateSQLiteStore,
    RotationRoundRecord,
    RotationRoundState,
)


VALID_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
SPACED_FEN = "  8/8/8/8/8/8/4K3/7k w - - 0 1  "


class LessonApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "teaching.sqlite3"
        self.validated = []

        def validator(fen):
            self.validated.append(fen)
            if fen.strip() != VALID_FEN:
                raise ValueError("invalid test FEN")

        self.validator = validator
        self.service = LessonApplicationService(
            lesson_store=LessonSQLiteStore(self.db_path, fen_validator=validator),
            template_store=LessonTemplateSQLiteStore(self.db_path),
            session_store=LessonSessionSQLiteStore(self.db_path, fen_validator=validator),
            fen_validator=validator,
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def template():
        return LessonTemplate(
            "custom-one",
            "Custom lesson",
            "7-8",
            (
                LessonTemplateBlock(
                    "warmup", LessonItemKind.WARM_UP, "Warm up", 5, False
                ),
                LessonTemplateBlock(
                    "position", LessonItemKind.POSITION, "Position", 8, False
                ),
                LessonTemplateBlock(
                    "exercise", LessonItemKind.EXERCISE, "Exercise", 7, True
                ),
            ),
        )

    def test_template_plan_save_reopen_preserves_order_and_exact_fen(self):
        self.service.save_new_template(self.template(), level="beginner")
        position = LessonPosition("pos-1", "King exercise", SPACED_FEN, "Find move", "Private")
        assignment = PositionAssignment(
            "assign-1",
            "pos-1",
            AssignmentTarget.PARTICIPANTS,
            ("student-a", "student-b"),
        )
        plan = self.service.materialize_template(
            "custom-one",
            lesson_id="lesson-1",
            title="Lesson one",
            positions=(position,),
            assignments=(assignment,),
            position_bindings={"position": "pos-1"},
        )
        revision = self.service.save_new_plan(plan)
        self.assertEqual(1, revision.revision)

        reopened = LessonApplicationService(
            lesson_store=LessonSQLiteStore(self.db_path, fen_validator=self.validator),
            template_store=LessonTemplateSQLiteStore(self.db_path),
            session_store=LessonSessionSQLiteStore(self.db_path, fen_validator=self.validator),
            fen_validator=self.validator,
        )
        loaded, loaded_revision = reopened.load_plan("lesson-1")
        self.assertEqual(1, loaded_revision.revision)
        self.assertEqual(("warmup", "position", "exercise"), tuple(i.item_id for i in loaded.items))
        self.assertEqual(SPACED_FEN, loaded.positions[0].fen)
        self.assertEqual("Private", loaded.positions[0].teacher_notes)
        self.assertIn(SPACED_FEN, self.validated)

    def test_materialization_requires_explicit_position_binding(self):
        self.service.save_new_template(self.template(), level="beginner")
        with self.assertRaisesRegex(ValueError, "requires binding"):
            self.service.materialize_template(
                "custom-one", lesson_id="lesson-1", title="Lesson one"
            )

    def test_assignment_deployment_is_idempotent_and_target_order_is_stable(self):
        self.service.save_new_template(self.template(), level="beginner")
        position = LessonPosition("pos-1", "Position", VALID_FEN)
        assignment = PositionAssignment(
            "assign-1",
            "pos-1",
            AssignmentTarget.PARTICIPANTS,
            ("student-b", "student-a"),
        )
        plan = self.service.materialize_template(
            "custom-one",
            lesson_id="lesson-1",
            title="Lesson one",
            positions=(position,),
            assignments=(assignment,),
            position_bindings={"position": "pos-1"},
        )
        self.service.save_new_plan(plan)
        first = self.service.deploy_assignment(
            lesson_id="lesson-1",
            assignment_id="assign-1",
            classroom_session_id="class-1",
            batch_id="deploy-batch-1",
            first_sequence_no=4,
        )
        second = self.service.deploy_assignment(
            lesson_id="lesson-1",
            assignment_id="assign-1",
            classroom_session_id="class-1",
            batch_id="deploy-batch-1",
            first_sequence_no=4,
        )
        self.assertEqual(first, second)
        self.assertEqual(
            ("student-b", "student-a"), tuple(record.target_id for record in first.records)
        )
        self.assertEqual((4, 5), tuple(record.sequence_no for record in first.records))

    def test_all_group_and_demonstration_targets_remain_explicit(self):
        self.service.save_new_template(self.template(), level="beginner")
        position = LessonPosition("pos-1", "Position", VALID_FEN)
        assignments = (
            PositionAssignment("all-1", "pos-1", AssignmentTarget.ALL),
            PositionAssignment("group-1", "pos-1", AssignmentTarget.GROUP, (), "group-red"),
        )
        plan = self.service.materialize_template(
            "custom-one",
            lesson_id="lesson-1",
            title="Lesson one",
            positions=(position,),
            assignments=assignments,
            position_bindings={"position": "pos-1"},
        )
        self.service.save_new_plan(plan)
        all_batch = self.service.deploy_assignment(
            lesson_id="lesson-1",
            assignment_id="all-1",
            classroom_session_id="class-1",
            batch_id="all-batch",
            first_sequence_no=0,
        )
        group_batch = self.service.deploy_assignment(
            lesson_id="lesson-1",
            assignment_id="group-1",
            classroom_session_id="class-1",
            batch_id="group-batch",
            first_sequence_no=1,
        )
        demo_batch = self.service.deploy_demonstration_position(
            lesson_id="lesson-1",
            position_id="pos-1",
            classroom_session_id="class-1",
            batch_id="demo-batch",
            first_sequence_no=2,
        )
        self.assertEqual(("all", "class-1"), (all_batch.records[0].target_kind, all_batch.records[0].target_id))
        self.assertEqual(("group", "group-red"), (group_batch.records[0].target_kind, group_batch.records[0].target_id))
        self.assertEqual(("demonstration", "class-1"), (demo_batch.records[0].target_kind, demo_batch.records[0].target_id))

    def test_pairing_overrides_and_rotation_recover_after_reopen(self):
        pairing = ClassroomPairing(
            "pair-1", "student-a", "student-b", 300, 5, SPACED_FEN
        )
        batch = self.service.record_pairings(
            batch_id="pair-batch-1",
            lesson_id="lesson-1",
            classroom_session_id="class-1",
            pairings=(pairing,),
            game_session_ids=("game-1",),
        )
        self.assertEqual("student-a", batch.records[0].white_participant_id)
        self.assertEqual("student-b", batch.records[0].black_participant_id)
        self.assertEqual(300, batch.records[0].base_seconds)
        self.assertEqual(5, batch.records[0].increment_seconds)
        self.assertEqual(SPACED_FEN, batch.records[0].start_fen)

        self.service.save_rotation(
            RotationRoundRecord(
                "round-1",
                "class-1",
                1,
                "Round one",
                RotationRoundState.ACTIVE,
                ("pair-1",),
                (),
            )
        )
        reopened = LessonApplicationService(
            lesson_store=LessonSQLiteStore(self.db_path, fen_validator=self.validator),
            template_store=LessonTemplateSQLiteStore(self.db_path),
            session_store=LessonSessionSQLiteStore(self.db_path, fen_validator=self.validator),
            fen_validator=self.validator,
        )
        recovery = reopened.recover_classroom("class-1")
        self.assertEqual(("pair-1",), tuple(item.pairing_id for item in recovery.pairings))
        self.assertEqual(("round-1",), tuple(item.round_id for item in recovery.rotations))

    def test_invalid_fen_fails_at_application_boundary_before_storage(self):
        self.service.save_new_template(self.template(), level="beginner")
        position = LessonPosition("pos-1", "Bad", "not-a-fen")
        plan = self.service.materialize_template(
            "custom-one",
            lesson_id="lesson-1",
            title="Lesson one",
            positions=(position,),
            position_bindings={"position": "pos-1"},
        )
        with self.assertRaisesRegex(ValueError, "Core rejected FEN"):
            self.service.save_new_plan(plan)
        with self.assertRaisesRegex(Exception, "unknown lesson"):
            self.service.load_plan("lesson-1")

    def test_default_preset_seed_is_idempotent(self):
        first = self.service.ensure_default_templates()
        second = self.service.ensure_default_templates()
        self.assertEqual(first, second)
        self.assertEqual(3, len(first))
        preset, revision = self.service.load_template("preschool")
        self.assertTrue(preset.is_preset)
        self.assertEqual("beginner", preset.level)
        self.assertEqual(1, revision.revision)


if __name__ == "__main__":
    unittest.main()
