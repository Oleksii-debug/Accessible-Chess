from __future__ import annotations

"""D10 lifecycle composition for Classroom deletion and review-progress privacy.

``StudentProgressStore`` is intentionally a separate authority for review metrics,
not a second course-progress model.  That separation means an explicit student
deletion must coordinate the Classroom tombstone with the review ledger instead
of leaving personally bound review records behind.

This module is domain composition only.  It does not publish either store to
disk; a durable composition layer must publish the returned values under its
own crash/rollback contract.
"""

from dataclasses import dataclass

from . import education_workspace as ew
from .student_progress import StudentProgressLedger


REVIEW_PROGRESS_DELETE_POLICY = "purge-on-explicit-student-delete-v1"


@dataclass(frozen=True, slots=True)
class StudentDeletionWithProgress:
    """Result of one validated student-deletion privacy transition."""

    workspace: ew.EducationWorkspace
    progress: StudentProgressLedger
    purged_record_count: int

    def __post_init__(self) -> None:
        if type(self.workspace) is not ew.EducationWorkspace:
            raise TypeError("workspace must be EducationWorkspace")
        if type(self.progress) is not StudentProgressLedger:
            raise TypeError("progress must be StudentProgressLedger")
        if type(self.purged_record_count) is not int or self.purged_record_count < 0:
            raise ValueError("purged_record_count must be a non-negative integer")


def _purge_student_reviews(
    progress: StudentProgressLedger,
    *,
    student_id: str,
) -> tuple[StudentProgressLedger, int]:
    """Return a rebuilt ledger with every review owned by ``student_id`` removed.

    Rebuilding through ``StudentProgressLedger.restore`` also rebuilds the
    record-id and per-session sequence indexes from the surviving canonical
    records.  The input ledger is never mutated.
    """

    if type(progress) is not StudentProgressLedger:
        raise TypeError("progress must be StudentProgressLedger")

    snapshot = progress.snapshot()
    records = snapshot["records"]
    if not isinstance(records, list):
        raise ValueError("student progress snapshot records are invalid")

    kept: list[object] = []
    purged = 0
    for raw_record in records:
        if not isinstance(raw_record, dict):
            # The canonical snapshot producer emits dictionaries.  Fail closed
            # rather than attempting to reinterpret a corrupted in-memory value.
            raise ValueError("student progress snapshot record is invalid")
        if raw_record.get("student_id") == student_id:
            purged += 1
        else:
            kept.append(raw_record)

    rebuilt = StudentProgressLedger.restore(
        {
            "schema_version": snapshot["schema_version"],
            "records": kept,
        }
    )
    return rebuilt, purged


def delete_student_and_purge_reviews(
    workspace: ew.EducationWorkspace,
    progress: StudentProgressLedger,
    *,
    student_id: str,
    operation_id: str,
    expected_student_revision: int,
    expected_ledger_revision: int,
) -> StudentDeletionWithProgress:
    """Apply the explicit D10 delete policy to Classroom and review metrics.

    The canonical Classroom deletion runs first.  If it rejects the request,
    the input review ledger is untouched.  Only after that transition succeeds
    do we build a new review ledger with every record carrying the deleted
    ``student_id`` removed.  Unrelated records retain their exact serialized
    values and order.

    This function deliberately returns new domain values instead of writing
    either durable store.  It therefore cannot overclaim cross-file crash
    atomicity; the final durable composition owner must publish both returned
    values under one explicit recovery/rollback protocol.
    """

    if type(progress) is not StudentProgressLedger:
        raise TypeError("progress must be StudentProgressLedger")

    deleted_workspace = ew.delete_student(
        workspace,
        student_id=student_id,
        operation_id=operation_id,
        expected_student_revision=expected_student_revision,
        expected_ledger_revision=expected_ledger_revision,
    )
    purged_progress, purged_count = _purge_student_reviews(
        progress,
        student_id=student_id,
    )
    return StudentDeletionWithProgress(
        workspace=deleted_workspace,
        progress=purged_progress,
        purged_record_count=purged_count,
    )
