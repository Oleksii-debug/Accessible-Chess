from __future__ import annotations

"""Provider-neutral deployment of durable prepared positions to lesson students.

This module owns no Board, move history, clock, transport, or second position
store.  Assignments reference the canonical D10 EducationWorkspace
PreparedPosition by exact identity + revision and are validated against the
canonical LessonSession/ClassroomSnapshot on creation and reconnect.
"""

from dataclasses import dataclass, fields
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping

from .education_workspace import (
    EducationWorkspace,
    EducationWorkspaceError,
    get_prepared_position,
)
from .teaching_session import (
    LessonSession,
    TeachingPositionSource,
    validate_lesson_session_scope,
)


PREPARED_POSITION_DEPLOYMENT_VERSION = 1
MAX_DEPLOYMENT_ASSIGNMENTS = 1_000
MAX_DEPLOYMENT_JSON_BYTES = 1_000_000
MAX_WIRE_INTEGER = (1 << 53) - 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class PreparedPositionDeploymentError(ValueError):
    """Fail-closed error for prepared-position deployment contracts."""


class DeploymentTargetKind(str, Enum):
    ALL = "all"
    SELECTED = "selected"
    GROUP = "group"


@dataclass(frozen=True)
class DeploymentTarget:
    kind: DeploymentTargetKind
    student_ids: tuple[str, ...] = ()
    group_id: str | None = None

    def __post_init__(self) -> None:
        kind = _enum(self.kind, DeploymentTargetKind, "deployment target kind")
        object.__setattr__(self, "kind", kind)
        students = _id_tuple(self.student_ids, "deployment target student ids")
        object.__setattr__(self, "student_ids", students)
        group_id = None if self.group_id is None else _id(self.group_id, "deployment group id")
        object.__setattr__(self, "group_id", group_id)

        if kind is DeploymentTargetKind.ALL:
            if students or group_id is not None:
                raise PreparedPositionDeploymentError("all target cannot carry selected students or group")
        elif kind is DeploymentTargetKind.SELECTED:
            if not students or group_id is not None:
                raise PreparedPositionDeploymentError("selected target requires students only")
        else:
            if students or group_id is None:
                raise PreparedPositionDeploymentError("group target requires one group id only")


@dataclass(frozen=True)
class PreparedPositionAssignment:
    assignment_id: str
    student_id: str
    position_id: str
    position_revision: int

    def __post_init__(self) -> None:
        _id(self.assignment_id, "prepared-position assignment id")
        _id(self.student_id, "prepared-position student id")
        _id(self.position_id, "prepared position id")
        _revision(self.position_revision, "prepared position revision")


@dataclass(frozen=True)
class PreparedPositionDeploymentBatch:
    batch_id: str
    lesson_session_id: str
    lesson_session_digest: str
    target: DeploymentTarget
    assignments: tuple[PreparedPositionAssignment, ...]
    version: int = PREPARED_POSITION_DEPLOYMENT_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        _id(self.batch_id, "prepared-position deployment batch id")
        _id(self.lesson_session_id, "lesson session id")
        _digest_text(self.lesson_session_digest, "lesson session digest")
        if type(self.target) is not DeploymentTarget:
            raise PreparedPositionDeploymentError("deployment target must be canonical DeploymentTarget")
        if (
            type(self.assignments) is not tuple
            or not self.assignments
            or len(self.assignments) > MAX_DEPLOYMENT_ASSIGNMENTS
        ):
            raise PreparedPositionDeploymentError("deployment assignments must be a bounded non-empty tuple")
        if any(type(item) is not PreparedPositionAssignment for item in self.assignments):
            raise PreparedPositionDeploymentError("deployment assignments contain invalid record type")

        assignment_ids = tuple(item.assignment_id for item in self.assignments)
        student_ids = tuple(item.student_id for item in self.assignments)
        if len(set(assignment_ids)) != len(assignment_ids):
            raise PreparedPositionDeploymentError("deployment assignment ids must be unique")
        if len(set(student_ids)) != len(student_ids):
            raise PreparedPositionDeploymentError("a student may receive only one position per batch")
        if (
            self.target.kind is DeploymentTargetKind.SELECTED
            and student_ids != self.target.student_ids
        ):
            raise PreparedPositionDeploymentError(
                "selected deployment assignments must exactly match target student order"
            )
        for item in self.assignments:
            if item.assignment_id != _assignment_id(self.batch_id, item.student_id):
                raise PreparedPositionDeploymentError("deployment assignment id is not stable for batch/student")

    @property
    def digest(self) -> str:
        return _digest(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "batch_id": self.batch_id,
            "lesson_session_id": self.lesson_session_id,
            "lesson_session_digest": self.lesson_session_digest,
            "target": _target_record(self.target),
            "assignments": [_assignment_record(item) for item in self.assignments],
        }

    def to_record(self) -> dict[str, Any]:
        body = self._body()
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        text = _canonical_json(self.to_record())
        if _utf8_size(text) > MAX_DEPLOYMENT_JSON_BYTES:
            raise PreparedPositionDeploymentError("deployment batch JSON exceeds size limit")
        return text

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "PreparedPositionDeploymentBatch":
        data = _mapping(value, "prepared-position deployment batch")
        expected = {
            "version",
            "batch_id",
            "lesson_session_id",
            "lesson_session_digest",
            "target",
            "assignments",
            "digest",
        }
        _exact_keys(data, expected, "prepared-position deployment batch")

        # Bound and canonicalize every variable-size field before hashing the
        # supplied record. from_json() has a wire-byte cap, but from_record()
        # is also a public trust boundary and must not serialize an unbounded
        # caller-owned list/string merely to discover that it is invalid.
        _version(data["version"])
        _id(data["batch_id"], "prepared-position deployment batch id")
        _id(data["lesson_session_id"], "lesson session id")
        _digest_text(data["lesson_session_digest"], "lesson session digest")

        target_data = _mapping(data["target"], "deployment target")
        _exact_keys(target_data, {"kind", "student_ids", "group_id"}, "deployment target")
        raw_target_students = target_data["student_ids"]
        if (
            type(raw_target_students) is not list
            or len(raw_target_students) > MAX_DEPLOYMENT_ASSIGNMENTS
        ):
            raise PreparedPositionDeploymentError(
                "deployment target student ids must be a bounded JSON array"
            )
        target = DeploymentTarget(
            kind=target_data["kind"],
            student_ids=tuple(raw_target_students),
            group_id=target_data["group_id"],
        )

        raw_assignments = data["assignments"]
        if (
            type(raw_assignments) is not list
            or not raw_assignments
            or len(raw_assignments) > MAX_DEPLOYMENT_ASSIGNMENTS
        ):
            raise PreparedPositionDeploymentError(
                "deployment assignments must be a bounded non-empty JSON array"
            )
        assignment_fields = {field.name for field in fields(PreparedPositionAssignment)}
        assignments = []
        for raw in raw_assignments:
            item = _mapping(raw, "prepared-position assignment")
            _exact_keys(item, assignment_fields, "prepared-position assignment")
            assignments.append(PreparedPositionAssignment(**dict(item)))

        supplied = _digest_text(data["digest"], "deployment batch digest")
        body = {key: data[key] for key in expected if key != "digest"}
        if _digest(body) != supplied:
            raise PreparedPositionDeploymentError("deployment batch digest mismatch")

        return cls(
            batch_id=data["batch_id"],
            lesson_session_id=data["lesson_session_id"],
            lesson_session_digest=data["lesson_session_digest"],
            target=target,
            assignments=tuple(assignments),
            version=data["version"],
        )

    @classmethod
    def from_json(cls, text: str) -> "PreparedPositionDeploymentBatch":
        if type(text) is not str:
            raise PreparedPositionDeploymentError("deployment batch JSON must be exact text")
        if _utf8_size(text) > MAX_DEPLOYMENT_JSON_BYTES:
            raise PreparedPositionDeploymentError("deployment batch JSON exceeds size limit")
        try:
            raw = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except json.JSONDecodeError as exc:
            raise PreparedPositionDeploymentError("invalid deployment batch JSON") from exc
        except RecursionError as exc:
            raise PreparedPositionDeploymentError("deployment batch JSON exceeds nesting limit") from exc
        return cls.from_record(raw)


def plan_prepared_position_deployment(
    lesson_session: LessonSession,
    workspace: EducationWorkspace,
    *,
    batch_id: str,
    position_by_student: Mapping[str, str],
    target: DeploymentTarget | None = None,
) -> PreparedPositionDeploymentBatch:
    """Build one deterministic student->PreparedPosition reference batch."""

    lesson_session, workspace = _authorities(lesson_session, workspace)
    batch_id = _id(batch_id, "prepared-position deployment batch id")
    target = DeploymentTarget(DeploymentTargetKind.ALL) if target is None else target
    if type(target) is not DeploymentTarget:
        raise PreparedPositionDeploymentError("target must be canonical DeploymentTarget")

    students = _resolve_target_students(lesson_session, workspace, target)
    mapping = _position_mapping(position_by_student)
    if set(mapping) != set(students):
        raise PreparedPositionDeploymentError("position mapping must exactly cover deployment target students")

    assignments = []
    for student_id in students:
        position_id = mapping[student_id]
        try:
            position = get_prepared_position(workspace, position_id)
        except EducationWorkspaceError as exc:
            raise PreparedPositionDeploymentError("deployment references unknown prepared position") from exc
        assignments.append(
            PreparedPositionAssignment(
                assignment_id=_assignment_id(batch_id, student_id),
                student_id=student_id,
                position_id=position.position_id,
                position_revision=position.revision,
            )
        )

    return PreparedPositionDeploymentBatch(
        batch_id=batch_id,
        lesson_session_id=lesson_session.session_id,
        lesson_session_digest=lesson_session.digest,
        target=target,
        assignments=tuple(assignments),
    )


def plan_uniform_prepared_position_deployment(
    lesson_session: LessonSession,
    workspace: EducationWorkspace,
    *,
    batch_id: str,
    position_id: str,
    target: DeploymentTarget | None = None,
) -> PreparedPositionDeploymentBatch:
    """Deploy one existing PreparedPosition to all students in one target.

    This is the one-position convenience contract for ALL, GROUP, or one/more
    SELECTED students.  It deliberately builds the same canonical per-student
    mapping consumed by plan_prepared_position_deployment, so retry identity,
    revisions, reconnect validation, and wire format remain one authority.
    """

    lesson_session, workspace = _authorities(lesson_session, workspace)
    target = DeploymentTarget(DeploymentTargetKind.ALL) if target is None else target
    if type(target) is not DeploymentTarget:
        raise PreparedPositionDeploymentError("target must be canonical DeploymentTarget")
    position_id = _id(position_id, "prepared position id")
    students = _resolve_target_students(lesson_session, workspace, target)
    return plan_prepared_position_deployment(
        lesson_session,
        workspace,
        batch_id=batch_id,
        target=target,
        position_by_student={
            student_id: position_id
            for student_id in students
        },
    )


def assert_prepared_position_deployment_retry(
    existing: PreparedPositionDeploymentBatch,
    candidate: PreparedPositionDeploymentBatch,
) -> None:
    """Require a repeated batch identity to preserve its exact canonical payload."""

    if type(existing) is not PreparedPositionDeploymentBatch or type(candidate) is not PreparedPositionDeploymentBatch:
        raise PreparedPositionDeploymentError("deployment retry requires canonical batches")
    if existing.batch_id != candidate.batch_id:
        raise PreparedPositionDeploymentError("deployment retry batch id mismatch")
    if existing.digest != candidate.digest:
        raise PreparedPositionDeploymentError("deployment batch id was reused with changed payload")


def assert_prepared_position_deployment_scope(
    batch: PreparedPositionDeploymentBatch,
    lesson_session: LessonSession,
    workspace: EducationWorkspace,
) -> None:
    """Validate a deserialized/reconnected batch against live authorities."""

    if type(batch) is not PreparedPositionDeploymentBatch:
        raise PreparedPositionDeploymentError("scope check requires PreparedPositionDeploymentBatch")
    lesson_session, workspace = _authorities(lesson_session, workspace)

    if (
        batch.lesson_session_id != lesson_session.session_id
        or batch.lesson_session_digest != lesson_session.digest
    ):
        raise PreparedPositionDeploymentError("deployment batch does not match lesson session")

    students = _resolve_target_students(lesson_session, workspace, batch.target)
    assigned_students = tuple(item.student_id for item in batch.assignments)
    if assigned_students != students:
        raise PreparedPositionDeploymentError("deployment batch student scope changed")

    for item in batch.assignments:
        if item.assignment_id != _assignment_id(batch.batch_id, item.student_id):
            raise PreparedPositionDeploymentError("deployment assignment identity drift")
        try:
            position = get_prepared_position(workspace, item.position_id)
        except EducationWorkspaceError as exc:
            raise PreparedPositionDeploymentError("deployment prepared position is unavailable") from exc
        if position.revision != item.position_revision:
            raise PreparedPositionDeploymentError("deployment prepared position revision is stale")


def resolve_prepared_position_source(
    batch: PreparedPositionDeploymentBatch,
    assignment_id: str,
    lesson_session: LessonSession,
    workspace: EducationWorkspace,
) -> TeachingPositionSource:
    """Resolve one assignment only after the whole reconnect contract is valid."""

    assert_prepared_position_deployment_scope(batch, lesson_session, workspace)
    assignment_id = _id(assignment_id, "prepared-position assignment id")
    item = next((entry for entry in batch.assignments if entry.assignment_id == assignment_id), None)
    if item is None:
        raise PreparedPositionDeploymentError("unknown prepared-position assignment id")
    try:
        return get_prepared_position(workspace, item.position_id).source
    except EducationWorkspaceError as exc:
        raise PreparedPositionDeploymentError("deployment prepared position is unavailable") from exc


def _authorities(
    lesson_session: LessonSession,
    workspace: EducationWorkspace,
) -> tuple[LessonSession, EducationWorkspace]:
    if type(lesson_session) is not LessonSession:
        raise PreparedPositionDeploymentError("deployment requires canonical LessonSession")
    if type(workspace) is not EducationWorkspace:
        raise PreparedPositionDeploymentError("deployment requires canonical EducationWorkspace")
    try:
        validate_lesson_session_scope(lesson_session, workspace.classroom)
    except Exception as exc:
        raise PreparedPositionDeploymentError("lesson session is outside current classroom scope") from exc
    return lesson_session, workspace


def _resolve_target_students(
    lesson_session: LessonSession,
    workspace: EducationWorkspace,
    target: DeploymentTarget,
) -> tuple[str, ...]:
    allowed = tuple(lesson_session.student_ids)
    active = {item.student_id for item in workspace.classroom.students if not item.deleted}

    if target.kind is DeploymentTargetKind.ALL:
        selected = allowed
    elif target.kind is DeploymentTargetKind.SELECTED:
        selected = target.student_ids
        if any(student_id not in allowed for student_id in selected):
            raise PreparedPositionDeploymentError("selected deployment student is outside lesson session")
    else:
        groups = {item.group_id for item in workspace.classroom.groups}
        if target.group_id not in groups:
            raise PreparedPositionDeploymentError("deployment group is unavailable")
        lesson = next(
            (
                item
                for item in workspace.classroom.lessons
                if item.lesson_id == lesson_session.lesson_id
            ),
            None,
        )
        if lesson is None:
            raise PreparedPositionDeploymentError("deployment lesson is unavailable")
        group_students: set[str] = set()
        matching_course_group = False
        for cohort in workspace.classroom.cohorts:
            if (
                cohort.group_id == target.group_id
                and cohort.course_id == lesson.course_id
            ):
                matching_course_group = True
                group_students.update(cohort.student_ids)
        if not matching_course_group:
            raise PreparedPositionDeploymentError(
                "deployment group is outside lesson course"
            )
        selected = tuple(student_id for student_id in allowed if student_id in group_students)

    if not selected:
        raise PreparedPositionDeploymentError("deployment target resolves to no lesson students")
    if len(selected) > MAX_DEPLOYMENT_ASSIGNMENTS:
        raise PreparedPositionDeploymentError("deployment target exceeds assignment limit")
    if any(student_id not in active for student_id in selected):
        raise PreparedPositionDeploymentError("deployment target contains unavailable student")
    return selected


def _position_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > MAX_DEPLOYMENT_ASSIGNMENTS:
        raise PreparedPositionDeploymentError("position mapping must be a bounded mapping")
    result: dict[str, str] = {}
    for raw_student, raw_position in value.items():
        student_id = _id(raw_student, "deployment student id")
        position_id = _id(raw_position, "prepared position id")
        if student_id in result:
            raise PreparedPositionDeploymentError("position mapping contains duplicate student")
        result[student_id] = position_id
    return result


def _assignment_id(batch_id: str, student_id: str) -> str:
    # Both canonical ids may contain ":", so delimiter concatenation is
    # ambiguous (for example "a:b"+"c" vs "a"+"b:c"). NUL is outside the
    # canonical id alphabet and therefore provides one unambiguous framing.
    preimage = (
        b"accessible-chess:prepared-position-assignment:v1\0"
        + batch_id.encode("ascii")
        + b"\0"
        + student_id.encode("ascii")
    )
    digest = hashlib.sha256(preimage).hexdigest()[:24]
    return f"deploy-{digest}"


def _target_record(target: DeploymentTarget) -> dict[str, Any]:
    return {
        "kind": target.kind.value,
        "student_ids": list(target.student_ids),
        "group_id": target.group_id,
    }


def _assignment_record(item: PreparedPositionAssignment) -> dict[str, Any]:
    return {field.name: getattr(item, field.name) for field in fields(item)}


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise PreparedPositionDeploymentError(f"{label} must be a canonical opaque identifier")
    return value


def _id_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > MAX_DEPLOYMENT_ASSIGNMENTS:
        raise PreparedPositionDeploymentError(f"{label} must be a bounded tuple")
    checked = tuple(_id(item, label) for item in value)
    if len(set(checked)) != len(checked):
        raise PreparedPositionDeploymentError(f"{label} contains duplicate identifiers")
    return checked


def _enum(value: object, enum_type, label: str):
    if type(value) is enum_type:
        return value
    if type(value) is not str:
        raise PreparedPositionDeploymentError(f"{label} is invalid")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise PreparedPositionDeploymentError(f"unsupported {label}: {value!r}") from exc


def _revision(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise PreparedPositionDeploymentError(f"{label} must be a JSON-safe non-negative exact integer")
    return value


def _version(value: object) -> int:
    if type(value) is not int or value != PREPARED_POSITION_DEPLOYMENT_VERSION:
        raise PreparedPositionDeploymentError(f"unsupported deployment version: {value!r}")
    return value


def _digest_text(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise PreparedPositionDeploymentError(f"{label} must be lowercase SHA-256 hex")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise PreparedPositionDeploymentError(f"{label} must be an exact-key object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise PreparedPositionDeploymentError(
            f"{label} schema mismatch; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise PreparedPositionDeploymentError("deployment batch cannot be serialized canonically") from exc


def _digest(value: object) -> str:
    text = _canonical_json(value)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PreparedPositionDeploymentError(
            "deployment JSON contains invalid Unicode"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _utf8_size(text: str) -> int:
    if type(text) is not str:
        raise PreparedPositionDeploymentError("deployment JSON must be exact text")
    total = 0
    for character in text:
        codepoint = ord(character)
        if codepoint <= 0x7F:
            total += 1
        elif codepoint <= 0x7FF:
            total += 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise PreparedPositionDeploymentError(
                "deployment JSON contains invalid Unicode"
            )
        elif codepoint <= 0xFFFF:
            total += 3
        else:
            total += 4
        if total > MAX_DEPLOYMENT_JSON_BYTES:
            return total
    return total


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise PreparedPositionDeploymentError("deployment JSON integer exceeds exact wire bounds")
    parsed = int(value, 10)
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise PreparedPositionDeploymentError("deployment JSON integer exceeds exact wire bounds")
    return parsed


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PreparedPositionDeploymentError(f"duplicate deployment JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise PreparedPositionDeploymentError(f"non-finite deployment JSON constant is not allowed: {value}")


__all__ = [
    "DeploymentTarget",
    "DeploymentTargetKind",
    "PreparedPositionAssignment",
    "PreparedPositionDeploymentBatch",
    "PreparedPositionDeploymentError",
    "assert_prepared_position_deployment_retry",
    "assert_prepared_position_deployment_scope",
    "plan_prepared_position_deployment",
    "plan_uniform_prepared_position_deployment",
    "resolve_prepared_position_source",
]
