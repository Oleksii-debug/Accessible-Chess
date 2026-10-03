from __future__ import annotations

"""Student-safe composition of named prepared positions and deployment batches.

This module is intentionally a convergence adapter only.  D10
EducationWorkspace/PreparedPosition remains the durable named-position
authority and classroom_prepared_position_deployment remains assignment,
targeting, reconnect, and revision authority.  The adapter exposes only the
student-visible title/prompt plus the already-canonical TeachingPositionSource;
teacher-only notes, authoring tags, and lesson ordering never enter this
surface.
"""

from dataclasses import dataclass

from .classroom_prepared_position_deployment import (
    PreparedPositionDeploymentBatch,
    PreparedPositionDeploymentError,
    assert_prepared_position_deployment_scope,
)
from .education_workspace import (
    EducationWorkspace,
    EducationWorkspaceError,
    get_prepared_position,
)
from .teaching_session import LessonSession, TeachingPositionSource


class PreparedPositionStudentViewError(ValueError):
    """Stable failure for stale or malformed student prepared-position views."""


@dataclass(frozen=True, slots=True)
class PreparedPositionStudentView:
    """One student-visible assignment resolved from canonical owner state."""

    assignment_id: str
    student_id: str
    position_id: str
    position_revision: int
    title: str
    student_prompt: str
    source: TeachingPositionSource

    def __post_init__(self) -> None:
        for label, value in (
            ("assignment_id", self.assignment_id),
            ("student_id", self.student_id),
            ("position_id", self.position_id),
            ("title", self.title),
            ("student_prompt", self.student_prompt),
        ):
            if type(value) is not str:
                raise TypeError(f"{label} must be exact text")
        if not self.assignment_id or not self.student_id or not self.position_id:
            raise ValueError("student prepared-position identities must be non-empty")
        if not self.title:
            raise ValueError("student prepared-position title must be non-empty")
        if type(self.position_revision) is not int or self.position_revision < 0:
            raise TypeError("position_revision must be a non-negative exact integer")
        if type(self.source) is not TeachingPositionSource:
            raise TypeError("source must be canonical TeachingPositionSource")


def resolve_prepared_position_student_view(
    batch: PreparedPositionDeploymentBatch,
    assignment_id: str,
    lesson_session: LessonSession,
    workspace: EducationWorkspace,
) -> PreparedPositionStudentView:
    """Resolve one assignment only after validating the complete live batch.

    Whole-batch scope validation is intentionally performed before assignment
    lookup.  A changed lesson, student scope, or any missing/revised prepared
    position therefore invalidates the batch atomically rather than allowing a
    stale subset to continue.
    """

    if type(assignment_id) is not str:
        raise PreparedPositionStudentViewError(
            "prepared-position assignment id must be exact text"
        )
    try:
        assert_prepared_position_deployment_scope(
            batch,
            lesson_session,
            workspace,
        )
    except PreparedPositionDeploymentError as exc:
        raise PreparedPositionStudentViewError(
            "prepared-position deployment is no longer valid"
        ) from exc

    matches = tuple(
        item
        for item in batch.assignments
        if item.assignment_id == assignment_id
    )
    if len(matches) != 1:
        raise PreparedPositionStudentViewError(
            "prepared-position assignment is unavailable"
        )
    assignment = matches[0]

    try:
        position = get_prepared_position(workspace, assignment.position_id)
    except EducationWorkspaceError as exc:
        raise PreparedPositionStudentViewError(
            "prepared position is unavailable"
        ) from exc
    if position.revision != assignment.position_revision:
        raise PreparedPositionStudentViewError(
            "prepared-position deployment is no longer valid"
        )

    return PreparedPositionStudentView(
        assignment_id=assignment.assignment_id,
        student_id=assignment.student_id,
        position_id=position.position_id,
        position_revision=position.revision,
        title=position.title,
        student_prompt=position.student_prompt,
        source=position.source,
    )


__all__ = [
    "PreparedPositionStudentView",
    "PreparedPositionStudentViewError",
    "resolve_prepared_position_student_view",
]
