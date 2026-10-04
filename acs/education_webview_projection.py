from __future__ import annotations

"""Bounded Classes/Courses/Assignments presentation over canonical D10 state.

This module reads :class:`EducationWorkspace` through a provider and owns only
ephemeral selection/page state.  It never persists records, evaluates progress,
or accepts classroom identities, revisions, chess state, or source references
from browser content.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import secrets
from typing import Any

from . import classroom_domain as cd
from .education_workspace import EducationWorkspace
from .full_product_ui_shell import UILanguage, concise_user_error


WorkspaceProvider = Callable[[], EducationWorkspace]
CommandDispatch = Callable[[str, Mapping[str, object]], Any]
MAX_PAGE_SIZE = 100


class EducationCollection(str, Enum):
    CLASS = "class"
    GROUP = "group"
    STUDENT = "student"
    LESSON = "lesson"
    COURSE = "course"
    EXERCISE = "exercise"
    ASSIGNMENT = "assignment"
    HOMEWORK = "homework"
    STUDENT_GAME = "student_game"
    PROGRESS = "progress"
    RESULT = "result"


EDUCATION_COLLECTION_ORDER = tuple(EducationCollection)


_TEXT = {
    UILanguage.UA: {
        "document": "Класи, курси та завдання",
        "class": "Класи",
        "group": "Групи",
        "student": "Учні",
        "lesson": "Заняття",
        "course": "Курси",
        "exercise": "Вправи",
        "assignment": "Завдання",
        "homework": "Домашня робота",
        "student_game": "Партії учнів",
        "progress": "Прогрес",
        "result": "Результати",
        "empty": "Записів немає.",
        "selected": "Вибрано",
        "new_class": "Новий клас",
        "open": "Відкрити",
        "previous": "Попередня сторінка",
        "next": "Наступна сторінка",
        "page": "Сторінка",
        "of": "з",
        "deleted_student": "Видалений учень",
        "student_game_label": "Партія учня",
        "groups": "груп",
        "lessons": "занять",
        "completed": "завершено",
        "due": "до",
        "consent_not_collected": "згоду не отримано",
        "consent_granted": "згоду надано",
        "consent_withdrawn": "згоду відкликано",
        "homework_assigned": "призначено",
        "homework_in_progress": "в роботі",
        "homework_submitted": "подано",
        "homework_returned": "повернено",
    },
    UILanguage.EN: {
        "document": "Classes, courses, and assignments",
        "class": "Classes",
        "group": "Groups",
        "student": "Students",
        "lesson": "Lessons",
        "course": "Courses",
        "exercise": "Exercises",
        "assignment": "Assignments",
        "homework": "Homework",
        "student_game": "Student games",
        "progress": "Progress",
        "result": "Results",
        "empty": "No records.",
        "selected": "Selected",
        "new_class": "New class",
        "open": "Open",
        "previous": "Previous page",
        "next": "Next page",
        "page": "Page",
        "of": "of",
        "deleted_student": "Deleted student",
        "student_game_label": "Student game",
        "groups": "groups",
        "lessons": "lessons",
        "completed": "completed",
        "due": "due",
        "consent_not_collected": "consent not collected",
        "consent_granted": "consent granted",
        "consent_withdrawn": "consent withdrawn",
        "homework_assigned": "assigned",
        "homework_in_progress": "in progress",
        "homework_submitted": "submitted",
        "homework_returned": "returned",
    },
}


_OPEN_ACTIONS = {
    EducationCollection.CLASS: "classes.open",
    EducationCollection.STUDENT: "classes.student_open",
    EducationCollection.LESSON: "classes.lesson_open",
    EducationCollection.ASSIGNMENT: "classes.assignment_open",
}


@dataclass(frozen=True, slots=True)
class EducationWebViewEvent:
    kind: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _Record:
    record_id: str
    label: str
    secondary: str = ""
    status: str = ""


class EducationWebViewProjection:
    """Read-only browser projection with bounded paging and opaque item keys."""

    def __init__(
        self,
        workspace_provider: WorkspaceProvider,
        dispatch: CommandDispatch,
        *,
        language: UILanguage = UILanguage.UA,
        page_size: int = MAX_PAGE_SIZE,
    ) -> None:
        if not callable(workspace_provider):
            raise TypeError("education workspace provider must be callable")
        if not callable(dispatch):
            raise TypeError("education dispatcher must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError("education page size must be from 1 to 100")
        self._workspace_provider = workspace_provider
        self._dispatch = dispatch
        self._language = language
        self._page_size = page_size
        self._selected: dict[EducationCollection, str | None] = {
            kind: None for kind in EDUCATION_COLLECTION_ORDER
        }
        self._pages = {kind: 0 for kind in EDUCATION_COLLECTION_ORDER}
        self._item_key_secret = secrets.token_bytes(32)

    @property
    def language(self) -> UILanguage:
        return self._language

    def _workspace(self) -> EducationWorkspace:
        workspace = self._workspace_provider()
        if type(workspace) is not EducationWorkspace:
            raise TypeError("education provider must return EducationWorkspace")
        return workspace

    @staticmethod
    def _parse_kind(value: EducationCollection | str) -> EducationCollection:
        if isinstance(value, EducationCollection):
            return value
        if type(value) is not str:
            raise TypeError("education collection kind must be text")
        try:
            return EducationCollection(value.strip().lower())
        except ValueError:
            raise ValueError("unsupported education collection kind") from None

    @staticmethod
    def _bounded(value: object, *, limit: int = 200) -> str:
        if type(value) is not str:
            raise TypeError("education presentation text must be exact text")
        return value.strip()[:limit]

    def _item_key(self, kind: EducationCollection, record_id: str) -> str:
        message = f"{kind.value}\0{record_id}".encode("utf-8")
        return hmac.new(self._item_key_secret, message, hashlib.sha256).hexdigest()

    def _records(self, workspace: EducationWorkspace) -> dict[EducationCollection, tuple[_Record, ...]]:
        classroom = workspace.classroom
        labels = _TEXT[self._language]
        classes = {item.class_id: item for item in classroom.classes}
        students = {item.student_id: item for item in classroom.students}
        courses = {item.course_id: item for item in classroom.courses}
        cohorts = {item.cohort_id: item for item in classroom.cohorts}
        lessons = {item.lesson_id: item for item in classroom.lessons}
        assignments = {item.assignment_id: item for item in classroom.assignments}

        def student_label(student_id: str) -> str:
            student = students[student_id]
            return labels["deleted_student"] if student.deleted else student.pseudonym

        consent_labels = {
            cd.ConsentState.NOT_COLLECTED: labels["consent_not_collected"],
            cd.ConsentState.GRANTED: labels["consent_granted"],
            cd.ConsentState.WITHDRAWN: labels["consent_withdrawn"],
        }
        homework_labels = {
            cd.HomeworkStatus.ASSIGNED: labels["homework_assigned"],
            cd.HomeworkStatus.IN_PROGRESS: labels["homework_in_progress"],
            cd.HomeworkStatus.SUBMITTED: labels["homework_submitted"],
            cd.HomeworkStatus.RETURNED: labels["homework_returned"],
        }

        return {
            EducationCollection.CLASS: tuple(
                _Record(item.class_id, item.title, status=f"{len(item.group_ids)} {labels['groups']}")
                for item in classroom.classes
            ),
            EducationCollection.GROUP: tuple(
                _Record(item.group_id, item.title, secondary=classes[item.class_id].title)
                for item in classroom.groups
            ),
            EducationCollection.STUDENT: tuple(
                _Record(
                    item.student_id,
                    student_label(item.student_id),
                    status=consent_labels[item.consent],
                )
                for item in classroom.students
            ),
            EducationCollection.LESSON: tuple(
                _Record(item.lesson_id, item.title, secondary=courses[item.course_id].title)
                for item in classroom.lessons
            ),
            EducationCollection.COURSE: tuple(
                _Record(item.course_id, item.title, status=f"{len(item.lesson_ids)} {labels['lessons']}")
                for item in classroom.courses
            ),
            EducationCollection.EXERCISE: tuple(
                _Record(item.material_id, item.title)
                for item in classroom.materials
                if item.kind.strip().casefold() == "exercise"
            ),
            EducationCollection.ASSIGNMENT: tuple(
                _Record(
                    item.assignment_id,
                    item.title,
                    secondary=lessons[item.lesson_id].title,
                    status=f"{labels['due']} {item.due_at}" if item.due_at else "",
                )
                for item in classroom.assignments
            ),
            EducationCollection.HOMEWORK: tuple(
                _Record(
                    item.homework_id,
                    assignments[item.assignment_id].title,
                    secondary=student_label(item.student_id),
                    status=homework_labels[item.status],
                )
                for item in classroom.homework
            ),
            EducationCollection.STUDENT_GAME: tuple(
                _Record(
                    item.student_game_id,
                    labels["student_game_label"],
                    secondary=student_label(item.student_id),
                    status=(
                        assignments[item.assignment_id].title
                        if item.assignment_id is not None
                        else ""
                    ),
                )
                for item in classroom.student_games
            ),
            EducationCollection.PROGRESS: tuple(
                _Record(
                    item.progress_id,
                    student_label(item.student_id),
                    secondary=courses[item.course_id].title,
                    status=(
                        f"{len(item.completed_lesson_ids)}/{len(courses[item.course_id].lesson_ids)} "
                        f"{labels['completed']}"
                    ),
                )
                for item in classroom.progress
            ),
            EducationCollection.RESULT: tuple(
                _Record(
                    item.result_id,
                    assignments[item.assignment_id].title,
                    secondary=student_label(item.student_id),
                    status=(
                        item.result_code
                        if item.score_basis_points is None
                        else f"{item.result_code}, {item.score_basis_points / 100:g}%"
                    ),
                )
                for item in classroom.results
            ),
        }

    def _section(
        self,
        kind: EducationCollection,
        records: tuple[_Record, ...],
    ) -> dict[str, object]:
        labels = _TEXT[self._language]
        page_count = max(1, (len(records) + self._page_size - 1) // self._page_size)
        page = min(self._pages[kind], page_count - 1)
        self._pages[kind] = page
        start = page * self._page_size
        visible = records[start : start + self._page_size]
        visible_ids = {item.record_id for item in visible}
        selected_id = self._selected[kind]
        if selected_id not in visible_ids:
            selected_id = visible[0].record_id if visible else None
            self._selected[kind] = selected_id

        items: list[dict[str, object]] = []
        focus_target = ""
        for record in visible:
            key = self._item_key(kind, record.record_id)
            dom_id = f"education-{kind.value}-{key}"
            selected = record.record_id == selected_id
            if selected:
                focus_target = dom_id
            items.append(
                {
                    "item_key": key,
                    "dom_id": dom_id,
                    "label": self._bounded(record.label, limit=160),
                    "secondary": self._bounded(record.secondary, limit=200),
                    "status": self._bounded(record.status, limit=160),
                    "selected": selected,
                }
            )

        return {
            "kind": kind.value,
            "dom_id": f"education-section-{kind.value}",
            "heading": labels[kind.value],
            "items": tuple(items),
            "empty_message": labels["empty"] if not items else "",
            "focus_target": focus_target,
            "page": page + 1,
            "page_count": page_count,
            "page_label": f"{labels['page']} {page + 1} {labels['of']} {page_count}",
            "can_previous": page > 0,
            "can_next": page + 1 < page_count,
            "previous_label": labels["previous"],
            "next_label": labels["next"],
            "open_label": labels["open"],
            "open_enabled": selected_id is not None and kind in _OPEN_ACTIONS,
            "create_action": (
                {"command": "education.new_class", "label": labels["new_class"]}
                if kind is EducationCollection.CLASS
                else None
            ),
        }

    def snapshot(self) -> dict[str, object]:
        records = self._records(self._workspace())
        return {
            "document": {
                "lang": self._language.value,
                "heading": _TEXT[self._language]["document"],
            },
            "sections": tuple(
                self._section(kind, records[kind])
                for kind in EDUCATION_COLLECTION_ORDER
            ),
        }

    def _safe_error(self, _exc: Exception) -> EducationWebViewEvent:
        return EducationWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._language)},
        )

    def select(self, kind: EducationCollection | str, item_key: str) -> EducationWebViewEvent:
        try:
            parsed = self._parse_kind(kind)
            records = self._records(self._workspace())[parsed]
            section = self._section(parsed, records)
            visible = records[
                (section["page"] - 1) * self._page_size : section["page"] * self._page_size
            ]
            matches = [
                record for record in visible
                if hmac.compare_digest(self._item_key(parsed, record.record_id), item_key)
            ]
            if len(matches) != 1:
                raise LookupError("education item is not present on the current page")
            self._selected[parsed] = matches[0].record_id
            updated = self._section(parsed, records)
        except Exception as exc:
            return self._safe_error(exc)
        return EducationWebViewEvent(
            "selection",
            {
                "snapshot": updated,
                "focus_target": updated["focus_target"],
                "announcement": _TEXT[self._language]["selected"],
            },
        )

    def move_selection(self, kind: EducationCollection | str, delta: int) -> EducationWebViewEvent:
        try:
            parsed = self._parse_kind(kind)
            if type(delta) is not int or delta not in {-1, 1}:
                raise ValueError("selection delta must be -1 or 1")
            records = self._records(self._workspace())[parsed]
            if not records:
                raise LookupError("education collection is empty")
            self._section(parsed, records)
            selected = self._selected[parsed]
            index = next(i for i, item in enumerate(records) if item.record_id == selected)
            target = index + delta
            if not 0 <= target < len(records):
                raise LookupError("education collection boundary")
            self._pages[parsed] = target // self._page_size
            self._selected[parsed] = records[target].record_id
            updated = self._section(parsed, records)
        except Exception as exc:
            return self._safe_error(exc)
        return EducationWebViewEvent(
            "selection",
            {"snapshot": updated, "focus_target": updated["focus_target"], "announcement": ""},
        )

    def change_page(self, kind: EducationCollection | str, direction: int) -> EducationWebViewEvent:
        try:
            parsed = self._parse_kind(kind)
            if type(direction) is not int or direction not in {-1, 1}:
                raise ValueError("page direction must be -1 or 1")
            records = self._records(self._workspace())[parsed]
            self._section(parsed, records)
            target = self._pages[parsed] + direction
            page_count = max(1, (len(records) + self._page_size - 1) // self._page_size)
            if not 0 <= target < page_count:
                raise LookupError("education page boundary")
            self._pages[parsed] = target
            self._selected[parsed] = None
            updated = self._section(parsed, records)
        except Exception as exc:
            return self._safe_error(exc)
        return EducationWebViewEvent(
            "page",
            {"snapshot": updated, "focus_target": updated["focus_target"], "announcement": ""},
        )

    def open_selected(self, kind: EducationCollection | str) -> EducationWebViewEvent:
        try:
            parsed = self._parse_kind(kind)
            action = _OPEN_ACTIONS[parsed]
            records = self._records(self._workspace())[parsed]
            selected_id = self._selected[parsed]
            if selected_id not in {item.record_id for item in records}:
                raise LookupError("no current education item is selected")
            self._dispatch(action, {"record_id": selected_id})
        except Exception as exc:
            return self._safe_error(exc)
        return EducationWebViewEvent("delegated", {"kind": parsed.value, "action": action})

    def new_class(self) -> EducationWebViewEvent:
        try:
            self._dispatch("classes.new", {})
        except Exception as exc:
            return self._safe_error(exc)
        return EducationWebViewEvent("delegated", {"action": "classes.new"})
