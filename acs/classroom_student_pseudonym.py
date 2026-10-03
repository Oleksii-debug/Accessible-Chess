from __future__ import annotations

"""Privacy-safe mutation boundary for classroom-visible student pseudonyms.

Student identity, consent, revision and persistence remain owned by the existing
Classroom/D10 authorities. This module changes only the visible pseudonym of an
existing active student and delegates atomic history anchoring to
education_workspace.commit_classroom().
"""

from dataclasses import replace

from . import classroom_domain as cd
from .education_workspace import (
    EducationWorkspace,
    EducationWorkspaceError,
    commit_classroom,
)


MAX_STUDENT_PSEUDONYM_CHARS = 80
MAX_WIRE_INTEGER = (1 << 53) - 1


class ClassroomStudentPseudonymError(ValueError):
    """Raised when a classroom-visible pseudonym mutation is unsafe or stale."""


def rename_student_pseudonym(
    workspace: EducationWorkspace,
    *,
    student_id: str,
    pseudonym: str,
    operation_id: str,
    expected_student_revision: int,
    expected_ledger_revision: int,
) -> EducationWorkspace:
    """Rename one existing classroom student without changing stable identity.

    Publishing a human-visible classroom label is permitted only after explicit
    student consent. Local profile identity and provider participant identity
    are intentionally absent from this boundary.
    """

    if type(workspace) is not EducationWorkspace:
        raise TypeError("workspace must be EducationWorkspace")
    student = _student(workspace, student_id)
    expected_student_revision = _revision(
        expected_student_revision,
        "expected student revision",
    )
    _revision(expected_ledger_revision, "expected education ledger revision")
    if student.deleted:
        raise ClassroomStudentPseudonymError(
            "deleted student pseudonym cannot be changed"
        )
    if student.consent is not cd.ConsentState.GRANTED:
        raise ClassroomStudentPseudonymError(
            "classroom pseudonym publication requires explicit consent"
        )

    normalized = normalize_student_pseudonym(pseudonym)
    # Match the existing D10 desired-state retry contract used by consent:
    # once the exact desired visible state is already current, let the durable
    # operation receipt/CAS decide whether this is an idempotent retry.  Do not
    # reject only because the successful prior mutation advanced Student.revision.
    if normalized == student.pseudonym:
        try:
            return commit_classroom(
                workspace,
                workspace.classroom,
                operation_id=operation_id,
                expected_ledger_revision=expected_ledger_revision,
            )
        except EducationWorkspaceError as exc:
            raise ClassroomStudentPseudonymError(
                "student pseudonym publication was rejected"
            ) from exc

    if student.revision != expected_student_revision:
        raise ClassroomStudentPseudonymError("stale student revision")
    if student.revision >= MAX_WIRE_INTEGER:
        raise ClassroomStudentPseudonymError("student revision is exhausted")

    updated = replace(
        student,
        pseudonym=normalized,
        revision=student.revision + 1,
    )
    classroom = replace(
        workspace.classroom,
        students=tuple(
            updated if item.student_id == student.student_id else item
            for item in workspace.classroom.students
        ),
    )
    try:
        return commit_classroom(
            workspace,
            classroom,
            operation_id=operation_id,
            expected_ledger_revision=expected_ledger_revision,
        )
    except (cd.ClassroomDomainError, EducationWorkspaceError) as exc:
        raise ClassroomStudentPseudonymError(
            "student pseudonym publication was rejected"
        ) from exc


def normalize_student_pseudonym(value: object) -> str:
    """Return canonical accessible display text without deriving any identity."""

    if type(value) is not str:
        raise ClassroomStudentPseudonymError("student pseudonym must be text")
    if any(
        ord(character) < 32
        or ord(character) == 127
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in value
    ):
        raise ClassroomStudentPseudonymError(
            "student pseudonym contains invalid control text"
        )
    normalized = " ".join(value.split())
    if not normalized:
        raise ClassroomStudentPseudonymError(
            "student pseudonym must not be blank"
        )
    if len(normalized) > MAX_STUDENT_PSEUDONYM_CHARS:
        raise ClassroomStudentPseudonymError("student pseudonym is too long")
    return normalized


def _student(workspace: EducationWorkspace, student_id: object) -> cd.Student:
    if type(student_id) is not str:
        raise ClassroomStudentPseudonymError("student id must be exact text")
    matches = tuple(
        student
        for student in workspace.classroom.students
        if student.student_id == student_id
    )
    if len(matches) != 1:
        raise ClassroomStudentPseudonymError("unknown or ambiguous student")
    return matches[0]


def _revision(value: object, label: str) -> int:
    if (
        type(value) is not int
        or not 0 <= value <= MAX_WIRE_INTEGER
    ):
        raise ClassroomStudentPseudonymError(
            f"{label} must be a bounded non-negative integer"
        )
    return value


__all__ = [
    "ClassroomStudentPseudonymError",
    "MAX_STUDENT_PSEUDONYM_CHARS",
    "normalize_student_pseudonym",
    "rename_student_pseudonym",
]
