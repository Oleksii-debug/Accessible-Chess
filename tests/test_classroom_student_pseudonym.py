from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from acs import classroom_domain as cd
from acs.classroom_student_pseudonym import (
    ClassroomStudentPseudonymError,
    MAX_STUDENT_PSEUDONYM_CHARS,
    MAX_WIRE_INTEGER,
    normalize_student_pseudonym,
    rename_student_pseudonym,
)
from acs.education_workspace import EducationWorkspace
from acs.education_workspace_store import EducationWorkspaceStore


STAMP = "2026-10-03T06:00:00Z"


def student(
    student_id: str = "student-1",
    pseudonym: str = "Knight-17",
    *,
    consent: cd.ConsentState = cd.ConsentState.GRANTED,
    deleted: bool = False,
    revision: int = 0,
) -> cd.Student:
    return cd.Student(
        student_id=student_id,
        pseudonym=pseudonym,
        consent=consent,
        deleted=deleted,
        revision=revision,
    )


def workspace_with(
    first: cd.Student | None = None,
    second: cd.Student | None = None,
) -> EducationWorkspace:
    first = first or student()
    second = second or student(
        "student-2",
        "Bishop-9",
        consent=cd.ConsentState.GRANTED,
    )
    notes = (
        (
            cd.TeacherNote(
                "note-1",
                first.student_id,
                "Private coaching note",
                STAMP,
            ),
        )
        if not first.deleted and first.consent is cd.ConsentState.GRANTED
        else ()
    )
    classroom = cd.ClassroomSnapshot(
        students=(first, second),
        teacher_notes=notes,
    )
    return EducationWorkspace.empty(classroom)


def find_student(workspace: EducationWorkspace, student_id: str) -> cd.Student:
    return next(
        item for item in workspace.classroom.students
        if item.student_id == student_id
    )


class ClassroomStudentPseudonymTests(unittest.TestCase):
    def test_consent_gated_rename_normalizes_visible_text_and_preserves_identity(self) -> None:
        before = workspace_with()
        original_second = find_student(before, "student-2")
        original_notes = before.classroom.teacher_notes

        after = rename_student_pseudonym(
            before,
            student_id="student-1",
            pseudonym="  Alice   Knight  ",
            operation_id="rename-1",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )

        renamed = find_student(after, "student-1")
        self.assertEqual(renamed.student_id, "student-1")
        self.assertEqual(renamed.pseudonym, "Alice Knight")
        self.assertEqual(renamed.revision, 1)
        self.assertIs(renamed.consent, cd.ConsentState.GRANTED)
        self.assertFalse(renamed.deleted)
        self.assertEqual(find_student(after, "student-2"), original_second)
        self.assertEqual(after.classroom.teacher_notes, original_notes)
        self.assertEqual(after.ledger.revision, 1)
        self.assertEqual(after.ledger.classroom_digest, after.classroom.digest)
        self.assertEqual(len(after.ledger.operation_receipts), 1)
        self.assertEqual(
            after.ledger.operation_receipts[0].operation_id,
            "rename-1",
        )
        self.assertEqual(
            after.ledger.operation_receipts[0].operation_kind,
            "reconcile_classroom",
        )
        self.assertEqual(find_student(before, "student-1").pseudonym, "Knight-17")

    def test_publish_requires_explicit_granted_consent(self) -> None:
        for consent in (
            cd.ConsentState.NOT_COLLECTED,
            cd.ConsentState.WITHDRAWN,
        ):
            with self.subTest(consent=consent):
                before = workspace_with(
                    student(consent=consent),
                )
                with self.assertRaisesRegex(
                    ClassroomStudentPseudonymError,
                    "requires explicit consent",
                ):
                    rename_student_pseudonym(
                        before,
                        student_id="student-1",
                        pseudonym="Visible Name",
                        operation_id="rename-no-consent",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )
                self.assertEqual(before.ledger.revision, 0)
                self.assertEqual(
                    find_student(before, "student-1").pseudonym,
                    "Knight-17",
                )

    def test_deleted_student_cannot_be_revived_through_pseudonym_mutation(self) -> None:
        deleted = student(
            pseudonym="",
            consent=cd.ConsentState.WITHDRAWN,
            deleted=True,
            revision=7,
        )
        before = workspace_with(deleted)
        with self.assertRaisesRegex(
            ClassroomStudentPseudonymError,
            "deleted student pseudonym cannot be changed",
        ):
            rename_student_pseudonym(
                before,
                student_id="student-1",
                pseudonym="Revived",
                operation_id="rename-deleted",
                expected_student_revision=7,
                expected_ledger_revision=0,
            )
        current = find_student(before, "student-1")
        self.assertTrue(current.deleted)
        self.assertEqual(current.pseudonym, "")

    def test_stale_student_revision_rejects_changed_visible_state(self) -> None:
        before = workspace_with(student(revision=4))
        with self.assertRaisesRegex(
            ClassroomStudentPseudonymError,
            "stale student revision",
        ):
            rename_student_pseudonym(
                before,
                student_id="student-1",
                pseudonym="New Name",
                operation_id="rename-stale-student",
                expected_student_revision=3,
                expected_ledger_revision=0,
            )
        self.assertEqual(before.ledger.revision, 0)

    def test_stale_ledger_revision_rejects_publication_without_mutating_input(self) -> None:
        before = workspace_with()
        with self.assertRaisesRegex(
            ClassroomStudentPseudonymError,
            "publication was rejected",
        ):
            rename_student_pseudonym(
                before,
                student_id="student-1",
                pseudonym="New Name",
                operation_id="rename-stale-ledger",
                expected_student_revision=0,
                expected_ledger_revision=1,
            )
        self.assertEqual(find_student(before, "student-1").pseudonym, "Knight-17")
        self.assertEqual(before.ledger.revision, 0)

    def test_exact_retry_after_success_uses_durable_receipt_despite_old_revisions(self) -> None:
        before = workspace_with()
        after = rename_student_pseudonym(
            before,
            student_id="student-1",
            pseudonym="Alice Knight",
            operation_id="rename-retry",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )

        retried = rename_student_pseudonym(
            after,
            student_id="student-1",
            pseudonym="Alice Knight",
            operation_id="rename-retry",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )

        self.assertIs(retried, after)
        self.assertEqual(find_student(retried, "student-1").revision, 1)
        self.assertEqual(retried.ledger.revision, 1)
        self.assertEqual(len(retried.ledger.operation_receipts), 1)

    def test_same_desired_state_with_new_operation_still_uses_ledger_cas(self) -> None:
        before = workspace_with()
        with self.assertRaisesRegex(
            ClassroomStudentPseudonymError,
            "publication was rejected",
        ):
            rename_student_pseudonym(
                before,
                student_id="student-1",
                pseudonym="Knight-17",
                operation_id="new-noop-operation",
                expected_student_revision=99,
                expected_ledger_revision=1,
            )
        self.assertEqual(before.ledger.revision, 0)

    def test_revision_exhaustion_fails_before_building_invalid_student(self) -> None:
        before = workspace_with(student(revision=MAX_WIRE_INTEGER))
        with self.assertRaisesRegex(
            ClassroomStudentPseudonymError,
            "revision is exhausted",
        ):
            rename_student_pseudonym(
                before,
                student_id="student-1",
                pseudonym="Next Name",
                operation_id="rename-exhausted",
                expected_student_revision=MAX_WIRE_INTEGER,
                expected_ledger_revision=0,
            )
        self.assertEqual(
            find_student(before, "student-1").revision,
            MAX_WIRE_INTEGER,
        )

    def test_visible_pseudonym_boundary_rejects_controls_blank_surrogates_and_oversize(self) -> None:
        invalid = (
            "",
            "   ",
            "Alice\nKnight",
            "Alice\tKnight",
            "Alice\x00Knight",
            "Alice\x7fKnight",
            "Alice\ud800Knight",
            "X" * (MAX_STUDENT_PSEUDONYM_CHARS + 1),
        )
        for value in invalid:
            with self.subTest(value=repr(value)[:50]):
                with self.assertRaises(ClassroomStudentPseudonymError):
                    normalize_student_pseudonym(value)
        with self.assertRaisesRegex(
            ClassroomStudentPseudonymError,
            "must be text",
        ):
            normalize_student_pseudonym(123)

    def test_normalization_collapses_safe_whitespace_without_changing_unicode_text(self) -> None:
        self.assertEqual(
            normalize_student_pseudonym("  Олексій\u00a0  Knight  "),
            "Олексій Knight",
        )

    def test_unknown_or_non_text_student_identity_fails_without_fallback(self) -> None:
        before = workspace_with()
        for value in ("missing-student", 123):
            with self.subTest(value=value):
                with self.assertRaises(ClassroomStudentPseudonymError):
                    rename_student_pseudonym(
                        before,
                        student_id=value,
                        pseudonym="Visible Name",
                        operation_id="rename-missing",
                        expected_student_revision=0,
                        expected_ledger_revision=0,
                    )

    def test_durable_store_cas_reopens_renamed_pseudonym_and_anchored_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "education-workspace.json"
            store = EducationWorkspaceStore(path)
            before = workspace_with()
            first_revision = store.save(before, expected_revision=None)

            after = rename_student_pseudonym(
                before,
                student_id="student-1",
                pseudonym="Durable Name",
                operation_id="rename-durable",
                expected_student_revision=0,
                expected_ledger_revision=0,
            )
            second_revision = store.save(
                after,
                expected_revision=first_revision,
            )
            self.assertNotEqual(first_revision, second_revision)

            reopened = EducationWorkspaceStore(path).load()
            self.assertIsNotNone(reopened)
            self.assertEqual(reopened.revision, second_revision)
            restored = reopened.workspace
            self.assertEqual(
                find_student(restored, "student-1").pseudonym,
                "Durable Name",
            )
            self.assertEqual(find_student(restored, "student-1").student_id, "student-1")
            self.assertEqual(find_student(restored, "student-1").revision, 1)
            self.assertEqual(
                restored.ledger.classroom_digest,
                restored.classroom.digest,
            )
            self.assertEqual(restored.ledger.revision, 1)

    def test_source_boundary_has_no_profile_or_provider_identity_authority(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "acs"
            / "classroom_student_pseudonym.py"
        ).read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertNotIn("profile_id", lowered)
        self.assertNotIn("local_profile", lowered)
        self.assertNotIn("livekit", lowered)
        self.assertNotIn("jwt", lowered)
        self.assertNotIn("token", lowered)


if __name__ == "__main__":
    unittest.main()
