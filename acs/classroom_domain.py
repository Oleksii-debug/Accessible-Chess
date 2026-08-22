from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping

CLASSROOM_VERSION = 1
MAX_RECORDS_PER_COLLECTION = 5000
MAX_LINKS_PER_RECORD = 2000
MAX_SNAPSHOT_BYTES = 2_000_000
MAX_TEXT = 512
MAX_NOTE_TEXT = 4000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ClassroomDomainError(ValueError):
    """Raised when classroom data is stale, corrupt, or non-canonical."""


class ConsentState(str, Enum):
    NOT_COLLECTED = "not_collected"
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


class HomeworkStatus(str, Enum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    RETURNED = "returned"


@dataclass(frozen=True)
class Student:
    student_id: str
    pseudonym: str
    consent: ConsentState = ConsentState.NOT_COLLECTED
    deleted: bool = False
    revision: int = 0

    def __post_init__(self) -> None:
        _id(self.student_id, "student id")
        consent = _enum(self.consent, ConsentState, "consent")
        _revision(self.revision, "student revision")
        if type(self.deleted) is not bool:
            raise ClassroomDomainError("student deleted flag must be boolean")
        if self.deleted:
            if self.pseudonym != "" or consent is not ConsentState.WITHDRAWN:
                raise ClassroomDomainError("deleted student must be an identity-minimized withdrawn-consent tombstone")
        else:
            _text(self.pseudonym, "student pseudonym", max_len=128)
        object.__setattr__(self, "consent", consent)

    @property
    def can_collect_personal_data(self) -> bool:
        return not self.deleted and self.consent is ConsentState.GRANTED


@dataclass(frozen=True)
class ClassroomClass:
    class_id: str
    title: str
    group_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.class_id, "class id")
        _text(self.title, "class title")
        _id_tuple(self.group_ids, "class group ids")


@dataclass(frozen=True)
class Group:
    group_id: str
    class_id: str
    title: str

    def __post_init__(self) -> None:
        _id(self.group_id, "group id")
        _id(self.class_id, "group class id")
        _text(self.title, "group title")


@dataclass(frozen=True)
class Course:
    course_id: str
    title: str
    lesson_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.course_id, "course id")
        _text(self.title, "course title")
        _id_tuple(self.lesson_ids, "course lesson ids")


@dataclass(frozen=True)
class Cohort:
    cohort_id: str
    course_id: str
    student_ids: tuple[str, ...]
    group_id: str | None = None

    def __post_init__(self) -> None:
        _id(self.cohort_id, "cohort id")
        _id(self.course_id, "cohort course id")
        _optional_id(self.group_id, "cohort group id")
        _id_tuple(self.student_ids, "cohort student ids")


@dataclass(frozen=True)
class LessonMaterial:
    material_id: str
    kind: str
    title: str
    source_ref: str | None = None

    def __post_init__(self) -> None:
        _id(self.material_id, "material id")
        _text(self.kind, "material kind", max_len=64)
        _text(self.title, "material title")
        _optional_id(self.source_ref, "material source ref")


@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    course_id: str
    title: str
    material_ids: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        _id(self.lesson_id, "lesson id")
        _id(self.course_id, "lesson course id")
        _text(self.title, "lesson title")
        _id_tuple(self.material_ids, "lesson material ids")
        _timestamp(self.created_at, "lesson created_at")


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    lesson_id: str
    cohort_id: str
    title: str
    created_at: str
    due_at: str | None = None

    def __post_init__(self) -> None:
        _id(self.assignment_id, "assignment id")
        _id(self.lesson_id, "assignment lesson id")
        _id(self.cohort_id, "assignment cohort id")
        _text(self.title, "assignment title")
        _timestamp(self.created_at, "assignment created_at")
        if self.due_at is not None:
            _timestamp(self.due_at, "assignment due_at")


@dataclass(frozen=True)
class Homework:
    homework_id: str
    assignment_id: str
    student_id: str
    status: HomeworkStatus = HomeworkStatus.ASSIGNED
    response_ref: str | None = None

    def __post_init__(self) -> None:
        _id(self.homework_id, "homework id")
        _id(self.assignment_id, "homework assignment id")
        _id(self.student_id, "homework student id")
        object.__setattr__(self, "status", _enum(self.status, HomeworkStatus, "homework status"))
        _optional_id(self.response_ref, "homework response ref")


@dataclass(frozen=True)
class StudentGame:
    student_game_id: str
    student_id: str
    game_id: str
    assignment_id: str | None = None

    def __post_init__(self) -> None:
        _id(self.student_game_id, "student game id")
        _id(self.student_id, "student game student id")
        _id(self.game_id, "student game canonical game id")
        _optional_id(self.assignment_id, "student game assignment id")


@dataclass(frozen=True)
class Result:
    result_id: str
    student_id: str
    assignment_id: str
    result_code: str
    score_basis_points: int | None = None

    def __post_init__(self) -> None:
        _id(self.result_id, "result id")
        _id(self.student_id, "result student id")
        _id(self.assignment_id, "result assignment id")
        _text(self.result_code, "result code", max_len=64)
        if self.score_basis_points is not None and (
            type(self.score_basis_points) is not int or not 0 <= self.score_basis_points <= 10_000
        ):
            raise ClassroomDomainError("score basis points must be an integer from 0 to 10000")


@dataclass(frozen=True)
class Progress:
    progress_id: str
    student_id: str
    course_id: str
    completed_lesson_ids: tuple[str, ...]
    revision: int = 0

    def __post_init__(self) -> None:
        _id(self.progress_id, "progress id")
        _id(self.student_id, "progress student id")
        _id(self.course_id, "progress course id")
        _id_tuple(self.completed_lesson_ids, "completed lesson ids")
        _revision(self.revision, "progress revision")


@dataclass(frozen=True)
class TeacherNote:
    note_id: str
    student_id: str
    text: str
    created_at: str

    def __post_init__(self) -> None:
        _id(self.note_id, "teacher note id")
        _id(self.student_id, "teacher note student id")
        _text(self.text, "teacher note text", max_len=MAX_NOTE_TEXT, canonical_edges=False)
        _timestamp(self.created_at, "teacher note created_at")


@dataclass(frozen=True)
class ClassroomSnapshot:
    students: tuple[Student, ...] = ()
    classes: tuple[ClassroomClass, ...] = ()
    groups: tuple[Group, ...] = ()
    courses: tuple[Course, ...] = ()
    cohorts: tuple[Cohort, ...] = ()
    materials: tuple[LessonMaterial, ...] = ()
    lessons: tuple[Lesson, ...] = ()
    assignments: tuple[Assignment, ...] = ()
    homework: tuple[Homework, ...] = ()
    student_games: tuple[StudentGame, ...] = ()
    results: tuple[Result, ...] = ()
    progress: tuple[Progress, ...] = ()
    teacher_notes: tuple[TeacherNote, ...] = ()
    version: int = CLASSROOM_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        for _, attr, record_type, _ in _COLLECTIONS:
            _typed_tuple(getattr(self, attr), record_type, attr)

        students = _index(self.students, "student_id", "student")
        classes = _index(self.classes, "class_id", "class")
        groups = _index(self.groups, "group_id", "group")
        courses = _index(self.courses, "course_id", "course")
        cohorts = _index(self.cohorts, "cohort_id", "cohort")
        materials = _index(self.materials, "material_id", "material")
        lessons = _index(self.lessons, "lesson_id", "lesson")
        assignments = _index(self.assignments, "assignment_id", "assignment")
        for _, attr, _, id_attr in _COLLECTIONS[8:]:
            _index(getattr(self, attr), id_attr, attr)

        for item in self.groups:
            if item.class_id not in classes:
                raise ClassroomDomainError(f"group {item.group_id} references unknown class")
        for item in self.classes:
            expected = {group.group_id for group in self.groups if group.class_id == item.class_id}
            if set(item.group_ids) != expected:
                raise ClassroomDomainError(f"class {item.class_id} group index is inconsistent")

        for item in self.lessons:
            if item.course_id not in courses:
                raise ClassroomDomainError(f"lesson {item.lesson_id} references unknown course")
            if any(material_id not in materials for material_id in item.material_ids):
                raise ClassroomDomainError(f"lesson {item.lesson_id} references unknown material")
        for item in self.courses:
            expected = {lesson.lesson_id for lesson in self.lessons if lesson.course_id == item.course_id}
            if set(item.lesson_ids) != expected:
                raise ClassroomDomainError(f"course {item.course_id} lesson index is inconsistent")

        for item in self.cohorts:
            if item.course_id not in courses:
                raise ClassroomDomainError(f"cohort {item.cohort_id} references unknown course")
            if item.group_id is not None and item.group_id not in groups:
                raise ClassroomDomainError(f"cohort {item.cohort_id} references unknown group")
            for student_id in item.student_ids:
                _active_student(student_id, students, f"cohort {item.cohort_id}")

        for item in self.assignments:
            lesson, cohort = lessons.get(item.lesson_id), cohorts.get(item.cohort_id)
            if lesson is None or cohort is None:
                raise ClassroomDomainError(f"assignment {item.assignment_id} has an unknown lesson or cohort")
            if lesson.course_id != cohort.course_id:
                raise ClassroomDomainError(f"assignment {item.assignment_id} crosses course/cohort boundary")

        for item in self.homework:
            _assignment_student(item.student_id, item.assignment_id, students, cohorts, assignments, "homework")
        for item in self.results:
            _assignment_student(item.student_id, item.assignment_id, students, cohorts, assignments, "result")
        for item in self.student_games:
            _active_student(item.student_id, students, "student game")
            if item.assignment_id is not None:
                _assignment_student(item.student_id, item.assignment_id, students, cohorts, assignments, "student game")
        for item in self.progress:
            _active_student(item.student_id, students, "progress")
            if item.course_id not in courses:
                raise ClassroomDomainError(f"progress {item.progress_id} references unknown course")
            for lesson_id in item.completed_lesson_ids:
                lesson = lessons.get(lesson_id)
                if lesson is None or lesson.course_id != item.course_id:
                    raise ClassroomDomainError(f"progress {item.progress_id} references lesson outside its course")
        for item in self.teacher_notes:
            student = _active_student(item.student_id, students, "teacher note")
            if student.consent is not ConsentState.GRANTED:
                raise ClassroomDomainError("teacher notes require explicit student consent")

    @property
    def digest(self) -> str:
        return _digest(self._body())

    def _body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"version": self.version}
        for wire_key, attr, _, _ in _COLLECTIONS:
            body[wire_key] = [_encode_record(item) for item in getattr(self, attr)]
        return body

    def to_record(self) -> dict[str, Any]:
        record = self._body()
        record["digest"] = _digest(record)
        return record

    def to_json(self) -> str:
        text = json.dumps(self.to_record(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(text.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ClassroomDomainError("classroom snapshot exceeds size limit")
        return text

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "ClassroomSnapshot":
        data = _mapping(value, "classroom snapshot")
        expected = {"version", "digest", *[wire_key for wire_key, _, _, _ in _COLLECTIONS]}
        _exact_keys(data, expected, "classroom snapshot")
        _version(data["version"])
        supplied_digest = _digest_text(data["digest"])
        kwargs: dict[str, Any] = {}
        for wire_key, attr, record_type, _ in _COLLECTIONS:
            raw = data[wire_key]
            if type(raw) is not list or len(raw) > MAX_RECORDS_PER_COLLECTION:
                raise ClassroomDomainError(f"{wire_key} must be a bounded JSON array")
            kwargs[attr] = tuple(_decode_record(record_type, item) for item in raw)
        snapshot = cls(version=data["version"], **kwargs)
        if snapshot.digest != supplied_digest:
            raise ClassroomDomainError("classroom snapshot digest mismatch")
        return snapshot

    @classmethod
    def from_json(cls, text: str) -> "ClassroomSnapshot":
        if type(text) is not str:
            raise ClassroomDomainError("classroom snapshot JSON must be exact text")
        if len(text.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ClassroomDomainError("classroom snapshot exceeds size limit")
        try:
            raw = json.loads(text, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise ClassroomDomainError("invalid classroom snapshot JSON") from exc
        return cls.from_record(raw)


def set_student_consent(
    snapshot: ClassroomSnapshot, student_id: str, expected_revision: int, consent: ConsentState | str
) -> ClassroomSnapshot:
    _snapshot(snapshot)
    student_id = _id(student_id, "student id")
    _revision(expected_revision, "expected revision")
    target = _find_student(snapshot, student_id)
    if target.revision != expected_revision:
        raise ClassroomDomainError("stale student revision")
    if target.deleted:
        raise ClassroomDomainError("deleted student consent cannot be changed")
    consent = _enum(consent, ConsentState, "consent")
    if consent is target.consent:
        return snapshot
    updated = replace(target, consent=consent, revision=target.revision + 1)
    notes = snapshot.teacher_notes if consent is ConsentState.GRANTED else tuple(
        item for item in snapshot.teacher_notes if item.student_id != student_id
    )
    return replace(snapshot, students=tuple(updated if item.student_id == student_id else item for item in snapshot.students), teacher_notes=notes)


def delete_student(snapshot: ClassroomSnapshot, student_id: str, expected_revision: int) -> ClassroomSnapshot:
    _snapshot(snapshot)
    student_id = _id(student_id, "student id")
    _revision(expected_revision, "expected revision")
    target = _find_student(snapshot, student_id)
    if target.revision != expected_revision:
        raise ClassroomDomainError("stale student revision")
    if target.deleted:
        return snapshot
    tombstone = Student(target.student_id, "", ConsentState.WITHDRAWN, True, target.revision + 1)
    return replace(
        snapshot,
        students=tuple(tombstone if item.student_id == student_id else item for item in snapshot.students),
        cohorts=tuple(replace(item, student_ids=tuple(s for s in item.student_ids if s != student_id)) for item in snapshot.cohorts),
        homework=tuple(item for item in snapshot.homework if item.student_id != student_id),
        student_games=tuple(item for item in snapshot.student_games if item.student_id != student_id),
        results=tuple(item for item in snapshot.results if item.student_id != student_id),
        progress=tuple(item for item in snapshot.progress if item.student_id != student_id),
        teacher_notes=tuple(item for item in snapshot.teacher_notes if item.student_id != student_id),
    )


def _snapshot(value: object) -> ClassroomSnapshot:
    if type(value) is not ClassroomSnapshot:
        raise ClassroomDomainError("operation requires ClassroomSnapshot")
    return value


def _find_student(snapshot: ClassroomSnapshot, student_id: str) -> Student:
    for student in snapshot.students:
        if student.student_id == student_id:
            return student
    raise ClassroomDomainError("unknown student")


def _assignment_student(student_id, assignment_id, students, cohorts, assignments, label) -> None:
    _active_student(student_id, students, label)
    assignment = assignments.get(assignment_id)
    if assignment is None:
        raise ClassroomDomainError(f"{label} references unknown assignment")
    if student_id not in cohorts[assignment.cohort_id].student_ids:
        raise ClassroomDomainError(f"{label} student is not in assignment cohort")


def _active_student(student_id, students, label) -> Student:
    student = students.get(student_id)
    if student is None or student.deleted:
        raise ClassroomDomainError(f"{label} references unavailable student")
    return student


def _index(values, attr, label):
    result = {}
    for item in values:
        key = getattr(item, attr)
        if key in result:
            raise ClassroomDomainError(f"duplicate {label} id: {key}")
        result[key] = item
    return result


def _typed_tuple(value, record_type, label) -> None:
    if type(value) is not tuple or len(value) > MAX_RECORDS_PER_COLLECTION:
        raise ClassroomDomainError(f"{label} must be a bounded tuple")
    if any(type(item) is not record_type for item in value):
        raise ClassroomDomainError(f"{label} contains invalid record type")


def _id_tuple(value, label) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > MAX_LINKS_PER_RECORD:
        raise ClassroomDomainError(f"{label} must be a bounded tuple")
    checked = tuple(_id(item, label) for item in value)
    if len(set(checked)) != len(checked):
        raise ClassroomDomainError(f"{label} contains duplicate identifiers")
    return checked


def _id(value, label) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ClassroomDomainError(f"{label} must be a canonical opaque identifier")
    return value


def _optional_id(value, label):
    return None if value is None else _id(value, label)


def _text(value, label, *, max_len=MAX_TEXT, canonical_edges=True) -> str:
    if type(value) is not str or not value.strip() or len(value) > max_len or "\x00" in value:
        raise ClassroomDomainError(f"{label} violates exact text boundary")
    if canonical_edges and value != value.strip():
        raise ClassroomDomainError(f"{label} must not contain boundary whitespace")
    return value


def _timestamp(value, label) -> str:
    return _text(value, label, max_len=128)


def _revision(value, label) -> int:
    if type(value) is not int or value < 0:
        raise ClassroomDomainError(f"{label} must be a non-negative integer")
    return value


def _enum(value, enum_type, label):
    if isinstance(value, enum_type):
        return value
    if type(value) is not str:
        raise ClassroomDomainError(f"{label} must be exact text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ClassroomDomainError(f"unsupported {label}: {value!r}") from exc


def _version(value) -> int:
    if type(value) is not int or value != CLASSROOM_VERSION:
        raise ClassroomDomainError(f"unsupported classroom schema version: {value!r}")
    return value


def _mapping(value, label) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ClassroomDomainError(f"{label} must be an exact-key object")
    return value


def _exact_keys(value, expected, label) -> None:
    actual = set(value)
    if actual != expected:
        raise ClassroomDomainError(f"{label} schema mismatch; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")


def _digest_text(value) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ClassroomDomainError("snapshot digest must be lowercase SHA-256 hex")
    return value


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClassroomDomainError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ClassroomDomainError(f"non-finite JSON constant is not allowed: {value}")


def _encode_record(item) -> dict[str, Any]:
    result = {}
    for field in fields(item):
        value = getattr(item, field.name)
        if isinstance(value, Enum):
            value = value.value
        elif type(value) is tuple:
            value = list(value)
        result[field.name] = value
    return result


def _decode_record(record_type, value):
    data = _mapping(value, f"{record_type.__name__} record")
    names = {field.name for field in fields(record_type)}
    _exact_keys(data, names, f"{record_type.__name__} record")
    kwargs = dict(data)
    for field_name in _TUPLE_FIELDS.get(record_type, ()):
        raw = kwargs[field_name]
        if type(raw) is not list or len(raw) > MAX_LINKS_PER_RECORD:
            raise ClassroomDomainError(f"{field_name} must be a bounded JSON array")
        kwargs[field_name] = tuple(raw)
    return record_type(**kwargs)


_TUPLE_FIELDS = {
    ClassroomClass: ("group_ids",),
    Course: ("lesson_ids",),
    Cohort: ("student_ids",),
    Lesson: ("material_ids",),
    Progress: ("completed_lesson_ids",),
}

_COLLECTIONS = (
    ("students", "students", Student, "student_id"),
    ("classes", "classes", ClassroomClass, "class_id"),
    ("groups", "groups", Group, "group_id"),
    ("courses", "courses", Course, "course_id"),
    ("cohorts", "cohorts", Cohort, "cohort_id"),
    ("materials", "materials", LessonMaterial, "material_id"),
    ("lessons", "lessons", Lesson, "lesson_id"),
    ("assignments", "assignments", Assignment, "assignment_id"),
    ("homework", "homework", Homework, "homework_id"),
    ("student_games", "student_games", StudentGame, "student_game_id"),
    ("results", "results", Result, "result_id"),
    ("progress", "progress", Progress, "progress_id"),
    ("teacher_notes", "teacher_notes", TeacherNote, "note_id"),
)
