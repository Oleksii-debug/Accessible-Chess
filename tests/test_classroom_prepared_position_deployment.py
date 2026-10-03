from __future__ import annotations

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from acs import classroom_prepared_position_deployment as dp
from acs.classroom_domain import (
    ClassroomClass,
    ClassroomSnapshot,
    Cohort,
    Course,
    Group,
    Lesson,
    Student,
)
from acs.education_workspace import (
    EducationWorkspace,
    get_prepared_position,
    save_prepared_position,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)


FEN_A = "8/8/8/8/8/8/4K3/7k w - -"
FEN_B = "8/8/8/8/8/3k4/8/4K3 w - -"
FEN_C = "8/8/8/8/3k4/8/8/4K3 b - -"
STAMP = "2026-10-02T20:00:00Z"


def _classroom() -> ClassroomSnapshot:
    return ClassroomSnapshot(
        students=(
            Student("s1", "Student 1"),
            Student("s2", "Student 2"),
            Student("s3", "Student 3"),
        ),
        classes=(
            ClassroomClass(
                "class-1",
                "Class",
                ("group-1", "group-2"),
            ),
        ),
        groups=(
            Group("group-1", "class-1", "Lesson group"),
            Group("group-2", "class-1", "Other course group"),
        ),
        courses=(
            Course("course-1", "Course", ("lesson-1",)),
            Course("course-2", "Other course", ()),
        ),
        cohorts=(
            Cohort("cohort-1", "course-1", ("s1", "s2"), "group-1"),
            Cohort("cohort-2", "course-2", ("s3",), "group-2"),
        ),
        lessons=(
            Lesson("lesson-1", "course-1", "Lesson", (), STAMP),
        ),
    )


def _lesson(*, step_id: str = "step-1") -> LessonSession:
    step = TeachingStep(
        step_id,
        TeachingActivity.TEACHER_EXPLAINS,
        "Explain the prepared position.",
        default_policy(TeachingActivity.TEACHER_EXPLAINS),
    )
    return LessonSession(
        "session-1",
        "lesson-1",
        TeachingPositionSource(PositionSourceKind.START),
        (step,),
        student_ids=("s1", "s2", "s3"),
    )


def _workspace() -> EducationWorkspace:
    workspace = EducationWorkspace.empty(_classroom())
    workspace = save_prepared_position(
        workspace,
        position_id="pos-a",
        source=TeachingPositionSource(PositionSourceKind.FEN, FEN_A),
        expected_position_revision=0,
    )
    workspace = save_prepared_position(
        workspace,
        position_id="pos-b",
        source=TeachingPositionSource(PositionSourceKind.FEN, FEN_B),
        expected_position_revision=0,
    )
    return workspace


def _all_mapping() -> dict[str, str]:
    return {"s1": "pos-a", "s2": "pos-b", "s3": "pos-a"}


class PreparedPositionDeploymentTests(unittest.TestCase):
    def test_all_target_is_deterministic_and_uses_stable_assignment_ids(self) -> None:
        lesson = _lesson()
        workspace = _workspace()
        kwargs = dict(
            batch_id="batch-1",
            position_by_student=_all_mapping(),
        )

        first = dp.plan_prepared_position_deployment(lesson, workspace, **kwargs)
        retry = dp.plan_prepared_position_deployment(lesson, workspace, **kwargs)

        self.assertEqual(first, retry)
        self.assertEqual(first.digest, retry.digest)
        self.assertEqual(first.target.kind, dp.DeploymentTargetKind.ALL)
        self.assertEqual(
            tuple(item.student_id for item in first.assignments),
            ("s1", "s2", "s3"),
        )
        self.assertEqual(
            tuple(item.assignment_id for item in first.assignments),
            tuple(item.assignment_id for item in retry.assignments),
        )
        self.assertEqual(len({item.assignment_id for item in first.assignments}), 3)
        dp.assert_prepared_position_deployment_retry(first, retry)

    def test_assignment_identity_framing_is_unambiguous_for_colon_ids(self) -> None:
        self.assertNotEqual(
            dp._assignment_id("a:b", "c"),
            dp._assignment_id("a", "b:c"),
        )
        self.assertEqual(
            dp._assignment_id("a:b", "c"),
            dp._assignment_id("a:b", "c"),
        )

    def test_resolve_assignment_returns_canonical_prepared_source_only(self) -> None:
        lesson = _lesson()
        workspace = _workspace()
        batch = dp.plan_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-source",
            position_by_student=_all_mapping(),
        )
        assignment = batch.assignments[0]

        source = dp.resolve_prepared_position_source(
            batch,
            assignment.assignment_id,
            lesson,
            workspace,
        )

        self.assertEqual(source, get_prepared_position(workspace, assignment.position_id).source)
        self.assertEqual(source.fen, TeachingPositionSource(PositionSourceKind.FEN, FEN_A).fen)
        self.assertFalse(hasattr(batch, "board"))
        self.assertFalse(hasattr(assignment, "fen"))

    def test_selected_target_requires_exact_mapping_and_preserves_requested_order(self) -> None:
        target = dp.DeploymentTarget(
            dp.DeploymentTargetKind.SELECTED,
            student_ids=("s3", "s1"),
        )
        batch = dp.plan_prepared_position_deployment(
            _lesson(),
            _workspace(),
            batch_id="batch-selected",
            target=target,
            position_by_student={"s3": "pos-b", "s1": "pos-a"},
        )

        self.assertEqual(
            tuple(item.student_id for item in batch.assignments),
            ("s3", "s1"),
        )

        with self.assertRaisesRegex(dp.PreparedPositionDeploymentError, "exactly cover"):
            dp.plan_prepared_position_deployment(
                _lesson(),
                _workspace(),
                batch_id="batch-selected-bad",
                target=target,
                position_by_student={"s3": "pos-b"},
            )

    def test_group_target_is_lesson_course_scoped(self) -> None:
        lesson = _lesson()
        workspace = _workspace()
        target = dp.DeploymentTarget(
            dp.DeploymentTargetKind.GROUP,
            group_id="group-1",
        )
        batch = dp.plan_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-group",
            target=target,
            position_by_student={"s1": "pos-a", "s2": "pos-b"},
        )
        self.assertEqual(
            tuple(item.student_id for item in batch.assignments),
            ("s1", "s2"),
        )

        other_course = dp.DeploymentTarget(
            dp.DeploymentTargetKind.GROUP,
            group_id="group-2",
        )
        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "outside lesson course",
        ):
            dp.plan_prepared_position_deployment(
                lesson,
                workspace,
                batch_id="batch-cross-course",
                target=other_course,
                position_by_student={"s3": "pos-a"},
            )

    def test_target_shapes_and_unknown_students_fail_closed(self) -> None:
        with self.assertRaises(dp.PreparedPositionDeploymentError):
            dp.DeploymentTarget(dp.DeploymentTargetKind.ALL, student_ids=("s1",))
        with self.assertRaises(dp.PreparedPositionDeploymentError):
            dp.DeploymentTarget(dp.DeploymentTargetKind.SELECTED)
        with self.assertRaises(dp.PreparedPositionDeploymentError):
            dp.DeploymentTarget(dp.DeploymentTargetKind.GROUP)
        with self.assertRaisesRegex(dp.PreparedPositionDeploymentError, "outside lesson session"):
            dp.plan_prepared_position_deployment(
                _lesson(),
                _workspace(),
                batch_id="batch-outsider",
                target=dp.DeploymentTarget(
                    dp.DeploymentTargetKind.SELECTED,
                    student_ids=("outsider",),
                ),
                position_by_student={"outsider": "pos-a"},
            )


    def test_uniform_all_target_deploys_one_position_without_manual_mapping(self) -> None:
        batch = dp.plan_uniform_prepared_position_deployment(
            _lesson(),
            _workspace(),
            batch_id="batch-uniform-all",
            position_id="pos-a",
        )

        self.assertEqual(batch.target.kind, dp.DeploymentTargetKind.ALL)
        self.assertEqual(
            tuple(item.student_id for item in batch.assignments),
            ("s1", "s2", "s3"),
        )
        self.assertEqual(
            {item.position_id for item in batch.assignments},
            {"pos-a"},
        )
        self.assertEqual(
            {item.position_revision for item in batch.assignments},
            {0},
        )

    def test_uniform_group_and_one_student_targets_reuse_same_batch_contract(self) -> None:
        lesson = _lesson()
        workspace = _workspace()

        group = dp.plan_uniform_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-uniform-group",
            position_id="pos-b",
            target=dp.DeploymentTarget(
                dp.DeploymentTargetKind.GROUP,
                group_id="group-1",
            ),
        )
        self.assertEqual(
            tuple(item.student_id for item in group.assignments),
            ("s1", "s2"),
        )
        self.assertEqual(
            {item.position_id for item in group.assignments},
            {"pos-b"},
        )

        one = dp.plan_uniform_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-uniform-one",
            position_id="pos-a",
            target=dp.DeploymentTarget(
                dp.DeploymentTargetKind.SELECTED,
                student_ids=("s3",),
            ),
        )
        self.assertEqual(len(one.assignments), 1)
        self.assertEqual(one.assignments[0].student_id, "s3")
        self.assertEqual(one.assignments[0].position_id, "pos-a")

        retry = dp.plan_uniform_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-uniform-one",
            position_id="pos-a",
            target=dp.DeploymentTarget(
                dp.DeploymentTargetKind.SELECTED,
                student_ids=("s3",),
            ),
        )
        dp.assert_prepared_position_deployment_retry(one, retry)

    def test_uniform_deployment_unknown_position_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "unknown prepared position",
        ):
            dp.plan_uniform_prepared_position_deployment(
                _lesson(),
                _workspace(),
                batch_id="batch-uniform-missing",
                position_id="missing",
            )


    def test_unknown_prepared_position_fails_before_batch_publication(self) -> None:
        mapping = _all_mapping()
        mapping["s2"] = "missing"
        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "unknown prepared position",
        ):
            dp.plan_prepared_position_deployment(
                _lesson(),
                _workspace(),
                batch_id="batch-missing",
                position_by_student=mapping,
            )

    def test_retry_rejects_same_batch_id_with_changed_semantics(self) -> None:
        lesson = _lesson()
        workspace = _workspace()
        first = dp.plan_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-retry",
            position_by_student=_all_mapping(),
        )
        changed_mapping = _all_mapping()
        changed_mapping["s1"] = "pos-b"
        changed = dp.plan_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-retry",
            position_by_student=changed_mapping,
        )
        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "reused with changed payload",
        ):
            dp.assert_prepared_position_deployment_retry(first, changed)

    def test_selected_wire_batch_rejects_assignment_scope_mismatch_before_live_lookup(self) -> None:
        lesson = _lesson()
        workspace = _workspace()
        batch = dp.plan_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-selected-wire",
            target=dp.DeploymentTarget(
                dp.DeploymentTargetKind.SELECTED,
                student_ids=("s1", "s2"),
            ),
            position_by_student={"s1": "pos-a", "s2": "pos-b"},
        )
        record = batch.to_record()
        first, second = record["assignments"]
        record["assignments"] = [
            {**first, "student_id": "s2", "assignment_id": dp._assignment_id(batch.batch_id, "s2")},
            {**second, "student_id": "s1", "assignment_id": dp._assignment_id(batch.batch_id, "s1")},
        ]
        body = {key: value for key, value in record.items() if key != "digest"}
        record["digest"] = dp._digest(body)

        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "exactly match target student order",
        ):
            dp.PreparedPositionDeploymentBatch.from_record(record)

    def test_selected_constructor_rejects_assignment_for_student_outside_target(self) -> None:
        target = dp.DeploymentTarget(
            dp.DeploymentTargetKind.SELECTED,
            student_ids=("s1",),
        )
        assignment = dp.PreparedPositionAssignment(
            assignment_id=dp._assignment_id("batch-local-scope", "s2"),
            student_id="s2",
            position_id="pos-a",
            position_revision=0,
        )
        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "exactly match target student order",
        ):
            dp.PreparedPositionDeploymentBatch(
                batch_id="batch-local-scope",
                lesson_session_id="session-1",
                lesson_session_digest="0" * 64,
                target=target,
                assignments=(assignment,),
            )

    def test_reconnect_rejects_changed_lesson_digest(self) -> None:
        lesson = _lesson()
        workspace = _workspace()
        batch = dp.plan_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-lesson-drift",
            position_by_student=_all_mapping(),
        )
        changed_lesson = _lesson(step_id="step-changed")

        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "does not match lesson session",
        ):
            dp.assert_prepared_position_deployment_scope(
                batch,
                changed_lesson,
                workspace,
            )

    def test_reconnect_rejects_revised_prepared_position(self) -> None:
        lesson = _lesson()
        workspace = _workspace()
        batch = dp.plan_prepared_position_deployment(
            lesson,
            workspace,
            batch_id="batch-stale-position",
            position_by_student=_all_mapping(),
        )

        updated = save_prepared_position(
            workspace,
            position_id="pos-a",
            source=TeachingPositionSource(PositionSourceKind.FEN, FEN_C),
            expected_position_revision=0,
        )
        self.assertEqual(get_prepared_position(updated, "pos-a").revision, 1)

        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "revision is stale",
        ):
            dp.assert_prepared_position_deployment_scope(
                batch,
                lesson,
                updated,
            )

    def test_assignment_identity_cannot_be_forged(self) -> None:
        batch = dp.plan_prepared_position_deployment(
            _lesson(),
            _workspace(),
            batch_id="batch-identity",
            position_by_student=_all_mapping(),
        )
        forged = replace(batch.assignments[0], assignment_id="deploy-forged")
        with self.assertRaisesRegex(
            dp.PreparedPositionDeploymentError,
            "not stable",
        ):
            replace(batch, assignments=(forged,) + batch.assignments[1:])

    def test_json_round_trip_is_canonical_tamper_evident_and_closed_world(self) -> None:
        batch = dp.plan_prepared_position_deployment(
            _lesson(),
            _workspace(),
            batch_id="batch-json",
            position_by_student=_all_mapping(),
        )
        text = batch.to_json()
        restored = dp.PreparedPositionDeploymentBatch.from_json(text)

        self.assertEqual(restored, batch)
        self.assertEqual(restored.to_json(), text)
        self.assertEqual(restored.digest, batch.digest)

        record = batch.to_record()
        record["lesson_session_id"] = "other-session"
        with self.assertRaisesRegex(dp.PreparedPositionDeploymentError, "digest mismatch"):
            dp.PreparedPositionDeploymentBatch.from_record(record)

        record = batch.to_record()
        record["future"] = True
        with self.assertRaisesRegex(dp.PreparedPositionDeploymentError, "schema mismatch"):
            dp.PreparedPositionDeploymentBatch.from_record(record)

        duplicate = text[:-1] + ',"digest":"' + batch.digest + '"}'
        with self.assertRaisesRegex(dp.PreparedPositionDeploymentError, "duplicate"):
            dp.PreparedPositionDeploymentBatch.from_json(duplicate)

    def test_hostile_json_is_collapsed_to_domain_errors(self) -> None:
        batch = dp.plan_prepared_position_deployment(
            _lesson(),
            _workspace(),
            batch_id="batch-hostile",
            position_by_student=_all_mapping(),
        )
        text = batch.to_json()

        surrogate = text.replace(
            '"batch_id":"batch-hostile"',
            '"batch_id":"\\ud800"',
        )
        with self.assertRaises(dp.PreparedPositionDeploymentError):
            dp.PreparedPositionDeploymentBatch.from_json(surrogate)

        huge_integer = text.replace(
            '"version":1',
            '"version":9007199254740992',
        )
        with self.assertRaises(dp.PreparedPositionDeploymentError):
            dp.PreparedPositionDeploymentBatch.from_json(huge_integer)

        nonfinite = text.replace('"version":1', '"version":NaN')
        with self.assertRaises(dp.PreparedPositionDeploymentError):
            dp.PreparedPositionDeploymentBatch.from_json(nonfinite)

    def test_record_bounds_fail_before_digest_materialization(self) -> None:
        batch = dp.plan_prepared_position_deployment(
            _lesson(),
            _workspace(),
            batch_id="batch-record-bounds",
            position_by_student=_all_mapping(),
        )

        oversized_assignments = batch.to_record()
        oversized_assignments["assignments"] = [
            oversized_assignments["assignments"][0]
        ] * (dp.MAX_DEPLOYMENT_ASSIGNMENTS + 1)
        with patch.object(
            dp,
            "_digest",
            side_effect=AssertionError("digest must not run before assignment bound"),
        ) as digest:
            with self.assertRaisesRegex(
                dp.PreparedPositionDeploymentError,
                "bounded non-empty JSON array",
            ):
                dp.PreparedPositionDeploymentBatch.from_record(
                    oversized_assignments
                )
            digest.assert_not_called()

        oversized_target = batch.to_record()
        oversized_target["target"]["student_ids"] = ["s1"] * (
            dp.MAX_DEPLOYMENT_ASSIGNMENTS + 1
        )
        with patch.object(
            dp,
            "_digest",
            side_effect=AssertionError("digest must not run before target bound"),
        ) as digest:
            with self.assertRaisesRegex(
                dp.PreparedPositionDeploymentError,
                "bounded JSON array",
            ):
                dp.PreparedPositionDeploymentBatch.from_record(oversized_target)
            digest.assert_not_called()

    def test_wire_byte_limit_runs_before_json_parse_without_encode_copy(self) -> None:
        with (
            patch.object(dp, "MAX_DEPLOYMENT_JSON_BYTES", 10),
            patch.object(
                dp.json,
                "loads",
                side_effect=AssertionError("JSON parser must not run after byte overflow"),
            ) as loads,
        ):
            with self.assertRaisesRegex(
                dp.PreparedPositionDeploymentError,
                "size limit",
            ):
                dp.PreparedPositionDeploymentBatch.from_json('"éééééé"')
            loads.assert_not_called()

        with patch.object(
            dp.json,
            "loads",
            side_effect=AssertionError("JSON parser must not receive invalid Unicode"),
        ) as loads:
            with self.assertRaisesRegex(
                dp.PreparedPositionDeploymentError,
                "invalid Unicode",
            ):
                dp.PreparedPositionDeploymentBatch.from_json("\ud800")
            loads.assert_not_called()

    def test_resource_bounds_apply_to_wire_payload(self) -> None:
        batch = dp.plan_prepared_position_deployment(
            _lesson(),
            _workspace(),
            batch_id="batch-bounds",
            position_by_student=_all_mapping(),
        )
        with patch.object(dp, "MAX_DEPLOYMENT_JSON_BYTES", 10):
            with self.assertRaisesRegex(dp.PreparedPositionDeploymentError, "size limit"):
                batch.to_json()
            with self.assertRaisesRegex(dp.PreparedPositionDeploymentError, "size limit"):
                dp.PreparedPositionDeploymentBatch.from_json("x" * 11)


if __name__ == "__main__":
    unittest.main()
