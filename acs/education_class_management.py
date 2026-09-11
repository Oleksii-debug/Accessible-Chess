from __future__ import annotations

"""Trusted class-creation composition over the canonical D10 workspace.

This module owns no second Classroom model or persistence store.  It creates one
``ClassroomClass`` inside the existing ``ClassroomSnapshot`` and delegates the
history re-anchor to :func:`education_workspace.commit_classroom`.
"""

from dataclasses import replace

from . import classroom_domain as cd
from .education_workspace import EducationWorkspace, EducationWorkspaceError, commit_classroom


def create_class(
    workspace: EducationWorkspace,
    *,
    class_id: str,
    title: str,
    operation_id: str,
) -> EducationWorkspace:
    """Return a workspace containing one newly-created class.

    ``class_id`` and ``operation_id`` are trusted-host inputs.  Browser content is
    deliberately limited to presentation intent; the final-product application
    generates both identifiers before calling this function.
    """

    if type(workspace) is not EducationWorkspace:
        raise EducationWorkspaceError("class creation requires EducationWorkspace")
    if type(class_id) is not str or type(operation_id) is not str:
        raise EducationWorkspaceError("class creation identities must be text")
    if type(title) is not str:
        raise EducationWorkspaceError("class title must be text")

    canonical_title = title.strip()
    if not canonical_title:
        raise EducationWorkspaceError("class title must not be empty")

    try:
        new_class = cd.ClassroomClass(class_id=class_id, title=canonical_title)
        classroom = replace(
            workspace.classroom,
            classes=(*workspace.classroom.classes, new_class),
        )
    except cd.ClassroomDomainError as exc:
        raise EducationWorkspaceError("class creation rejected") from exc

    return commit_classroom(
        workspace,
        classroom,
        operation_id=operation_id,
        expected_ledger_revision=workspace.ledger.revision,
    )


__all__ = ["create_class"]
