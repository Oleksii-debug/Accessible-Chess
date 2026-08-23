from __future__ import annotations

from dataclasses import dataclass, fields, replace
import hashlib
import json
import re
from typing import Any, Mapping

from .classroom_domain import ClassroomSnapshot


EDUCATION_RECORDS_VERSION = 1
MAX_RECORDS_PER_COLLECTION = 10_000
MAX_OPERATION_RECEIPTS = 20_000
MAX_SNAPSHOT_BYTES = 4_000_000
MAX_TEXT = 512
MAX_WIRE_INTEGER = (1 << 53) - 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class EducationRecordsError(ValueError):
    """Raised when durable education data is stale, ambiguous, corrupt, or unauthorized."""


@dataclass(frozen=True)
class SubmissionRecord:
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
            raise EducationRecordsError("submission attempt must be an integer from 1 to 10000")


@dataclass(frozen=True)
class ProgressEvent:
    event_id: str
    student_id: str
    course_id: str
    lesson_id: str
    completed_at: str
    score_basis_points: int | None = None

    def __post_init__(self) -> None:
        _id(self.event_id, "progress event id")
        _id(self.student_id, "progress student id")
        _id(self.course_id, "progress course id")
        _id(self.lesson_id, "progress lesson id")
        _timestamp(self.completed_at, "progress completed_at")
        if self.score_basis_points is not None and (
            type(self.score_basis_points) is not int or not 0 <= self.score_basis_points <= 10_000
        ):
            raise EducationRecordsError("progress score basis points must be an integer from 0 to 10000")


@dataclass(frozen=True)
class RemoteSessionRecord:
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
        checked_students = _id_tuple(self.student_ids, "remote session student ids")
        _timestamp(self.started_at, "remote session started_at")
        if self.closed_at is not None:
            _timestamp(self.closed_at, "remote session closed_at")
        _revision(self.revision, "remote session revision")
        _revision(self.last_remote_sequence, "remote session sequence")
        _digest_text(self.snapshot_digest, "remote session snapshot digest")
        object.__setattr__(self, "student_ids", checked_students)


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


@dataclass(frozen=True)
class StudentRecordsView:
    student_id: str
    submissions: tuple[SubmissionRecord, ...]
    progress_events: tuple[ProgressEvent, ...]
    sessions: tuple[StudentSessionView, ...]

    def __post_init__(self) -> None:
        _id(self.student_id, "student view id")
        _typed_tuple(self.submissions, SubmissionRecord, "student view submissions")
        _typed_tuple(self.progress_events, ProgressEvent, "student view progress events")
        _typed_tuple(self.sessions, StudentSessionView, "student view sessions")
        if any(item.student_id != self.student_id for item in self.submissions):
            raise EducationRecordsError("student view contains another student's submission")
        if any(item.student_id != self.student_id for item in self.progress_events):
            raise EducationRecordsError("student view contains another student's progress")


@dataclass(frozen=True)
class EducationLedger:
    classroom_digest: str
    revision: int = 0
    submissions: tuple[SubmissionRecord, ...] = ()
    progress_events: tuple[ProgressEvent, ...] = ()
    remote_sessions: tuple[RemoteSessionRecord, ...] = ()
    operation_receipts: tuple[OperationReceipt, ...] = ()
    version: int = EDUCATION_RECORDS_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        _digest_text(self.classroom_digest, "classroom digest")
        _revision(self.revision, "education ledger revision")
        _typed_tuple(self.submissions, SubmissionRecord, "submissions")
        _typed_tuple(self.progress_events, ProgressEvent, "progress events")
        _typed_tuple(self.remote_sessions, RemoteSessionRecord, "remote sessions")
        if type(self.operation_receipts) is not tuple or len(self.operation_receipts) > MAX_OPERATION_RECEIPTS:
            raise EducationRecordsError("operation receipts must be a bounded tuple")
        if any(type(item) is not OperationReceipt for item in self.operation_receipts):
            raise EducationRecordsError("operation receipts contain invalid record type")
        _unique(self.submissions, "submission_id", "submission")
        _unique(self.progress_events, "event_id", "progress event")
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
            "progress_events": [_encode_record(item) for item in self.progress_events],
            "remote_sessions": [_encode_record(item) for item in self.remote_sessions],
            "operation_receipts": [_encode_record(item) for item in self.operation_receipts],
        }

    def to_record(self) -> dict[str, Any]:
        body = self._body()
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        text = _canonical_json(self.to_record())
        if _utf8_size(text) > MAX_SNAPSHOT_BYTES:
            raise EducationRecordsError("education records snapshot exceeds size limit")
        return text

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "EducationLedger":
        data = _mapping(value, "education records snapshot")
        expected = {
            "version",
            "classroom_digest",
            "revision",
            "submissions",
            "progress_events",
            "remote_sessions",
            "operation_receipts",
            "digest",
        }
        _exact_keys(data, expected, "education records snapshot")
        _version(data["version"])
        supplied_digest = _digest_text(data["digest"], "education records digest")
        body = {key: data[key] for key in expected if key != "digest"}
        if _digest(body) != supplied_digest:
            raise EducationRecordsError("education records snapshot digest mismatch")
        ledger = cls(
            version=data["version"],
            classroom_digest=data["classroom_digest"],
            revision=data["revision"],
            submissions=_decode_records(data["submissions"], SubmissionRecord, "submissions"),
            progress_events=_decode_records(data["progress_events"], ProgressEvent, "progress_events"),
            remote_sessions=_decode_records(data["remote_sessions"], RemoteSessionRecord, "remote sessions"),
            operation_receipts=_decode_records(
                data["operation_receipts"], OperationReceipt, "operation receipts", limit=MAX_OPERATION_RECEIPTS
            ),
        )
        return ledger

    @classmethod
    def from_json(cls, text: str) -> "EducationLedger":
        if type(text) is not str:
            raise EducationRecordsError("education records JSON must be exact text")
        if _utf8_size(text) > MAX_SNAPSHOT_BYTES:
            raise EducationRecordsError("education records snapshot exceeds size limit")
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
            raise EducationRecordsError("education records JSON exceeds nesting limit") from exc
        return cls.from_record(raw)

    def student_view(self, actor_student_id: str) -> StudentRecordsView:
        """Return only the actor student's durable private records.

        There is deliberately no arbitrary subject parameter. A student-facing adapter
        cannot request another student's response/progress through this API.
        """

        actor_student_id = _id(actor_student_id, "student view actor id")
        submissions = tuple(item for item in self.submissions if item.student_id == actor_student_id)
        progress = tuple(item for item in self.progress_events if item.student_id == actor_student_id)
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
        return StudentRecordsView(actor_student_id, submissions, progress, sessions)


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
    ledger, classroom = _preflight(ledger, classroom, expected_revision)
    record = SubmissionRecord(submission_id, assignment_id, student_id, response_ref, submitted_at, attempt)
    _require_assignment_student(classroom, student_id, assignment_id)
    payload = _record_payload(record)
    duplicate = _idempotency(ledger, operation_id, "submit_assignment", payload)
    if duplicate:
        return ledger
    if any(item.submission_id == record.submission_id for item in ledger.submissions):
        raise EducationRecordsError("duplicate submission id")
    return _commit(
        ledger,
        operation_id,
        "submit_assignment",
        payload,
        submissions=ledger.submissions + (record,),
    )


def record_progress(
    ledger: EducationLedger,
    classroom: ClassroomSnapshot,
    *,
    event_id: str,
    operation_id: str,
    student_id: str,
    course_id: str,
    lesson_id: str,
    completed_at: str,
    score_basis_points: int | None = None,
    expected_revision: int,
) -> EducationLedger:
    ledger, classroom = _preflight(ledger, classroom, expected_revision)
    event = ProgressEvent(event_id, student_id, course_id, lesson_id, completed_at, score_basis_points)
    _require_course_student_lesson(classroom, student_id, course_id, lesson_id)
    payload = _record_payload(event)
    duplicate = _idempotency(ledger, operation_id, "record_progress", payload)
    if duplicate:
        return ledger
    if any(item.event_id == event.event_id for item in ledger.progress_events):
        raise EducationRecordsError("duplicate progress event id")
    return _commit(
        ledger,
        operation_id,
        "record_progress",
        payload,
        progress_events=ledger.progress_events + (event,),
    )


def checkpoint_remote_session(
    ledger: EducationLedger,
    classroom: ClassroomSnapshot,
    *,
    record_id: str,
    operation_id: str,
    session_id: str,
    student_ids: tuple[str, ...],
    started_at: str,
    closed_at: str | None,
    last_remote_sequence: int,
    snapshot_digest: str,
    expected_session_revision: int,
    expected_revision: int,
) -> EducationLedger:
    ledger, classroom = _preflight(ledger, classroom, expected_revision)
    _revision(expected_session_revision, "expected remote session revision")
    student_ids = _id_tuple(student_ids, "remote session student ids")
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
    if _idempotency(ledger, operation_id, "checkpoint_remote_session", payload):
        return ledger
    existing = next((item for item in ledger.remote_sessions if item.session_id == candidate.session_id), None)
    if existing is None:
        if expected_session_revision != 0:
            raise EducationRecordsError("stale remote session revision")
        if any(item.record_id == candidate.record_id for item in ledger.remote_sessions):
            raise EducationRecordsError("duplicate remote session record id")
        updated = ledger.remote_sessions + (candidate,)
    else:
        if existing.record_id != candidate.record_id:
            raise EducationRecordsError("remote session id is already bound to another record id")
        if existing.revision != expected_session_revision:
            raise EducationRecordsError("stale remote session revision")
        if existing.student_ids != candidate.student_ids or existing.started_at != candidate.started_at:
            raise EducationRecordsError("remote session stable identity fields cannot change")
        if candidate.last_remote_sequence < existing.last_remote_sequence:
            raise EducationRecordsError("remote session sequence cannot move backwards")
        if (
            candidate.last_remote_sequence == existing.last_remote_sequence
            and candidate.snapshot_digest != existing.snapshot_digest
        ):
            raise EducationRecordsError("remote session sequence conflicts with a different snapshot digest")
        if existing.closed_at is not None and candidate.closed_at != existing.closed_at:
            raise EducationRecordsError("closed remote session cannot be reopened or reclosed differently")
        replacement = replace(candidate, revision=existing.revision + 1)
        updated = tuple(replacement if item.session_id == existing.session_id else item for item in ledger.remote_sessions)
    return _commit(
        ledger,
        operation_id,
        "checkpoint_remote_session",
        payload,
        remote_sessions=updated,
    )


def reconcile_classroom(
    ledger: EducationLedger,
    classroom: ClassroomSnapshot,
    *,
    operation_id: str,
    expected_revision: int,
) -> EducationLedger:
    """Re-anchor records to a new classroom snapshot and honor student deletion.

    Historical assignment/course references are retained for active students. Deleted
    or unavailable students are removed from private submissions/progress and from
    remote-session participant lists. This is explicit privacy lifecycle handling,
    not a generic database migration.
    """

    _ledger(ledger)
    _classroom(classroom)
    _revision(expected_revision, "expected education ledger revision")
    if ledger.revision != expected_revision:
        raise EducationRecordsError("stale education ledger revision")
    payload = {"classroom_digest": classroom.digest}
    if _idempotency(ledger, operation_id, "reconcile_classroom", payload):
        return ledger
    active = {student.student_id for student in classroom.students if not student.deleted}
    sessions = tuple(
        replace(item, student_ids=tuple(student_id for student_id in item.student_ids if student_id in active))
        for item in ledger.remote_sessions
    )
    return _commit(
        ledger,
        operation_id,
        "reconcile_classroom",
        payload,
        classroom_digest=classroom.digest,
        submissions=tuple(item for item in ledger.submissions if item.student_id in active),
        progress_events=tuple(item for item in ledger.progress_events if item.student_id in active),
        remote_sessions=sessions,
    )


def _preflight(
    ledger: EducationLedger, classroom: ClassroomSnapshot, expected_revision: int
) -> tuple[EducationLedger, ClassroomSnapshot]:
    _ledger(ledger)
    _classroom(classroom)
    _revision(expected_revision, "expected education ledger revision")
    if ledger.revision != expected_revision:
        raise EducationRecordsError("stale education ledger revision")
    if ledger.classroom_digest != classroom.digest:
        raise EducationRecordsError("education ledger is anchored to a different classroom snapshot")
    return ledger, classroom


def _commit(ledger: EducationLedger, operation_id: str, operation_kind: str, payload: object, **changes) -> EducationLedger:
    receipt = OperationReceipt(_id(operation_id, "operation id"), operation_kind, _digest(payload))
    if len(ledger.operation_receipts) >= MAX_OPERATION_RECEIPTS:
        raise EducationRecordsError("operation receipt limit exceeded")
    changes["revision"] = ledger.revision + 1
    changes["operation_receipts"] = ledger.operation_receipts + (receipt,)
    return replace(ledger, **changes)


def _idempotency(ledger: EducationLedger, operation_id: str, operation_kind: str, payload: object) -> bool:
    operation_id = _id(operation_id, "operation id")
    payload_digest = _digest(payload)
    for receipt in ledger.operation_receipts:
        if receipt.operation_id != operation_id:
            continue
        if receipt.operation_kind == operation_kind and receipt.payload_digest == payload_digest:
            return True
        raise EducationRecordsError("operation id was already used with different content")
    return False


def _require_active_student(classroom: ClassroomSnapshot, student_id: str):
    student_id = _id(student_id, "student id")
    student = next((item for item in classroom.students if item.student_id == student_id), None)
    if student is None or student.deleted:
        raise EducationRecordsError("student is unavailable")
    return student


def _require_assignment_student(classroom: ClassroomSnapshot, student_id: str, assignment_id: str) -> None:
    _require_active_student(classroom, student_id)
    assignment_id = _id(assignment_id, "assignment id")
    assignment = next((item for item in classroom.assignments if item.assignment_id == assignment_id), None)
    if assignment is None:
        raise EducationRecordsError("unknown assignment")
    cohort = next((item for item in classroom.cohorts if item.cohort_id == assignment.cohort_id), None)
    if cohort is None or student_id not in cohort.student_ids:
        raise EducationRecordsError("student is not assigned to this assignment")


def _require_course_student_lesson(
    classroom: ClassroomSnapshot, student_id: str, course_id: str, lesson_id: str
) -> None:
    _require_active_student(classroom, student_id)
    course_id = _id(course_id, "course id")
    lesson_id = _id(lesson_id, "lesson id")
    lesson = next((item for item in classroom.lessons if item.lesson_id == lesson_id), None)
    if lesson is None or lesson.course_id != course_id:
        raise EducationRecordsError("progress lesson does not belong to course")
    enrolled = any(item.course_id == course_id and student_id in item.student_ids for item in classroom.cohorts)
    if not enrolled:
        raise EducationRecordsError("student is not enrolled in course")


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
        raise EducationRecordsError(f"unsupported education records schema version: {value!r}")
    return value


def _revision(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise EducationRecordsError(
            f"{label} must be a non-negative JSON-safe integer not greater than {MAX_WIRE_INTEGER}"
        )
    return value


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise EducationRecordsError(f"{label} must be a canonical opaque identifier")
    return value


def _id_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > MAX_RECORDS_PER_COLLECTION:
        raise EducationRecordsError(f"{label} must be a bounded tuple")
    checked = tuple(_id(item, label) for item in value)
    if len(set(checked)) != len(checked):
        raise EducationRecordsError(f"{label} contains duplicate identifiers")
    return checked


def _text(value: object, label: str, *, max_len: int = MAX_TEXT) -> str:
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > max_len or "\x00" in value:
        raise EducationRecordsError(f"{label} violates exact text boundary")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise EducationRecordsError(f"{label} contains an invalid Unicode scalar value")
    return value


def _timestamp(value: object, label: str) -> str:
    return _text(value, label, max_len=128)


def _digest_text(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise EducationRecordsError(f"{label} must be lowercase SHA-256 hex")
    return value


def _typed_tuple(value: object, record_type: type, label: str) -> None:
    if type(value) is not tuple or len(value) > MAX_RECORDS_PER_COLLECTION:
        raise EducationRecordsError(f"{label} must be a bounded tuple")
    if any(type(item) is not record_type for item in value):
        raise EducationRecordsError(f"{label} contains invalid record type")


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


def _decode_records(raw: object, record_type: type, label: str, *, limit: int = MAX_RECORDS_PER_COLLECTION) -> tuple:
    if type(raw) is not list or len(raw) > limit:
        raise EducationRecordsError(f"{label} must be a bounded JSON array")
    names = {field.name for field in fields(record_type)}
    result = []
    for item in raw:
        data = _mapping(item, f"{record_type.__name__} record")
        _exact_keys(data, names, f"{record_type.__name__} record")
        kwargs = dict(data)
        for field in fields(record_type):
            if field.name == "student_ids":
                value = kwargs[field.name]
                if type(value) is not list:
                    raise EducationRecordsError("remote session student_ids must be a JSON array")
                kwargs[field.name] = tuple(value)
        result.append(record_type(**kwargs))
    return tuple(result)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise EducationRecordsError(f"{label} must be an exact-key object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise EducationRecordsError(
            f"{label} schema mismatch; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise EducationRecordsError("education records cannot be serialized canonically") from exc


def _digest(value: object) -> str:
    text = _canonical_json(value)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EducationRecordsError("education records contain an invalid Unicode scalar value") from exc
    return hashlib.sha256(encoded).hexdigest()


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise EducationRecordsError("education records contain an invalid Unicode scalar value") from exc


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise EducationRecordsError("education records JSON integer exceeds exact wire bounds")
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise EducationRecordsError("invalid education records JSON integer") from exc
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise EducationRecordsError("education records JSON integer exceeds exact wire bounds")
    return parsed


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EducationRecordsError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise EducationRecordsError(f"non-finite JSON constant is not allowed: {value}")
