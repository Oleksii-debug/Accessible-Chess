from __future__ import annotations

import json
import unittest

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs.education_progress_lifecycle import (
    REVIEW_PROGRESS_DELETE_POLICY,
    delete_student_and_purge_reviews,
)
from acs.student_progress import StudentProgressLedger


class D10ReviewProgressDeletePrivacyTests(unittest.TestCase):
    @staticmethod
    def _workspace() -> ew.EducationWorkspace:
        classroom = cd.ClassroomSnapshot(
            students=(
                cd.Student("s1", "Knight-17", cd.ConsentState.GRANTED),
                cd.Student("s2", "Bishop-9"),
            )
        )
        return ew.EducationWorkspace.empty(classroom)

    @staticmethod
    def _progress() -> StudentProgressLedger:
        progress = StudentProgressLedger()
        progress.append_game_review(
            record_id="s1-review-a",
            student_id="s1",
            session_id="lesson-a",
            sequence=1,
            game_ref="game-a",
            source_revision="rev-a",
        )
        progress.append_game_review(
            record_id="s2-review",
            student_id="s2",
            session_id="lesson-a",
            sequence=1,
            game_ref="game-b",
            source_revision="rev-b",
        )
        progress.append_game_review(
            record_id="s1-review-b",
            student_id="s1",
            session_id="lesson-b",
            sequence=1,
            game_ref="game-c",
            source_revision="rev-c",
        )
        return progress

    def test_policy_is_explicit_purge_on_explicit_student_delete(self) -> None:
        self.assertEqual(
            REVIEW_PROGRESS_DELETE_POLICY,
            "purge-on-explicit-student-delete-v1",
        )

    def test_explicit_delete_purges_all_target_reviews_and_preserves_unrelated_records(self) -> None:
        workspace = self._workspace()
        progress = self._progress()
        before_workspace = workspace.to_json()
        before_progress = progress.snapshot()
        unrelated_before = tuple(
            record
            for record in before_progress["records"]
            if record["student_id"] == "s2"
        )

        result = delete_student_and_purge_reviews(
            workspace,
            progress,
            student_id="s1",
            operation_id="delete-s1",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )

        deleted = next(
            item for item in result.workspace.classroom.students if item.student_id == "s1"
        )
        self.assertTrue(deleted.deleted)
        self.assertEqual(deleted.pseudonym, "")
        self.assertEqual(result.purged_record_count, 2)

        remaining = result.progress.snapshot()["records"]
        self.assertEqual(
            tuple(record for record in remaining if record["student_id"] == "s2"),
            unrelated_before,
        )
        self.assertFalse(any(record["student_id"] == "s1" for record in remaining))
        self.assertNotIn('"student_id": "s1"', json.dumps(result.progress.snapshot(), sort_keys=True))
        self.assertEqual(result.progress.summary("s2", "lesson-a").record_count, 1)

        # Domain composition is functional: callers can publish or roll back both
        # returned values without hidden mutation of either input authority.
        self.assertEqual(workspace.to_json(), before_workspace)
        self.assertEqual(progress.snapshot(), before_progress)

    def test_failed_student_delete_cannot_partially_purge_review_progress(self) -> None:
        workspace = self._workspace()
        progress = self._progress()
        before_workspace = workspace.to_json()
        before_progress = progress.snapshot()

        with self.assertRaises(ew.EducationWorkspaceError):
            delete_student_and_purge_reviews(
                workspace,
                progress,
                student_id="s1",
                operation_id="stale-delete-s1",
                expected_student_revision=7,
                expected_ledger_revision=0,
            )

        self.assertEqual(workspace.to_json(), before_workspace)
        self.assertEqual(progress.snapshot(), before_progress)

    def test_delete_without_target_reviews_is_deterministic_and_does_not_touch_other_students(self) -> None:
        workspace = self._workspace()
        progress = StudentProgressLedger()
        progress.append_game_review(
            record_id="only-s2",
            student_id="s2",
            session_id="lesson-a",
            sequence=1,
            game_ref="game-b",
            source_revision="rev-b",
        )
        before = progress.snapshot()

        result = delete_student_and_purge_reviews(
            workspace,
            progress,
            student_id="s1",
            operation_id="delete-empty-s1",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )

        self.assertEqual(result.purged_record_count, 0)
        self.assertEqual(result.progress.snapshot(), before)
        self.assertIsNot(result.progress, progress)

    def test_invalid_progress_authority_fails_before_classroom_transition(self) -> None:
        workspace = self._workspace()
        before_workspace = workspace.to_json()
        with self.assertRaises(TypeError):
            delete_student_and_purge_reviews(
                workspace,
                object(),  # type: ignore[arg-type]
                student_id="s1",
                operation_id="bad-progress",
                expected_student_revision=0,
                expected_ledger_revision=0,
            )
        self.assertEqual(workspace.to_json(), before_workspace)


if __name__ == "__main__":
    unittest.main()
