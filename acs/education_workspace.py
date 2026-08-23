from __future__ import annotations

"""Atomic composition boundary for current Classroom state and D10 history.

``ClassroomSnapshot`` remains the authority for current educational state.
``EducationLedger`` remains the authority for immutable assignment-attempt and
remote-session checkpoint history. This module binds them into one validated
workspace so callers never have to publish two independently durable files and
risk a crash leaving their classroom digest/history anchor out of sync.

No chess state, Training evaluation, Library/ACSDB data, or live D09 Classroom
interaction state is owned here.
"""

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Mapping

from . import classroom_domain as cd
from . import education_records as er


EDUCATION_WORKSPACE_VERSION = 1
MAX_WORKSPACE_JSON_BYTES = cd.MAX_SNAPSHOT_BYTES + er.MAX_SNAPSHOT_BYTES + 256_000
MAX_WIRE_INTEGER = (1 << 53) - 1
_WORKSPACE_FIELDS = frozenset({"version", "classroom", "ledger", "digest"})


class EducationWorkspaceError(ValueError):
    """Raised for stale, corrupt, privacy-unsafe, or non-canonical workspaces."""


@dataclass(frozen=True)
class EducationWorkspace:
    """One canonical D10 persistence unit.

    The ledger must always be anchored to the exact current ClassroomSnapshot.
    ``EducationWorkspaceStore`` can therefore publish both authorities with one
    filesystem replace instead of a two-file best-effort sequence.
    """

    classroom: cd.ClassroomSnapshot
    ledger: er.EducationLedger
    version: int = EDUCATION_WORKSPACE_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != EDUCATION_WORKSPACE_VERSION:
            raise EducationWorkspaceError(
                f"unsupported education workspace version: {self.version!r}"
            )
        if type(self.classroom) is not cd.ClassroomSnapshot:
            raise EducationWorkspaceError("workspace classroom must be ClassroomSnapshot")
        if type(self.ledger) is not er.EducationLedger:
            raise EducationWorkspaceError("workspace ledger must be EducationLedger")
        if self.ledger.classroom_digest != self.classroom.digest:
            raise EducationWorkspaceError(
                "workspace ledger is not anchored to the current classroom"
            )

    @classmethod
    def empty(cls, classroom: cd.ClassroomSnapshot) -> "EducationWorkspace":
        if type(classroom) is not cd.ClassroomSnapshot:
            raise EducationWorkspaceError("workspace requires ClassroomSnapshot")
        return cls(classroom=classroom, ledger=er.EducationLedger.empty(classroom))

    @property
    def digest(self) -> str:
        return _digest(self._body())

    def _body(self) -> dict[str, object]:
        return {
            "version": self.version,
            "classroom": self.classroom.to_record(),
            "ledger": self.ledger.to_record(),
        }

    def to_record(self) -> dict[str, object]:
        record = self._body()
        record["digest"] = _digest(record)
        return record

    def to_json(self) -> str:
        text = _canonical_json(self.to_record())
        if _utf8_size(text) > MAX_WORKSPACE_JSON_BYTES:
            raise EducationWorkspaceError("education workspace exceeds size limit")
        return text

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "EducationWorkspace":
        data = _mapping(value, "education workspace")
        if set(data) != _WORKSPACE_FIELDS:
            raise EducationWorkspaceError("education workspace schema mismatch")
        supplied_digest = _digest_text(data["digest"], "workspace digest")
        body = {key: data[key] for key in ("version", "classroom", "ledger")}
        if _digest(body) != supplied_digest:
            raise EducationWorkspaceError("education workspace digest mismatch")
        version = data["version"]
        if type(version) is not int or version != EDUCATION_WORKSPACE_VERSION:
            raise EducationWorkspaceError(
                f"unsupported education workspace version: {version!r}"
            )
        raw_classroom = _mapping(data["classroom"], "workspace classroom")
        raw_ledger = _mapping(data["ledger"], "workspace ledger")
        try:
            classroom = cd.ClassroomSnapshot.from_record(raw_classroom)
            ledger = er.EducationLedger.from_record(raw_ledger)
        except (cd.ClassroomDomainError, er.EducationRecordsError) as exc:
            raise EducationWorkspaceError("invalid nested education workspace state") from exc
        return cls(classroom=classroom, ledger=ledger, version=version)

    @classmethod
    def from_json(cls, text: str) -> "EducationWorkspace":
        if type(text) is not str:
            raise EducationWorkspaceError("education workspace JSON must be exact text")
        if _utf8_size(text) > MAX_WORKSPACE_JSON_BYTES:
            raise EducationWorkspaceError("education workspace exceeds size limit")
        try:
            raw = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except json.JSONDecodeError as exc:
            raise EducationWorkspaceError("invalid education workspace JSON") from exc
        except RecursionError as exc:
            raise EducationWorkspaceError(
                "education workspace JSON exceeds nesting limit"
            ) from exc
        return cls.from_record(raw)

    def student_view(self, actor_student_id: str) -> er.StudentRecordsView:
        return self.ledger.student_view(self.classroom, actor_student_id)


def commit_classroom(
    workspace: EducationWorkspace,
    new_classroom: cd.ClassroomSnapshot,
    *,
    operation_id: str,
    expected_ledger_revision: int,
) -> EducationWorkspace:
    """Atomically re-anchor validated current Classroom state to D10 history.

    This is the generic composition primitive for canonical Classroom mutations.
    It does not manufacture domain records. Callers must first produce a valid
    ``ClassroomSnapshot`` through the owning domain. Deleted student tombstones
    are monotonic: once deleted, an identity cannot silently disappear or revive.
    """

    workspace = _workspace(workspace)
    if type(new_classroom) is not cd.ClassroomSnapshot:
        raise EducationWorkspaceError("new classroom must be ClassroomSnapshot")
    _protect_student_tombstones(workspace.classroom, new_classroom)
    try:
        ledger = er.reconcile_classroom(
            workspace.ledger,
            new_classroom,
            operation_id=operation_id,
            expected_revision=expected_ledger_revision,
        )
    except er.EducationRecordsError as exc:
        raise EducationWorkspaceError("classroom commit rejected") from exc
    if new_classroom == workspace.classroom and ledger is workspace.ledger:
        return workspace
    return EducationWorkspace(classroom=new_classroom, ledger=ledger)


def submit_homework(
    workspace: EducationWorkspace,
    *,
    homework_id: str,
    submission_id: str,
    operation_id: str,
    student_id: str,
    assignment_id: str,
    response_ref: str,
    submitted_at: str,
    attempt: int,
    expected_ledger_revision: int,
) -> EducationWorkspace:
    """Commit current Homework state and immutable attempt history together.

    A successful result contains both the updated canonical Homework record and
    the immutable SubmissionRecord in one anchored workspace. Any validation,
    CAS, attempt-order, or idempotency failure returns no new state.
    """

    workspace = _workspace(workspace)
    homework = _find_homework(workspace.classroom, homework_id)
    if homework.student_id != student_id or homework.assignment_id != assignment_id:
        raise EducationWorkspaceError(
            "homework identity does not match student and assignment"
        )
    if type(attempt) is not int or not 1 <= attempt <= 10_000:
        raise EducationWorkspaceError("attempt must be an integer from 1 to 10000")

    try:
        ledger_after_submission = er.submit_assignment(
            workspace.ledger,
            workspace.classroom,
            submission_id=submission_id,
            operation_id=operation_id,
            student_id=student_id,
            assignment_id=assignment_id,
            response_ref=response_ref,
            submitted_at=submitted_at,
            attempt=attempt,
            expected_revision=expected_ledger_revision,
        )
    except er.EducationRecordsError as exc:
        raise EducationWorkspaceError("assignment submission rejected") from exc

    if ledger_after_submission is workspace.ledger:
        if (
            homework.status is cd.HomeworkStatus.SUBMITTED
            and homework.response_ref == response_ref
        ):
            return workspace
    else:
        previous_attempts = tuple(
            item.attempt
            for item in workspace.ledger.submissions
            if item.student_id == student_id and item.assignment_id == assignment_id
        )
        expected_attempt = 1 if not previous_attempts else max(previous_attempts) + 1
        if attempt != expected_attempt:
            raise EducationWorkspaceError(
                f"submission attempt must be the next sequence value {expected_attempt}"
            )

    updated_homework = replace(
        homework,
        status=cd.HomeworkStatus.SUBMITTED,
        response_ref=response_ref,
    )
    new_classroom = replace(
        workspace.classroom,
        homework=tuple(
            updated_homework if item.homework_id == homework.homework_id else item
            for item in workspace.classroom.homework
        ),
    )
    _protect_student_tombstones(workspace.classroom, new_classroom)

    anchor_operation_id = _derived_operation_id(operation_id, "homework-anchor")
    try:
        anchored_ledger = er.reconcile_classroom(
            ledger_after_submission,
            new_classroom,
            operation_id=anchor_operation_id,
            expected_revision=ledger_after_submission.revision,
        )
    except er.EducationRecordsError as exc:
        raise EducationWorkspaceError(
            "assignment submission could not be anchored to current homework"
        ) from exc
    return EducationWorkspace(classroom=new_classroom, ledger=anchored_ledger)


def set_student_consent(
    workspace: EducationWorkspace,
    *,
    student_id: str,
    consent: cd.ConsentState | str,
    operation_id: str,
    expected_student_revision: int,
    expected_ledger_revision: int,
) -> EducationWorkspace:
    """Apply consent/teacher-note privacy changes and re-anchor history."""

    workspace = _workspace(workspace)
    desired = _consent(consent)
    current = _find_student(workspace.classroom, student_id)
    if current.consent is desired and not current.deleted:
        return commit_classroom(
            workspace,
            workspace.classroom,
            operation_id=operation_id,
            expected_ledger_revision=expected_ledger_revision,
        )

    try:
        new_classroom = cd.set_student_consent(
            workspace.classroom,
            student_id,
            expected_student_revision,
            desired,
        )
    except cd.ClassroomDomainError as exc:
        raise EducationWorkspaceError("student consent change rejected") from exc
    return commit_classroom(
        workspace,
        new_classroom,
        operation_id=operation_id,
        expected_ledger_revision=expected_ledger_revision,
    )


def delete_student(
    workspace: EducationWorkspace,
    *,
    student_id: str,
    operation_id: str,
    expected_student_revision: int,
    expected_ledger_revision: int,
) -> EducationWorkspace:
    """Delete/tombstone a student and purge D10 private history atomically."""

    workspace = _workspace(workspace)
    current = _find_student(workspace.classroom, student_id)
    if current.deleted:
        return commit_classroom(
            workspace,
            workspace.classroom,
            operation_id=operation_id,
            expected_ledger_revision=expected_ledger_revision,
        )
    try:
        new_classroom = cd.delete_student(
            workspace.classroom,
            student_id,
            expected_student_revision,
        )
    except cd.ClassroomDomainError as exc:
        raise EducationWorkspaceError("student deletion rejected") from exc
    return commit_classroom(
        workspace,
        new_classroom,
        operation_id=operation_id,
        expected_ledger_revision=expected_ledger_revision,
    )


def checkpoint_remote_session(
    workspace: EducationWorkspace,
    **kwargs: object,
) -> EducationWorkspace:
    """Persist D09-owned live-session checkpoint metadata without live state."""

    workspace = _workspace(workspace)
    try:
        ledger = er.checkpoint_remote_session(
            workspace.ledger,
            workspace.classroom,
            **kwargs,
        )
    except (TypeError, er.EducationRecordsError) as exc:
        raise EducationWorkspaceError("remote session checkpoint rejected") from exc
    if ledger is workspace.ledger:
        return workspace
    return EducationWorkspace(classroom=workspace.classroom, ledger=ledger)


def _workspace(value: object) -> EducationWorkspace:
    if type(value) is not EducationWorkspace:
        raise EducationWorkspaceError("operation requires EducationWorkspace")
    if value.ledger.classroom_digest != value.classroom.digest:
        raise EducationWorkspaceError("workspace anchor is corrupt")
    return value


def _find_homework(classroom: cd.ClassroomSnapshot, homework_id: str) -> cd.Homework:
    if type(homework_id) is not str:
        raise EducationWorkspaceError("homework id must be text")
    matches = tuple(
        item for item in classroom.homework if item.homework_id == homework_id
    )
    if len(matches) != 1:
        raise EducationWorkspaceError("unknown or ambiguous homework")
    return matches[0]


def _find_student(classroom: cd.ClassroomSnapshot, student_id: str) -> cd.Student:
    if type(student_id) is not str:
        raise EducationWorkspaceError("student id must be text")
    for student in classroom.students:
        if student.student_id == student_id:
            return student
    raise EducationWorkspaceError("unknown student")


def _consent(value: cd.ConsentState | str) -> cd.ConsentState:
    if isinstance(value, cd.ConsentState):
        return value
    if type(value) is not str:
        raise EducationWorkspaceError("consent must be ConsentState or exact text")
    try:
        return cd.ConsentState(value)
    except ValueError as exc:
        raise EducationWorkspaceError("unsupported consent state") from exc


def _protect_student_tombstones(
    old: cd.ClassroomSnapshot,
    new: cd.ClassroomSnapshot,
) -> None:
    old_by_id = {student.student_id: student for student in old.students}
    new_by_id = {student.student_id: student for student in new.students}
    for student_id, previous in old_by_id.items():
        current = new_by_id.get(student_id)
        if current is None:
            raise EducationWorkspaceError(
                "existing student identity cannot disappear; use a tombstone"
            )
        if previous.deleted and not current.deleted:
            raise EducationWorkspaceError("deleted student identity cannot be revived")


def _derived_operation_id(operation_id: object, purpose: str) -> str:
    if type(operation_id) is not str or not operation_id:
        raise EducationWorkspaceError("operation id must be non-empty text")
    try:
        seed = f"{purpose}\0{operation_id}".encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EducationWorkspaceError("operation id contains invalid Unicode") from exc
    return "ws:" + hashlib.sha256(seed).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or any(type(key) is not str for key in value)
    ):
        raise EducationWorkspaceError(f"{label} must be an exact-key object")
    return value


def _digest_text(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EducationWorkspaceError(f"{label} must be lowercase SHA-256 hex")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise EducationWorkspaceError(
            "education workspace cannot be serialized canonically"
        ) from exc


def _digest(value: object) -> str:
    text = _canonical_json(value)
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EducationWorkspaceError(
            "education workspace contains invalid Unicode"
        ) from exc
    return hashlib.sha256(data).hexdigest()


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise EducationWorkspaceError(
            "education workspace contains invalid Unicode"
        ) from exc


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise EducationWorkspaceError(
            "education workspace integer exceeds exact wire bounds"
        )
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise EducationWorkspaceError("invalid education workspace integer") from exc
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise EducationWorkspaceError(
            "education workspace integer exceeds exact wire bounds"
        )
    return parsed


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EducationWorkspaceError(f"duplicate workspace JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise EducationWorkspaceError(
        f"non-finite workspace JSON constant is not allowed: {value}"
    )
