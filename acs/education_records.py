from __future__ import annotations

"""Append-only education activity records outside canonical ClassroomSnapshot state.

Authority boundaries are deliberate:
- ``ClassroomSnapshot`` owns students/classes/groups/courses/lessons/assignments,
  current Homework/Result/Progress state, consent, and deletion.
- this module owns immutable assignment-attempt history and durable remote-session
  checkpoint metadata that are awkward to model as current-state Classroom records.
- training/game review metrics remain the responsibility of the existing
  StudentProgressLedger when that proven package is composed.

No chess position, move legality, engine score/PV, live pointer, highlight, hover,
or click state is reimplemented here.
"""

from dataclasses import dataclass, fields, replace
import hashlib
import json
import re
from typing import Any, Mapping

from .classroom_domain import ClassroomSnapshot, Progress
from .remote_session import (
    RemoteEventKind,
    RemoteSessionLog,
)
from .teaching_session import (
    LessonSession,
    validate_lesson_session_scope,
)


EDUCATION_RECORDS_VERSION = 1
MAX_RECORDS_PER_COLLECTION = 10_000
MAX_OPERATION_RECEIPTS = 20_000
MAX_SNAPSHOT_BYTES = 4_000_000
MAX_TEXT = 512
MAX_WIRE_INTEGER = (1 << 53) - 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class EducationRecordsError(ValueError):
    """Raised when education activity is stale, corrupt, or unauthorized."""


@dataclass(frozen=True)
class SubmissionRecord:
    """One immutable assignment response attempt.

    ``ClassroomSnapshot.Homework`` remains the current assignment state; this record
    is append-only history so retries and prior attempts are never overwritten.
    ``response_ref`` is an opaque identifier, not filesystem content.
    """

    submission_id: str
    assignment_id: str
    student_id: str
    response_ref: str
    submitted_at: str
    attempt: int = 1

    def __post_init__(self) -> None:
        _id(self.submission_id, "submission id")
        _id(self.assignment_id, "submission assignment id")
        _id(self.student_id, "submission student id")
        _id(self.response_ref, "submission response ref")
        _timestamp(self.submitted_at, "submission submitted_at")
        if type(self.attempt) is not int or not 1 <= self.attempt <= 10_000:
            raise EducationRecordsError(
                "submission attempt must be an integer from 1 to 10000"
            )


@dataclass(frozen=True)
class RemoteSessionRecord:
    """Durable checkpoint reference for D09-owned live Classroom interaction.

    Only identity, participants, sequence, and content digest cross this boundary.
    The live session event log/position/pointer/annotations remain owned elsewhere.
    """

    record_id: str
    session_id: str
    student_ids: tuple[str, ...]
    started_at: str
    closed_at: str | None
    last_remote_sequence: int
    snapshot_digest: str
    revision: int = 0

    def __post_init__(self) -> None:
        _id(self.record_id, "remote session record id")
        _id(self.session_id, "remote session id")
        object.__setattr__(
            self,
            "student_ids",
            _id_tuple(self.student_ids, "remote session student ids"),
        )
        _timestamp(self.started_at, "remote session started_at")
        if self.closed_at is not None:
            _timestamp(self.closed_at, "remote session closed_at")
        _revision(self.last_remote_sequence, "remote session sequence")
        _digest_text(self.snapshot_digest, "remote session snapshot digest")
        _revision(self.revision, "remote session revision")


@dataclass(frozen=True)
class OperationReceipt:
    operation_id: str
    operation_kind: str
    payload_digest: str

    def __post_init__(self) -> None:
        _id(self.operation_id, "operation id")
        _text(self.operation_kind, "operation kind", max_len=64)
        _digest_text(self.payload_digest, "operation payload digest")


@dataclass(frozen=True)
class StudentSessionView:
    session_id: str
    started_at: str
    closed_at: str | None
    last_remote_sequence: int

    def __post_init__(self) -> None:
        _id(self.session_id, "student session id")
        _timestamp(self.started_at, "student session started_at")
        if self.closed_at is not None:
            _timestamp(self.closed_at, "student session closed_at")
        _revision(self.last_remote_sequence, "student session sequence")


@dataclass(frozen=True)
class StudentRecordsView:
    """Privacy-filtered student projection.

    Progress is projected from the canonical ClassroomSnapshot rather than copied
    into EducationLedger.  Session participant membership is intentionally hidden.
    """

    student_id: str
    submissions: tuple[SubmissionRecord, ...]
    progress: tuple[Progress, ...]
    sessions: tuple[StudentSessionView, ...]

    def __post_init__(self) -> None:
        _id(self.student_id, "student view id")
        _typed_tuple(self.submissions, SubmissionRecord, "student view submissions")
        _typed_tuple(self.progress, Progress, "student view progress")
        _typed_tuple(self.sessions, StudentSessionView, "student view sessions")
        if any(item.student_id != self.student_id for item in self.submissions):
            raise EducationRecordsError(
                "student view contains another student's submission"
            )
        if any(item.student_id != self.student_id for item in self.progress):
            raise EducationRecordsError(
                "student view contains another student's progress"
            )


@dataclass(frozen=True)
class EducationLedger:
    classroom_digest: str
    revision: int = 0
    submissions: tuple[SubmissionRecord, ...] = ()
    remote_sessions: tuple[RemoteSessionRecord, ...] = ()
    operation_receipts: tuple[OperationReceipt, ...] = ()
    version: int = EDUCATION_RECORDS_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        _digest_text(self.classroom_digest, "classroom digest")
        _revision(self.revision, "education ledger revision")
        _typed_tuple(self.submissions, SubmissionRecord, "submissions")
        _typed_tuple(self.remote_sessions, RemoteSessionRecord, "remote sessions")
        if (
            type(self.operation_receipts) is not tuple
            or len(self.operation_receipts) > MAX_OPERATION_RECEIPTS
        ):
            raise EducationRecordsError("operation receipts must be a bounded tuple")
        if any(type(item) is not OperationReceipt for item in self.operation_receipts):
            raise EducationRecordsError(
                "operation receipts contain invalid record type"
            )
        _unique(self.submissions, "submission_id", "submission")
        _unique(self.remote_sessions, "record_id", "remote session record")
        _unique(self.remote_sessions, "session_id", "remote session")
        _unique(self.operation_receipts, "operation_id", "operation receipt")

    @classmethod
    def empty(cls, classroom: ClassroomSnapshot) -> "EducationLedger":
        _classroom(classroom)
        return cls(classroom_digest=classroom.digest)

    @property
    def digest(self) -> str:
        return _digest(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "classroom_digest": self.classroom_digest,
            "revision": self.revision,
            "submissions": [_encode_record(item) for item in self.submissions],
            "remote_sessions": [
                _encode_record(item) for item in self.remote_sessions
            ],
            "operation_receipts": [
                _encode_record(item) for item in self.operation_receipts
            ],
        }

    def to_record(self) -> dict[str, Any]:
        body = self._body()
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        text = _canonical_json(self.to_record())
        if _utf8_size(text) > MAX_SNAPSHOT_BYTES:
            raise EducationRecordsError(
                "education records snapshot exceeds size limit"
            )
        return text

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "EducationLedger":
        data = _mapping(value, "education records snapshot")
        expected = {
            "version",
            "classroom_digest",
            "revision",
            "submissions",
            "remote_sessions",
            "operation_receipts",
            "digest",
        }
        _exact_keys(data, expected, "education records snapshot")
        _version(data["version"])
        supplied_digest = _digest_text(
            data["digest"], "education records digest"
        )
        body = {key: data[key] for key in expected if key != "digest"}
        if _digest(body) != supplied_digest:
            raise EducationRecordsError(
                "education records snapshot digest mismatch"
            )
        return cls(
            version=data["version"],
            classroom_digest=data["classroom_digest"],
            revision=data["revision"],
            submissions=_decode_records(
                data["submissions"], SubmissionRecord, "submissions"
            ),
            remote_sessions=_decode_records(
                data["remote_sessions"], RemoteSessionRecord, "remote sessions"
            ),
            operation_receipts=_decode_records(
                data["operation_receipts"],
                OperationReceipt,
                "operation receipts",
                limit=MAX_OPERATION_RECEIPTS,
            ),
        )

    @classmethod
    def from_json(cls, text: str) -> "EducationLedger":
        if type(text) is not str:
            raise EducationRecordsError(
                "education records JSON must be exact text"
            )
        if _utf8_size(text) > MAX_SNAPSHOT_BYTES:
            raise EducationRecordsError(
                "education records snapshot exceeds size limit"
            )
        try:
            raw = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except json.JSONDecodeError as exc:
            raise EducationRecordsError("invalid education records JSON") from exc
        except RecursionError as exc:
            raise EducationRecordsError(
                "education records JSON exceeds nesting limit"
            ) from exc
        return cls.from_record(raw)

    def student_view(
        self,
        classroom: ClassroomSnapshot,
        actor_student_id: str,
    ) -> StudentRecordsView:
        """Return only current canonical state plus this actor's private history.

        There is deliberately no arbitrary subject parameter.  The current
        ClassroomSnapshot is mandatory, so a deleted student cannot use a stale
        EducationLedger before privacy reconciliation.
        """

        _anchor(self, classroom)
        actor_student_id = _id(actor_student_id, "student view actor id")
        _require_active_student(classroom, actor_student_id)
        submissions = tuple(
            item
            for item in self.submissions
            if item.student_id == actor_student_id
        )
        progress = tuple(
            item
            for item in classroom.progress
            if item.student_id == actor_student_id
        )
        sessions = tuple(
            StudentSessionView(
                session_id=item.session_id,
                started_at=item.started_at,
                closed_at=item.closed_at,
                last_remote_sequence=item.last_remote_sequence,
            )
            for item in self.remote_sessions
            if actor_student_id in item.student_ids
        )
        return StudentRecordsView(
            actor_student_id,
            submissions,
            progress,
            sessions,
        )


def submit_assignment(
    ledger: EducationLedger,
    classroom: ClassroomSnapshot,
    *,
    submission_id: str,
    operation_id: str,
    student_id: str,
    assignment_id: str,
    response_ref: str,
    submitted_at: str,
    attempt: int = 1,
    expected_revision: int,
) -> EducationLedger:
    ledger, classroom = _anchor(ledger, classroom)
    record = SubmissionRecord(
        submission_id,
        assignment_id,
        student_id,
        response_ref,
        submitted_at,
        attempt,
    )
    _require_assignment_student(classroom, student_id, assignment_id)
    payload = _record_payload(record)
    if _idempotency(ledger, operation_id, "submit_assignment", payload):
        return ledger
    _check_revision(ledger, expected_revision)
    if any(item.submission_id == record.submission_id for item in ledger.submissions):
        raise EducationRecordsError("duplicate submission id")
    return _commit(
        ledger,
        operation_id,
        "submit_assignment",
        payload,
        submissions=ledger.submissions + (record,),
    )


def checkpoint_remote_session(
    ledger: EducationLedger,
    classroom: ClassroomSnapshot,
    *,
    record_id: str,
    operation_id: str,
    lesson_session: LessonSession,
    remote_session_log: RemoteSessionLog,
    started_at: str,
    closed_at: str | None,
    expected_session_revision: int,
    expected_revision: int,
) -> EducationLedger:
    ledger, classroom = _anchor(ledger, classroom)
    _revision(expected_session_revision, "expected remote session revision")
    (
        session_id,
        student_ids,
        last_remote_sequence,
        snapshot_digest,
    ) = _canonical_remote_checkpoint(
        classroom,
        lesson_session,
        remote_session_log,
    )
    for student_id in student_ids:
        _require_active_student(classroom, student_id)
    candidate = RemoteSessionRecord(
        record_id=record_id,
        session_id=session_id,
        student_ids=student_ids,
        started_at=started_at,
        closed_at=closed_at,
        last_remote_sequence=last_remote_sequence,
        snapshot_digest=snapshot_digest,
        revision=expected_session_revision,
    )
    payload = _record_payload(candidate)
    if _idempotency(
        ledger,
        operation_id,
        "checkpoint_remote_session",
        payload,
    ):
        return ledger
    _check_revision(ledger, expected_revision)

    existing = next(
        (
            item
            for item in ledger.remote_sessions
            if item.session_id == candidate.session_id
        ),
        None,
    )
    if existing is None:
        if expected_session_revision != 0:
            raise EducationRecordsError("stale remote session revision")
        if any(
            item.record_id == candidate.record_id
            for item in ledger.remote_sessions
        ):
            raise EducationRecordsError("duplicate remote session record id")
        updated = ledger.remote_sessions + (candidate,)
    else:
        if existing.record_id != candidate.record_id:
            raise EducationRecordsError(
                "remote session id is already bound to another record id"
            )
        if existing.revision != expected_session_revision:
            raise EducationRecordsError("stale remote session revision")
        if (
            existing.student_ids != candidate.student_ids
            or existing.started_at != candidate.started_at
        ):
            raise EducationRecordsError(
                "remote session stable identity fields cannot change"
            )
        if existing.closed_at is not None:
            raise EducationRecordsError(
                "closed remote session cannot accept new checkpoints"
            )
        if candidate.last_remote_sequence < existing.last_remote_sequence:
            raise EducationRecordsError(
                "remote session sequence cannot move backwards"
            )
        if candidate.last_remote_sequence == existing.last_remote_sequence:
            if candidate.snapshot_digest != existing.snapshot_digest:
                raise EducationRecordsError(
                    "remote session sequence conflicts with a different snapshot digest"
                )
            if not (existing.closed_at is None and candidate.closed_at is not None):
                raise EducationRecordsError("duplicate remote session checkpoint")
        replacement = replace(candidate, revision=existing.revision + 1)
        updated = tuple(
            replacement if item.session_id == existing.session_id else item
            for item in ledger.remote_sessions
        )
    return _commit(
        ledger,
        operation_id,
        "checkpoint_remote_session",
        payload,
        remote_sessions=updated,
    )


def _canonical_remote_checkpoint(
    classroom: ClassroomSnapshot,
    lesson_session: object,
    remote_session_log: object,
) -> tuple[str, tuple[str, ...], int, str]:
    """Freeze D09 sources into one verified D10 checkpoint identity.

    Callers cannot supply session identity, participant membership, sequence, or
    digest independently.  The teaching plan owns participant membership while
    ``RemoteSessionLog`` owns the replayed sequence and snapshot digest.  A fresh
    snapshot replay also detects a corrupted or forged in-memory log before any
    ledger CAS or receipt is evaluated.
    """

    if type(lesson_session) is not LessonSession:
        raise EducationRecordsError(
            "remote checkpoint requires canonical LessonSession"
        )
    if type(remote_session_log) is not RemoteSessionLog:
        raise EducationRecordsError(
            "remote checkpoint requires canonical RemoteSessionLog"
        )
    try:
        validate_lesson_session_scope(lesson_session, classroom)
        snapshot_text = remote_session_log.to_json()
        canonical_log = RemoteSessionLog.from_json(snapshot_text)
        snapshot = canonical_log.to_snapshot()
    except Exception as exc:
        raise EducationRecordsError(
            "remote session snapshot is not canonical"
        ) from exc
    if canonical_log.state.session_id != lesson_session.session_id:
        raise EducationRecordsError(
            "remote session log does not match lesson session identity"
        )

    students = lesson_session.student_ids
    allowed_students = frozenset(students)
    for event in canonical_log.events:
        student_id: object | None = None
        if event.kind is RemoteEventKind.STUDENT_ANSWER:
            student_id = event.payload["student_id"]
        elif event.kind is RemoteEventKind.ACTIVE_STUDENT:
            student_id = event.payload["student_id"]
        if student_id is not None and student_id not in allowed_students:
            raise EducationRecordsError(
                "remote session references a student outside the lesson session"
            )

    digest = snapshot["digest"]
    if type(digest) is not str:
        raise EducationRecordsError("remote session snapshot digest is invalid")
    return (
        lesson_session.session_id,
        students,
        canonical_log.state.last_sequence,
        digest,
    )


def reconcile_classroom(
    ledger: EducationLedger,
    classroom: ClassroomSnapshot,
    *,
    operation_id: str,
    expected_revision: int,
) -> EducationLedger:
    """Re-anchor history to a new classroom snapshot and honor deletion.

    Historical assignment IDs are retained for active students even if a course or
    assignment later changes.  Deleted/unavailable students are removed from
    private submissions and remote participant lists.  Canonical Classroom
    Homework/Result/Progress deletion is already performed by classroom_domain.

    Privacy-driven participant-list changes increment the per-session CAS revision,
    forcing reconnecting session writers to refresh before another checkpoint.
    """

    _ledger(ledger)
    _classroom(classroom)
    payload = {"classroom_digest": classroom.digest}
    if _idempotency(ledger, operation_id, "reconcile_classroom", payload):
        return ledger
    _check_revision(ledger, expected_revision)

    active = {
        student.student_id
        for student in classroom.students
        if not student.deleted
    }

    def reconcile_session(item: RemoteSessionRecord) -> RemoteSessionRecord:
        filtered = tuple(
            student_id
            for student_id in item.student_ids
            if student_id in active
        )
        if filtered == item.student_ids:
            return item
        return replace(
            item,
            student_ids=filtered,
            revision=item.revision + 1,
        )

    return _commit(
        ledger,
        operation_id,
        "reconcile_classroom",
        payload,
        classroom_digest=classroom.digest,
        submissions=tuple(
            item for item in ledger.submissions if item.student_id in active
        ),
        remote_sessions=tuple(
            reconcile_session(item) for item in ledger.remote_sessions
        ),
    )


def _anchor(
    ledger: EducationLedger,
    classroom: ClassroomSnapshot,
) -> tuple[EducationLedger, ClassroomSnapshot]:
    _ledger(ledger)
    _classroom(classroom)
    if ledger.classroom_digest != classroom.digest:
        raise EducationRecordsError(
            "education ledger is anchored to a different classroom snapshot"
        )
    return ledger, classroom


def _check_revision(ledger: EducationLedger, expected_revision: int) -> None:
    _revision(expected_revision, "expected education ledger revision")
    if ledger.revision != expected_revision:
        raise EducationRecordsError("stale education ledger revision")


def _commit(
    ledger: EducationLedger,
    operation_id: str,
    operation_kind: str,
    payload: object,
    **changes,
) -> EducationLedger:
    receipt = OperationReceipt(
        _id(operation_id, "operation id"),
        operation_kind,
        _digest(payload),
    )
    if len(ledger.operation_receipts) >= MAX_OPERATION_RECEIPTS:
        raise EducationRecordsError("operation receipt limit exceeded")
    changes["revision"] = ledger.revision + 1
    changes["operation_receipts"] = ledger.operation_receipts + (receipt,)
    return replace(ledger, **changes)


def _idempotency(
    ledger: EducationLedger,
    operation_id: str,
    operation_kind: str,
    payload: object,
) -> bool:
    operation_id = _id(operation_id, "operation id")
    payload_digest = _digest(payload)
    for receipt in ledger.operation_receipts:
        if receipt.operation_id != operation_id:
            continue
        if (
            receipt.operation_kind == operation_kind
            and receipt.payload_digest == payload_digest
        ):
            return True
        raise EducationRecordsError(
            "operation id was already used with different content"
        )
    return False


def _require_active_student(
    classroom: ClassroomSnapshot,
    student_id: str,
):
    student_id = _id(student_id, "student id")
    student = next(
        (
            item
            for item in classroom.students
            if item.student_id == student_id
        ),
        None,
    )
    if student is None or student.deleted:
        raise EducationRecordsError("student is unavailable")
    return student


def _require_assignment_student(
    classroom: ClassroomSnapshot,
    student_id: str,
    assignment_id: str,
) -> None:
    _require_active_student(classroom, student_id)
    assignment_id = _id(assignment_id, "assignment id")
    assignment = next(
        (
            item
            for item in classroom.assignments
            if item.assignment_id == assignment_id
        ),
        None,
    )
    if assignment is None:
        raise EducationRecordsError("unknown assignment")
    cohort = next(
        (
            item
            for item in classroom.cohorts
            if item.cohort_id == assignment.cohort_id
        ),
        None,
    )
    if cohort is None or student_id not in cohort.student_ids:
        raise EducationRecordsError(
            "student is not assigned to this assignment"
        )


def _ledger(value: object) -> EducationLedger:
    if type(value) is not EducationLedger:
        raise EducationRecordsError("operation requires EducationLedger")
    return value


def _classroom(value: object) -> ClassroomSnapshot:
    if type(value) is not ClassroomSnapshot:
        raise EducationRecordsError("operation requires ClassroomSnapshot")
    return value


def _version(value: object) -> int:
    if type(value) is not int or value != EDUCATION_RECORDS_VERSION:
        raise EducationRecordsError(
            f"unsupported education records schema version: {value!r}"
        )
    return value


def _revision(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise EducationRecordsError(
            f"{label} must be a non-negative JSON-safe integer "
            f"not greater than {MAX_WIRE_INTEGER}"
        )
    return value


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise EducationRecordsError(
            f"{label} must be a canonical opaque identifier"
        )
    return value


def _id_tuple(value: object, label: str) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or len(value) > MAX_RECORDS_PER_COLLECTION
    ):
        raise EducationRecordsError(f"{label} must be a bounded tuple")
    checked = tuple(_id(item, label) for item in value)
    if len(set(checked)) != len(checked):
        raise EducationRecordsError(
            f"{label} contains duplicate identifiers"
        )
    return checked


def _text(value: object, label: str, *, max_len: int = MAX_TEXT) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value) > max_len
        or "\x00" in value
    ):
        raise EducationRecordsError(f"{label} violates exact text boundary")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise EducationRecordsError(
            f"{label} contains an invalid Unicode scalar value"
        )
    return value


def _timestamp(value: object, label: str) -> str:
    return _text(value, label, max_len=128)


def _digest_text(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise EducationRecordsError(
            f"{label} must be lowercase SHA-256 hex"
        )
    return value


def _typed_tuple(value: object, record_type: type, label: str) -> None:
    if (
        type(value) is not tuple
        or len(value) > MAX_RECORDS_PER_COLLECTION
    ):
        raise EducationRecordsError(f"{label} must be a bounded tuple")
    if any(type(item) is not record_type for item in value):
        raise EducationRecordsError(
            f"{label} contains invalid record type"
        )


def _unique(values: tuple, attr: str, label: str) -> None:
    seen = set()
    for item in values:
        key = getattr(item, attr)
        if key in seen:
            raise EducationRecordsError(f"duplicate {label} id: {key}")
        seen.add(key)


def _record_payload(item: object) -> dict[str, Any]:
    return _encode_record(item)


def _encode_record(item: object) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields(item):
        value = getattr(item, field.name)
        if type(value) is tuple:
            value = list(value)
        result[field.name] = value
    return result


def _decode_records(
    raw: object,
    record_type: type,
    label: str,
    *,
    limit: int = MAX_RECORDS_PER_COLLECTION,
) -> tuple:
    if type(raw) is not list or len(raw) > limit:
        raise EducationRecordsError(
            f"{label} must be a bounded JSON array"
        )
    names = {field.name for field in fields(record_type)}
    result = []
    for item in raw:
        data = _mapping(item, f"{record_type.__name__} record")
        _exact_keys(data, names, f"{record_type.__name__} record")
        kwargs = dict(data)
        if record_type is RemoteSessionRecord:
            raw_students = kwargs["student_ids"]
            if type(raw_students) is not list:
                raise EducationRecordsError(
                    "remote session student_ids must be a JSON array"
                )
            kwargs["student_ids"] = tuple(raw_students)
        result.append(record_type(**kwargs))
    return tuple(result)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or any(type(key) is not str for key in value)
    ):
        raise EducationRecordsError(f"{label} must be an exact-key object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise EducationRecordsError(
            f"{label} schema mismatch; "
            f"missing={sorted(expected-actual)}, "
            f"extra={sorted(actual-expected)}"
        )


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise EducationRecordsError(
            "education records cannot be serialized canonically"
        ) from exc


def _digest(value: object) -> str:
    text = _canonical_json(value)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EducationRecordsError(
            "education records contain an invalid Unicode scalar value"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise EducationRecordsError(
            "education records contain an invalid Unicode scalar value"
        ) from exc


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise EducationRecordsError(
            "education records JSON integer exceeds exact wire bounds"
        )
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise EducationRecordsError(
            "invalid education records JSON integer"
        ) from exc
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise EducationRecordsError(
            "education records JSON integer exceeds exact wire bounds"
        )
    return parsed


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EducationRecordsError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise EducationRecordsError(
        f"non-finite JSON constant is not allowed: {value}"
    )
